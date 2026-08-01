"""Event-driven coordinator for Pool Filter Analytics."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_MINIMUM_DROP,
    CONF_OFFLINE_THRESHOLD,
    CONF_SAMPLE_INTERVAL,
    CONF_SOURCE_ENTITY,
    DEFAULT_MINIMUM_DROP,
    DEFAULT_OFFLINE_THRESHOLD,
    DEFAULT_SAMPLE_INTERVAL,
    DOMAIN,
    STORAGE_VERSION,
)
from .models import AnalyticsEngine

_LOGGER = logging.getLogger(__name__)


class PoolFilterAnalyticsCoordinator(DataUpdateCoordinator[AnalyticsEngine]):
    """Coordinate source sensor changes and persisted analytics state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
        )
        self.entry = entry
        self.source_entity = entry.data[CONF_SOURCE_ENTITY]
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}",
        )
        self.engine = AnalyticsEngine(
            offline_threshold=float(
                entry.options.get(CONF_OFFLINE_THRESHOLD, DEFAULT_OFFLINE_THRESHOLD)
            ),
            minimum_drop=float(
                entry.options.get(CONF_MINIMUM_DROP, DEFAULT_MINIMUM_DROP)
            ),
            sample_interval_seconds=int(
                entry.options.get(CONF_SAMPLE_INTERVAL, DEFAULT_SAMPLE_INTERVAL)
            ),
        )
        self._unsub_state = None

    async def async_setup(self) -> None:
        """Restore state and subscribe to the configured pressure sensor."""
        if stored := await self._store.async_load():
            self.engine = AnalyticsEngine.from_dict(
                stored,
                offline_threshold=self.engine.offline_threshold,
                minimum_drop=self.engine.minimum_drop,
                sample_interval_seconds=self.engine.sample_interval_seconds,
            )

        if (
            pressure := self._pressure_from_state(
                self.hass.states.get(self.source_entity)
            )
        ) is not None:
            self.engine.handle_sample(datetime.now(UTC), pressure)

        self.async_set_updated_data(self.engine)
        self._unsub_state = async_track_state_change_event(
            self.hass,
            [self.source_entity],
            self._async_source_changed,
        )

    async def async_shutdown(self) -> None:
        """Remove source listeners and persist the latest state."""
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        await self._store.async_save(self.engine.as_dict())
        await super().async_shutdown()

    @callback
    def _async_source_changed(self, event: Event) -> None:
        """Process a source entity state change."""
        pressure = self._pressure_from_state(event.data.get("new_state"))
        if pressure is None:
            return
        if self.engine.handle_sample(datetime.now(UTC), pressure):
            self.async_set_updated_data(self.engine)
            self._schedule_save()

    async def async_mark_bump(self) -> None:
        """Manually mark the start of a bump maintenance sequence."""
        pressure = self._pressure_from_state(self.hass.states.get(self.source_entity))
        if pressure is None:
            raise HomeAssistantError(
                f"{self.source_entity} does not currently have a numeric pressure"
            )
        self.engine.mark_bump(datetime.now(UTC), pressure)
        self.async_set_updated_data(self.engine)
        await self._store.async_save(self.engine.as_dict())

    async def async_mark_backwash(self) -> None:
        """Manually mark a full backwash and reset the filter cycle."""
        pressure = self._pressure_from_state(self.hass.states.get(self.source_entity))
        self.engine.mark_backwash(datetime.now(UTC), pressure)
        self.async_set_updated_data(self.engine)
        await self._store.async_save(self.engine.as_dict())

    @callback
    def _schedule_save(self) -> None:
        """Coalesce frequent sample persistence writes."""
        self._store.async_delay_save(self.engine.as_dict, 30)

    @staticmethod
    def _pressure_from_state(state: State | None) -> float | None:
        """Return a finite, non-negative numeric state."""
        if state is None:
            return None
        try:
            pressure = float(state.state)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(pressure) or pressure < 0:
            return None
        return pressure
