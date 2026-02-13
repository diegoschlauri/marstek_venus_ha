"""Sensor platform for the Marstek Venus HA integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, SIGNAL_DIAGNOSTICS_UPDATED
from .coordinator import MarstekCoordinator


@dataclass(frozen=True, slots=True)
class DiagnosticSensorDescription(SensorEntityDescription):
    value_fn: Callable[[MarstekCoordinator], Any] | None = None


DIAGNOSTIC_SENSORS: tuple[DiagnosticSensorDescription, ...] = (
    DiagnosticSensorDescription(
        key="is_running",
        name="Is Running",
        value_fn=lambda c: c.is_running,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="service_call_cache_entries",
        name="Service Call Cache Entries",
        value_fn=lambda c: c.service_call_cache_size,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="wallbox_charge_paused",
        name="Wallbox Charge Paused",
        value_fn=lambda c: c.wallbox_charge_paused,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="wallbox_power_is_stable",
        name="Wallbox Power is stable",
        value_fn=lambda c: c.wallbox_power_is_stable,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="wallbox_wait_start",
        name="Wallbox Wait Start",
        value_fn=lambda c: c.wallbox_wait_start,
        device_class=SensorDeviceClass.TIMESTAMP,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="wallbox_start_delay_end",
        name="Wallbox Start Delay End",
        value_fn=lambda c: c.wallbox_start_delay_end,
        device_class=SensorDeviceClass.TIMESTAMP,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="wallbox_cooldown_end",
        name="Wallbox Cooldown End",
        value_fn=lambda c: c.wallbox_cooldown_end,
        device_class=SensorDeviceClass.TIMESTAMP,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="wallbox_stabilization_start",
        name="Wallbox Stabilization Start",
        value_fn=lambda c: c.wallbox_stabilization_start,
        device_class=SensorDeviceClass.TIMESTAMP,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="battery_priority",
        name="Battery Priority",
        value_fn=lambda c: c.battery_priority_ids,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="priority_next_update",
        name="Priority Next Update",
        value_fn=lambda c: c.priority_next_update,
        device_class=SensorDeviceClass.TIMESTAMP,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="priority_rate_limit_end",
        name="Priority Rate Limit End",
        value_fn=lambda c: c.priority_rate_limit_end,
        device_class=SensorDeviceClass.TIMESTAMP,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="last_power_direction",
        name="Last Power Direction",
        value_fn=lambda c: c.last_power_direction_name,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="below_min_charge_count",
        name="Below Min Charge Count",
        value_fn=lambda c: c.below_min_charge_count,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="below_min_discharge_count",
        name="Below Min Discharge Count",
        value_fn=lambda c: c.below_min_discharge_count,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="pid_integral",
        name="PID Integral",
        value_fn=lambda c: c.pid_integral,
        has_entity_name=True,
    ),
    DiagnosticSensorDescription(
        key="pid_prev_error",
        name="PID Previous Error",
        value_fn=lambda c: c.pid_prev_error,
        has_entity_name=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    coordinator: MarstekCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        MarstekDiagnosticSensor(coordinator, entry, description)
        for description in DIAGNOSTIC_SENSORS
    )


class MarstekDiagnosticSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: MarstekCoordinator,
        entry: ConfigEntry,
        description: DiagnosticSensorDescription,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self.entity_description = description

        self._attr_unique_id = f"{entry.entry_id}_diag_{description.key}"
        self._attr_has_entity_name = True
        self._attr_name = description.name
        self._attr_device_class = description.device_class

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Marstek Venus HA",
        )

    @property
    def available(self) -> bool:
        return self._coordinator.is_running

    @property
    def native_value(self) -> Any:
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self._coordinator)

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
