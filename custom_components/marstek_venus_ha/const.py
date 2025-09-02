"""Constants for the Marstek Venus HA integration."""

DOMAIN = "marstek_venus_ha"

# Configuration Keys
CONF_GRID_POWER_SENSOR = "grid_power_sensor"
CONF_SMOOTHING_SECONDS = "smoothing_seconds"
CONF_BATTERY_1_ENTITY = "battery_1_entity"
CONF_BATTERY_2_ENTITY = "battery_2_entity"
CONF_BATTERY_3_ENTITY = "battery_3_entity"
CONF_MIN_SOC = "min_soc"
CONF_MAX_SOC = "max_soc"
CONF_POWER_STAGE_1 = "power_stage_1"
CONF_POWER_STAGE_2 = "power_stage_2"
CONF_PRIORITY_INTERVAL = "priority_interval"
CONF_WALLBOX_POWER_SENSOR = "wallbox_power_sensor"
CONF_WALLBOX_MAX_SURPLUS = "wallbox_max_surplus"
CONF_WALLBOX_CABLE_SENSOR = "wallbox_cable_sensor"

# Default values
DEFAULT_SMOOTHING_SECONDS = 5
DEFAULT_MIN_SOC = 10
DEFAULT_MAX_SOC = 95
DEFAULT_POWER_STAGE_1 = 1800
DEFAULT_POWER_STAGE_2 = 3600
DEFAULT_PRIORITY_INTERVAL = 15
DEFAULT_WALLBOX_MAX_SURPLUS = 1500

# Update interval for the main coordinator loop
COORDINATOR_UPDATE_INTERVAL_SECONDS = 1
