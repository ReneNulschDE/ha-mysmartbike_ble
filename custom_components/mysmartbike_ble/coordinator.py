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

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._ble_device.address

    @property
    def is_connected(self) -> bool:
        """Return connection status."""
        return self._is_connected

    @property
    def vin(self) -> str | None:
        """Return the VIN/serial number if available."""
        return self._parser.vin

    @property
    def protocol_version(self) -> str | None:
        """Return the protocol version if available."""
        return self._parser.protocol_version

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

    async def async_disconnect(self) -> None:
        """Disconnect from the device (user initiated)."""
        _LOGGER.debug("User-initiated disconnect for %s", self._ble_device.address)
        self._manual_disconnect = True
        await self._cleanup_client(send_close=True, wait_for_slot=True)

    async def async_reconnect(self) -> None:
        """Reconnect to the device (user initiated)."""
        _LOGGER.debug("User-initiated reconnect for %s", self._ble_device.address)

        # Clean up any existing client first
        await self._cleanup_client(send_close=False, wait_for_slot=True)

        # Clear manual disconnect flag to allow auto-reconnect
        self._manual_disconnect = False

        try:
            await self._connect()
        except Exception as ex:
            error_str = str(ex).lower()
            if "not reachable" not in error_str and "turn on the bike" not in error_str:
                _LOGGER.error("Reconnect failed: %s", ex)
            raise

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the device."""
        # Auto-reconnect if not connected and not manually disconnected
        if not self._is_connected and not self._manual_disconnect:
            try:
                await self._connect()
            except Exception:
                pass  # Connection errors are logged in _connect()

        # Return current state from parser, ensure it's never None
        state = self._parser.state or {
            "battery_primary": None,
            "battery_secondary": None,
            "motor": None,
            "assist": None,
            "ebm": None,
        }

        # Add RSSI (signal strength) to state
        try:
            service_info = bluetooth.async_last_service_info(
                self.hass, self._ble_device.address, connectable=True
            )
            state["rssi"] = service_info.rssi if service_info else None
        except Exception:
            state["rssi"] = None

        return state

    async def _connect(self) -> None:
        """Connect to the device and start notifications."""
        # Clean up any existing client before connecting
        if self._client:
            _LOGGER.debug("Cleaning up existing client before new connection")
            await self._cleanup_client(send_close=False, wait_for_slot=True)

        try:
            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self._ble_device.address,
            )

            # Start notifications and request device info
            await self._client.start_notify(NOTIFY_UUID, self._notification_handler)
            await self._client.write_gatt_char(WRITE_UUID, VIN_REQUEST_MESSAGE)
            await asyncio.sleep(0.2)
            await self._client.write_gatt_char(WRITE_UUID, PROTOCOL_REQUEST_MESSAGE)

            self._is_connected = True
            _LOGGER.debug("Connected to %s", self._ble_device.address)

        except (BleakError, asyncio.TimeoutError) as ex:
            self._is_connected = False
            error_str = str(ex).lower()

            if "no longer reachable" in error_str or "out of connection slots" in error_str:
                _LOGGER.warning("Device %s not reachable - turn on the bike", self._ble_device.address)
                raise UpdateFailed(f"Device {self._ble_device.address} is not reachable") from ex
            else:
                _LOGGER.error("Failed to connect to %s: %s", self._ble_device.address, ex)
                raise UpdateFailed(f"Failed to connect to device: {ex}") from ex

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
        await self._cleanup_client(send_close=True, wait_for_slot=False)
