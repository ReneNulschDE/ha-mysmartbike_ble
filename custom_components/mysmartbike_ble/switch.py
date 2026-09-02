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
    def available(self) -> bool:
        """Return True - the connection wish can always be changed."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True if connection is desired (not manually disconnected).

        Restored from storage on startup, so a bike the user deliberately
        disconnected is not woken again by a Home Assistant restart.
        """
        return not self.coordinator._manual_disconnect

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:bluetooth-connect" if self.is_on else "mdi:bluetooth-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch - request connection to the bike.

        The switch reflects the *wish* to be connected, so it publishes the new
        state right away and leaves the retrying to the coordinator. Awaiting the
        connect attempt here used to leave the toggle looking stuck for up to a
        minute whenever no connectable adapter could reach the bike; the failure
        is reported by the coordinator, which also de-duplicates the logging.
        """
        self.coordinator.async_request_connect()
        self.async_write_ha_state()

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
