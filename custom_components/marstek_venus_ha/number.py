"""Number platform for the Marstek Venus HA integration (per-battery backup reserve SoC)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    DOMAIN,
    SIGNAL_DIAGNOSTICS_UPDATED,
    MIN_BACKUP_RESERVE_SOC,
    MAX_BACKUP_RESERVE_SOC,
)
from .coordinator import MarstekCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    coordinator: MarstekCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        BatteryBackupReserveSocNumber(entry, coordinator, batt_id)
        for batt_id in coordinator.battery_ids
    )


class BatteryBackupReserveSocNumber(NumberEntity):
    """Additional min SoC (backup reserve) used for discharging when the reserve switch is on."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:battery-heart-variant"
    _attr_native_min_value = float(MIN_BACKUP_RESERVE_SOC)
    _attr_native_max_value = float(MAX_BACKUP_RESERVE_SOC)
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, coordinator: MarstekCoordinator, batt_id: str) -> None:
        self._entry = entry
        self._data = coordinator
        self._batt_id = batt_id
        label = batt_id.replace("_", " ").capitalize()
        self._attr_name = f"{label} Backup Reserve SoC"
        self._attr_unique_id = f"{entry.entry_id}_{batt_id}_backup_reserve_soc"

    @property
    def available(self) -> bool:
        return True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Marstek Venus HA",
        )

    @property
    def native_value(self) -> float:
        return self._data.get_battery_backup_reserve_soc(self._batt_id)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "battery_id": self._batt_id,
            "backup_reserve_active": self._data.is_battery_backup_reserve_enabled(self._batt_id),
            "effective_discharge_min_soc": self._data.get_battery_discharge_min_soc(self._batt_id),
        }

    async def async_set_native_value(self, value: float) -> None:
        await self._data.async_set_battery_backup_reserve_soc(self._batt_id, value)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)

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

