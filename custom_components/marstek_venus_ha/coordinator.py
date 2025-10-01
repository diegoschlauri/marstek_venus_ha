"""Coordinator for the Marstek Venus HA integration."""
import logging
from collections import deque
from datetime import datetime, timedelta
import asyncio

from homeassistant.core import HomeAssistant, State
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_ON

from .const import (
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
    CONF_WALLBOX_START_DELAY_SECONDS,
    COORDINATOR_UPDATE_INTERVAL_SECONDS
)

_LOGGER = logging.getLogger(__name__)

class MarstekCoordinator:
    """The main coordinator for handling battery logic."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        # Erstelle eine kombinierte Konfiguration.
        # Beginne mit den Daten aus der Ersteinrichtung...
        self.config = dict(entry.data)
        # ...und überschreibe sie mit den Werten aus dem Options-Flow.
        self.config.update(entry.options)

        self._is_running = False
        self._unsub_listener = None

        # State variables
        self._power_history = deque(maxlen=self._get_deque_size("smoothing"))
        self._battery_priority = []
        self._last_priority_update = datetime.min
        self._last_power_direction = 0  # 1 for charging, -1 for discharging, 0 for neutral
        
        # Wallbox state
        self._wallbox_charge_paused = False
        self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))

        # Collect battery entities
        self._battery_entities = [
            b for b in [
                self.config.get(CONF_BATTERY_1_ENTITY),
                self.config.get(CONF_BATTERY_2_ENTITY),
                self.config.get(CONF_BATTERY_3_ENTITY),
            ] if b
        ]

    def _get_deque_size(self, mode: str):
        """Calculate deque size based on config."""
        if mode == "smoothing":
            seconds = self.config.get(CONF_SMOOTHING_SECONDS)
        elif mode == "wallbox":
            seconds = self.config.get(CONF_WALLBOX_RESUME_CHECK_SECONDS)
        else:
            return 1
            
        return max(1, seconds // COORDINATOR_UPDATE_INTERVAL_SECONDS)

    async def wait_for_entity_available(self, entity_id, timeout=60):
        """Wait until the entity is available or timeout."""
        event = asyncio.Event()
    
        def _listener(entity, old_state, new_state):
            if new_state and new_state.state not in ("unavailable", "unknown"):
                event.set()
    
        # Check if already available
        state = self.hass.states.get(entity_id)
        if state and state.state not in ("unavailable", "unknown"):
            return
    
        remove = async_track_state_change(self.hass, entity_id, _listener)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            remove()
    
    async def async_start_listening(self):
        """Start the coordinator's update loop."""
        # Wait for grid_power_sensor
        grid_power_sensor = self.config.get(CONF_GRID_POWER_SENSOR)
        await self.wait_for_entity_available(grid_power_sensor)
    
        # Wait for wallbox_cable_sensor if defined
        wallbox_cable_sensor = self.config.get(CONF_WALLBOX_CABLE_SENSOR)
        if wallbox_cable_sensor:
            await self.wait_for_entity_available(wallbox_cable_sensor)
            
        if not self._is_running:
            # Re-initialize deques on start
            self._power_history = deque(maxlen=self._get_deque_size("smoothing"))
            self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))
            await self._set_all_batteries_to_zero() # Reset Batteries to 0 on Start-Up
            self._unsub_listener = async_track_time_interval(
                self.hass,
                self._async_update,
                timedelta(seconds=COORDINATOR_UPDATE_INTERVAL_SECONDS),
            )
            self._is_running = True
            _LOGGER.info("Marstek Venus HA Integration coordinator started.")

    async def async_stop_listening(self):
        """Stop the coordinator's update loop."""
        if self._unsub_listener:
            self._unsub_listener()
            self._unsub_listener = None
        self._is_running = False
        await self._set_all_batteries_to_zero()
        _LOGGER.info("Marstek Venus HA Integration coordinator stopped.")

    def _get_entity_state(self, entity_id: str) -> State | None:
        """Safely get the state of an entity."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.warning(f"Entity '{entity_id}' is unavailable or unknown.")
            return None
        return state

    async def _async_update(self, now=None):
        """Fetch new data and run the logic."""
        _LOGGER.debug("Coordinator update triggered.")

        real_power = self._get_real_power()
        if real_power is None:
            _LOGGER.warning("Could not determine real power. Skipping update cycle.")
            return

        if await self._handle_wallbox_logic(real_power):
            _LOGGER.debug("Wallbox logic took control. Ending update cycle.")
            return
        
        await self._update_battery_priority_if_needed(real_power)
        await self._distribute_power(real_power, self._last_power_direction)

    def _get_float_state(self, entity_id: str) -> float | None:
        """Safely get a float value from a state."""
        state = self._get_entity_state(entity_id)
        if state is None:
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(f"Could not parse state of '{entity_id}' as float: '{state.state}'")
            return None

    def _get_smoothed_grid_power(self) -> float | None:
        """Get the current power from the grid sensor and calculate the smoothed average."""
        grid_sensor_id = self.config.get(CONF_GRID_POWER_SENSOR)
        current_power = self._get_float_state(grid_sensor_id)
        
        if current_power is None:
            return None
            
        self._power_history.append(current_power)
        if not self._power_history:
            return 0.0

        avg_power = sum(self._power_history) / len(self._power_history)
        _LOGGER.debug(f"Current grid power: {current_power}W, Smoothed grid power: {avg_power:.2f}W")
        return avg_power

    def _get_real_power(self) -> float | None:
        """Get the real power of the house excluding the batteries. A positiv value means the house uses more power than it produced excluding the batteries. 
        A negative value means the house produces more power than its acutally used excluding the batteries."""
        smoothed_grid_power = self._get_smoothed_grid_power()
        
        if smoothed_grid_power is None:
            return None

        # Get the current power of all batteries
        total_battery_power = 0
        total_battery_power = sum(
                p for p in [
                    self._get_float_state(f"sensor.{b}_power") for b in self._battery_entities
                ] if p is not None and p > 0
            )
        
        # Calculate real power based on batterie direction
        if self._last_power_direction == -1: #Batteries are actually discharging 
            real_power = (smoothed_grid_power + total_battery_power) 
        elif self._last_power_direction == 1: #Batteries are actually charging
            real_power = (smoothed_grid_power - total_battery_power)
        else:
            real_power = smoothed_grid_power
        
        _LOGGER.debug(f"Current real power without batteries: {real_power}W")
        return real_power

    async def _handle_wallbox_logic(self, real_power: float) -> bool:
        """Implement the wallbox charging logic. Returns True if it took control."""
        wb_power_sensor = self.config.get(CONF_WALLBOX_POWER_SENSOR)
        wb_cable_sensor = self.config.get(CONF_WALLBOX_CABLE_SENSOR)
        max_surplus = self.config.get(CONF_WALLBOX_MAX_SURPLUS)
        stability_treshold = self.config.get(CONF_WALLBOX_POWER_STABILITY_THRESHOLD)
        start_delay = self.config.get(CONF_WALLBOX_START_DELAY_SECONDS)

        if not all([wb_power_sensor, wb_cable_sensor, max_surplus is not None]):
            self._wallbox_charge_paused = False
            return False

        cable_state = self._get_entity_state(wb_cable_sensor)
        if not cable_state or cable_state.state != STATE_ON:
            self._wallbox_charge_paused = False
            self._wallbox_power_history.clear()
            return False

        wb_power = self._get_float_state(wb_power_sensor) or 0.0
        self._wallbox_power_history.append(wb_power)

        # Reset wait timer if it exceeds 10 hour (safety)
        if hasattr(self, "_wallbox_wait_start") and self._wallbox_wait_start is not None:
            elapsed = (datetime.now() - self._wallbox_wait_start).total_seconds()
            if elapsed > 36000: 
                self._wallbox_wait_start = None

        # Rule 1: Always prevent battery discharge if wallbox is drawing power
        if wb_power > 100:
            _LOGGER.debug("Wallbox is active, ensuring batteries do not discharge.")
            # Reset wallbox wait timer if wallbox is active
            self._wallbox_wait_start = None
            if self._last_power_direction == -1:
                await self._set_all_batteries_to_zero()
                return True # Take control to stop discharging

        # Rule 2: Check if battery charging should be PAUSED for the car
        if real_power < -max_surplus:
            _LOGGER.info(f"Real surplus ({abs(real_power):.0f}W) > max ({max_surplus}W). Try pausing battery charging.")
            # If wallbox does not start charging (wb_power <= 100) in 120 seconds, free batteries
            if wb_power <= 100:
            # Only start timer if not already started
                if not hasattr(self, "_wallbox_wait_start") or self._wallbox_wait_start is None:
                    # pause Batteries, start timer
                    self._wallbox_wait_start = datetime.now()
                    self._wallbox_charge_paused = True
                    await self._set_all_batteries_to_zero()
                    return True
                else:
                    # Check elapsed time
                    elapsed = (datetime.now() - self._wallbox_wait_start).total_seconds()
                    if elapsed > start_delay:
                        # Time exceeded, resume battery logic
                        _LOGGER.info(f"Wallbox did not start charging in {start_delay} seconds. Resuming battery logic.")
                        self._wallbox_charge_paused = False
                        self._wallbox_power_history.clear()
                        return False

        # Rule 3: Check if paused charging can be RESUMED
        if self._wallbox_charge_paused:
            # Check if history is full (5 minutes passed)
            if len(self._wallbox_power_history) == self._wallbox_power_history.maxlen:
                oldest_power = self._wallbox_power_history[0]
                power_increase = wb_power - oldest_power
                
                # If power has not increased significantly, car is likely full or at max rate
                if power_increase < stability_treshold:
                    _LOGGER.info(f"Wallbox power has stabilized. Resuming battery charging logic.")
                    self._wallbox_charge_paused = False
                    self._wallbox_power_history.clear()
                    # We return False to let the normal logic resume charging.
                    # The discharge protection (Rule 1) will still apply if wb_power > 100 Watt.
                    return False

            # If still paused, keep batteries at zero
            _LOGGER.debug("Battery charging remains paused for wallbox.")
            await self._set_all_batteries_to_zero()
            return True

        return False

    async def _update_battery_priority_if_needed(self, real_power: float):
        """Check conditions and update battery priority list."""
        min_surplus_for_check = self.config.get(CONF_MIN_SURPLUS, 50)
        min_consumption_for_check = self.config.get(CONF_MIN_CONSUMPTION, 50)
        
        # power direction: 1 for charging, -1 for discharging, 0 for neutral
        power_direction = 0

        # decide the new direction
        if real_power  < -abs(min_surplus_for_check):
            power_direction = 1 # charging
        elif real_power  > abs(min_consumption_for_check):
            power_direction = -1 # discharging

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
            soc = self._get_float_state(f"sensor.{base_entity_id}_soc")
            if soc is None:
                continue

            if power_direction == 1 and soc < max_soc:
                available_batteries.append({"id": base_entity_id, "soc": soc})
            elif power_direction == -1 and soc > min_soc:
                available_batteries.append({"id": base_entity_id, "soc": soc})

        is_reverse = (power_direction == -1)
        self._battery_priority = sorted(available_batteries, key=lambda x: x['soc'], reverse=is_reverse)
        _LOGGER.debug(f"New battery priority: {self._battery_priority}")

    async def _distribute_power(self, power: float, power_direction: int):
        """Control battery charge/discharge based on power stages."""
        abs_power = abs(power)
        if power_direction == -1: #Currently Discharging
            stage1 = self.config.get(CONF_POWER_STAGE_DISCHARGE_1)
            stage2 = self.config.get(CONF_POWER_STAGE_DISCHARGE_2)
        else:
            stage1 = self.config.get(CONF_POWER_STAGE_CHARGE_1)
            stage2 = self.config.get(CONF_POWER_STAGE_CHARGE_2)
        
        num_available = len(self._battery_priority)
        if num_available == 0 or self._last_power_direction == 0:
            await self._set_all_batteries_to_zero()
            return
            
        active_batteries = []
        if abs_power <= stage1 or num_available == 1:
            active_batteries = self._battery_priority[:1]
        elif (stage1 < abs_power <= stage2) or num_available == 2:
            active_batteries = self._battery_priority[:2]
        else:
            active_batteries = self._battery_priority[:3]

        if not active_batteries:
            await self._set_all_batteries_to_zero()
            return

        power_per_battery = round(abs_power / len(active_batteries))
        active_battery_ids = [b['id'] for b in active_batteries]

        _LOGGER.debug(f"Distributing {power:.0f}W to {len(active_battery_ids)} batteries: {active_battery_ids} with {power_per_battery}W each.")

        for battery_base_id in self._battery_entities:
            if battery_base_id in active_battery_ids:
                await self._set_battery_power(battery_base_id, power_per_battery, self._last_power_direction)
            else:
                await self._set_battery_power(battery_base_id, 0, 0)

    async def _set_battery_power(self, base_entity_id: str, power: int, direction: int):
        """Set the charge or discharge power for a single battery."""
        charge_entity = f"number.{base_entity_id}_charge_power"
        discharge_entity = f"number.{base_entity_id}_discharge_power"
        
        try:
            if direction == 1:
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": power}, blocking=True)
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": 0}, blocking=True)
            elif direction == -1:
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": 0}, blocking=True)
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": power}, blocking=True)
            else:
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": 0}, blocking=True)
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": 0}, blocking=True)
            # Add a small delay to prevent overwhelming the device APIs
            await asyncio.sleep(0.1)
        except Exception as e:
            _LOGGER.error(f"Failed to set power for {base_entity_id}: {e}")

    async def _set_all_batteries_to_zero(self):
        """Set all configured batteries to 0 charge and discharge power."""
        _LOGGER.debug("Setting all batteries to 0W.")
        tasks = [self._set_battery_power(b_id, 0, 0) for b_id in self._battery_entities]
        await asyncio.gather(*tasks)
