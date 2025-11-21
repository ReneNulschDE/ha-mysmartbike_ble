"""Binary sensor platform for MySmartBike BLE integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up MySmartBike BLE binary sensor entities."""
    coordinator: MySmartBikeCoordinator = entry.runtime_data

    async_add_entities([MySmartBikeConnectionSensor(coordinator, entry)])


class MySmartBikeConnectionSensor(CoordinatorEntity[MySmartBikeCoordinator], BinarySensorEntity):
    """Binary sensor showing BLE connection status to the bike."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: MySmartBikeCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }
        if coordinator.vin:
            self._attr_device_info["serial_number"] = coordinator.vin
        if coordinator.protocol_version:
            self._attr_device_info["sw_version"] = coordinator.protocol_version
        self._attr_translation_key = "connected"

    @property
    def is_on(self) -> bool:
        """Return True if connected to the bike."""
        return self.coordinator.is_connected

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Connected"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:bluetooth-connect" if self.is_on else "mdi:bluetooth-off"
