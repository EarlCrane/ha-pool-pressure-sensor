"""Manual event buttons for Pool Filter Analytics."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PoolFilterAnalyticsCoordinator


@dataclass(frozen=True, kw_only=True)
class PoolAnalyticsButtonDescription(ButtonEntityDescription):
    """Describe a manual analytics event button."""

    press_fn: Callable[[PoolFilterAnalyticsCoordinator], Awaitable[None]]


BUTTONS: tuple[PoolAnalyticsButtonDescription, ...] = (
    PoolAnalyticsButtonDescription(
        key="mark_bump",
        translation_key="mark_bump",
        icon="mdi:filter-cog-outline",
        press_fn=lambda coordinator: coordinator.async_mark_bump(),
    ),
    PoolAnalyticsButtonDescription(
        key="mark_backwash",
        translation_key="mark_backwash",
        icon="mdi:filter-sync-outline",
        press_fn=lambda coordinator: coordinator.async_mark_backwash(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Pool Filter Analytics buttons."""
    coordinator: PoolFilterAnalyticsCoordinator = entry.runtime_data
    async_add_entities(
        PoolFilterAnalyticsButton(coordinator, entry, description)
        for description in BUTTONS
    )


class PoolFilterAnalyticsButton(
    CoordinatorEntity[PoolFilterAnalyticsCoordinator], ButtonEntity
):
    """Represent a manually marked filter event."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PoolFilterAnalyticsCoordinator,
        entry: ConfigEntry,
        description: PoolAnalyticsButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="EarlCrane",
            model="Pool Filter Analytics",
        )

    async def async_press(self) -> None:
        """Mark the configured filter event."""
        await self.entity_description.press_fn(self.coordinator)
