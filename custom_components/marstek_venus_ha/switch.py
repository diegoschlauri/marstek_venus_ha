import logging
from datetime import datetime

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo
from .coordinator import MarstekCoordinator, PowerDir
from .const import DOMAIN, SIGNAL_DIAGNOSTICS_UPDATED

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [
        ControlSwitch(entry, coordinator),
        ChargingSwitch(entry, coordinator),
        DischargingSwitch(entry, coordinator),
        WallboxPrioritySwitch(entry, coordinator),
        BlockDischargingCCSwitch(entry, coordinator)
    ]
    for batt_id in coordinator.battery_ids:
        entities.append(BatteryEnabledSwitch(entry, coordinator, batt_id))
        entities.append(BatteryBackupReserveSwitch(entry, coordinator, batt_id))
    async_add_entities(entities)


def _battery_label(batt_id: str) -> str:
    """'battery_1' -> 'Battery 1'."""
    return batt_id.replace("_", " ").capitalize()


class _BatteryRuntimeSwitch(SwitchEntity):
    """Base class for per-battery runtime switches (always available, persisted in the store)."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator, batt_id: str):
        self._entry = entry
        self._data = data_object
        self._batt_id = batt_id

    @property
    def available(self) -> bool:
        # Always available so automations can change the setting at any time;
        # it is applied as soon as the control logic is running.
        return True

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

    def _common_attributes(self) -> dict:
        return {
            "battery_id": self._batt_id,
            "current_soc": self._data.get_battery_current_soc(self._batt_id),
            "in_priority_list": self._batt_id in self._data.battery_priority_ids.split(),
        }


class BatteryEnabledSwitch(_BatteryRuntimeSwitch):
    """Include (on) or completely exclude (off) a battery from the control logic."""

    _attr_icon = "mdi:battery-sync"

    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator, batt_id: str):
        super().__init__(entry, data_object, batt_id)
        self._attr_name = f"{_battery_label(batt_id)} Active"
        self._attr_unique_id = f"{entry.entry_id}_{batt_id}_enabled_switch"

    @property
    def is_on(self) -> bool:
        return self._data.is_battery_enabled(self._batt_id)

    @property
    def extra_state_attributes(self) -> dict:
        return self._common_attributes()

    async def async_turn_on(self, **kwargs):
        await self._data.async_set_battery_enabled(self._batt_id, True)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)

    async def async_turn_off(self, **kwargs):
        await self._data.async_set_battery_enabled(self._batt_id, False)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)


class BatteryBackupReserveSwitch(_BatteryRuntimeSwitch):
    """Activate the additional backup reserve (min SoC for discharging) of a battery."""

    _attr_icon = "mdi:battery-lock"

    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator, batt_id: str):
        super().__init__(entry, data_object, batt_id)
        self._attr_name = f"{_battery_label(batt_id)} Backup Reserve"
        self._attr_unique_id = f"{entry.entry_id}_{batt_id}_backup_reserve_switch"

    @property
    def is_on(self) -> bool:
        return self._data.is_battery_backup_reserve_enabled(self._batt_id)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = self._common_attributes()
        attrs["backup_reserve_soc"] = self._data.get_battery_backup_reserve_soc(self._batt_id)
        attrs["effective_discharge_min_soc"] = self._data.get_battery_discharge_min_soc(self._batt_id)
        return attrs

    async def async_turn_on(self, **kwargs):
        await self._data.async_set_battery_backup_reserve_enabled(self._batt_id, True)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)

    async def async_turn_off(self, **kwargs):
        await self._data.async_set_battery_backup_reserve_enabled(self._batt_id, False)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)


class ControlSwitch(SwitchEntity):
    """Switch to enable/disable the entire integration's control logic."""

    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        """Initialize the switch."""
        self._entry = entry
        self._data = data_object
        self._attr_name = "Control Batteries"
        self._attr_unique_id = f"{entry.entry_id}_control_switch"

    @property
    def available(self) -> bool:
        """Return if the switch is available."""
        return True  # Always available to allow re-enabling control

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return bool(self._data._control_enabled)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Marstek Venus HA",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DIAGNOSTICS_UPDATED,
                self._handle_coordinator_update,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        if not self._data._control_enabled:
            _LOGGER.info("Battery control has been enabled.")
            self._data._control_enabled = True
            # Reset PID state to avoid leftover integral/derivative states
            # from previous runs causing incorrect control on re-enable.
            try:
                self._data._reset_pid_state()
            except Exception:
                # Best-effort: ignore if method not present for backward compatibility
                pass
            await self._data.async_save_settings()
            self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
            self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
            self.async_write_ha_state()
            async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
            if hasattr(self._data, "async_request_update"):
                self.hass.async_create_task(self._data.async_request_update(reason="control_enabled"))
            await self._data.async_start_listening()  # Start listening to updates when control is enabled

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._data._control_enabled:
            self._data._control_enabled = False
            # Reset PID state when disabling control to avoid windup
            try:
                self._data._reset_pid_state()
            except Exception:
                pass
            await self._data.async_save_settings()
            self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
            self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
            self.async_write_ha_state()
            async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
            await self._data.async_stop_listening()  # Stop listening to updates when control is disabled

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
        await self._data.async_save_settings()
        self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
        self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._allow_charging = False
        await self._data.async_save_settings()
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
        await self._data.async_save_settings()
        self._data._battery_priority = []  # Clear battery priority to force recalculation on next update
        self._data._last_power_direction = PowerDir.NEUTRAL  # Reset power direction to force recalculation
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._allow_discharging = False
        await self._data.async_save_settings()
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
        await self._data.async_save_settings()
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
        await self._data.async_save_settings()
        self._data._wallbox_charge_paused = False  # Release Batteries from blockade
        self._data._last_wallbox_pause_attempt = datetime.min  # Reset last pause attempt to allow immediate action
        self._data._wallbox_power_history.clear()  # Clear power history to allow immediate stability assessment
        self._data._wallbox_power_is_stable = False  # Reset stability flag to force reassessment
        self._data._wallbox_stabilization_start = None  # Reset stabilization timer
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

class BlockDischargingCCSwitch(SwitchEntity):
    def __init__(self, entry: ConfigEntry, data_object: MarstekCoordinator):
        self._entry = entry
        self._data = data_object
        self._attr_name = "Block discharging while carcharging"
        self._attr_unique_id = f"{entry.entry_id}_block_discharging_cc_switch"

    @property
    def available(self) -> bool:
        return bool(self._data.is_running)

    @property
    def is_on(self) -> bool:
        return bool(self._data._block_discharging_while_carcharging)

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
        self._data._block_discharging_while_carcharging = True
        await self._data.async_save_settings()
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))

    async def async_turn_off(self, **kwargs):
        self._data._block_discharging_while_carcharging = False
        await self._data.async_save_settings()
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)
        if hasattr(self._data, "async_request_update"):
            self.hass.async_create_task(self._data.async_request_update(reason="switch_toggle"))