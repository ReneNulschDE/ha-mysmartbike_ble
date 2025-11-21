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
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    WRITE_UUID,
    NOTIFY_UUID,
    VIN_REQUEST_MESSAGE,
    PROTOCOL_REQUEST_MESSAGE,
    CLOSE_MESSAGE,
    SCAN_INTERVAL,
    CONF_LOG_BLE_MESSAGES,
    CONF_DEVICE_NAME,
)
from .parsers import BikeDataParser

_LOGGER = logging.getLogger(__name__)


class MySmartBikeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching MySmartBike data."""

    def __init__(
        self,
        hass: HomeAssistant,
        ble_device: BluetoothServiceInfoBleak,
        entry: ConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self._ble_device = ble_device
        self._entry = entry
        self._client: BleakClient | None = None
        self._parser = BikeDataParser()
        self._is_connected = False
        self._notify_task: asyncio.Task | None = None
        self._manual_disconnect = False  # Track if user manually disconnected
        _LOGGER.debug(
            "Coordinator initialized: address=%s, is_connected=%s, manual_disconnect=%s, scan_interval=%s",
            ble_device.address,
            self._is_connected,
            self._manual_disconnect,
            SCAN_INTERVAL,
        )

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._ble_device.address

    @property
    def is_connected(self) -> bool:
        """Return connection status."""
        _LOGGER.debug(
            "Coordinator.is_connected property called: returning %s (manual_disconnect: %s)",
            self._is_connected,
            self._manual_disconnect,
        )
        return self._is_connected

    @property
    def vin(self) -> str | None:
        """Return the VIN/serial number if available."""
        return self._parser.vin

    @property
    def protocol_version(self) -> str | None:
        """Return the protocol version if available."""
        return self._parser.protocol_version

    async def async_disconnect(self) -> None:
        """Disconnect from the device (user initiated)."""
        _LOGGER.debug(
            "Coordinator.async_disconnect called for %s (user initiated) - current state: is_connected=%s, manual_disconnect=%s, client=%s",
            self._ble_device.address,
            self._is_connected,
            self._manual_disconnect,
            self._client is not None,
        )

        # Mark as manually disconnected to prevent auto-reconnect
        self._manual_disconnect = True
        _LOGGER.debug("Coordinator.async_disconnect: Set manual_disconnect=True")

        if self._client:
            _LOGGER.debug("Coordinator.async_disconnect: Client exists, cleaning up connection")
            client_to_cleanup = self._client
            self._client = None  # Clear reference immediately
            self._is_connected = False

            try:
                # Only send close message if still connected
                if client_to_cleanup.is_connected:
                    # Send close message to bike before disconnecting
                    _LOGGER.debug("Coordinator.async_disconnect: Sending close message ($D$I#@)")
                    try:
                        await client_to_cleanup.write_gatt_char(WRITE_UUID, CLOSE_MESSAGE)
                        _LOGGER.debug("Coordinator.async_disconnect: Close message sent")
                        await asyncio.sleep(0.5)
                    except Exception as ex:
                        _LOGGER.debug("Coordinator.async_disconnect: Error sending close message: %s", ex)

                    # Stop notifications
                    try:
                        await client_to_cleanup.stop_notify(NOTIFY_UUID)
                        _LOGGER.debug("Coordinator.async_disconnect: Stopped notifications")
                    except Exception as ex:
                        _LOGGER.debug("Coordinator.async_disconnect: Error stopping notifications: %s", ex)

                    # Disconnect from device
                    try:
                        await client_to_cleanup.disconnect()
                        _LOGGER.debug("Coordinator.async_disconnect: Disconnected from device")
                    except Exception as ex:
                        _LOGGER.debug("Coordinator.async_disconnect: Error during disconnect: %s", ex)
                else:
                    _LOGGER.debug("Coordinator.async_disconnect: Client exists but not connected, skipping disconnect")

            except Exception as ex:
                _LOGGER.debug("Coordinator.async_disconnect: Unexpected error during disconnect: %s", ex, exc_info=True)
            finally:
                # Force delete the client object to help garbage collection
                del client_to_cleanup

                # Give BLE adapter significant time to release connection slot
                _LOGGER.debug("Coordinator.async_disconnect: Waiting for connection slot release (3 seconds)")
                await asyncio.sleep(3.0)
                _LOGGER.debug("Coordinator.async_disconnect: Cleaned up client (is_connected=%s)", self._is_connected)
        else:
            _LOGGER.debug("Coordinator.async_disconnect: No client to disconnect")
            self._is_connected = False

        _LOGGER.debug(
            "Coordinator.async_disconnect completed - final state: is_connected=%s, manual_disconnect=%s",
            self._is_connected,
            self._manual_disconnect,
        )

    async def async_reconnect(self) -> None:
        """Reconnect to the device (user initiated)."""
        _LOGGER.debug(
            "Coordinator.async_reconnect called for %s (user initiated) - current state: is_connected=%s, manual_disconnect=%s, client=%s",
            self._ble_device.address,
            self._is_connected,
            self._manual_disconnect,
            self._client is not None,
        )

        # Clean up any existing client first
        if self._client:
            _LOGGER.debug("Coordinator.async_reconnect: Found existing client, cleaning up first")
            old_client = self._client
            self._client = None
            self._is_connected = False

            try:
                if old_client.is_connected:
                    await old_client.disconnect()
                    _LOGGER.debug("Coordinator.async_reconnect: Disconnected existing client")
            except Exception as ex:
                _LOGGER.debug("Coordinator.async_reconnect: Error disconnecting old client: %s", ex)
            finally:
                del old_client
                # Wait longer for connection slot to be released
                _LOGGER.debug("Coordinator.async_reconnect: Waiting for connection slot release (3 seconds)")
                await asyncio.sleep(3.0)
                _LOGGER.debug("Coordinator.async_reconnect: Cleaned up old client and waited for slot release")

        # Clear manual disconnect flag to allow auto-reconnect
        self._manual_disconnect = False
        _LOGGER.debug("Coordinator.async_reconnect: Set manual_disconnect=False")

        try:
            await self._connect()
            _LOGGER.debug(
                "Coordinator.async_reconnect completed - final state: is_connected=%s, manual_disconnect=%s",
                self._is_connected,
                self._manual_disconnect,
            )
        except Exception as ex:
            # Only log as error if it's not a "device not reachable" issue
            error_str = str(ex).lower()
            if "not reachable" in error_str or "turn on the bike" in error_str:
                _LOGGER.debug("Coordinator.async_reconnect: Device not reachable, will retry later")
            else:
                _LOGGER.error("Coordinator.async_reconnect failed: %s", ex, exc_info=True)
            raise

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the device."""
        _LOGGER.debug(
            "Coordinator._async_update_data called - current state: is_connected=%s, manual_disconnect=%s",
            self._is_connected,
            self._manual_disconnect,
        )

        # Don't auto-reconnect if user manually disconnected
        if not self._is_connected and not self._manual_disconnect:
            _LOGGER.debug("Coordinator._async_update_data: Not connected and not manual disconnect, attempting auto-reconnect")
            try:
                await self._connect()
                _LOGGER.debug("Coordinator._async_update_data: Auto-reconnect successful (is_connected=%s)", self._is_connected)
            except Exception as ex:
                # Only log as warning if device is not reachable, otherwise debug
                error_str = str(ex).lower()
                if "not reachable" in error_str or "turn on the bike" in error_str:
                    _LOGGER.debug("Coordinator._async_update_data: Auto-reconnect skipped - device not reachable")
                else:
                    _LOGGER.debug("Coordinator._async_update_data: Auto-reconnect failed: %s", ex)
        elif not self._is_connected and self._manual_disconnect:
            _LOGGER.debug("Coordinator._async_update_data: Not connected but manual_disconnect=True, skipping auto-reconnect")
        else:
            _LOGGER.debug("Coordinator._async_update_data: Already connected, no action needed")

        # Return current state from parser, ensure it's never None
        state = self._parser.state or {
            "battery_primary": None,
            "battery_secondary": None,
            "motor": None,
            "assist": None,
            "ebm": None,
        }

        # Add RSSI (signal strength) to state
        # Get latest service info which contains current RSSI
        try:
            service_info = bluetooth.async_last_service_info(
                self.hass, self._ble_device.address, connectable=True
            )
            state["rssi"] = service_info.rssi if service_info else None
        except Exception as ex:
            _LOGGER.debug("Could not get RSSI: %s", ex)
            state["rssi"] = None

        _LOGGER.debug("Coordinator._async_update_data: Returning state (has_data=%s, rssi=%s)", self._parser.state is not None, state.get("rssi"))
        return state

    async def _connect(self) -> None:
        """Connect to the device and start notifications."""
        _LOGGER.debug(
            "Coordinator._connect: Attempting to connect to %s (current is_connected=%s, manual_disconnect=%s, client=%s)",
            self._ble_device.address,
            self._is_connected,
            self._manual_disconnect,
            self._client is not None,
        )

        # Clean up any existing client before connecting
        if self._client:
            _LOGGER.warning("Coordinator._connect: Client already exists, cleaning up before new connection")
            old_client = self._client
            self._client = None
            try:
                if old_client.is_connected:
                    await old_client.disconnect()
            except Exception as ex:
                _LOGGER.debug("Coordinator._connect: Error cleaning up old client: %s", ex)
            finally:
                del old_client
                _LOGGER.debug("Coordinator._connect: Waiting for connection slot release (3 seconds)")
                await asyncio.sleep(3.0)

        try:
            _LOGGER.debug("Coordinator._connect: Calling establish_connection for %s", self._ble_device.address)

            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._ble_device.address,
            )

            _LOGGER.debug("Coordinator._connect: Successfully connected to %s, client=%s", self._ble_device.address, self._client)

            # Start notifications first
            _LOGGER.debug("Coordinator._connect: Starting notifications on UUID %s", NOTIFY_UUID)
            await self._client.start_notify(NOTIFY_UUID, self._notification_handler)
            _LOGGER.debug("Coordinator._connect: Started notifications successfully")

            # Request VIN/serial number ($S$V#@)
            _LOGGER.debug("Coordinator._connect: Requesting VIN/serial number")
            await self._client.write_gatt_char(WRITE_UUID, VIN_REQUEST_MESSAGE)
            _LOGGER.debug("Coordinator._connect: VIN request sent")

            # Small delay between requests
            await asyncio.sleep(0.2)

            # Request protocol version ($S$P#@)
            _LOGGER.debug("Coordinator._connect: Requesting protocol version")
            await self._client.write_gatt_char(WRITE_UUID, PROTOCOL_REQUEST_MESSAGE)
            _LOGGER.debug("Coordinator._connect: Protocol request sent")

            self._is_connected = True
            _LOGGER.debug("Coordinator._connect: Set is_connected=True")

        except (BleakError, asyncio.TimeoutError) as ex:
            self._is_connected = False

            # Check if error is due to device not being reachable (turned off)
            error_str = str(ex).lower()
            if "no longer reachable" in error_str or "out of connection slots" in error_str:
                _LOGGER.warning(
                    "Coordinator._connect: Device %s is not reachable or powered off. "
                    "Turn on the bike to connect.",
                    self._ble_device.address
                )
                raise UpdateFailed(
                    f"Device {self._ble_device.address} is not reachable. "
                    "Please turn on the bike."
                ) from ex
            else:
                _LOGGER.error(
                    "Coordinator._connect: Failed to connect to device %s: %s (is_connected set to False)",
                    self._ble_device.address,
                    ex,
                    exc_info=True,
                )
                raise UpdateFailed(f"Failed to connect to device: {ex}") from ex

    def _notification_handler(self, sender: int, data: bytearray) -> None:
        """Handle notification data."""
        _LOGGER.debug("Received notification from %s: %s", sender, data.hex())

        # Recognize message type before saving
        message_type = self._parser.recognize_message_type(bytes(data))

        # Save BLE message to file if option is enabled (run in executor to avoid blocking)
        if self._entry.options.get(CONF_LOG_BLE_MESSAGES, False):
            self.hass.async_add_executor_job(self._save_ble_message, data, message_type)

        # Parse the message
        self._parser.handle_message(bytes(data))

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

            _LOGGER.debug("Saved BLE message to: %s", filepath)

        except Exception as ex:
            _LOGGER.error("Failed to save BLE message to file: %s", ex, exc_info=True)

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        _LOGGER.debug(
            "Coordinator.async_shutdown called - current state: is_connected=%s, manual_disconnect=%s, client=%s",
            self._is_connected,
            self._manual_disconnect,
            self._client is not None,
        )

        if self._client:
            _LOGGER.debug("Coordinator.async_shutdown: Client exists, cleaning up connection")
            client_to_cleanup = self._client
            self._client = None
            self._is_connected = False

            try:
                # Only send close message if still connected
                if client_to_cleanup.is_connected:
                    # Send close message to bike before disconnecting
                    try:
                        _LOGGER.debug("Coordinator.async_shutdown: Sending close message ($D$I#@)")
                        await client_to_cleanup.write_gatt_char(WRITE_UUID, CLOSE_MESSAGE)
                        _LOGGER.debug("Coordinator.async_shutdown: Close message sent")
                        await asyncio.sleep(0.5)
                    except Exception as ex:
                        _LOGGER.debug("Coordinator.async_shutdown: Error sending close message: %s", ex)

                    # Stop notifications
                    try:
                        await client_to_cleanup.stop_notify(NOTIFY_UUID)
                        _LOGGER.debug("Coordinator.async_shutdown: Stopped notifications")
                    except Exception as ex:
                        _LOGGER.debug("Coordinator.async_shutdown: Error stopping notifications: %s", ex)

                    # Disconnect from device
                    try:
                        await client_to_cleanup.disconnect()
                        _LOGGER.debug("Coordinator.async_shutdown: Disconnected from device")
                    except Exception as ex:
                        _LOGGER.debug("Coordinator.async_shutdown: Error during disconnect: %s", ex)
                else:
                    _LOGGER.debug("Coordinator.async_shutdown: Client exists but not connected, skipping disconnect")

            except Exception as ex:
                _LOGGER.debug("Coordinator.async_shutdown: Unexpected error during shutdown: %s", ex, exc_info=True)
            finally:
                del client_to_cleanup
                _LOGGER.debug("Coordinator.async_shutdown: Cleaned up client")
        else:
            _LOGGER.debug("Coordinator.async_shutdown: No client to clean up")
            self._is_connected = False

        _LOGGER.debug("Coordinator.async_shutdown completed")
