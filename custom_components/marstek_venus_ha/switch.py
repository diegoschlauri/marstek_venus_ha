from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from .coordinator import MarstekCoordinator
from .const import DOMAIN, SIGNAL_DIAGNOSTICS_UPDATED


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChargingSwitch(entry, coordinator), DischargingSwitch(entry, coordinator)])


class ChargingSwitch(SwitchEntity):
    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        self._entry = entry
        self._data = data_object
        self._attr_name = "Charging Allowed"
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
        self.async_write_ha_state()
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._allow_charging = False
        self.async_write_ha_state()
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))


class DischargingSwitch(SwitchEntity):
    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        self._entry = entry
        self._data = data_object
        self._attr_name = "Discharging Allowed"
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
        self.async_write_ha_state()
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._allow_discharging = False
        self.async_write_ha_state()
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))