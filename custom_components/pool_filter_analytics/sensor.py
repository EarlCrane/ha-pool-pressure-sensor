"""Sensor entities for Pool Filter Analytics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPressure, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolFilterAnalyticsCoordinator
from .models import AnalyticsEngine


@dataclass(frozen=True, kw_only=True)
class PoolAnalyticsSensorDescription(SensorEntityDescription):
    """Describe a Pool Filter Analytics sensor."""

    value_fn: Callable[[AnalyticsEngine], str | int | float | None]


SENSORS: tuple[PoolAnalyticsSensorDescription, ...] = (
    PoolAnalyticsSensorDescription(
        key="state",
        translation_key="state",
        icon="mdi:pool",
        value_fn=lambda engine: engine.state,
    ),
    PoolAnalyticsSensorDescription(
        key="bump_count",
        translation_key="bump_count",
        icon="mdi:counter",
        value_fn=lambda engine: engine.bump_count,
    ),
    PoolAnalyticsSensorDescription(
        key="cycle_age",
        translation_key="cycle_age",
        icon="mdi:calendar-clock",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda engine: engine.cycle_age_hours(datetime.now(UTC)),
    ),
    PoolAnalyticsSensorDescription(
        key="pressure_before",
        translation_key="pressure_before",
        icon="mdi:gauge",
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda engine: engine.pressure_before,
    ),
    PoolAnalyticsSensorDescription(
        key="pressure_after",
        translation_key="pressure_after",
        icon="mdi:gauge-low",
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda engine: engine.pressure_after,
    ),
    PoolAnalyticsSensorDescription(
        key="recovery_progress",
        translation_key="recovery_progress",
        icon="mdi:progress-clock",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda engine: engine.recovery_progress,
    ),
    PoolAnalyticsSensorDescription(
        key="recovery_elapsed",
        translation_key="recovery_elapsed",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda engine: engine.recovery_elapsed_hours,
    ),
    PoolAnalyticsSensorDescription(
        key="last_recovery_time",
        translation_key="last_recovery_time",
        icon="mdi:timer-check-outline",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda engine: engine.last_recovery_hours,
    ),
    PoolAnalyticsSensorDescription(
        key="tau",
        translation_key="tau",
        icon="mdi:chart-bell-curve-cumulative",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda engine: engine.tau_hours,
    ),
    PoolAnalyticsSensorDescription(
        key="fit_quality",
        translation_key="fit_quality",
        icon="mdi:chart-scatter-plot",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda engine: (
            round(engine.fit_quality * 100, 1)
            if engine.fit_quality is not None
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Pool Filter Analytics sensors."""
    coordinator: PoolFilterAnalyticsCoordinator = entry.runtime_data
    async_add_entities(
        PoolFilterAnalyticsSensor(coordinator, entry, description)
        for description in SENSORS
    )


class PoolFilterAnalyticsSensor(
    CoordinatorEntity[PoolFilterAnalyticsCoordinator], SensorEntity
):
    """Represent one analytics value."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolFilterAnalyticsCoordinator,
        entry: ConfigEntry,
        description: PoolAnalyticsSensorDescription,
    ) -> None:
        """Initialize an analytics sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="EarlCrane",
            model="Pool Filter Analytics",
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Read the latest value from the in-memory model."""
        self._attr_native_value = self.entity_description.value_fn(
            self.coordinator.engine
        )
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Populate the initial value before registering updates."""
        self._attr_native_value = self.entity_description.value_fn(
            self.coordinator.engine
        )
        await super().async_added_to_hass()
