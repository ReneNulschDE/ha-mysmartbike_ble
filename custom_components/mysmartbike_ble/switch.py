"""Switch platform for MySmartBike BLE integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MySmartBikeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MySmartBike BLE switch entities."""
    coordinator: MySmartBikeCoordinator = entry.runtime_data
    async_add_entities([MySmartBikeConnectionSwitch(coordinator, entry)])


class MySmartBikeConnectionSwitch(CoordinatorEntity[MySmartBikeCoordinator], SwitchEntity):
    """Switch to control BLE connection to the bike."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MySmartBikeCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connection"
        # Build device info with optional serial number (VIN)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }
        if coordinator.vin:
            self._attr_device_info["serial_number"] = coordinator.vin
        if coordinator.protocol_version:
            self._attr_device_info["sw_version"] = coordinator.protocol_version
        self._attr_translation_key = "connection"

    @property
    def is_on(self) -> bool:
        """Return True if connection is desired (not manually disconnected)."""
        return not self.coordinator._manual_disconnect

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:bluetooth-connect" if self.is_on else "mdi:bluetooth-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch - request connection to the bike."""
        self.async_write_ha_state()

        try:
            await self.coordinator.async_reconnect()
        except Exception as ex:
            error_msg = str(ex).lower()
            if "not reachable" in error_msg:
                _LOGGER.warning("Cannot connect - bike not reachable. Will auto-connect when available.")
            else:
                _LOGGER.error("Failed to connect to bike: %s", ex)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch - disconnect from the bike.

        WARNING: This will turn off the bike after ~5 minutes! It must be manually
        turned on again or connected to power.
        """
        _LOGGER.warning("Disconnecting from bike - it will turn off after ~5 minutes")
        try:
            await self.coordinator.async_disconnect()
            self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.error("Failed to disconnect from bike: %s", ex)
