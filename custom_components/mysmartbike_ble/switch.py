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
    _LOGGER.debug("Setting up switch platform for entry_id: %s", entry.entry_id)
    coordinator: MySmartBikeCoordinator = entry.runtime_data

    _LOGGER.debug("Adding connection switch entity (coordinator.is_connected: %s)", coordinator.is_connected)
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
        _LOGGER.debug(
            "Switch initialized: unique_id=%s, coordinator.is_connected=%s",
            self._attr_unique_id,
            coordinator.is_connected,
        )

    @property
    def is_on(self) -> bool:
        """Return True if connection is desired (not manually disconnected)."""
        # Switch represents the desired state, not the actual connection status
        # If manual_disconnect is False, user wants to be connected
        state = not self.coordinator._manual_disconnect
        _LOGGER.debug(
            "Switch is_on property called: returning %s (manual_disconnect=%s, is_connected=%s)",
            state,
            self.coordinator._manual_disconnect,
            self.coordinator.is_connected
        )
        return state

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:bluetooth-connect" if self.is_on else "mdi:bluetooth-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch - request connection to the bike."""
        _LOGGER.debug(
            "Switch.async_turn_on called (current coordinator.is_connected: %s, manual_disconnect: %s)",
            self.coordinator.is_connected,
            self.coordinator._manual_disconnect,
        )

        # Update state immediately - switch is now ON (connection desired)
        self.async_write_ha_state()

        try:
            await self.coordinator.async_reconnect()
            _LOGGER.debug(
                "Switch.async_turn_on: reconnect completed (coordinator.is_connected: %s)",
                self.coordinator.is_connected,
            )
        except Exception as ex:
            # Provide user-friendly error message
            error_msg = str(ex)
            if "not reachable" in error_msg.lower():
                _LOGGER.warning(
                    "Switch.async_turn_on: Cannot connect now - bike is not reachable. "
                    "Will auto-connect when bike is powered on."
                )
            else:
                _LOGGER.error("Switch.async_turn_on: Failed to connect to bike: %s", ex, exc_info=True)
            # Switch stays ON - coordinator will auto-reconnect when bike becomes available

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch - disconnect from the bike.

        WARNING: This will turn off the bike after ~5 minutes! It must be manually
        turned on again or connected to power.
        """
        _LOGGER.warning(
            "Switch.async_turn_off called - Disconnecting from bike (current coordinator.is_connected: %s). "
            "Bike will turn off after approximately 5 minutes and must be manually turned on again or connected to power",
            self.coordinator.is_connected,
        )
        try:
            await self.coordinator.async_disconnect()
            _LOGGER.debug(
                "Switch.async_turn_off: disconnect completed (coordinator.is_connected: %s, manual_disconnect: %s)",
                self.coordinator.is_connected,
                self.coordinator._manual_disconnect,
            )
            self.async_write_ha_state()
            _LOGGER.debug("Switch.async_turn_off: state written to HA")
        except Exception as ex:
            _LOGGER.error("Switch.async_turn_off: Failed to disconnect from bike: %s", ex, exc_info=True)
