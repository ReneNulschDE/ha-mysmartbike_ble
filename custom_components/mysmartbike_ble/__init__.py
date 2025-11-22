"""The MySmartBike BLE integration."""
from __future__ import annotations

import logging

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
    address = entry.data[CONF_DEVICE_ADDRESS]

    # Get BLE device
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if not ble_device:
        # Log warning only once per config entry
        hass.data.setdefault(DOMAIN, {})
        warning_key = f"warned_{entry.entry_id}"

        if not hass.data[DOMAIN].get(warning_key):
            _LOGGER.warning(
                "MySmartBike device %s not found - ensure bike is powered on and in range",
                address
            )
            hass.data[DOMAIN][warning_key] = True
        raise ConfigEntryNotReady(f"Could not find MySmartBike device with address {address}")

    # Clear warning flag when device is found
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(f"warned_{entry.entry_id}", None)

    # Create and initialize coordinator
    coordinator = MySmartBikeCoordinator(hass, ble_device, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.debug("MySmartBike BLE setup completed for %s", address)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: MySmartBikeCoordinator = entry.runtime_data
        await coordinator.async_shutdown()

        # Clean up warning flag from hass.data
        if DOMAIN in hass.data:
            hass.data[DOMAIN].pop(f"warned_{entry.entry_id}", None)

    return unload_ok
