"""Config flow for Marstek Venus HA integration."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_GRID_POWER_SENSOR,
    CONF_SMOOTHING_SECONDS,
    CONF_BATTERY_1_ENTITY,
    CONF_BATTERY_2_ENTITY,
    CONF_BATTERY_3_ENTITY,
    CONF_MIN_SOC,
    CONF_MAX_SOC,
    CONF_POWER_STAGE_1,
    CONF_POWER_STAGE_2,
    CONF_PRIORITY_INTERVAL,
    CONF_WALLBOX_POWER_SENSOR,
    CONF_WALLBOX_MAX_SURPLUS,
    CONF_WALLBOX_CABLE_SENSOR,
    DEFAULT_SMOOTHING_SECONDS,
    DEFAULT_MIN_SOC,
    DEFAULT_MAX_SOC,
    DEFAULT_POWER_STAGE_1,
    DEFAULT_POWER_STAGE_2,
    DEFAULT_PRIORITY_INTERVAL,
    DEFAULT_WALLBOX_MAX_SURPLUS,
)

class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Venus HA."""

    VERSION = 1

    @callback
    def async_get_options_flow(self, config_entry):
        """Get the options flow for this handler."""
        return MarstekOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # You can add validation here if needed
            return self.async_create_entry(title="Marstek Intelligent Battery Control", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_GRID_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_SMOOTHING_SECONDS, default=DEFAULT_SMOOTHING_SECONDS): int,
                vol.Required(CONF_BATTERY_1_ENTITY): str,
                vol.Optional(CONF_BATTERY_2_ENTITY, default=""): str,
                vol.Optional(CONF_BATTERY_3_ENTITY, default=""): str,
                vol.Required(CONF_MIN_SOC, default=DEFAULT_MIN_SOC): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(CONF_MAX_SOC, default=DEFAULT_MAX_SOC): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(CONF_POWER_STAGE_1, default=DEFAULT_POWER_STAGE_1): int,
                vol.Required(CONF_POWER_STAGE_2, default=DEFAULT_POWER_STAGE_2): int,
                vol.Required(CONF_PRIORITY_INTERVAL, default=DEFAULT_PRIORITY_INTERVAL): int,
                vol.Optional(CONF_WALLBOX_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_WALLBOX_MAX_SURPLUS, default=DEFAULT_WALLBOX_MAX_SURPLUS): int,
                vol.Optional(CONF_WALLBOX_CABLE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

class MarstekOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_GRID_POWER_SENSOR,
                    default=self.config_entry.data.get(CONF_GRID_POWER_SENSOR),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SMOOTHING_SECONDS,
                    default=self.config_entry.data.get(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS),
                ): int,
                vol.Required(
                    CONF_BATTERY_1_ENTITY,
                    default=self.config_entry.data.get(CONF_BATTERY_1_ENTITY),
                ): str,
                vol.Optional(
                    CONF_BATTERY_2_ENTITY,
                    default=self.config_entry.data.get(CONF_BATTERY_2_ENTITY, ""),
                ): str,
                vol.Optional(
                    CONF_BATTERY_3_ENTITY,
                    default=self.config_entry.data.get(CONF_BATTERY_3_ENTITY, ""),
                ): str,
                vol.Required(
                    CONF_MIN_SOC,
                    default=self.config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_MAX_SOC,
                    default=self.config_entry.data.get(CONF_MAX_SOC, DEFAULT_MAX_SOC),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_POWER_STAGE_1,
                    default=self.config_entry.data.get(CONF_POWER_STAGE_1, DEFAULT_POWER_STAGE_1),
                ): int,
                vol.Required(
                    CONF_POWER_STAGE_2,
                    default=self.config_entry.data.get(CONF_POWER_STAGE_2, DEFAULT_POWER_STAGE_2),
                ): int,
                vol.Required(
                    CONF_PRIORITY_INTERVAL,
                    default=self.config_entry.data.get(CONF_PRIORITY_INTERVAL, DEFAULT_PRIORITY_INTERVAL),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_POWER_SENSOR,
                    default=self.config_entry.data.get(CONF_WALLBOX_POWER_SENSOR),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_WALLBOX_MAX_SURPLUS,
                    default=self.config_entry.data.get(CONF_WALLBOX_MAX_SURPLUS, DEFAULT_WALLBOX_MAX_SURPLUS),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_CABLE_SENSOR,
                    default=self.config_entry.data.get(CONF_WALLBOX_CABLE_SENSOR),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
