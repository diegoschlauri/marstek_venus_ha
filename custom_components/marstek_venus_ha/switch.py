from datetime import datetime

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from .coordinator import MarstekCoordinator, PowerDir
from .const import DOMAIN, SIGNAL_DIAGNOSTICS_UPDATED


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChargingSwitch(entry, coordinator), DischargingSwitch(entry, coordinator), WallboxPrioritySwitch(entry, coordinator)])


class ChargingSwitch(SwitchEntity):
    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        self._entry = entry
        self._data = data_object
        self._attr_name = "Allow Charging"
        self._attr_unique_id = f"{entry.entry_id}_charging_switch"

    @property
    def available(self) -> bool:
        return bool(self._data.is_running)

    @property
    def is_on(self) -> bool:
        return bool(self._data._allow_charging)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Marstek Venus HA",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DIAGNOSTICS_UPDATED,
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self._data._allow_charging = True
        self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
        self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._allow_charging = False
        self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
        self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))


class DischargingSwitch(SwitchEntity):
    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        self._entry = entry
        self._data = data_object
        self._attr_name = "Allow Discharging"
        self._attr_unique_id = f"{entry.entry_id}_discharging_switch"

    @property
    def available(self) -> bool:
        return bool(self._data.is_running)

    @property
    def is_on(self) -> bool:
        return bool(self._data._allow_discharging)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Marstek Venus HA",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DIAGNOSTICS_UPDATED,
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self._data._allow_discharging = True
        self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
        self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._allow_discharging = False
        self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
        self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

class WallboxPrioritySwitch(SwitchEntity):
    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        self._entry = entry
        self._data = data_object
        self._attr_name = "Wallbox Priority"
        self._attr_unique_id = f"{entry.entry_id}_wallbox_priority_switch"

    @property
    def available(self) -> bool:
        return bool(self._data.is_running)

    @property
    def is_on(self) -> bool:
        return bool(self._data._wallbox_priority)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Marstek Venus HA",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DIAGNOSTICS_UPDATED,
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        self._data._wallbox_priority = True
        self._data._wallbox_wait_start = None  # Reset wallbox wait timer to allow immediate priority
        self._data._last_wallbox_pause_attempt = datetime.min  # Reset last pause attempt to allow immediate action
        self._data._wallbox_power_history.clear()  # Clear power history to allow immediate stability assessment
        self._data._wallbox_power_is_stable = False  # Reset stability flag to force reassessment
        self._data._wallbox_stabilization_start = None  # Reset stabilization timer
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._wallbox_priority = False
        self._data._wallbox_charge_paused = False  # Release Batteries from blockade
        self._data._last_wallbox_pause_attempt = datetime.min  # Reset last pause attempt to allow immediate action
        self._data._wallbox_power_history.clear()  # Clear power history to allow immediate stability assessment
        self._data._wallbox_power_is_stable = False  # Reset stability flag to force reassessment
        self._data._wallbox_stabilization_start = None  # Reset stabilization timer
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))