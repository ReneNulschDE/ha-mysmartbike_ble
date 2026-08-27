"""The MySmartBike BLE integration."""
from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_DEVICE_ADDRESS, DOMAIN, STORAGE_VERSION
from .coordinator import MySmartBikeCoordinator, storage_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MySmartBike BLE from a config entry.

    Setup never depends on the bike being in range. A bike that is switched off
    or parked out of reach is the normal case, so the entry loads with the
    persisted state and the coordinator connects whenever the bike shows up.
    """
    address = entry.data[CONF_DEVICE_ADDRESS]

    coordinator = MySmartBikeCoordinator(hass, address, entry)
    # Restore before the platforms are set up so the entities' first state
    # write already carries the last known values and the serial number.
    await coordinator.async_restore()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Connect the moment the bike advertises instead of waiting for a poll tick.
    entry.async_on_unload(coordinator.async_start_bluetooth_watch())

    if bluetooth.async_ble_device_from_address(hass, address, connectable=True) is None:
        _LOGGER.info(
            "MySmartBike device %s not in range - showing last known values, "
            "will connect automatically once the bike is powered on",
            address,
        )

    entry.async_create_background_task(
        hass, coordinator.async_first_connect(), f"{DOMAIN} initial connect {address}"
    )

    _LOGGER.debug("MySmartBike BLE setup completed for %s", address)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: MySmartBikeCoordinator = entry.runtime_data
        await coordinator.async_shutdown()

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the persisted state when the bike is removed from Home Assistant."""
    await Store(hass, STORAGE_VERSION, storage_key(entry)).async_remove()
