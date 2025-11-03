"""Coordinator for the Marstek Venus HA integration."""
import logging
from collections import deque
from datetime import datetime, timedelta
import asyncio

from homeassistant.core import HomeAssistant, State
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
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
    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS
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
        self._last_wallbox_pause_attempt = datetime.min # For 60-minute cooldown
        self._wallbox_wait_start = None # Initialisiert: Timer für den Start-Delay
        self._wallbox_cable_was_on = False # Trackt den vorherigen Kabelzustand

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
            
        return max(1, seconds)

    async def wait_for_entity_available(self, entity_id, timeout=60):
        """Wait until the entity is available or timeout."""
        # Füge eine Sicherheitsabfrage hinzu, falls die entity_id leer ist
        if not entity_id:
            _LOGGER.warning("wait_for_entity_available called with empty entity_id.")
            return
        wait_event = asyncio.Event()
    
        def _listener(event):
            entity_id = event.data.get("entity_id")
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            if new_state and new_state.state not in ("unavailable", "unknown"):
                wait_event.set()
    
        # Check if already available
        state = self.hass.states.get(entity_id)
        if state and state.state not in ("unavailable", "unknown"):
            return
    
        remove = async_track_state_change_event(self.hass, [entity_id], _listener)

        try:
            await asyncio.wait_for(wait_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            remove()
    
    async def async_start_listening(self):
        """Start the coordinator's update loop."""
        # Wait concurrently for configured entities (avoids additive timeouts)
        wait_entities = []
        grid_power_sensor = self.config.get(CONF_GRID_POWER_SENSOR)
        if grid_power_sensor:
            wait_entities.append(grid_power_sensor)

        for key in (CONF_BATTERY_1_ENTITY, CONF_BATTERY_2_ENTITY, CONF_BATTERY_3_ENTITY):
            ent = self.config.get(key)
            if ent:
                wait_entities.append(ent)

        wallbox_cable_sensor = self.config.get(CONF_WALLBOX_CABLE_SENSOR)
        if wallbox_cable_sensor:
            wait_entities.append(wallbox_cable_sensor)

        if wait_entities:
            # run all waits in parallel; total wait <= max individual timeout (default 60s)
            await asyncio.gather(*(self.wait_for_entity_available(e) for e in wait_entities))

            
        if not self._is_running:
            # Re-initialize deques on start
            self._power_history = deque(maxlen=self._get_deque_size("smoothing"))
            self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))
            self._last_wallbox_pause_attempt = datetime.min # Reset cooldown on start
            #Reset Batteries to 0 on Start-Up in background to avoid blocking startup
            self.hass.async_create_task(self._set_all_batteries_to_zero())            
            coordinator_update_interval = self.config.get(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS)
            self._unsub_listener = async_track_time_interval(
                self.hass,
                self._async_update,
                timedelta(seconds=coordinator_update_interval),
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
        smoothing = self.config.get(CONF_SMOOTHING_SECONDS)
        if smoothing > 0:
            avg_power = sum(self._power_history) / len(self._power_history)
        else:
            return current_power
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
                    self._get_float_state(f"sensor.{b}_ac_power") for b in self._battery_entities
                ] if p is not None and p != 0
            )
        
        # Calculate real power based on batterie direction
        if self._last_power_direction == -1: #Batteries are actually discharging 
            real_power = (smoothed_grid_power + abs(total_battery_power)) 
        elif self._last_power_direction == 1: #Batteries are actually charging
            real_power = (smoothed_grid_power - abs(total_battery_power))
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
        retry_minutes = self.config.get(CONF_WALLBOX_RETRY_MINUTES, 60)
        retry_seconds = retry_minutes * 60

        # 0. Grundvoraussetzungen prüfen
        if not all([wb_power_sensor, wb_cable_sensor, max_surplus is not None]):
            _LOGGER.debug("Wallbox configuration incomplete. Skipping wallbox logic.")
            self._wallbox_charge_paused = False
            self._wallbox_cable_was_on = False # Zurücksetzen des Kabelzustands
            return False

        cable_state = self._get_entity_state(wb_cable_sensor)

        cable_on = cable_state and cable_state.state == STATE_ON

        if not cable_on:
            _LOGGER.debug("Wallbox cable unplugged or unavailable. Skipping wallbox logic.")
            if self._wallbox_charge_paused or self._wallbox_cable_was_on:
                _LOGGER.info("Wallbox cable unplugged. Resetting wallbox wait states and pause.")
                self._wallbox_charge_paused = False
                self._wallbox_power_history.clear()
                self._wallbox_wait_start = None
                self._wallbox_cable_was_on = False
                self._last_wallbox_pause_attempt = datetime.min # Reset cooldown on unplug
            return False
        
        self._wallbox_cable_was_on = True # Kabel ist jetzt eingesteckt
            
        wb_power = 0.0
        wb_power_state = self._get_entity_state(wb_power_sensor)
        _LOGGER.debug(f"Wallbox power state: {wb_power_state.state if wb_power_state else 'N/A'}")
        if wb_power_state:
            try:
                wb_power = float(wb_power_state.state)
                unit = wb_power_state.attributes.get("unit_of_measurement")
                if unit and unit.lower() == 'kw':
                    wb_power *= 1000
                _LOGGER.debug(f"Wallbox power interpreted as: {wb_power}W")
            except (ValueError, TypeError):
                _LOGGER.warning(f"Could not parse state of '{wb_power_sensor}' as float: '{wb_power_state.state}'")
    
        self._wallbox_power_history.append(wb_power)

        # 1. Höchste Priorität: Entladeschutz, wenn Wallbox aktiv ist
        if wb_power > 100 and self._last_power_direction == -1:
            _LOGGER.debug("Wallbox is active, ensuring batteries do not discharge.")
            await self._set_all_batteries_to_zero()
            return True

        # 2. Zustandsprüfung: Ist eine Ladepause für die Wallbox aktiv?
        if self._wallbox_charge_paused:
            # JA, Pause ist aktiv. Prüfe Bedingungen, um die Pause zu BEENDEN.
            _LOGGER.debug("Wallbox pause is currently active. Checking conditions to end pause.")
            # Regel 1.5: Überschuss weggefallen? -> -> Pause beenden (gilt nur, wenn das Auto nicht geladen hat)
            if (real_power >= -max_surplus) and (wb_power <= 100):
                _LOGGER.info(f"Surplus ({abs(real_power):.0f}W) is below threshold ({max_surplus}W). And Wallbox-Power ({wb_power}W) is below 100. Releasing batteries.")
                self._wallbox_charge_paused = False
                self._wallbox_power_history.clear()
                self._wallbox_wait_start = None
                return False

            # Regel 2 (Timeout): Auto hat nicht angefangen zu laden? -> Pause beenden
            if self._wallbox_wait_start is not None:
                elapsed = (datetime.now() - self._wallbox_wait_start).total_seconds()
                if elapsed > start_delay:
                    _LOGGER.info(f"Wallbox did not start charging in {start_delay}s. Releasing batteries.")
                    self._wallbox_charge_paused = False
                    self._wallbox_power_history.clear()
                    self._wallbox_wait_start = None
                    return False

            # Regel 3: Auto lädt, ist die Leistung stabil? -> Pause beenden
            if wb_power > 100:
                self._wallbox_wait_start = None # Timer wird irrelevant, sobald das Auto lädt
                if len(self._wallbox_power_history) == self._wallbox_power_history.maxlen:
                    # NEUE LOGIK: Prüfe die Spanne (Min/Max) der History
                    min_power = min(self._wallbox_power_history)
                    max_power = max(self._wallbox_power_history)
                    power_spread = max_power - min_power # Die Differenz zwischen Min und Max

                    _LOGGER.debug(f"Wallbox resume check: Min={min_power:.0f}W, Max={max_power:.0f}W, Spread={power_spread:.0f}W")

                    if power_spread < stability_treshold:
                        _LOGGER.debug(f"Wallbox power has stabilized (Spread < {stability_treshold}W). Releasing batteries.")
                        self._wallbox_charge_paused = False
                        self._wallbox_power_history.clear()
                        return False

            # Keine Bedingung zum Beenden erfüllt -> Pause beibehalten
            _LOGGER.debug("Wallbox pause remains active. Batteries set to zero.")
            await self._set_all_batteries_to_zero()
            return True

        # 3. Zustandsprüfung: Keine Ladepause aktiv. Prüfen, ob eine gestartet werden soll.
        else:
            _LOGGER.debug("No wallbox pause active. Checking if conditions to start pause are met.")
            # Regel 2 (Start): Genug Überschuss UND Auto lädt nicht UND Cooldown abgelaufen? -> Pause starten
            if real_power < -max_surplus and wb_power <= 100:
                now = datetime.now()
                time_since_last_attempt = (now - self._last_wallbox_pause_attempt).total_seconds()
                
                # *** Die Pause sofort starten, wenn dies der ERSTE Versuch ist (datetime.min),
                # *** ODER wenn der Cooldown abgelaufen ist.
                is_first_attempt = self._last_wallbox_pause_attempt == datetime.min
                cooldown_elapsed = time_since_last_attempt > retry_seconds

                if is_first_attempt or cooldown_elapsed:
                    
                    # Wenn es nicht der erste Versuch ist, aber der Cooldown abgelaufen ist,
                    # wird dies als INFO geloggt, da es ein normaler Retry ist.
                    if cooldown_elapsed:
                         _LOGGER.info(f"High surplus ({abs(real_power):.0f}W) and inactive wallbox. Cooldown elapsed. Starting pause for car (batteries to 0 for {start_delay}s).")
                    else: # is_first_attempt
                         _LOGGER.info(f"High surplus ({abs(real_power):.0f}W) and wallbox just connected. Starting initial pause for car (batteries to 0 for {start_delay}s).")
                         
                    self._last_wallbox_pause_attempt = now # Cooldown-Timer (für den nächsten Versuch) starten
                    self._wallbox_wait_start = now        # Start-Delay-Timer (für den aktuellen Versuch) starten
                    self._wallbox_charge_paused = True 
                    await self._set_all_batteries_to_zero() 
                    return True
                else:
                    _LOGGER.debug(f"High surplus, but wallbox pause is on cooldown ({time_since_last_attempt:.0f}s / {retry_seconds}s).")
        
        # Kein Grund zur Intervention -> Normale Batterielogik ausführen lassen
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
            soc = self._get_float_state(f"sensor.{base_entity_id}_battery_soc")
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
        stage_offset = self.config.get(CONF_POWER_STAGE_OFFSET, 50)
        max_discharge_power = self.config.get(CONF_MAX_DISCHARGE_POWER,2500)
        max_charge_power = self.config.get(CONF_MAX_CHARGE_POWER,2500)
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
        
        # 1. Ermittle die Anzahl der Batterien, die aktuell Leistung liefern/aufnehmen
        num_currently_active = 0
        for b_id in self._battery_entities:
            power_state = self._get_float_state(f"sensor.{b_id}_ac_power")
            # Zähle Batterien mit mehr als 10W (Toleranz für Rauschen)
            if power_state is not None and abs(power_state) > 10:
                num_currently_active += 1

        _LOGGER.debug(f"Hysteresis check: num_available={num_available}, num_currently_active={num_currently_active}, abs_power={abs_power:.0f}W")
        
        # 2. Implementiere Hysterese-Logik basierend auf dem aktuellen Zustand
        target_num_batteries = 0

        if num_currently_active <= 1:
            # Aktuell 0 oder 1 Batterie aktiv. Logik zum HOCHschalten:
            # Schwelle = STUFE + OFFSET
            if abs_power > (stage2 + stage_offset):
                target_num_batteries = 3
            elif abs_power > (stage1 + stage_offset):
                target_num_batteries = 2
            else:
                # Leistung ist unter (stage1 + offset)
                target_num_batteries = 1

        elif num_currently_active == 2:
            # Aktuell 2 Batterien aktiv. Logik zum HOCH- oder RUNTERschalten:
            if abs_power > (stage2 + stage_offset):  # HOCHschalten
                target_num_batteries = 3
            elif abs_power < (stage1 - stage_offset):  # RUNTERschalten
                target_num_batteries = 1
            else:
                # Bleibe im Hysterese-Bereich: (stage1 - offset) <= power <= (stage2 + offset)
                target_num_batteries = 2

        else:  # num_currently_active >= 3
            # Aktuell 3 Batterien aktiv. Logik zum RUNTERschalten:
            # Schwelle = STUFE - OFFSET
            if abs_power < (stage1 - stage_offset):
                target_num_batteries = 1
            elif abs_power < (stage2 - stage_offset):
                target_num_batteries = 2
            else:
                # Bleibe im Hysterese-Bereich: power >= (stage2 - offset)
                target_num_batteries = 3

        # Berücksichtige die maximal verfügbaren Batterien (aus der Prioritätenliste)
        if num_available == 1:
            target_num_batteries = 1
        elif num_available == 2:
            target_num_batteries = min(target_num_batteries, 2)
        else:
            # Dies deckt num_available == 3 oder mehr ab
            target_num_batteries = min(target_num_batteries, 3)

        active_batteries = self._battery_priority[:target_num_batteries]

        if not active_batteries:
            await self._set_all_batteries_to_zero()
            return

        power_per_battery = round(abs_power / len(active_batteries))
        # Ensure we do not exceed max charge/discharge power
        if power_direction == 1: #Charging
            power_per_battery = min(power_per_battery, max_charge_power)
        elif power_direction == -1: #Discharging
            power_per_battery = min(power_per_battery, max_discharge_power) 

        active_battery_ids = [b['id'] for b in active_batteries]

        _LOGGER.debug(f"Distributing {power:.0f}W to {len(active_battery_ids)} batteries: {active_battery_ids} with {power_per_battery}W each.")

        for battery_base_id in self._battery_entities:
            if battery_base_id in active_battery_ids:
                await self._set_battery_power(battery_base_id, power_per_battery, self._last_power_direction)
            else:
                await self._set_battery_power(battery_base_id, 0, 0)

    async def _set_battery_power(self, base_entity_id: str, power: int, direction: int):
        """Set the charge or discharge power for a single battery."""
        charge_entity = f"number.{base_entity_id}_modbus_set_forcible_charge_power"
        discharge_entity = f"number.{base_entity_id}_modbus_set_forcible_discharge_power"
        force_mode= f"select.{base_entity_id}_modbus_force_mode"
        modbus_control_mode = f"switch.{base_entity_id}_modbus_rs485_control_mode"
        # Ensure Modbus control mode is set to 'forcible'
        await self.hass.services.async_call("switch", "turn_on", {"entity_id": modbus_control_mode}, blocking=True)
        
        try:
            if direction == 1: #Charging the Batteries
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": power}, blocking=True)
                await self.hass.services.async_call("select", "select_option", {"entity_id": force_mode, "option": "Charge"}, blocking=True)
            elif direction == -1: #Discharging the Batteries
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": power}, blocking=True)
                await self.hass.services.async_call("select", "select_option", {"entity_id": force_mode, "option": "Discharge"}, blocking=True)
            else: #Set to 0
                await self.hass.services.async_call("number", "set_value", {"entity_id": charge_entity, "value": 0}, blocking=True)
                await self.hass.services.async_call("number", "set_value", {"entity_id": discharge_entity, "value": 0}, blocking=True)
                await self.hass.services.async_call("select", "select_option", {"entity_id": force_mode, "option": "None"}, blocking=True)

            # Add a small delay to prevent overwhelming the device APIs
            await asyncio.sleep(0.1)
        except Exception as e:
            _LOGGER.error(f"Failed to set power for {base_entity_id}: {e}")

    async def _set_all_batteries_to_zero(self):
        """Set all configured batteries power to 0."""
        _LOGGER.debug("Setting all batteries to 0W.")
        tasks = [self._set_battery_power(b_id, 0, 0) for b_id in self._battery_entities]
        await asyncio.gather(*tasks)
