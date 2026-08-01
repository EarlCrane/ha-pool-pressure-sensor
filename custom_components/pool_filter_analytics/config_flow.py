"""Config flow for Pool Filter Analytics."""

from __future__ import annotations

import math
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_MINIMUM_DROP,
    CONF_OFFLINE_THRESHOLD,
    CONF_SAMPLE_INTERVAL,
    CONF_SOURCE_ENTITY,
    DEFAULT_MINIMUM_DROP,
    DEFAULT_OFFLINE_THRESHOLD,
    DEFAULT_SAMPLE_INTERVAL,
    DOMAIN,
)


class PoolFilterAnalyticsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Pool Filter Analytics config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select a pressure history sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            source_entity = user_input[CONF_SOURCE_ENTITY]
            state = self.hass.states.get(source_entity)
            if state is None:
                errors[CONF_SOURCE_ENTITY] = "entity_not_found"
            else:
                try:
                    value = float(state.state)
                except (TypeError, ValueError):
                    errors[CONF_SOURCE_ENTITY] = "not_numeric"
                else:
                    if not math.isfinite(value) or value < 0:
                        errors[CONF_SOURCE_ENTITY] = "not_numeric"

            if not errors:
                await self.async_set_unique_id(source_entity)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Pool Filter Analytics",
                    data={CONF_SOURCE_ENTITY: source_entity},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SOURCE_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PoolFilterAnalyticsOptionsFlow:
        """Create the options flow."""
        return PoolFilterAnalyticsOptionsFlow()


class PoolFilterAnalyticsOptionsFlow(config_entries.OptionsFlow):
    """Configure recovery detection thresholds."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OFFLINE_THRESHOLD,
                        default=options.get(
                            CONF_OFFLINE_THRESHOLD, DEFAULT_OFFLINE_THRESHOLD
                        ),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0, max=20)),
                    vol.Required(
                        CONF_MINIMUM_DROP,
                        default=options.get(CONF_MINIMUM_DROP, DEFAULT_MINIMUM_DROP),
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=20)),
                    vol.Required(
                        CONF_SAMPLE_INTERVAL,
                        default=options.get(
                            CONF_SAMPLE_INTERVAL, DEFAULT_SAMPLE_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                }
            ),
        )
