"""Config flow for Marstek Venus HA Integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_CT_MODE,
    CONF_GRID_POWER_SENSOR,
    CONF_PV_POWER_SENSOR,
    CONF_SMOOTHING_SECONDS,
    CONF_MIN_SURPLUS,
    CONF_MIN_CONSUMPTION,
    CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING,
    CONF_BATTERY_1_ENTITY,
    CONF_BATTERY_2_ENTITY,
    CONF_BATTERY_3_ENTITY,
    CONF_MIN_SOC,
    CONF_MAX_SOC,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MAX_CHARGE_POWER,
    CONF_POWER_STAGE_DISCHARGE_1,
    CONF_POWER_STAGE_DISCHARGE_2,
    CONF_POWER_STAGE_CHARGE_1,
    CONF_POWER_STAGE_CHARGE_2,
    CONF_POWER_STAGE_OFFSET,
    CONF_PRIORITY_INTERVAL,
    CONF_WALLBOX_POWER_SENSOR,
    CONF_WALLBOX_MAX_SURPLUS,
    CONF_WALLBOX_CABLE_SENSOR,
    CONF_WALLBOX_POWER_STABILITY_THRESHOLD,
    CONF_WALLBOX_RESUME_CHECK_SECONDS,
    CONF_WALLBOX_START_DELAY_SECONDS,
    CONF_WALLBOX_RETRY_MINUTES,
    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    CONF_SERVICE_CALL_CACHE_SECONDS,
    CONF_PID_ENABLED,
    CONF_PID_KP,
    CONF_PID_KI,
    CONF_PID_KD,
    DEFAULT_CT_MODE,
    DEFAULT_SMOOTHING_SECONDS,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_MIN_CONSUMPTION,
    DEFAULT_MAX_LIMIT_BREACHES_BEFORE_ZEROING,
    DEFAULT_MIN_SOC,
    DEFAULT_MAX_SOC,
    DEFAULT_MAX_DISCHARGE_POWER,
    DEFAULT_MAX_CHARGE_POWER,
    DEFAULT_POWER_STAGE_DISCHARGE_1,
    DEFAULT_POWER_STAGE_DISCHARGE_2,
    DEFAULT_POWER_STAGE_CHARGE_1,
    DEFAULT_POWER_STAGE_CHARGE_2,
    DEFAULT_POWER_STAGE_OFFSET,
    DEFAULT_PRIORITY_INTERVAL,
    DEFAULT_WALLBOX_MAX_SURPLUS,
    DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD,
    DEFAULT_WALLBOX_RESUME_CHECK_SECONDS,
    DEFAULT_WALLBOX_START_DELAY_SECONDS,
    DEFAULT_WALLBOX_RETRY_MINUTES,
    DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    DEFAULT_SERVICE_CALL_CACHE_SECONDS,
    DEFAULT_PID_ENABLED,
    DEFAULT_PID_KP,
    DEFAULT_PID_KI,
    DEFAULT_PID_KD,
)

class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Venus HA."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        self._data: dict = {}

    async def async_step_user(self, user_input=None):
        """Standard entry point for config flows."""
        return await self.async_step_basic(user_input)

    async def async_step_basic(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_batteries()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_CT_MODE, default=DEFAULT_CT_MODE): bool,
                vol.Required(CONF_GRID_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_PV_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_SMOOTHING_SECONDS, default=DEFAULT_SMOOTHING_SECONDS): int,
                vol.Required(
                    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
                    default=DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS,
                ): int,
                vol.Required(
                    CONF_SERVICE_CALL_CACHE_SECONDS,
                    default=DEFAULT_SERVICE_CALL_CACHE_SECONDS,
                ): int,
            }
        )

        return self.async_show_form(
            step_id="basic", data_schema=data_schema, errors=errors
        )

    async def async_step_batteries(self, user_input=None):
        """Battery configuration step."""
        errors = {}
        placeholders = {"missing": ""}
        if user_input is not None:
            missing = self._validate_battery_entities(user_input)
            if missing:
                errors["base"] = "missing_battery_entities"
                placeholders["missing"] = ", ".join(missing)
            else:
                self._data.update(user_input)
                return await self.async_step_wallbox()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_BATTERY_1_ENTITY): str,
                vol.Optional(CONF_BATTERY_2_ENTITY, default=""): str,
                vol.Optional(CONF_BATTERY_3_ENTITY, default=""): str,
                vol.Required(CONF_MIN_SOC, default=DEFAULT_MIN_SOC): int,
                vol.Required(CONF_MAX_SOC, default=DEFAULT_MAX_SOC): int,
                vol.Required(CONF_MAX_DISCHARGE_POWER, default=DEFAULT_MAX_DISCHARGE_POWER): int,
                vol.Required(CONF_MAX_CHARGE_POWER, default=DEFAULT_MAX_CHARGE_POWER): int,
                vol.Required(CONF_MIN_SURPLUS, default=DEFAULT_MIN_SURPLUS): int,
                vol.Required(CONF_MIN_CONSUMPTION, default=DEFAULT_MIN_CONSUMPTION): int,
                vol.Required(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, default=DEFAULT_MAX_LIMIT_BREACHES_BEFORE_ZEROING): int,
                vol.Required(CONF_POWER_STAGE_DISCHARGE_1, default=DEFAULT_POWER_STAGE_DISCHARGE_1): int,
                vol.Required(CONF_POWER_STAGE_DISCHARGE_2, default=DEFAULT_POWER_STAGE_DISCHARGE_2): int,
                vol.Required(CONF_POWER_STAGE_CHARGE_1, default=DEFAULT_POWER_STAGE_CHARGE_1): int,
                vol.Required(CONF_POWER_STAGE_CHARGE_2, default=DEFAULT_POWER_STAGE_CHARGE_2): int,
                vol.Required(CONF_POWER_STAGE_OFFSET, default=DEFAULT_POWER_STAGE_OFFSET): int,
                vol.Required(CONF_PRIORITY_INTERVAL, default=DEFAULT_PRIORITY_INTERVAL): int,
            }
        )

        return self.async_show_form(
            step_id="batteries",
            data_schema=data_schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    def _validate_battery_entities(self, user_input: dict) -> list[str]:
        missing: list[str] = []
        base_ids = [
            user_input.get(CONF_BATTERY_1_ENTITY),
            user_input.get(CONF_BATTERY_2_ENTITY),
            user_input.get(CONF_BATTERY_3_ENTITY),
        ]
        base_ids = [b.strip() for b in base_ids if isinstance(b, str) and b.strip()]

        for base in base_ids:
            expected = [
                f"sensor.{base}_ac_power",
                f"sensor.{base}_battery_soc",
                f"number.{base}_modbus_set_forcible_charge_power",
                f"number.{base}_modbus_set_forcible_discharge_power",
                f"select.{base}_modbus_force_mode",
                f"switch.{base}_modbus_rs485_control_mode",
            ]
            for ent_id in expected:
                if self.hass.states.get(ent_id) is None:
                    missing.append(ent_id)
        return missing

    async def async_step_wallbox(self, user_input=None):
        """Wallbox configuration step."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_pid()

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_WALLBOX_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_WALLBOX_MAX_SURPLUS, default=DEFAULT_WALLBOX_MAX_SURPLUS): int,
                vol.Optional(CONF_WALLBOX_CABLE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                vol.Optional(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, default=DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD): int,
                vol.Optional(CONF_WALLBOX_RESUME_CHECK_SECONDS, default=DEFAULT_WALLBOX_RESUME_CHECK_SECONDS): int,
                vol.Optional(CONF_WALLBOX_START_DELAY_SECONDS, default=DEFAULT_WALLBOX_START_DELAY_SECONDS): int,
                vol.Optional(CONF_WALLBOX_RETRY_MINUTES, default=DEFAULT_WALLBOX_RETRY_MINUTES): int,
            }
        )

        return self.async_show_form(step_id="wallbox", data_schema=data_schema)

    async def async_step_pid(self, user_input=None):
        """PID configuration step."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="Marstek Venus HA", data=self._data)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PID_ENABLED, default=DEFAULT_PID_ENABLED): bool,
                vol.Required(CONF_PID_KP, default=DEFAULT_PID_KP): vol.Coerce(float),
                vol.Required(CONF_PID_KI, default=DEFAULT_PID_KI): vol.Coerce(float),
                vol.Required(CONF_PID_KD, default=DEFAULT_PID_KD): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="pid", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return MarstekOptionsFlowHandler(config_entry)


class MarstekOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        self._options = dict(config_entry.options)
        self._all_mode = False

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["all", "basic", "batteries", "wallbox", "pid"],
        )

    async def async_step_all(self, user_input=None):
        """Run through all sections."""
        self._all_mode = True
        return await self.async_step_basic()

    def _get_val(self, key, default):
        """Helper to get current value from options or data."""
        return self._options.get(key, self.config_entry.data.get(key, default))

    async def async_step_basic(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            if self._all_mode: return await self.async_step_batteries()
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="basic",
            data_schema=vol.Schema({
                vol.Required(CONF_CT_MODE, default=self._get_val(CONF_CT_MODE, DEFAULT_CT_MODE)): bool,
                vol.Required(CONF_GRID_POWER_SENSOR, default=self._get_val(CONF_GRID_POWER_SENSOR, "")): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(CONF_PV_POWER_SENSOR, default=self._get_val(CONF_PV_POWER_SENSOR, "")): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(CONF_SMOOTHING_SECONDS, default=self._get_val(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS)): int,
                vol.Required(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS, default=self._get_val(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS, DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS)): int,
                vol.Required(CONF_SERVICE_CALL_CACHE_SECONDS, default=self._get_val(CONF_SERVICE_CALL_CACHE_SECONDS, DEFAULT_SERVICE_CALL_CACHE_SECONDS)): int,
            })
        )

    async def async_step_batteries(self, user_input=None):
        errors = {}
        placeholders = {"missing": ""}
        if user_input is not None:
            missing = self._validate_battery_entities(user_input)
            if missing:
                errors["base"] = "missing_battery_entities"
                placeholders["missing"] = ", ".join(missing)
            else:
                self._options.update(user_input)
                if self._all_mode: return await self.async_step_wallbox()
                return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="batteries",
            errors=errors,
            description_placeholders=placeholders,
            data_schema=vol.Schema({
                vol.Required(CONF_BATTERY_1_ENTITY, default=self._get_val(CONF_BATTERY_1_ENTITY, "")): str,
                vol.Optional(CONF_BATTERY_2_ENTITY, default=self._get_val(CONF_BATTERY_2_ENTITY, "")): str,
                vol.Optional(CONF_BATTERY_3_ENTITY, default=self._get_val(CONF_BATTERY_3_ENTITY, "")): str,
                vol.Required(CONF_MIN_SOC, default=self._get_val(CONF_MIN_SOC, DEFAULT_MIN_SOC)): int,
                vol.Required(CONF_MAX_SOC, default=self._get_val(CONF_MAX_SOC, DEFAULT_MAX_SOC)): int,
                vol.Required(CONF_MAX_DISCHARGE_POWER, default=self._get_val(CONF_MAX_DISCHARGE_POWER, DEFAULT_MAX_DISCHARGE_POWER)): int,
                vol.Required(CONF_MAX_CHARGE_POWER, default=self._get_val(CONF_MAX_CHARGE_POWER, DEFAULT_MAX_CHARGE_POWER)): int,
                vol.Required(CONF_MIN_SURPLUS, default=self._get_val(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS)): int,
                vol.Required(CONF_MIN_CONSUMPTION, default=self._get_val(CONF_MIN_CONSUMPTION, DEFAULT_MIN_CONSUMPTION)): int,
                vol.Required(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, default=self._get_val(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, DEFAULT_MAX_LIMIT_BREACHES_BEFORE_ZEROING)): int,
                vol.Required(CONF_POWER_STAGE_DISCHARGE_1, default=self._get_val(CONF_POWER_STAGE_DISCHARGE_1, DEFAULT_POWER_STAGE_DISCHARGE_1)): int,
                vol.Required(CONF_POWER_STAGE_DISCHARGE_2, default=self._get_val(CONF_POWER_STAGE_DISCHARGE_2, DEFAULT_POWER_STAGE_DISCHARGE_2)): int,
                vol.Required(CONF_POWER_STAGE_CHARGE_1, default=self._get_val(CONF_POWER_STAGE_CHARGE_1, DEFAULT_POWER_STAGE_CHARGE_1)): int,
                vol.Required(CONF_POWER_STAGE_CHARGE_2, default=self._get_val(CONF_POWER_STAGE_CHARGE_2, DEFAULT_POWER_STAGE_CHARGE_2)): int,
                vol.Required(CONF_POWER_STAGE_OFFSET, default=self._get_val(CONF_POWER_STAGE_OFFSET, DEFAULT_POWER_STAGE_OFFSET)): int,
                vol.Required(CONF_PRIORITY_INTERVAL, default=self._get_val(CONF_PRIORITY_INTERVAL, DEFAULT_PRIORITY_INTERVAL)): int,
            })
        )

    def _validate_battery_entities(self, user_input: dict) -> list[str]:
        # Logik identisch zu oben, nutzt aber hass aus dem handler
        missing = []
        for key in [CONF_BATTERY_1_ENTITY, CONF_BATTERY_2_ENTITY, CONF_BATTERY_3_ENTITY]:
            base = user_input.get(key, "").strip()
            if not base: continue
            expected = [f"sensor.{base}_ac_power", f"sensor.{base}_battery_soc", f"number.{base}_modbus_set_forcible_charge_power", f"number.{base}_modbus_set_forcible_discharge_power", f"select.{base}_modbus_force_mode", f"switch.{base}_modbus_rs485_control_mode"]
            for ent_id in expected:
                if self.hass.states.get(ent_id) is None: missing.append(ent_id)
        return missing

    async def async_step_wallbox(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            if self._all_mode: return await self.async_step_pid()
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="wallbox",
            data_schema=vol.Schema({
                vol.Optional(CONF_WALLBOX_POWER_SENSOR, default=self._get_val(CONF_WALLBOX_POWER_SENSOR, "")): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(CONF_WALLBOX_MAX_SURPLUS, default=self._get_val(CONF_WALLBOX_MAX_SURPLUS, DEFAULT_WALLBOX_MAX_SURPLUS)): int,
                vol.Optional(CONF_WALLBOX_CABLE_SENSOR, default=self._get_val(CONF_WALLBOX_CABLE_SENSOR, "")): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                vol.Optional(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, default=self._get_val(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD)): int,
                vol.Optional(CONF_WALLBOX_RESUME_CHECK_SECONDS, default=self._get_val(CONF_WALLBOX_RESUME_CHECK_SECONDS, DEFAULT_WALLBOX_RESUME_CHECK_SECONDS)): int,
                vol.Optional(CONF_WALLBOX_START_DELAY_SECONDS, default=self._get_val(CONF_WALLBOX_START_DELAY_SECONDS, DEFAULT_WALLBOX_START_DELAY_SECONDS)): int,
                vol.Optional(CONF_WALLBOX_RETRY_MINUTES, default=self._get_val(CONF_WALLBOX_RETRY_MINUTES, DEFAULT_WALLBOX_RETRY_MINUTES)): int,
            })
        )

    async def async_step_pid(self, user_input=None):
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="pid",
            data_schema=vol.Schema({
                vol.Required(CONF_PID_ENABLED, default=self._get_val(CONF_PID_ENABLED, DEFAULT_PID_ENABLED)): bool,
                vol.Required(CONF_PID_KP, default=self._get_val(CONF_PID_KP, DEFAULT_PID_KP)): vol.Coerce(float),
                vol.Required(CONF_PID_KI, default=self._get_val(CONF_PID_KI, DEFAULT_PID_KI)): vol.Coerce(float),
                vol.Required(CONF_PID_KD, default=self._get_val(CONF_PID_KD, DEFAULT_PID_KD)): vol.Coerce(float),
            })
        )