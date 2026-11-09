"""Sensors for RTK-Base."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RTKBaseConfigEntry
from .const import DOMAIN
from .coordinator import RTKBaseCoordinator


@dataclass(frozen=True, kw_only=True)
class RTKBaseSensorDescription(SensorEntityDescription):
    """Describe an RTK-Base sensor."""

    value_key: str


SENSORS: tuple[RTKBaseSensorDescription, ...] = (
    RTKBaseSensorDescription(
        key="temperature",
        name="Temperature",
        value_key="temp_c",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="cpu_usage",
        name="CPU usage",
        value_key="cpu",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="memory_usage",
        name="Memory usage",
        value_key="mem_pct",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="memory_used",
        name="Memory used",
        value_key="memory_used_bytes",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="disk_usage",
        name="Disk usage",
        value_key="disk_pct",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="uptime",
        name="Uptime",
        value_key="uptime_seconds",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="load_1m",
        name="Load average (1 min)",
        value_key="load_1m",
        native_unit_of_measurement="load",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="load_5m",
        name="Load average (5 min)",
        value_key="load_5m",
        native_unit_of_measurement="load",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RTKBaseSensorDescription(
        key="load_15m",
        name="Load average (15 min)",
        value_key="load_15m",
        native_unit_of_measurement="load",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RTKBaseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up RTK-Base sensors."""
    coordinator: RTKBaseCoordinator = entry.runtime_data
    async_add_entities(
        RTKBaseSensor(coordinator, entry, description)
        for description in SENSORS
    )


class RTKBaseSensor(CoordinatorEntity[RTKBaseCoordinator], SensorEntity):
    """A system measurement from an RTK-Base Pi."""

    entity_description: RTKBaseSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RTKBaseCoordinator,
        entry: RTKBaseConfigEntry,
        description: RTKBaseSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name="RTK-Base",
            manufacturer="RTK-Base",
            model="Raspberry Pi",
        )

    @property
    def native_value(self) -> int | float | None:
        """Return a finite numeric reading or mark it unavailable."""
        value: Any = self.coordinator.data.get(self.entity_description.value_key)
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            return None
        return value

    @property
    def available(self) -> bool:
        """Keep individual missing measurements unavailable."""
        return self.coordinator.last_update_success and self.native_value is not None
