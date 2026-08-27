"""Coordinator for MySmartBike BLE integration."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    WRITE_UUID,
    NOTIFY_UUID,
    VIN_REQUEST_MESSAGE,
    PROTOCOL_REQUEST_MESSAGE,
    CLOSE_MESSAGE,
    SCAN_INTERVAL,
    MIN_LINK_SECONDS_FOR_FAST_RECONNECT,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
    RESTORE_STATE_KEYS,
    VOLATILE_FIELDS,
    CONF_LOG_BLE_MESSAGES,
    CONF_DEVICE_NAME,
)
from .parsers import BikeDataParser

_LOGGER = logging.getLogger(__name__)


def storage_key(entry: ConfigEntry) -> str:
    """Return the .storage key holding the persisted state for a config entry."""
    return f"{DOMAIN}.{entry.entry_id}"


class MySmartBikeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching MySmartBike data.

    The coordinator is deliberately independent of the bike's availability: it
    is constructed from an address, resolves the `BLEDevice` on every connect
    attempt, and keeps serving the last known values while the bike is out of
    range or switched off.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self._address = address
        self._entry = entry
        self._client: BleakClient | None = None
        self._parser = BikeDataParser()
        self._is_connected = False
        self._connect_lock = asyncio.Lock()
        self._manual_disconnect = False  # Track if user manually disconnected
        self._last_seen: datetime | None = None
        self._save_armed = False
        self._unreachable_reason: str | None = None
        self._connecting = False
        self._advertisements_seen = 0
        self._connected_since: float | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry)
        )

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._address

    @property
    def is_connected(self) -> bool:
        """Return connection status."""
        return self._is_connected

    @property
    def last_seen(self) -> datetime | None:
        """Return when the last BLE notification was received, if ever."""
        return self._last_seen

    @property
    def vin(self) -> str | None:
        """Return the VIN/serial number if available."""
        return self._parser.vin

    @property
    def protocol_version(self) -> str | None:
        """Return the protocol version if available."""
        return self._parser.protocol_version

    def _resolve_device(self) -> Any:
        """Resolve the current BLEDevice for our address, or None if not in range.

        Resolved per attempt rather than cached: a device object handed out by a
        previous scan goes stale when the adapter or the proxy serving it changes.
        """
        return bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def async_restore(self) -> None:
        """Load the persisted state into the parser.

        Must run before the entity platforms are set up so entities see values
        (and the device serial number) on their very first state write.
        """
        try:
            stored = await self._store.async_load()
        except Exception as ex:  # noqa: BLE001 - never let a bad store block setup
            _LOGGER.warning("Could not read stored state for %s: %s", self._address, ex)
            stored = None

        if not stored:
            self.data = self._parser.state
            return

        for key in RESTORE_STATE_KEYS:
            value = stored.get(key)
            if not isinstance(value, dict):
                continue
            restored = dict(value)
            for field in VOLATILE_FIELDS.get(key, ()):
                restored[field] = None
            self._parser.state[key] = restored

        self._parser.vin = stored.get("vin")
        self._parser.protocol_version = stored.get("protocol_version")
        self._manual_disconnect = bool(stored.get("manual_disconnect", False))

        if last_seen := stored.get("last_seen"):
            self._last_seen = dt_util.parse_datetime(last_seen)

        self._parser.state["last_seen"] = self._last_seen
        self.data = self._parser.state
        _LOGGER.debug(
            "Restored state for %s (last seen %s, connection %s)",
            self._address,
            self._last_seen,
            "disabled" if self._manual_disconnect else "enabled",
        )

    def _persist_data(self) -> dict[str, Any]:
        """Build the payload written to .storage."""
        return {
            **{key: self._parser.state.get(key) for key in RESTORE_STATE_KEYS},
            "vin": self._parser.vin,
            "protocol_version": self._parser.protocol_version,
            "manual_disconnect": self._manual_disconnect,
            "last_seen": self._last_seen.isoformat() if self._last_seen else None,
        }

    def _schedule_save(self) -> None:
        """Throttle writes to one per STORAGE_SAVE_DELAY.

        `Store.async_delay_save` debounces rather than throttles - it pushes
        `_next_write_time` forward on every call. Notifications arrive about
        once a second while connected, so re-arming on each one would postpone
        the write for as long as the bike stays connected and nothing would
        ever reach disk except on a clean shutdown. Arming only when no write
        is outstanding turns that into a throttle; `_data_to_save` runs at
        write time, so the persisted snapshot is still current.
        """
        if self._save_armed:
            return
        self._save_armed = True
        self._store.async_delay_save(self._data_to_save, STORAGE_SAVE_DELAY)

    def _data_to_save(self) -> dict[str, Any]:
        """Store calls this at write time; re-arms the next throttle window."""
        self._save_armed = False
        return self._persist_data()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @callback
    def async_start_bluetooth_watch(self) -> CALLBACK_TYPE:
        """Connect as soon as the bike advertises, instead of waiting for the poll."""
        return bluetooth.async_register_callback(
            self.hass,
            self._async_device_appeared,
            BluetoothCallbackMatcher(address=self._address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )

    @callback
    def _async_claim_connect(self) -> bool:
        """Reserve the right to run one connect attempt.

        Home Assistant invokes the bluetooth callback on *every* advertisement,
        and these bikes advertise several times a second. Without a claim, a
        disconnected bike would queue hundreds of connect tasks behind
        `_connect_lock`, each running a full `establish_connection` retry cycle
        against a proxy that is already struggling to hold the link.
        """
        if self._is_connected or self._manual_disconnect or self._connecting:
            return False
        self._connecting = True
        return True

    @callback
    def _async_device_appeared(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        """Handle the bike showing up in range."""
        self._advertisements_seen += 1
        if not self._async_claim_connect():
            return
        _LOGGER.debug(
            "Advertisement from %s (%d seen) - connecting now",
            self._address,
            self._advertisements_seen,
        )
        self._entry.async_create_background_task(
            self.hass, self._async_run_connect(), f"{DOMAIN} connect {self._address}"
        )

    @callback
    def _async_client_disconnected(self, client: BleakClient) -> None:
        """Handle the bike dropping the link (powered off, out of range, slot lost).

        Without this the coordinator would keep believing it is connected, so
        `binary_sensor.connected` would lie and `_async_update_data` would never
        retry - the values would silently stop updating.
        """
        if self._client is not client:
            return  # our own _cleanup_client already took ownership
        _LOGGER.debug("Lost connection to %s", self._address)
        self._client = None
        self._is_connected = False
        self.async_update_listeners()

        # Don't sit out the poll interval. These bikes stop advertising after an
        # unexpected link loss, so the advertisement watch does not fire, and
        # every notification has just pushed the poll timer another 30s out -
        # leaving the bike disconnected far longer than necessary.
        held_for = (
            self.hass.loop.time() - self._connected_since
            if self._connected_since is not None
            else 0.0
        )
        self._connected_since = None
        if held_for < MIN_LINK_SECONDS_FOR_FAST_RECONNECT:
            # A link that died almost immediately would spin; let the poll retry.
            return
        if not self._async_claim_connect():
            return
        self._entry.async_create_background_task(
            self.hass, self._async_run_connect(), f"{DOMAIN} reconnect {self._address}"
        )

    async def async_first_connect(self) -> None:
        """Attempt the initial connection without blocking setup."""
        if self._manual_disconnect:
            _LOGGER.debug(
                "Not connecting to %s - connection was switched off by the user",
                self._address,
            )
            return
        await self._async_try_connect()

    async def _async_try_connect(self) -> None:
        """Run a connect attempt unless one is already in flight."""
        if not self._async_claim_connect():
            return
        await self._async_run_connect()

    async def _async_run_connect(self) -> None:
        """Connect, reporting the expected 'bike is off' failures once each."""
        try:
            await self._connect()
        except UpdateFailed as ex:
            self._async_report_unreachable(str(ex))
        except Exception as ex:  # noqa: BLE001
            self._async_report_unreachable(f"Connection attempt failed: {ex}")
        finally:
            self._connecting = False

    def _async_report_unreachable(self, reason: str) -> None:
        """Log why we cannot connect - once per distinct reason.

        The poll retries every SCAN_INTERVAL, so warning every time would spam
        the log for a bike that is simply parked. Warning on change still tells
        the user *why* nothing happens, which silence never did.
        """
        if reason != self._unreachable_reason:
            self._unreachable_reason = reason
            _LOGGER.warning("%s", reason)
        else:
            _LOGGER.debug("%s", reason)

    def _no_route_reason(self) -> str:
        """Explain why the address did not resolve to a connectable device.

        A bike seen only by passive proxies looks identical to a bike that is
        switched off unless we say so - Shelly proxies never offer connections,
        so the address is "present" but never connectable.
        """
        if bluetooth.async_address_present(self.hass, self._address, connectable=False):
            return (
                f"Device {self._address} is advertising, but no Bluetooth adapter or "
                "proxy that supports active connections can reach it. Shelly proxies "
                "are passive-only - a local adapter or an ESPHome proxy is required"
            )
        return f"Device {self._address} is not reachable - turn on the bike"

    async def _cleanup_client(self, send_close: bool = True, wait_for_slot: bool = True) -> None:
        """Clean up BLE client connection.

        Args:
            send_close: Whether to send close message to bike before disconnecting.
            wait_for_slot: Whether to wait for BLE connection slot release.
        """
        if not self._client:
            return

        client = self._client
        self._client = None
        self._is_connected = False

        try:
            if client.is_connected:
                if send_close:
                    try:
                        await client.write_gatt_char(WRITE_UUID, CLOSE_MESSAGE)
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass  # Ignore close message errors

                try:
                    await client.stop_notify(NOTIFY_UUID)
                except Exception:
                    pass  # Ignore notification stop errors

                try:
                    await client.disconnect()
                except Exception as ex:
                    _LOGGER.debug("Error during BLE disconnect: %s", ex)
        except Exception as ex:
            _LOGGER.debug("Unexpected error during client cleanup: %s", ex)
        finally:
            del client
            if wait_for_slot:
                await asyncio.sleep(3.0)  # Wait for BLE connection slot release
            # Let binary_sensor.connected drop immediately instead of at the next poll.
            self.async_update_listeners()

    async def async_disconnect(self) -> None:
        """Disconnect from the device (user initiated)."""
        _LOGGER.debug("User-initiated disconnect for %s", self._address)
        self._manual_disconnect = True
        self._schedule_save()
        await self._cleanup_client(send_close=True, wait_for_slot=True)

    async def async_reconnect(self) -> None:
        """Reconnect to the device (user initiated)."""
        _LOGGER.debug("User-initiated reconnect for %s", self._address)

        # Clean up any existing client first
        await self._cleanup_client(send_close=False, wait_for_slot=True)

        # Clear manual disconnect flag to allow auto-reconnect
        self._manual_disconnect = False
        self._schedule_save()

        try:
            await self._connect()
        except Exception as ex:
            error_str = str(ex).lower()
            if "not reachable" not in error_str and "turn on the bike" not in error_str:
                _LOGGER.error("Reconnect failed: %s", ex)
            raise

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh diagnostics and auto-reconnect; never fails the entities.

        Values are last-known-good rather than live, so an unreachable bike must
        not mark the coordinator unsuccessful - that would take every entity to
        `unavailable` and throw away the restored state.
        """
        # Auto-reconnect if not connected and not manually disconnected
        if not self._is_connected and not self._manual_disconnect:
            await self._async_try_connect()

        state = self._parser.state

        # Add RSSI (signal strength) to state - None while out of range
        try:
            service_info = bluetooth.async_last_service_info(
                self.hass, self._address, connectable=True
            )
            state["rssi"] = service_info.rssi if service_info else None
        except Exception:
            state["rssi"] = None

        state["last_seen"] = self._last_seen
        _LOGGER.debug(
            "%s: connected=%s advertisements_seen=%s rssi=%s",
            self._address,
            self._is_connected,
            self._advertisements_seen,
            state["rssi"],
        )
        return state

    async def _connect(self) -> None:
        """Connect to the device and start notifications."""
        async with self._connect_lock:
            if self._is_connected:
                return

            ble_device = self._resolve_device()
            if ble_device is None:
                raise UpdateFailed(self._no_route_reason())

            # Clean up any existing client before connecting
            if self._client:
                _LOGGER.debug("Cleaning up existing client before new connection")
                await self._cleanup_client(send_close=False, wait_for_slot=True)

            try:
                # Held in a local: the handshake sleeps, and a concurrent
                # disconnect (switch off, dropped link) may clear self._client
                # underneath us - reading it back mid-handshake would crash.
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    self._address,
                    disconnected_callback=self._async_client_disconnected,
                    ble_device_callback=self._resolve_device,
                )
                self._client = client

                # Start notifications and request device info
                await client.start_notify(NOTIFY_UUID, self._notification_handler)
                await client.write_gatt_char(WRITE_UUID, VIN_REQUEST_MESSAGE)
                await asyncio.sleep(0.2)
                await client.write_gatt_char(WRITE_UUID, PROTOCOL_REQUEST_MESSAGE)

                if self._client is not client:
                    # Torn down while we were setting up - don't claim success.
                    _LOGGER.debug("Connection to %s was cancelled", self._address)
                    return

                self._is_connected = True
                self._connected_since = self.hass.loop.time()
                self._unreachable_reason = None
                _LOGGER.debug("Connected to %s", self._address)

            except (BleakError, asyncio.TimeoutError) as ex:
                self._is_connected = False
                error_str = str(ex).lower()

                if "no longer reachable" in error_str or "out of connection slots" in error_str:
                    _LOGGER.warning("Device %s not reachable - turn on the bike", self._address)
                    raise UpdateFailed(f"Device {self._address} is not reachable") from ex
                else:
                    _LOGGER.error("Failed to connect to %s: %s", self._address, ex)
                    raise UpdateFailed(f"Failed to connect to device: {ex}") from ex

        # Outside the lock: entities pick up the new connection state immediately.
        self.async_update_listeners()

    def _notification_handler(self, sender: int, data: bytearray) -> None:
        """Handle notification data."""
        # Recognize message type before saving
        message_type = self._parser.recognize_message_type(bytes(data))
        _LOGGER.debug("BLE notification [%s]: %s", message_type, data.hex())

        # Save BLE message to file if option is enabled (run in executor to avoid blocking)
        if self._entry.options.get(CONF_LOG_BLE_MESSAGES, False):
            self.hass.async_add_executor_job(self._save_ble_message, data, message_type)

        # Parse the message
        self._parser.handle_message(bytes(data))

        self._last_seen = dt_util.utcnow()
        self._parser.state["last_seen"] = self._last_seen
        self._schedule_save()

        # Update coordinator data
        self.async_set_updated_data(self._parser.state)

    def _save_ble_message(self, data: bytearray, message_type: str = "unknown") -> None:
        """Save BLE message to a file."""
        try:
            # Get device name from config
            device_name = self._entry.data.get(CONF_DEVICE_NAME, "unknown_device")
            # Sanitize device name for use in filename
            safe_device_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in device_name)

            # Create date string for filename (one file per day): YYYYMMDD
            date_str = datetime.now().strftime("%Y%m%d")

            # Create filename with device name and date
            filename = f"{safe_device_name}_{date_str}_ble_messages.log"

            # Get component directory path
            component_dir = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(component_dir, "messages")

            # Create directory if it doesn't exist
            os.makedirs(log_dir, exist_ok=True)

            # Full file path
            filepath = os.path.join(log_dir, filename)

            # Try to decode data as string (handle non-UTF8 data gracefully)
            try:
                data_str = data.decode("utf-8", errors="replace")
                # Replace control characters and non-printable chars with their hex representation
                data_str_clean = "".join(
                    c if c.isprintable() else f"\\x{ord(c):02x}" for c in data_str
                )
            except Exception:
                data_str_clean = "<decode error>"

            # Format message with timestamp (human-readable with milliseconds)
            timestamp_readable = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            # Format the hex part with message type, then pad to column 75 for the string value
            hex_part = f"[{timestamp_readable}] Type: {message_type:20} Hex: {data.hex()}"
            # Pad to column 75 (or at least add separator if hex is already longer)
            padding = max(75 - len(hex_part), 2)
            message_line = f"{hex_part}{' ' * padding}String: {data_str_clean}\n"

            # Append to file
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(message_line)

        except Exception as ex:
            _LOGGER.error("Failed to save BLE message to file: %s", ex)

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        _LOGGER.debug("Shutting down coordinator")
        await super().async_shutdown()
        await self._cleanup_client(send_close=True, wait_for_slot=False)
        # Flush any pending debounced write so an unload never loses the state.
        await self._store.async_save(self._persist_data())
