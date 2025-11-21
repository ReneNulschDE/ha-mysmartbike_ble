"""Sensor platform for MySmartBike BLE integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, CONF_DEVICE_NAME
from .coordinator import MySmartBikeCoordinator


def safe_get(data: dict[str, Any] | None, *keys: str) -> Any:
    """Safely get nested dictionary values."""
    if data is None:
        return None

    result = data
    for key in keys:
        if result is None or not isinstance(result, dict):
            return None
        result = result.get(key)
    return result


@dataclass
class MySmartBikeSensorEntityDescription(SensorEntityDescription):
    """Describes MySmartBike sensor entity."""

    value_fn: callable[[dict[str, Any]], Any] | None = None


SENSORS: tuple[MySmartBikeSensorEntityDescription, ...] = (
    # Battery Primary Sensors
    MySmartBikeSensorEntityDescription(
        key="battery_primary_soc",
        name="Battery SoC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_get(data, "battery_primary", "soc"),
    ),
    MySmartBikeSensorEntityDescription(
        key="battery_primary_temperature",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_get(data, "battery_primary", "temperature"),
    ),
    MySmartBikeSensorEntityDescription(
        key="battery_primary_remaining_wh",
        name="Battery Remaining Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_get(data, "battery_primary", "remaining_wh"),
    ),
    # Motor Sensors
    MySmartBikeSensorEntityDescription(
        key="motor_assist_level",
        name="Assist Level",
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: safe_get(data, "motor", "assist_level"),
    ),
    MySmartBikeSensorEntityDescription(
        key="motor_temperature",
        name="Motor Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: safe_get(data, "motor", "temperature_celsius"),
    ),
    MySmartBikeSensorEntityDescription(
        key="motor_speed",
        name="Speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        value_fn=lambda data: safe_get(data, "motor", "speed_kmh"),
    ),
    # EBM Sensors
    MySmartBikeSensorEntityDescription(
        key="odometer",
        name="Odometer",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda data: safe_get(data, "ebm", "odometry"),
    ),
    MySmartBikeSensorEntityDescription(
        key="range",
        name="Range",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:map-marker-distance",
        value_fn=lambda data: safe_get(data, "ebm", "autonomy"),
    ),
    MySmartBikeSensorEntityDescription(
        key="light",
        name="Light",
        icon="mdi:lightbulb",
        value_fn=lambda data: "On" if safe_get(data, "ebm", "is_light_on") else ("Off" if safe_get(data, "ebm") else None),
    ),
    MySmartBikeSensorEntityDescription(
        key="ebm_status",
        name="EBM Status",
        icon="mdi:information",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: safe_get(data, "ebm", "status"),
    ),
    # Connection Diagnostic Sensors
    MySmartBikeSensorEntityDescription(
        key="rssi",
        name="Signal Strength",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:wifi",
        value_fn=lambda data: safe_get(data, "rssi"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MySmartBike BLE sensors."""
    coordinator: MySmartBikeCoordinator = entry.runtime_data

    async_add_entities(
        MySmartBikeSensor(coordinator, entry, description)
        for description in SENSORS
    )


class MySmartBikeSensor(CoordinatorEntity[MySmartBikeCoordinator], SensorEntity):
    """Representation of a MySmartBike sensor."""

    entity_description: MySmartBikeSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MySmartBikeCoordinator,
        entry: ConfigEntry,
        description: MySmartBikeSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        device_name = entry.data[CONF_DEVICE_NAME]
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Build device info with optional serial number (VIN)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": device_name,
            "manufacturer": MANUFACTURER,
            "model": MODEL,
        }
        # Add serial number if available
        if coordinator.vin:
            self._attr_device_info["serial_number"] = coordinator.vin
        # Add protocol version as software version
        if coordinator.protocol_version:
            self._attr_device_info["sw_version"] = coordinator.protocol_version

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return None
