"""Coordinator for the Marstek Venus HA integration."""
import logging
from collections import deque
from datetime import datetime, timedelta
import asyncio

from homeassistant.core import HomeAssistant, State
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_ON

from .const import (
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
    COORDINATOR_UPDATE_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

class MarstekCoordinator:
    """The main coordinator for handling battery logic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        self.config = entry.data
        self._is_running = False
        self._unsub_listener = None

        # State variables
        self._power_history = deque(maxlen=self._get_deque_size())
        self._battery_priority = []
        self._last_priority_update = datetime.min
        self._last_power_direction = 0  # 1 for charging, -1 for discharging, 0 for neutral
        self._wallbox_charge_paused_at = None
        
        # Collect battery entities
        self._battery_entities = [
            b for b in [
                self.config.get(CONF_BATTERY_1_ENTITY),
                self.config.get(CONF_BATTERY_2_ENTITY),
                self.config.get(CONF_BATTERY_3_ENTITY),
            ] if b
        ]

    def _get_deque_size(self):
        """Calculate deque size based on config."""
        smoothing_seconds = self.config.get(CONF_SMOOTHING_SECONDS)
        return max(1, smoothing_seconds // COORDINATOR_UPDATE_INTERVAL_SECONDS)

    async def async_start_listening(self):
        """Start the coordinator's update loop."""
        if not self._is_running:
            self._unsub_listener = async_track_time_interval(
                self.hass,
                self._async_update,
                timedelta(seconds=COORDINATOR_UPDATE_INTERVAL_SECONDS),
            )
            self._is_running = True
            _LOGGER.info("Marstek Venus HA coordinator started.")

    async def async_stop_listening(self):
        """Stop the coordinator's update loop."""
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None
        self._is_running = False
        # Set all battery powers to 0 on shutdown
        await self._set_all_batteries_to_zero()
        _LOGGER.info("Marstek Venus HA coordinator stopped.")

    def _get_entity_state(self, entity_id: str) -> State | None:
        """Safely get the state of an entity."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.warning(f"Entity '{entity_id}' is unavailable or unknown.")
            return None
        return state

    async def _async_update(self, now=None):
        """Fetch new data and run the logic."""
        _LOGGER.debug("Coordinator update triggered.")

        # 1. Get smoothed grid power
        smoothed_power = self._get_smoothed_grid_power()
        if smoothed_power is None:
            _LOGGER.warning("Could not determine grid power. Skipping update cycle.")
            return

        # 2. Handle Wallbox logic, which can override battery control
        if await self._handle_wallbox_logic(smoothed_power):
            _LOGGER.debug("Wallbox logic took control. Ending update cycle.")
            return
        
        # 3. Determine if priority needs recalculation
        await self._update_battery_priority_if_needed(smoothed_power)

        # 4. Distribute power based on stages and priority
        await self._distribute_power(smoothed_power)

    def _get_smoothed_grid_power(self) -> float | None:
        """Get the current power from the grid sensor and calculate the smoothed average."""
        grid_sensor_id = self.config.get(CONF_GRID_POWER_SENSOR)
        grid_state = self._get_entity_state(grid_sensor_id)
        
        if grid_state is None:
            return None
        
        try:
            current_power = float(grid_state.state)
            self._power_history.append(current_power)
            
            if not self._power_history:
                return 0.0

            avg_power = sum(self._power_history) / len(self._power_history)
            _LOGGER.debug(f"Current power: {current_power}W, Smoothed power: {avg_power:.2f}W")
            return avg_power
        except (ValueError, TypeError):
            _LOGGER.error(f"Could not parse grid power sensor '{grid_sensor_id}' state: '{grid_state.state}'")
            return None

    async def _update_battery_priority_if_needed(self, current_power: float):
        """Check conditions and update battery priority list."""
        # Determine current power direction
        # Negative power is surplus (charging), positive is demand (discharging)
        power_direction = 0
        if current_power < -50:  # Hysteresis to prevent flipping
            power_direction = 1  # Charging
        elif current_power > 50:
            power_direction = -1 # Discharging

        priority_interval = timedelta(minutes=self.config.get(CONF_PRIORITY_INTERVAL))
        time_since_last_update = datetime.now() - self._last_priority_update

        if (
            power_direction != self._last_power_direction or
            time_since_last_update > priority_interval
        ):
            _LOGGER.info(f"Recalculating battery priority. Reason: {'Power direction changed' if power_direction != self._last_power_direction else 'Time interval elapsed'}")
            await self._calculate_battery_priority(power_direction)
            self._last_power_direction = power_direction
            self._last_priority_update = datetime.now()

    async def _calculate_battery_priority(self, power_direction: int):
        """Calculate the sorted list of batteries based on SoC."""
        if power_direction == 0:
            self._battery_priority = []
            return

        min_soc = self.config.get(CONF_MIN_SOC)
        max_soc = self.config.get(CONF_MAX_SOC)
        
        available_batteries = []
        for base_entity_id in self._battery_entities:
            soc_sensor_id = f"sensor.{base_entity_id}_soc"
            soc_state = self._get_entity_state(soc_sensor_id)
            
            if soc_state is None:
                continue
            
            try:
                soc = float(soc_state.state)
                # Check if battery is eligible based on direction and SoC limits
                if power_direction == 1 and soc < max_soc:  # Charging
                    available_batteries.append({"id": base_entity_id, "soc": soc})
                elif power_direction == -1 and soc > min_soc:  # Discharging
                    available_batteries.append({"id": base_entity_id, "soc": soc})
            except (ValueError, TypeError):
                _LOGGER.warning(f"Could not parse SoC for {soc_sensor_id}")
                continue
        
        # Sort the batteries
        # For charging, lowest SoC first (ascending)
        # For discharging, highest SoC first (descending)
        is_reverse = (power_direction == -1)
        self._battery_priority = sorted(available_batteries, key=lambda x: x['soc'], reverse=is_reverse)
        _LOGGER.debug(f"New battery priority: {self._battery_priority}")

    async def _distribute_power(self, power: float):
        """Control battery charge/discharge based on power stages."""
        abs_power = abs(power)
        stage1 = self.config.get(CONF_POWER_STAGE_1)
        stage2 = self.config.get(CONF_POWER_STAGE_2)
        
        num_available = len(self._battery_priority)
        if num_available == 0 or self._last_power_direction == 0:
            await self._set_all_batteries_to_zero()
            return
            
        active_batteries = []
        if abs_power <= stage1 or num_available == 1:
            active_batteries = self._battery_priority[:1]
        elif stage1 < abs_power <= stage2 or num_available == 2:
            active_batteries = self._battery_priority[:2]
        else: # abs_power > stage2 and num_available >= 3
            active_batteries = self._battery_priority[:3]

        if not active_batteries:
            await self._set_all_batteries_to_zero()
            return

        power_per_battery = round(abs_power / len(active_batteries))
        active_battery_ids = [b['id'] for b in active_batteries]

        _LOGGER.debug(f"Distributing {power:.0f}W to {len(active_battery_ids)} batteries: {active_battery_ids} with {power_per_battery}W each.")

        # Set power for all batteries
        for battery_base_id in self._battery_entities:
            if battery_base_id in active_battery_ids:
                await self._set_battery_power(battery_base_id, power_per_battery, self._last_power_direction)
            else:
                await self._set_battery_power(battery_base_id, 0, 0)

    async def _handle_wallbox_logic(self, smoothed_grid_power: float) -> bool:
        """Implement the wallbox charging logic. Returns True if it took control."""
        wb_power_sensor = self.config.get(CONF_WALLBOX_POWER_SENSOR)
        wb_cable_sensor = self.config.get(CONF_WALLBOX_CABLE_SENSOR)

        if not all([wb_power_sensor, wb_cable_sensor]):
            return False # Wallbox not configured

        cable_state = self._get_entity_state(wb_cable_sensor)
        if cable_state is None or cable_state.state != STATE_ON:
            self._wallbox_charge_paused_at = None # Reset pause timer if cable unplugged
            return False # Cable not plugged in, wallbox logic inactive

        # Cable is plugged in
        power_state = self._get_entity_state(wb_power_sensor)
        try:
            wb_power = float(power_state.state) if power_state else 0.0
        except (ValueError, TypeError):
            wb_power = 0.0

        # Rule: If wallbox is drawing power, stop ALL battery discharging
        if wb_power > 10: # Hysteresis
            _LOGGER.info("Wallbox is active, disabling all battery discharging.")
            # We only need to stop discharging. Charging from surplus is still ok.
            if self._last_power_direction == -1: # if we are currently discharging
                await self._set_all_batteries_to_zero()
                return True
        
        # Rule: If PV surplus is high, pause battery charging for the car
        # A negative smoothed_grid_power means surplus (e.g., -2000W is 2kW surplus)
        surplus = -smoothed_grid_power
        max_surplus = self.config.get(CONF_WALLBOX_MAX_SURPLUS)

        if surplus > max_surplus and self._last_power_direction == 1: # High surplus and we are charging
            _LOGGER.info(f"High PV surplus ({surplus:.0f}W > {max_surplus}W). Pausing battery charging for wallbox.")
            await self._set_all_batteries_to_zero()
            if self._wallbox_charge_paused_at is None:
                self._wallbox_charge_paused_at = datetime.now()
            return True # Wallbox logic takes control

        # Rule: If charging paused for > 5 mins and car hasn't started, resume battery charging
        if self._wallbox_charge_paused_at and wb_power < 10:
            pause_duration = datetime.now() - self._wallbox_charge_paused_at
            if pause_duration > timedelta(minutes=5):
                _LOGGER.info("Wallbox did not start charging for 5 minutes. Resuming battery charging.")
                self._wallbox_charge_paused_at = None
                return False # Let normal logic resume

        # If we paused and the car started charging, keep the timestamp to not resume later
        if self._wallbox_charge_paused_at and wb_power > 10:
             self._wallbox_charge_paused_at = None

        return False # Wallbox logic does not need to intervene

    async def _set_battery_power(self, base_entity_id: str, power: int, direction: int):
        """Set the charge or discharge power for a single battery."""
        charge_entity = f"number.{base_entity_id}_charge_power"
        discharge_entity = f"number.{base_entity_id}_discharge_power"
        
        try:
            if direction == 1: # Charging
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": power})
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": 0})
            elif direction == -1: # Discharging
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": 0})
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": power})
            else: # Set to zero
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": 0})
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": 0})
        except Exception as e:
            _LOGGER.error(f"Failed to set power for {base_entity_id}: {e}")

    async def _set_all_batteries_to_zero(self):
        """Set all configured batteries to 0 charge and discharge power."""
        _LOGGER.debug("Setting all batteries to 0W.")
        tasks = [self._set_battery_power(b_id, 0, 0) for b_id in self._battery_entities]
        await asyncio.gather(*tasks)
