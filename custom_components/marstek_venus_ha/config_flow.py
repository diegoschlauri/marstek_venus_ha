"""Config flow for Marstek Venus HA Integration."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_CT_MODE,
    CONF_GRID_POWER_SENSOR,
    CONF_PV_POWER_SENSOR,
    CONF_SMOOTHING_SECONDS,
    CONF_MIN_SURPLUS,
    CONF_MIN_CONSUMPTION,
    CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING,
    CONF_MIN_SOC,
    CONF_MAX_SOC,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MAX_CHARGE_POWER,
    CONF_POWER_STAGE_OFFSET,
    CONF_PRIORITY_INTERVAL,
    CONF_WALLBOX_POWER_SENSOR,
    CONF_WALLBOX_MAX_SURPLUS,
    CONF_WALLBOX_CABLE_SENSOR,
    CONF_WALLBOX_POWER_STABILITY_THRESHOLD,
    CONF_WALLBOX_STABILITY_MIN_POWER_GAP,
    CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS,
    CONF_WALLBOX_RESUME_CHECK_SECONDS,
    CONF_WALLBOX_START_DELAY_SECONDS,
    CONF_WALLBOX_RETRY_MINUTES,
    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    CONF_SERVICE_CALL_CACHE_SECONDS,
    CONF_PID_ENABLED,
    CONF_PID_KP,
    CONF_PID_KI,
    CONF_PID_KD,
    CONF_PID_FEEDFORWARD_ENABLED,
    CONF_PID_FEEDFORWARD_GAIN,
    DEFAULT_CT_MODE,
    DEFAULT_SMOOTHING_SECONDS,
    DEFAULT_MIN_SURPLUS,
    DEFAULT_MIN_CONSUMPTION,
    DEFAULT_MAX_LIMIT_BREACHES_BEFORE_ZEROING,
    DEFAULT_MIN_SOC,
    DEFAULT_MAX_SOC,
    DEFAULT_MAX_DISCHARGE_POWER,
    DEFAULT_MAX_CHARGE_POWER,
    DEFAULT_POWER_STAGE_OFFSET,
    DEFAULT_PRIORITY_INTERVAL,
    DEFAULT_WALLBOX_MAX_SURPLUS,
    DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD,
    DEFAULT_WALLBOX_STABILITY_MIN_POWER_GAP,
    DEFAULT_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS,
    DEFAULT_WALLBOX_RESUME_CHECK_SECONDS,
    DEFAULT_WALLBOX_START_DELAY_SECONDS,
    DEFAULT_WALLBOX_RETRY_MINUTES,
    DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    DEFAULT_SERVICE_CALL_CACHE_SECONDS,
    DEFAULT_PID_ENABLED,
    DEFAULT_PID_KP,
    DEFAULT_PID_KI,
    DEFAULT_PID_KD,
    DEFAULT_PID_FEEDFORWARD_ENABLED,
    DEFAULT_PID_FEEDFORWARD_GAIN,
    CONF_CHARGE_POWER_LEVEL_1,
    CONF_CHARGE_POWER_LEVEL_2,
    CONF_CHARGE_POWER_LEVEL_3,
    CONF_CHARGE_POWER_LEVEL_4,
    CONF_CHARGE_POWER_LEVEL_5,
    CONF_DISCHARGE_POWER_LEVEL_1,
    CONF_DISCHARGE_POWER_LEVEL_2,
    CONF_DISCHARGE_POWER_LEVEL_3,
    CONF_DISCHARGE_POWER_LEVEL_4,
    CONF_DISCHARGE_POWER_LEVEL_5,
    DEFAULT_CHARGE_POWER_LEVEL_1,
    DEFAULT_CHARGE_POWER_LEVEL_2,
    DEFAULT_CHARGE_POWER_LEVEL_3,
    DEFAULT_CHARGE_POWER_LEVEL_4,
    DEFAULT_CHARGE_POWER_LEVEL_5,
    DEFAULT_DISCHARGE_POWER_LEVEL_1,
    DEFAULT_DISCHARGE_POWER_LEVEL_2,
    DEFAULT_DISCHARGE_POWER_LEVEL_3,
    DEFAULT_DISCHARGE_POWER_LEVEL_4,
    DEFAULT_DISCHARGE_POWER_LEVEL_5,
    CONF_BATTERY_COUNT,
    DEFAULT_BATTERY_COUNT
)

class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Venus HA."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            self._data = dict(user_input)
            return await self.async_step_batteries()

        data_schema = vol.Schema(
            {   vol.Required(CONF_BATTERY_COUNT, default=DEFAULT_BATTERY_COUNT): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
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
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_batteries(self, user_input=None):
        """Battery configuration step. Create Dropdown for number of batteries."""
        errors = {}
        battery_count = self._data.get(CONF_BATTERY_COUNT, 1)
        
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_wallbox()
        
        schema_dict = {}
        # Generate selects for selected number of batteries
        for i in range(1, battery_count + 1):
            schema_dict[vol.Required(f"battery_{i}_ac_power_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
            schema_dict[vol.Required(f"battery_{i}_soc_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
            schema_dict[vol.Optional(f"battery_{i}_max_soc_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
            schema_dict[vol.Required(f"battery_{i}_charge_power_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
            schema_dict[vol.Required(f"battery_{i}_discharge_power_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
            schema_dict[vol.Required(f"battery_{i}_force_mode_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="select"))
            schema_dict[vol.Required(f"battery_{i}_rs485_mode_entity")] = selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))
            schema_dict[vol.Required(f"battery_{i}_custom_max_powers", default=False)] = bool
            schema_dict[vol.Required(f"battery_{i}_max_discharge_power", default=2500)] = int
            schema_dict[vol.Required(f"battery_{i}_max_charge_power", default=2500)] = int
        # Generate powerstages based on battery number
        if battery_count > 1:
            schema_dict[vol.Required(CONF_POWER_STAGE_OFFSET, default=DEFAULT_POWER_STAGE_OFFSET)] = int
            for i in range(1, battery_count):
                # Wir setzen einen sinnvollen Default-Wert (z.B. 1500W, 3000W, etc.)
                default_stage = i * 1500
                schema_dict[vol.Required(f"powerstage_{i}_to_{i+1}", default=default_stage)] = int


        schema_dict[vol.Required(CONF_MIN_SOC, default=DEFAULT_MIN_SOC)] = int
        schema_dict[vol.Required(CONF_MAX_SOC, default=DEFAULT_MAX_SOC)] = int
        schema_dict[vol.Required(CONF_MAX_DISCHARGE_POWER, default=DEFAULT_MAX_DISCHARGE_POWER)] = int
        schema_dict[vol.Required(CONF_MAX_CHARGE_POWER, default=DEFAULT_MAX_CHARGE_POWER)] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_1, default=DEFAULT_CHARGE_POWER_LEVEL_1)] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_2, default=DEFAULT_CHARGE_POWER_LEVEL_2)] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_3, default=DEFAULT_CHARGE_POWER_LEVEL_3)] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_4, default=DEFAULT_CHARGE_POWER_LEVEL_4)] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_5, default=DEFAULT_CHARGE_POWER_LEVEL_5)] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_1, default=DEFAULT_DISCHARGE_POWER_LEVEL_1)] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_2, default=DEFAULT_DISCHARGE_POWER_LEVEL_2)] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_3, default=DEFAULT_DISCHARGE_POWER_LEVEL_3)] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_4, default=DEFAULT_DISCHARGE_POWER_LEVEL_4)] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_5, default=DEFAULT_DISCHARGE_POWER_LEVEL_5)] = int
        schema_dict[vol.Required(CONF_MIN_SURPLUS, default=DEFAULT_MIN_SURPLUS)] = int
        schema_dict[vol.Required(CONF_MIN_CONSUMPTION, default=DEFAULT_MIN_CONSUMPTION)] = int
        schema_dict[vol.Required(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, default=DEFAULT_MAX_LIMIT_BREACHES_BEFORE_ZEROING)] = int
        schema_dict[vol.Required(CONF_PRIORITY_INTERVAL, default=DEFAULT_PRIORITY_INTERVAL)] = int

        return self.async_show_form(
            step_id="batteries",
            data_schema=vol.Schema(schema_dict),
            errors=errors
        )

    async def async_step_wallbox(self, user_input=None):
        """Wallbox configuration step."""
        errors = {}
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
                vol.Optional(CONF_WALLBOX_STABILITY_MIN_POWER_GAP, default=DEFAULT_WALLBOX_STABILITY_MIN_POWER_GAP): int,
                vol.Optional(CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS, default=DEFAULT_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS): int,
                vol.Optional(CONF_WALLBOX_RESUME_CHECK_SECONDS, default=DEFAULT_WALLBOX_RESUME_CHECK_SECONDS): int,
                vol.Optional(CONF_WALLBOX_START_DELAY_SECONDS, default=DEFAULT_WALLBOX_START_DELAY_SECONDS): int,
                vol.Optional(CONF_WALLBOX_RETRY_MINUTES, default=DEFAULT_WALLBOX_RETRY_MINUTES): int,
            }
        )

        return self.async_show_form(
            step_id="wallbox", data_schema=data_schema, errors=errors
        )

    async def async_step_pid(self, user_input=None):
        """PID configuration step."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Marstek Venus HA Integration",
                data=self._data,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_PID_ENABLED, default=DEFAULT_PID_ENABLED): bool,
                vol.Required(CONF_PID_KP, default=DEFAULT_PID_KP): vol.Coerce(float),
                vol.Required(CONF_PID_KI, default=DEFAULT_PID_KI): vol.Coerce(float),
                vol.Required(CONF_PID_KD, default=DEFAULT_PID_KD): vol.Coerce(float),
                vol.Required(CONF_PID_FEEDFORWARD_ENABLED, default=DEFAULT_PID_FEEDFORWARD_ENABLED): bool,
                vol.Required(CONF_PID_FEEDFORWARD_GAIN, default=DEFAULT_PID_FEEDFORWARD_GAIN): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="pid", data_schema=data_schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return MarstekOptionsFlowHandler()


class MarstekOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self) -> None:
        self._options: dict = {}
        self._all_mode: bool = False

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        self._options = dict(self.config_entry.options)
        if not self._options:
            self._options = dict(self.config_entry.data)
        self._all_mode = False
        return self.async_show_menu(
            step_id="init",
            menu_options=["all", "basic", "batteries", "wallbox", "pid"],
        )

    async def async_step_all(self, user_input=None):
        """Run through all option sections sequentially."""
        self._all_mode = True
        return await self.async_step_basic()

    async def async_step_basic(self, user_input=None):
        """Basic sensor/general options."""
        if user_input is not None:
            # PV Sensor explizit nullen wenn entfernt
            if CONF_PV_POWER_SENSOR not in user_input:
                user_input[CONF_PV_POWER_SENSOR] = None

            self._options.update(user_input)
            if self._all_mode:
                return await self.async_step_batteries()
            return self.async_create_entry(title="", data=self._options)

        data_schema = vol.Schema(
            {   vol.Required(
                    CONF_BATTERY_COUNT,
                    default=self._options.get(CONF_BATTERY_COUNT, self.config_entry.data.get(CONF_BATTERY_COUNT, DEFAULT_BATTERY_COUNT)),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
                vol.Required(
                    CONF_CT_MODE,
                    default=self._options.get(CONF_CT_MODE, self.config_entry.data.get(CONF_CT_MODE, DEFAULT_CT_MODE)),
                ): bool,
                vol.Required(
                    CONF_GRID_POWER_SENSOR,
                    default=self._options.get(CONF_GRID_POWER_SENSOR, self.config_entry.data.get(CONF_GRID_POWER_SENSOR)),
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_PV_POWER_SENSOR,
                    description={"suggested_value": self._options.get(CONF_PV_POWER_SENSOR, self.config_entry.data.get(CONF_PV_POWER_SENSOR))},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SMOOTHING_SECONDS,
                    default=self._options.get(CONF_SMOOTHING_SECONDS, self.config_entry.data.get(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS)),
                ): int,
                vol.Required(
                    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
                    default=self._options.get(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS, self.config_entry.data.get(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS, DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS)),
                ): int,
                vol.Required(
                    CONF_SERVICE_CALL_CACHE_SECONDS,
                    default=self._options.get(CONF_SERVICE_CALL_CACHE_SECONDS, self.config_entry.data.get(CONF_SERVICE_CALL_CACHE_SECONDS, DEFAULT_SERVICE_CALL_CACHE_SECONDS)),
                ): int
            }
        )
        return self.async_show_form(step_id="basic", data_schema=data_schema)

    async def async_step_batteries(self, user_input=None):
        """Battery configuration step."""
        errors: dict = {}

        # Hole die aktuelle Batterie-Anzahl aus den Optionen (wurde in basic ggf. aktualisiert)
        battery_count = self._options.get(CONF_BATTERY_COUNT, self.config_entry.data.get(CONF_BATTERY_COUNT, 1))

        if user_input is not None:
            for i in range(1, battery_count + 1):
                field_name = f"battery_{i}_max_soc_entity"
                if field_name not in user_input:
                    user_input[field_name] = None
            self._options.update(user_input)
            if self._all_mode:
                return await self.async_step_wallbox()
            return self.async_create_entry(title="", data=self._options)

        schema_dict = {}

        # 1. Dynamische Batterie-Entitäten generieren
        for i in range(1, battery_count + 1):
            schema_dict[vol.Required(
                f"battery_{i}_ac_power_entity",
                default=self._options.get(f"battery_{i}_ac_power_entity", self.config_entry.data.get(f"battery_{i}_ac_power_entity", ""))
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
            
            schema_dict[vol.Required(
                f"battery_{i}_soc_entity",
                default=self._options.get(f"battery_{i}_soc_entity", self.config_entry.data.get(f"battery_{i}_soc_entity", ""))
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
        
            schema_dict[vol.Optional(
                f"battery_{i}_max_soc_entity",
                default=self._options.get(
                    f"battery_{i}_max_soc_entity",
                    self.config_entry.data.get(f"battery_{i}_max_soc_entity", None),
                ),
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))

            schema_dict[vol.Required(
                f"battery_{i}_charge_power_entity",
                default=self._options.get(f"battery_{i}_charge_power_entity", self.config_entry.data.get(f"battery_{i}_charge_power_entity", ""))
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
            
            schema_dict[vol.Required(
                f"battery_{i}_discharge_power_entity",
                default=self._options.get(f"battery_{i}_discharge_power_entity", self.config_entry.data.get(f"battery_{i}_discharge_power_entity", ""))
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="number"))
            
            schema_dict[vol.Required(
                f"battery_{i}_force_mode_entity",
                default=self._options.get(f"battery_{i}_force_mode_entity", self.config_entry.data.get(f"battery_{i}_force_mode_entity", ""))
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="select"))
            
            schema_dict[vol.Required(
                f"battery_{i}_rs485_mode_entity",
                default=self._options.get(f"battery_{i}_rs485_mode_entity", self.config_entry.data.get(f"battery_{i}_rs485_mode_entity", ""))
            )] = selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))

            schema_dict[vol.Required(
                f"battery_{i}_custom_max_powers",
                default=self._options.get(f"battery_{i}_custom_max_powers", False)
            )] = bool

            schema_dict[vol.Required(
                f"battery_{i}_max_discharge_power",
                default=self._options.get(f"battery_{i}_max_discharge_power", self.config_entry.data.get(f"battery_{i}_max_discharge_power", 2500))
            )] = int

            schema_dict[vol.Required(
                f"battery_{i}_max_charge_power",
                default=self._options.get(f"battery_{i}_max_charge_power", self.config_entry.data.get(f"battery_{i}_max_charge_power", 2500))
            )] = int 

        # 2. Dynamische Powerstages (nur wenn mehr als 1 Batterie)
        if battery_count > 1:
            schema_dict[vol.Required(
                CONF_POWER_STAGE_OFFSET, 
                default=self._options.get(CONF_POWER_STAGE_OFFSET, self.config_entry.data.get(CONF_POWER_STAGE_OFFSET, DEFAULT_POWER_STAGE_OFFSET))
            )] = int
            
            for i in range(1, battery_count):
                default_stage = i * 1500
                saved_val = self._options.get(f"powerstage_{i}_to_{i+1}", self.config_entry.data.get(f"powerstage_{i}_to_{i+1}", default_stage))
                schema_dict[vol.Required(f"powerstage_{i}_to_{i+1}", default=saved_val)] = int
        
        # 3. Globale Limits & Stufen
        schema_dict[vol.Required(CONF_MIN_SOC, default=self._options.get(CONF_MIN_SOC, self.config_entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)))] = int
        schema_dict[vol.Required(CONF_MAX_SOC, default=self._options.get(CONF_MAX_SOC, self.config_entry.data.get(CONF_MAX_SOC, DEFAULT_MAX_SOC)))] = int
        schema_dict[vol.Required(CONF_MAX_DISCHARGE_POWER, default=self._options.get(CONF_MAX_DISCHARGE_POWER, self.config_entry.data.get(CONF_MAX_DISCHARGE_POWER, DEFAULT_MAX_DISCHARGE_POWER)))] = int
        schema_dict[vol.Required(CONF_MAX_CHARGE_POWER, default=self._options.get(CONF_MAX_CHARGE_POWER, self.config_entry.data.get(CONF_MAX_CHARGE_POWER, DEFAULT_MAX_CHARGE_POWER)))] = int
        
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_1, default=self._options.get(CONF_CHARGE_POWER_LEVEL_1, self.config_entry.data.get(CONF_CHARGE_POWER_LEVEL_1, DEFAULT_CHARGE_POWER_LEVEL_1)))] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_2, default=self._options.get(CONF_CHARGE_POWER_LEVEL_2, self.config_entry.data.get(CONF_CHARGE_POWER_LEVEL_2, DEFAULT_CHARGE_POWER_LEVEL_2)))] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_3, default=self._options.get(CONF_CHARGE_POWER_LEVEL_3, self.config_entry.data.get(CONF_CHARGE_POWER_LEVEL_3, DEFAULT_CHARGE_POWER_LEVEL_3)))] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_4, default=self._options.get(CONF_CHARGE_POWER_LEVEL_4, self.config_entry.data.get(CONF_CHARGE_POWER_LEVEL_4, DEFAULT_CHARGE_POWER_LEVEL_4)))] = int
        schema_dict[vol.Required(CONF_CHARGE_POWER_LEVEL_5, default=self._options.get(CONF_CHARGE_POWER_LEVEL_5, self.config_entry.data.get(CONF_CHARGE_POWER_LEVEL_5, DEFAULT_CHARGE_POWER_LEVEL_5)))] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_1, default=self._options.get(CONF_DISCHARGE_POWER_LEVEL_1, self.config_entry.data.get(CONF_DISCHARGE_POWER_LEVEL_1, DEFAULT_DISCHARGE_POWER_LEVEL_1)))] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_2, default=self._options.get(CONF_DISCHARGE_POWER_LEVEL_2, self.config_entry.data.get(CONF_DISCHARGE_POWER_LEVEL_2, DEFAULT_DISCHARGE_POWER_LEVEL_2)))] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_3, default=self._options.get(CONF_DISCHARGE_POWER_LEVEL_3, self.config_entry.data.get(CONF_DISCHARGE_POWER_LEVEL_3, DEFAULT_DISCHARGE_POWER_LEVEL_3)))] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_4, default=self._options.get(CONF_DISCHARGE_POWER_LEVEL_4, self.config_entry.data.get(CONF_DISCHARGE_POWER_LEVEL_4, DEFAULT_DISCHARGE_POWER_LEVEL_4)))] = int
        schema_dict[vol.Required(CONF_DISCHARGE_POWER_LEVEL_5, default=self._options.get(CONF_DISCHARGE_POWER_LEVEL_5, self.config_entry.data.get(CONF_DISCHARGE_POWER_LEVEL_5, DEFAULT_DISCHARGE_POWER_LEVEL_5)))] = int
        
        schema_dict[vol.Required(CONF_MIN_SURPLUS, default=self._options.get(CONF_MIN_SURPLUS, self.config_entry.data.get(CONF_MIN_SURPLUS, DEFAULT_MIN_SURPLUS)))] = int
        schema_dict[vol.Required(CONF_MIN_CONSUMPTION, default=self._options.get(CONF_MIN_CONSUMPTION, self.config_entry.data.get(CONF_MIN_CONSUMPTION, DEFAULT_MIN_CONSUMPTION)))] = int
        schema_dict[vol.Required(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, default=self._options.get(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, self.config_entry.data.get(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, DEFAULT_MAX_LIMIT_BREACHES_BEFORE_ZEROING)))] = int
        schema_dict[vol.Required(CONF_PRIORITY_INTERVAL, default=self._options.get(CONF_PRIORITY_INTERVAL, self.config_entry.data.get(CONF_PRIORITY_INTERVAL, DEFAULT_PRIORITY_INTERVAL)))] = int

        return self.async_show_form(
            step_id="batteries",
            data_schema=vol.Schema(schema_dict),
            errors=errors
        )


    async def async_step_wallbox(self, user_input=None):
        """Wallbox configuration step."""
        if user_input is not None:
            # Wallbox Sensoren explizit nullen wenn entfernt
            for field in [CONF_WALLBOX_POWER_SENSOR, CONF_WALLBOX_CABLE_SENSOR]:
                if field not in user_input:
                    user_input[field] = None

            self._options.update(user_input)
            if self._all_mode:
                return await self.async_step_pid()
            return self.async_create_entry(title="", data=self._options)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_WALLBOX_POWER_SENSOR,
                    description={"suggested_value": self._options.get(CONF_WALLBOX_POWER_SENSOR, self.config_entry.data.get(CONF_WALLBOX_POWER_SENSOR))},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
                vol.Optional(
                    CONF_WALLBOX_CABLE_SENSOR,
                    description={"suggested_value": self._options.get(CONF_WALLBOX_CABLE_SENSOR, self.config_entry.data.get(CONF_WALLBOX_CABLE_SENSOR))},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
                vol.Optional(
                    CONF_WALLBOX_MAX_SURPLUS,
                    default=self._options.get(CONF_WALLBOX_MAX_SURPLUS, self.config_entry.data.get(CONF_WALLBOX_MAX_SURPLUS, DEFAULT_WALLBOX_MAX_SURPLUS)),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_POWER_STABILITY_THRESHOLD,
                    default=self._options.get(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, self.config_entry.data.get(CONF_WALLBOX_POWER_STABILITY_THRESHOLD, DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD)),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_STABILITY_MIN_POWER_GAP,
                    default=self._options.get(CONF_WALLBOX_STABILITY_MIN_POWER_GAP, self.config_entry.data.get(CONF_WALLBOX_STABILITY_MIN_POWER_GAP, DEFAULT_WALLBOX_STABILITY_MIN_POWER_GAP)),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS,
                    default=self._options.get(CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS, self.config_entry.data.get(CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS, DEFAULT_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS)),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_RESUME_CHECK_SECONDS,
                    default=self._options.get(CONF_WALLBOX_RESUME_CHECK_SECONDS, self.config_entry.data.get(CONF_WALLBOX_RESUME_CHECK_SECONDS, DEFAULT_WALLBOX_RESUME_CHECK_SECONDS)),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_START_DELAY_SECONDS,
                    default=self._options.get(CONF_WALLBOX_START_DELAY_SECONDS, self.config_entry.data.get(CONF_WALLBOX_START_DELAY_SECONDS, DEFAULT_WALLBOX_START_DELAY_SECONDS)),
                ): int,
                vol.Optional(
                    CONF_WALLBOX_RETRY_MINUTES,
                    default=self._options.get(CONF_WALLBOX_RETRY_MINUTES, self.config_entry.data.get(CONF_WALLBOX_RETRY_MINUTES, DEFAULT_WALLBOX_RETRY_MINUTES)),
                ): int,
            }
        )
        return self.async_show_form(step_id="wallbox", data_schema=data_schema)

    async def async_step_pid(self, user_input=None):
        """PID configuration step."""
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_PID_ENABLED,
                    default=self._options.get(CONF_PID_ENABLED, self.config_entry.data.get(CONF_PID_ENABLED, DEFAULT_PID_ENABLED)),
                ): bool,
                vol.Required(
                    CONF_PID_KP,
                    default=self._options.get(CONF_PID_KP, self.config_entry.data.get(CONF_PID_KP, DEFAULT_PID_KP)),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_PID_KI,
                    default=self._options.get(CONF_PID_KI, self.config_entry.data.get(CONF_PID_KI, DEFAULT_PID_KI)),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_PID_KD,
                    default=self._options.get(CONF_PID_KD, self.config_entry.data.get(CONF_PID_KD, DEFAULT_PID_KD)),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_PID_FEEDFORWARD_ENABLED,
                    default=self._options.get(CONF_PID_FEEDFORWARD_ENABLED, self.config_entry.data.get(CONF_PID_FEEDFORWARD_ENABLED, DEFAULT_PID_FEEDFORWARD_ENABLED)),
                ): bool,
                vol.Required(
                    CONF_PID_FEEDFORWARD_GAIN,
                    default=self._options.get(CONF_PID_FEEDFORWARD_GAIN, self.config_entry.data.get(CONF_PID_FEEDFORWARD_GAIN, DEFAULT_PID_FEEDFORWARD_GAIN)),
                ): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="pid", data_schema=data_schema)