"""Config flow for Marstek Venus HA Integration."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_GRID_POWER_SENSOR,
    CONF_SMOOTHING_SECONDS,
    CONF_MIN_SURPLUS,
    CONF_MIN_CONSUMPTION,
    CONF_BATTERY_1_ENTITY,
    CONF_BATTERY_2_ENTITY,
    CONF_BATTERY_3_ENTITY,
    CONF_MIN_SOC,
    CONF_MAX_SOC,
    CONF_POWER_STAGE_DISCHARGE_1,
    CONF_POWER_STAGE_DISCHARGE_2,
    CONF_POWER_STAGE_CHARGE_1,
    CONF_POWER_STAGE_CHARGE_2,
    CONF_PRIORITY_INTERVAL,
    CONF_WALLBOX_POWER_SENSOR,
    CONF_WALLBOX_MAX_SURPLUS,
    CONF_WALLBOX_CABLE_SENSOR,
    CONF_WALLBOX_POWER_STABILITY_THRESHOLD,
    CONF_WALLBOX_RESUME_CHECK_SECONDS,
    DEFAULT_SMOOTHING_SECONDS,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_MIN_CONSUMPTION,
    DEFAULT_MIN_SOC,
    DEFAULT_MAX_SOC,
    DEFAULT_POWER_STAGE_DISCHARGE_1,
    DEFAULT_POWER_STAGE_DISCHARGE_2,
    DEFAULT_POWER_STAGE_CHARGE_1,
    DEFAULT_POWER_STAGE_CHARGE_2,
    DEFAULT_PRIORITY_INTERVAL,
    DEFAULT_WALLBOX_MAX_SURPLUS,
    DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD,
    DEFAULT_WALLBOX_RESUME_CHECK_SECONDS
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
            return self.async_create_entry(title="Marstek Venus HA Integration", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_GRID_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_SMOOTHING_SECONDS, default=DEFAULT_SMOOTHING_SECONDS): int,
                vol.Required(CONF_MIN_SURPLUS, default=DEFAULT_MIN_SURPLUS): int,
                vol.Required(CONF_MIN_CONSUMPTION, default=DEFAULT_MIN_CONSUMPTION): int,
                vol.Required(CONF_BATTERY_1_ENTITY): str,
                vol.Optional(CONF_BATTERY_2_ENTITY, default=""): str,
                vol.Optional(CONF_BATTERY_3_ENTITY, default=""): str,
                vol.Required(CONF_MIN_SOC, default=DEFAULT_MIN_SOC): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(CONF_MAX_SOC, default=DEFAULT_MAX_SOC): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(CONF_POWER_STAGE_DISCHARGE_1, default=DEFAULT_POWER_STAGE_DISCHARGE_1): int,
                vol.Required(CONF_POWER_STAGE_DISCHARGE_2, default=DEFAULT_POWER_STAGE_DISCHARGE_2): int,
                vol.Required(CONF_POWER_STAGE_CHARGE_1, default=DEFAULT_POWER_STAGE_CHARGE_1): int,
                vol.Required(CONF_POWER_STAGE_CHARGE_2, default=DEFAULT_POWER_STAGE_CHARGE_2): int,
                vol.Required(CONF_PRIORITY_INTERVAL, default=DEFAULT_PRIORITY_INTERVAL): int,
                vol.Optional(CONF_WALLBOX_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_WALLBOX_MAX_SURPLUS, default=DEFAULT_WALLBOX_MAX_SURPLUS): int,
                vol.Optional(CONF_WALLBOX_CABLE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                vol.Optional(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, default=DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD): int,
                vol.Optional(CONF_WALLBOX_RESUME_CHECK_SECONDS, default=DEFAULT_WALLBOX_RESUME_CHECK_SECONDS): int,
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

        # Erstelle das Schema und fülle es mit den Werten aus den 'options',
        # mit einem Fallback auf die ursprünglichen 'data'.
        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_GRID_POWER_SENSOR,
                    default=self.config_entry.options.get(
                        CONF_GRID_POWER_SENSOR, self.config_entry.data.get(CONF_GRID_POWER_SENSOR)
                    ),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SMOOTHING_SECONDS,
                    default=self.config_entry.options.get(
                        CONF_SMOOTHING_SECONDS, self.config_entry.data.get(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS)
                    ),
                ): int,
                vol.Required(
                    CONF_MIN_SURPLUS,
                    default=self.config_entry.options.get(
                        CONF_MIN_SURPLUS, self.config_entry.data.get(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS)
                    ),
                ): int,
                vol.Required(
                    CONF_MIN_CONSUMPTION,
                    default=self.config_entry.options.get(
                        CONF_MIN_CONSUMPTION, self.config_entry.data.get(CONF_MIN_CONSUMPTION, DEFAULT_MIN_CONSUMPTION)
                    ),
                ): int,
                vol.Required(
                    CONF_BATTERY_1_ENTITY,
                    default=self.config_entry.options.get(
                        CONF_BATTERY_1_ENTITY, self.config_entry.data.get(CONF_BATTERY_1_ENTITY)
                    ),
                ): str,
                vol.Optional(
                    CONF_BATTERY_2_ENTITY,
                    default=self.config_entry.options.get(
                        CONF_BATTERY_2_ENTITY, self.config_entry.data.get(CONF_BATTERY_2_ENTITY, "")
                    ),
                ): str,
                vol.Optional(
                    CONF_BATTERY_3_ENTITY,
                    default=self.config_entry.options.get(
                        CONF_BATTERY_3_ENTITY, self.config_entry.data.get(CONF_BATTERY_3_ENTITY, "")
                    ),
                ): str,
                vol.Required(
                    CONF_MIN_SOC,
                    default=self.config_entry.options.get(
                        CONF_MIN_SOC, self.config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_MAX_SOC,
                    default=self.config_entry.options.get(
                        CONF_MAX_SOC, self.config_entry.data.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_POWER_STAGE_DISCHARGE_1,
                    default=self.config_entry.options.get(
                        CONF_POWER_STAGE_DISCHARGE_1, self.config_entry.data.get(CONF_POWER_STAGE_DISCHARGE_1, DEFAULT_POWER_STAGE_DISCHARGE_1)
                    ),
                ): int,
                vol.Required(
                    CONF_POWER_STAGE_DISCHARGE_2,
                    default=self.config_entry.options.get(
                        CONF_POWER_STAGE_DISCHARGE_2, self.config_entry.data.get(CONF_POWER_STAGE_DISCHARGE_2, DEFAULT_POWER_STAGE_DISCHARGE_2)
                    ),
                ): int,
                vol.Required(
                    CONF_POWER_STAGE_CHARGE_1,
                    default=self.config_entry.options.get(
                        CONF_POWER_STAGE_CHARGE_1, self.config_entry.data.get(CONF_POWER_STAGE_CHARGE_1, DEFAULT_POWER_STAGE_CHARGE_1)
                    ),
                ): int,
                vol.Required(
                    CONF_POWER_STAGE_CHARGE_2,
                    default=self.config_entry.options.get(
                        CONF_POWER_STAGE_CHARGE_2, self.config_entry.data.get(CONF_POWER_STAGE_CHARGE_2, DEFAULT_POWER_STAGE_CHARGE_2)
                    ),
                ): int,
                vol.Required(
                    CONF_PRIORITY_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_PRIORITY_INTERVAL, self.config_entry.data.get(CONF_PRIORITY_INTERVAL, DEFAULT_PRIORITY_INTERVAL)
                    ),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_POWER_SENSOR,
                    default=self.config_entry.options.get(
                        CONF_WALLBOX_POWER_SENSOR, self.config_entry.data.get(CONF_WALLBOX_POWER_SENSOR)
                    ),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_WALLBOX_MAX_SURPLUS,
                    default=self.config_entry.options.get(
                        CONF_WALLBOX_MAX_SURPLUS, self.config_entry.data.get(CONF_WALLBOX_MAX_SURPLUS, DEFAULT_WALLBOX_MAX_SURPLUS)
                    ),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_CABLE_SENSOR,
                    default=self.config_entry.options.get(
                        CONF_WALLBOX_CABLE_SENSOR, self.config_entry.data.get(CONF_WALLBOX_CABLE_SENSOR)
                    ),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                vol.Optional(
                    CONF_WALLBOX_POWER_STABILITY_THRESHOLD,
                    default=self.config_entry.options.get(
                        CONF_WALLBOX_POWER_STABILITY_THRESHOLD, self.config_entry.data.get(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD)
                    ),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_RESUME_CHECK_SECONDS,
                    default=self.config_entry.options.get(
                        CONF_WALLBOX_RESUME_CHECK_SECONDS, self.config_entry.data.get(CONF_WALLBOX_RESUME_CHECK_SECONDS, DEFAULT_WALLBOX_RESUME_CHECK_SECONDS)
                    ),
                ): int,
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
