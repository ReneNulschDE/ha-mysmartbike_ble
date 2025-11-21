"""The MySmartBike BLE integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, CONF_DEVICE_ADDRESS
from .coordinator import MySmartBikeCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MySmartBike BLE from a config entry."""
    _LOGGER.debug("Setting up MySmartBike BLE integration for entry_id: %s", entry.entry_id)

    address = entry.data[CONF_DEVICE_ADDRESS]
    _LOGGER.debug("Device address from config: %s", address)

    # Get BLE device
    _LOGGER.debug("Looking up BLE device with address: %s", address)
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if not ble_device:
        # Log warning only once per config entry
        # Use hass.data for warning flag as it's separate from coordinator runtime_data
        hass.data.setdefault(DOMAIN, {})
        warning_key = f"warned_{entry.entry_id}"

        if not hass.data[DOMAIN].get(warning_key):
            _LOGGER.warning(
                "MySmartBike device with address %s not found. "
                "Make sure the bike is powered on and in range. "
                "Home Assistant will retry automatically",
                address
            )
            hass.data[DOMAIN][warning_key] = True
        raise ConfigEntryNotReady(f"Could not find MySmartBike device with address {address}")

    # Clear warning flag when device is found
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(f"warned_{entry.entry_id}", None)

    _LOGGER.debug("Found BLE device: %s", ble_device)

    # Create coordinator
    _LOGGER.debug("Creating coordinator for device %s", address)
    coordinator = MySmartBikeCoordinator(hass, ble_device, entry)

    # Perform first refresh
    _LOGGER.debug("Performing first coordinator refresh")
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.debug(
        "First refresh completed - coordinator state: is_connected=%s, manual_disconnect=%s",
        coordinator.is_connected,
        coordinator._manual_disconnect,
    )

    # Store coordinator in runtime_data
    entry.runtime_data = coordinator
    _LOGGER.debug("Coordinator stored in entry.runtime_data")

    # Forward entry setup to platforms
    _LOGGER.debug("Forwarding entry setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Platform setup completed")

    _LOGGER.debug("MySmartBike BLE integration setup completed successfully for entry_id: %s", entry.entry_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading MySmartBike BLE integration for entry_id: %s", entry.entry_id)

    # Unload platforms
    _LOGGER.debug("Unloading platforms: %s", PLATFORMS)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.debug("Platform unload result: %s", unload_ok)

    if unload_ok:
        coordinator: MySmartBikeCoordinator = entry.runtime_data
        _LOGGER.debug(
            "Coordinator retrieved from runtime_data - state: is_connected=%s, manual_disconnect=%s",
            coordinator.is_connected,
            coordinator._manual_disconnect,
        )
        await coordinator.async_shutdown()
        _LOGGER.debug("Coordinator shutdown completed")

        # Clean up warning flag from hass.data
        if DOMAIN in hass.data:
            hass.data[DOMAIN].pop(f"warned_{entry.entry_id}", None)
    else:
        _LOGGER.warning("Platform unload was not successful")

    _LOGGER.debug("MySmartBike BLE integration unload completed for entry_id: %s (result: %s)", entry.entry_id, unload_ok)
    return unload_ok
