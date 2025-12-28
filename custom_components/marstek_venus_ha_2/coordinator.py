"""Coordinator for the Marstek Venus HA integration."""
import logging
from collections import deque
from datetime import datetime, timedelta
import asyncio
from typing import Any, cast
from enum import IntEnum

from homeassistant.core import HomeAssistant, State, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, STATE_ON
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    SIGNAL_DIAGNOSTICS_UPDATED,
    CONF_CT_MODE,
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
    CONF_PV_POWER_SENSOR,
    CONF_WALLBOX_POWER_STABILITY_THRESHOLD,
    CONF_WALLBOX_RESUME_CHECK_SECONDS,
    CONF_WALLBOX_START_DELAY_SECONDS,
    CONF_WALLBOX_RETRY_MINUTES,
    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    CONF_SERVICE_CALL_CACHE_SECONDS,
    DEFAULT_MAX_DISCHARGE_POWER,
    DEFAULT_MAX_CHARGE_POWER,
    DEFAULT_MIN_SOC,
    DEFAULT_MAX_SOC,
    DEFAULT_PRIORITY_INTERVAL,
    DEFAULT_SMOOTHING_SECONDS,
    DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD,
    DEFAULT_WALLBOX_START_DELAY_SECONDS,
    DEFAULT_SERVICE_CALL_CACHE_SECONDS,
    CONF_PID_ENABLED,
    CONF_PID_KP,
    CONF_PID_KI,
    CONF_PID_KD,
    DEFAULT_PID_ENABLED,
    DEFAULT_PID_KP,
    DEFAULT_PID_KI,
    DEFAULT_PID_KD,
)

_LOGGER = logging.getLogger(__name__)

BELOW_MIN_CYCLES_TO_ZERO = 10

class PowerDir(IntEnum):
    NEUTRAL = 0
    CHARGE = 1
    DISCHARGE = -1

class MarstekCoordinator:
    """The main coordinator for handling battery logic."""

    def _as_aware_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return value

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize the coordinator."""
        self.hass = hass
        self.entry = entry
        # Erstelle eine kombinierte Konfiguration.
        # Beginne mit den Daten aus der Ersteinrichtung...
        self.config = dict(entry.data)
        # ...und überschreibe sie mit den Werten aus dem Options-Flow.
        self.config.update(entry.options)

        self._service_call_cache: dict[tuple[str, str, str, str], tuple[Any, datetime]] = {}
        self._service_call_cache_ttl_seconds = self.config.get(
            CONF_SERVICE_CALL_CACHE_SECONDS,
            DEFAULT_SERVICE_CALL_CACHE_SECONDS,
        )

        self._pid_enabled = self.config.get(CONF_PID_ENABLED, DEFAULT_PID_ENABLED)
        self._pid_kp = self.config.get(CONF_PID_KP, DEFAULT_PID_KP)
        self._pid_ki = self.config.get(CONF_PID_KI, DEFAULT_PID_KI)
        self._pid_kd = self.config.get(CONF_PID_KD, DEFAULT_PID_KD)

        self._pid_integral = 0.0
        self._pid_prev_error: float | None = None
        self._pid_prev_ts: datetime | None = None
        self._pid_suspended = False
        self._pid_suspend_direction: PowerDir = PowerDir.NEUTRAL

        self._is_running = False
        self._unsub_listeners: list[Any] = []

        self._instance_id = id(self)

        self._update_task: asyncio.Task | None = None
        self._update_lock = asyncio.Lock()
        self._last_update_start: datetime | None = None

        # State variables
        self._power_history = deque(maxlen=self._get_deque_size("smoothing"))
        self._battery_priority = []
        self._last_priority_update = datetime.min
        self._last_power_direction: PowerDir = PowerDir.NEUTRAL
        
        # Wallbox state
        self._wallbox_charge_paused = False
        self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))
        self._last_wallbox_pause_attempt = datetime.min # For 60-minute cooldown
        self._wallbox_wait_start = None # Initialisiert: Timer für den Start-Delay
        self._wallbox_cable_was_on = False # Trackt den vorherigen Kabelzustand

        # CT-Mode state
        self._ct_mode = self.config.get(CONF_CT_MODE, False)
        self._wallbox_is_active = False  # Track if wallbox currently controls

        # Counters for minimum threshold gating in _distribute_power
        self._below_min_charge_count = 0
        self._below_min_discharge_count = 0

        # Collect battery entities
        self._battery_entities = [
            b for b in [
                self.config.get(CONF_BATTERY_1_ENTITY),
                self.config.get(CONF_BATTERY_2_ENTITY),
                self.config.get(CONF_BATTERY_3_ENTITY),
            ] if b
        ]

    def _get_deque_size(self, mode: str):
        if mode == "smoothing":
            seconds = self.config.get(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS)
        elif mode == "wallbox":
            seconds = self.config.get(CONF_WALLBOX_RESUME_CHECK_SECONDS)
        else:
            return 1
        try:
            seconds_int = int(seconds or 0)
        except (TypeError, ValueError):
            seconds_int = 0
        return max(1, seconds_int)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def ct_mode(self) -> bool:
        return bool(self._ct_mode)

    @property
    def effective_update_interval(self) -> int:
        return int(self._get_effective_update_interval())

    @property
    def last_update_start_iso(self) -> str | None:
        value = self.last_update_start
        if value is None:
            return None
        return value.isoformat()

    @property
    def last_update_start(self) -> datetime | None:
        return self._as_aware_datetime(self._last_update_start)

    @property
    def service_call_cache_size(self) -> int:
        return len(self._service_call_cache)

    @property
    def wallbox_is_active(self) -> bool:
        return bool(self._wallbox_is_active)

    @property
    def wallbox_charge_paused(self) -> bool:
        return bool(self._wallbox_charge_paused)

    @property
    def wallbox_wait_start_iso(self) -> str | None:
        value = self.wallbox_wait_start
        if value is None:
            return None
        return value.isoformat()

    @property
    def wallbox_wait_start(self) -> datetime | None:
        return self._as_aware_datetime(self._wallbox_wait_start)

    @property
    def battery_priority_ids(self) -> str:
        try:
            return " ".join(str(b.get("id")) for b in self._battery_priority if isinstance(b, dict))
        except Exception:
            return ""

    @property
    def last_power_direction_name(self) -> str:
        try:
            return PowerDir(self._last_power_direction).name
        except Exception:
            return str(self._last_power_direction)

    @property
    def below_min_charge_count(self) -> int:
        return int(self._below_min_charge_count)

    @property
    def below_min_discharge_count(self) -> int:
        return int(self._below_min_discharge_count)

    @property
    def pid_enabled(self) -> bool:
        return bool(self._pid_enabled)

    @property
    def pid_integral(self) -> float:
        return float(self._pid_integral)

    @property
    def pid_prev_error(self) -> float | None:
        return self._pid_prev_error

    @property
    def wallbox_cooldown_remaining_seconds(self) -> int | None:
        try:
            if self._last_wallbox_pause_attempt == datetime.min:
                return None
            retry_minutes = self.config.get(CONF_WALLBOX_RETRY_MINUTES, 60)
            retry_seconds = int(retry_minutes) * 60
            end = self._last_wallbox_pause_attempt + timedelta(seconds=retry_seconds)
            remaining = int(round((end - datetime.now()).total_seconds()))
            return max(0, remaining)
        except Exception:
            return None

    @property
    def wallbox_cooldown_end_iso(self) -> str | None:
        try:
            if self._last_wallbox_pause_attempt == datetime.min:
                return None
            retry_minutes = self.config.get(CONF_WALLBOX_RETRY_MINUTES, 60)
            retry_seconds = int(retry_minutes) * 60
            end = self._last_wallbox_pause_attempt + timedelta(seconds=retry_seconds)
            end_dt = self._as_aware_datetime(end)
            return None if end_dt is None else end_dt.isoformat()
        except Exception:
            return None

    @property
    def wallbox_cooldown_end(self) -> datetime | None:
        try:
            if self._last_wallbox_pause_attempt == datetime.min:
                return None
            retry_minutes = self.config.get(CONF_WALLBOX_RETRY_MINUTES, 60)
            retry_seconds = int(retry_minutes) * 60
            end = self._last_wallbox_pause_attempt + timedelta(seconds=retry_seconds)
            return self._as_aware_datetime(end)
        except Exception:
            return None

    @property
    def wallbox_start_delay_remaining_seconds(self) -> int | None:
        try:
            if self._wallbox_wait_start is None:
                return None
            start_delay = int(self.config.get(CONF_WALLBOX_START_DELAY_SECONDS, 0))
            end = self._wallbox_wait_start + timedelta(seconds=start_delay)
            remaining = int(round((end - datetime.now()).total_seconds()))
            return max(0, remaining)
        except Exception:
            return None

    @property
    def wallbox_start_delay_end_iso(self) -> str | None:
        try:
            if self._wallbox_wait_start is None:
                return None
            start_delay = int(self.config.get(CONF_WALLBOX_START_DELAY_SECONDS, 0))
            end = self._wallbox_wait_start + timedelta(seconds=start_delay)
            end_dt = self._as_aware_datetime(end)
            return None if end_dt is None else end_dt.isoformat()
        except Exception:
            return None

    @property
    def wallbox_start_delay_end(self) -> datetime | None:
        try:
            if self._wallbox_wait_start is None:
                return None
            start_delay = int(self.config.get(CONF_WALLBOX_START_DELAY_SECONDS, 0))
            end = self._wallbox_wait_start + timedelta(seconds=start_delay)
            return self._as_aware_datetime(end)
        except Exception:
            return None

    @property
    def priority_next_update_remaining_seconds(self) -> int | None:
        try:
            if self._last_priority_update == datetime.min:
                return None
            minutes = self.config.get(CONF_PRIORITY_INTERVAL)
            interval_minutes = int(minutes) if minutes is not None else 0
            end = self._last_priority_update + timedelta(minutes=interval_minutes)
            remaining = int(round((end - datetime.now()).total_seconds()))
            return max(0, remaining)
        except Exception:
            return None

    @property
    def priority_next_update_iso(self) -> str | None:
        try:
            if self._last_priority_update == datetime.min:
                return None
            minutes = self.config.get(CONF_PRIORITY_INTERVAL)
            interval_minutes = int(minutes) if minutes is not None else 0
            end = self._last_priority_update + timedelta(minutes=interval_minutes)
            end_dt = self._as_aware_datetime(end)
            return None if end_dt is None else end_dt.isoformat()
        except Exception:
            return None

    @property
    def priority_next_update(self) -> datetime | None:
        try:
            if self._last_priority_update == datetime.min:
                return None
            minutes = self.config.get(CONF_PRIORITY_INTERVAL)
            interval_minutes = int(minutes) if minutes is not None else 0
            end = self._last_priority_update + timedelta(minutes=interval_minutes)
            return self._as_aware_datetime(end)
        except Exception:
            return None

    @property
    def priority_rate_limit_remaining_seconds(self) -> int | None:
        try:
            if self._last_priority_update == datetime.min:
                return None
            end = self._last_priority_update + timedelta(seconds=10)
            remaining = int(round((end - datetime.now()).total_seconds()))
            return max(0, remaining)
        except Exception:
            return None

    @property
    def priority_rate_limit_end_iso(self) -> str | None:
        try:
            if self._last_priority_update == datetime.min:
                return None
            end = self._last_priority_update + timedelta(seconds=10)
            end_dt = self._as_aware_datetime(end)
            return None if end_dt is None else end_dt.isoformat()
        except Exception:
            return None

    @property
    def priority_rate_limit_end(self) -> datetime | None:
        try:
            if self._last_priority_update == datetime.min:
                return None
            end = self._last_priority_update + timedelta(seconds=10)
            return self._as_aware_datetime(end)
        except Exception:
            return None

    def _get_service_call_cache_ttl(self) -> timedelta:
        try:
            seconds = int(self._service_call_cache_ttl_seconds)
        except (ValueError, TypeError):
            seconds = int(DEFAULT_SERVICE_CALL_CACHE_SECONDS)
        if seconds <= 0:
            return timedelta(seconds=0)
        return timedelta(seconds=seconds)

    async def _async_call_cached(
        self,
        domain: str,
        service: str,
        entity_id: str,
        cache_field: str,
        cache_value: Any,
        service_data: dict[str, Any],
        *,
        blocking: bool = True,
        force: bool = False,
    ) -> None:
        ttl = self._get_service_call_cache_ttl()
        now = datetime.now()
        cache_key = (domain, service, entity_id, cache_field)

        if not force:
            cached = self._service_call_cache.get(cache_key)
            if cached is not None:
                last_value, last_ts = cached
                is_same_value = last_value == cache_value
                is_expired = ttl.total_seconds() > 0 and (now - last_ts) > ttl
                if is_same_value and not is_expired:
                    return

        if not self.hass.services.has_service(domain, service):
            _LOGGER.warning(
                "Service %s.%s not available. Skipping call for %s",
                domain,
                service,
                entity_id,
            )
            return

        try:
            await self.hass.services.async_call(domain, service, service_data, blocking=blocking)
        except Exception as err:
            _LOGGER.warning(
                "Service call %s.%s failed for %s: %s",
                domain,
                service,
                entity_id,
                err,
            )
            return
        self._service_call_cache[cache_key] = (cache_value, now)

    async def wait_for_entity_available(self, entity_id, timeout=10):
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
        if self._is_running or self._unsub_listeners or self._update_task is not None:
            await self.async_stop_listening()

        self._pid_suspended = False
        self._pid_suspend_direction = PowerDir.NEUTRAL

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
            self._service_call_cache.clear()
            _LOGGER.debug("Running version 1.1.9")
            _LOGGER.debug("Service call cache cleared on coordinator start")
            self._below_min_charge_count = 0
            self._below_min_discharge_count = 0
            # Re-initialize deques on start
            self._power_history = deque(maxlen=self._get_deque_size("smoothing"))
            self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))
            self._last_wallbox_pause_attempt = datetime.min # Reset cooldown on start
            #Reset Batteries to 0 on Start-Up in background to avoid blocking startup
            self.hass.async_create_task(self._set_all_batteries_to_zero())            
            coordinator_update_interval = self.config.get(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS)
            # CT-Mode: Disable RS485 control mode (use automatic mode)
            if self._ct_mode:
                _LOGGER.info("CT-Mode enabled. Disabling RS485 Modbus control mode (setting batteries to automatic).")
                for battery_base_id in self._battery_entities:
                    modbus_control_mode = f"switch.{battery_base_id}_modbus_rs485_control_mode"
                    await self.hass.services.async_call("switch", "turn_off", {"entity_id": modbus_control_mode}, blocking=True)
            else:
                _LOGGER.info("CT-Mode disabled. Batteries remain in manual/forcible mode.")

            coordinator_update_interval = self._get_effective_update_interval()
            _LOGGER.info(
                "Starting coordinator in event-driven mode on sensor updates (min interval: %ss)",
                coordinator_update_interval,
            )

            # Subscribe to relevant sensor updates (grid power, PV power, wallbox cable).
            trigger_entities: list[str] = []

            grid_power_sensor = self.config.get(CONF_GRID_POWER_SENSOR)
            if grid_power_sensor:
                trigger_entities.append(grid_power_sensor)

            pv_power_sensor = self.config.get(CONF_PV_POWER_SENSOR)
            if pv_power_sensor:
                trigger_entities.append(pv_power_sensor)

            wb_cable_sensor = self.config.get(CONF_WALLBOX_CABLE_SENSOR)
            if wb_cable_sensor:
                trigger_entities.append(wb_cable_sensor)

            @callback
            def _on_state_change(event):
                entity_id = event.data.get("entity_id")

                def _schedule_update() -> None:
                    self.hass.async_create_task(
                        self.async_request_update(reason=f"state_change:{entity_id}")
                    )

                # Home Assistant may execute state-change callbacks from a non-event-loop thread.
                # Always schedule the task in a thread-safe way.
                self.hass.loop.call_soon_threadsafe(_schedule_update)

            if trigger_entities:
                remove = async_track_state_change_event(self.hass, trigger_entities, _on_state_change)
                self._unsub_listeners.append(remove)

            # Run one initial update after startup.
            self.hass.async_create_task(self.async_request_update(reason="startup"))

            self._is_running = True
            _LOGGER.info("Marstek Venus HA Integration coordinator started (id=%s).", self._instance_id)

    async def async_request_update(self, *, reason: str = "manual") -> None:
        """Request a coordinator update.

        This is safe to call from automations/services or state-change listeners.
        It enforces a minimum interval between updates and prevents concurrent runs.
        """
        if not self._is_running:
            return

        min_interval = float(self._get_effective_update_interval())

        async with self._update_lock:
            now = datetime.now()
            if self._last_update_start is not None:
                elapsed = (now - self._last_update_start).total_seconds()
                if elapsed < min_interval:
                    delay = min_interval - elapsed
                    if self._update_task is not None and not self._update_task.done():
                        return
                    self._update_task = self.hass.async_create_task(self._delayed_update(delay, reason))
                    return

            if self._update_task is not None and not self._update_task.done():
                return
            self._update_task = self.hass.async_create_task(self._run_update(reason))

    async def _delayed_update(self, delay: float, reason: str) -> None:
        await asyncio.sleep(max(0.0, delay))
        await self._run_update(reason)

    async def _run_update(self, reason: str) -> None:
        self._last_update_start = datetime.now()
        _LOGGER.debug("Coordinator update triggered (%s).", reason)
        await self._async_update()
        async_dispatcher_send(self.hass, SIGNAL_DIAGNOSTICS_UPDATED)

    async def async_stop_listening(self):
        """Stop the coordinator's update loop."""
        for unsub in self._unsub_listeners:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_listeners.clear()

        if self._update_task is not None and not self._update_task.done():
            self._update_task.cancel()
        self._update_task = None
        self._is_running = False
        await self._set_all_batteries_to_zero()
        _LOGGER.info("Marstek Venus HA Integration coordinator stopped (id=%s).", self._instance_id)

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
        # Note: logging is handled by _run_update to include a reason.

        # Net grid power (import/export). This is the signal PID should drive towards 0W.
        smoothed_grid_power = self._get_smoothed_grid_power()
        if smoothed_grid_power is None:
            _LOGGER.warning("Could not determine grid power. Skipping update cycle.")
            return

        # House load excluding batteries (used by the staging/hysteresis logic)
        real_power = self._get_real_power(smoothed_grid_power)
        if real_power is None:
            _LOGGER.warning("Could not determine real power. Skipping update cycle.")
            return

        wallbox_took_control = await self._handle_wallbox_logic(real_power)
        self._wallbox_is_active = wallbox_took_control
        
        if wallbox_took_control:
            _LOGGER.info("Wallbox logic took control. Ending update cycle.")
            self._pid_prev_error = None
            self._pid_prev_ts = None
            return

        if not self._ct_mode and self._pid_enabled:
            if self._pid_suspended:
                min_surplus_for_charging = self.config.get(CONF_MIN_SURPLUS, 50)
                min_consumption_for_discharging = self.config.get(CONF_MIN_CONSUMPTION, 50)

                should_resume = False
                if self._pid_suspend_direction == PowerDir.CHARGE:
                    should_resume = real_power < -float(min_surplus_for_charging)
                elif self._pid_suspend_direction == PowerDir.DISCHARGE:
                    should_resume = real_power > float(min_consumption_for_discharging)

                if not should_resume:
                    # Keep batteries at 0 and keep PID state reset until load crosses the threshold again.
                    await self._set_all_batteries_to_zero()
                    return

                _LOGGER.debug("PID suspension released (direction=%s)", self._pid_suspend_direction.name)
                self._pid_suspended = False
                self._pid_suspend_direction = PowerDir.NEUTRAL

            _LOGGER.debug("PID input grid power: %sW (target=0W)", round(smoothed_grid_power, 2))
            await self._pid_control_step(smoothed_grid_power)
            return

        # Get battery priority
        await self._update_battery_priority_if_needed(real_power)

        # Determine desired number of batteries based on power stages
        number_of_batteries = self._get_desired_number_of_batteries(real_power) 

        if self._ct_mode:
            # In CT-Mode, if wallbox is not active, disable Modbus control mode
            await self._disable_modbus_control_mode(number_of_batteries)
            _LOGGER.debug("CT-Mode active. Disabling Modbus control mode for needed batteries.")
        else:
            # Distribute power among batteries via Modbus control
            await self._distribute_power(real_power, number_of_batteries)

    async def _pid_control_step(self, real_power: float) -> None:
        """Run one PID control step to drive real_power towards 0W."""
        # Error is defined such that:
        # - Surplus (real_power < 0) -> positive error -> positive output -> charging
        # - Import  (real_power > 0) -> negative error -> negative output -> discharging
        error = -float(real_power)
        now = datetime.now()

        if self._pid_prev_ts is None:
            dt = 0.0
        else:
            dt = max(0.0, (now - self._pid_prev_ts).total_seconds())

        derivative = 0.0
        if dt > 0 and self._pid_prev_error is not None:
            derivative = (error - self._pid_prev_error) / dt

        try:
            max_discharge_power = int(self.config.get(CONF_MAX_DISCHARGE_POWER, 2500))
            max_charge_power = int(self.config.get(CONF_MAX_CHARGE_POWER, 2500))
        except (ValueError, TypeError):
            max_discharge_power = int(DEFAULT_MAX_DISCHARGE_POWER)
            max_charge_power = int(DEFAULT_MAX_CHARGE_POWER)

        raw_output = self._pid_compute_output(error, derivative)
        requested_abs_power = int(round(abs(raw_output)))
        number_of_batteries = self._get_desired_number_of_batteries(requested_abs_power)

        sat_pos = float(max_charge_power * max(1, number_of_batteries))
        sat_neg = float(max_discharge_power * max(1, number_of_batteries))

        output = self._pid_apply_anti_windup(
            error,
            dt,
            derivative,
            sat_pos,
            sat_neg,
        )

        self._pid_prev_error = error
        self._pid_prev_ts = now

        if output == 0:
            await self._set_all_batteries_to_zero()
            return

        direction = PowerDir.CHARGE if output > 0 else PowerDir.DISCHARGE
        requested_abs_power = int(round(abs(output)))

        # Update priority list with the same gating behavior as non-PID mode.
        await self._update_battery_priority_if_needed(power_direction=direction)

        # Ensure staging logic uses the intended direction
        self._last_power_direction = direction

        # Determine how many batteries to use based on requested output magnitude
        number_of_batteries = self._get_desired_number_of_batteries(requested_abs_power)

        # Clamp to configured max power before distributing
        max_total = max_charge_power if direction == PowerDir.CHARGE else max_discharge_power
        requested_abs_power = min(requested_abs_power, max_total * max(1, number_of_batteries))

        # _distribute_power uses abs(power) and self._last_power_direction for mode,
        # so just feed it the magnitude here.
        await self._distribute_power(float(requested_abs_power), number_of_batteries, from_pid=True)

    def _reset_pid_state(self) -> None:
        self._pid_integral = 0.0
        self._pid_prev_error = None
        self._pid_prev_ts = None

    def _pid_compute_output(self, error: float, derivative: float) -> float:
        """Compute PID output in Watts (signed)."""
        try:
            kp = float(self._pid_kp)
            ki = float(self._pid_ki)
            kd = float(self._pid_kd)
        except (ValueError, TypeError):
            kp = float(DEFAULT_PID_KP)
            ki = float(DEFAULT_PID_KI)
            kd = float(DEFAULT_PID_KD)

        output = (kp * error) + (ki * self._pid_integral) + (kd * derivative)

        if abs(output) < 1.0:
            return 0.0

        return output

    def _pid_apply_anti_windup(
        self,
        error: float,
        dt: float,
        derivative: float,
        sat_pos: float,
        sat_neg: float,
    ) -> float:
        try:
            kp = float(self._pid_kp)
            ki = float(self._pid_ki)
            kd = float(self._pid_kd)
        except (ValueError, TypeError):
            kp = float(DEFAULT_PID_KP)
            ki = float(DEFAULT_PID_KI)
            kd = float(DEFAULT_PID_KD)

        if ki == 0:
            output = (kp * error) + (kd * derivative)
            output = max(-sat_neg, min(sat_pos, output))
            return 0.0 if abs(output) < 1.0 else output

        # Integrate first (this yields the "unconstrained" integral state for this step)
        if dt > 0:
            self._pid_integral += error * dt

        # Compute unconstrained output with the updated integral
        u_unsat = (kp * error) + (ki * self._pid_integral) + (kd * derivative)
        u_sat = max(-sat_neg, min(sat_pos, u_unsat))

        # Back-calculation / tracking anti-windup:
        # When saturated, pull the integrator back so that the controller output matches u_sat.
        if u_sat != u_unsat:
            self._pid_integral += (u_sat - u_unsat) / ki

        # Safety clamp on integral so it cannot drive output beyond saturation on its own.
        if ki != 0:
            max_integral = max(sat_pos, sat_neg) / abs(ki)
            if self._pid_integral > max_integral:
                self._pid_integral = max_integral
            elif self._pid_integral < -max_integral:
                self._pid_integral = -max_integral

        output = (kp * error) + (ki * self._pid_integral) + (kd * derivative)
        output = max(-sat_neg, min(sat_pos, output))

        if abs(output) < 1.0:
            return 0.0

        return output

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
        if not isinstance(grid_sensor_id, str) or not grid_sensor_id:
            return None
        current_power = self._get_float_state(grid_sensor_id)
        
        if current_power is None:
            return None
            
        self._power_history.append(current_power)
        if not self._power_history:
            return 0.0
        try:
            smoothing = int(self.config.get(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS) or 0)
        except (TypeError, ValueError):
            smoothing = 0
        if smoothing > 0:
            avg_power = sum(self._power_history) / len(self._power_history)
        else:
            return current_power
        _LOGGER.debug(f"Current grid power: {current_power}W, Smoothed grid power: {avg_power:.2f}W")
        return avg_power

    def _get_pv_power(self) -> float | None:
        pv_sensor_id = self.config.get(CONF_PV_POWER_SENSOR)
        if not pv_sensor_id:
            return None
        pv_state = self._get_entity_state(pv_sensor_id)
        if pv_state is None:
            return None
        try:
            pv_power = float(pv_state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(f"Could not parse state of '{pv_sensor_id}' as float: '{pv_state.state}'")
            return None

        unit = pv_state.attributes.get("unit_of_measurement")
        if unit and unit.lower() == "kw":
            pv_power *= 1000
        return pv_power

    def _get_real_power(self, smoothed_grid_power: float | None) -> float | None:
        """Get the real power of the house excluding the batteries. A positiv value means the house uses more power than it produced excluding the batteries. 
        A negative value means the house produces more power than its acutally used excluding the batteries."""
        if smoothed_grid_power is None:
            return None

        # Get the current power of all batteries
        battery_powers: dict[str, float | None] = {
            b: self._get_float_state(f"sensor.{b}_ac_power") for b in self._battery_entities
        }
        total_battery_power = sum(p for p in battery_powers.values() if p is not None)
        
        # Calculate real power based on batterie power
        if total_battery_power != 0:
            real_power = (smoothed_grid_power + total_battery_power)
        else:
            real_power = smoothed_grid_power
        
        _LOGGER.debug(
            "Battery AC power readings: %s (total=%sW)",
            battery_powers,
            round(total_battery_power, 2),
        )
        _LOGGER.debug(f"Current real power without batteries: {real_power}W")
        return real_power

    async def _handle_wallbox_logic(self, real_power: float) -> bool:
        """Implement the wallbox charging logic. Returns True if it took control."""
        wb_power_sensor = self.config.get(CONF_WALLBOX_POWER_SENSOR)
        wb_cable_sensor = self.config.get(CONF_WALLBOX_CABLE_SENSOR)
        max_surplus = self.config.get(CONF_WALLBOX_MAX_SURPLUS)
        stability_treshold = self.config.get(CONF_WALLBOX_POWER_STABILITY_THRESHOLD)
        try:
            start_delay = int(self.config.get(CONF_WALLBOX_START_DELAY_SECONDS, DEFAULT_WALLBOX_START_DELAY_SECONDS) or 0)
        except (TypeError, ValueError):
            start_delay = int(DEFAULT_WALLBOX_START_DELAY_SECONDS)
        retry_minutes = self.config.get(CONF_WALLBOX_RETRY_MINUTES, 60)
        retry_seconds = retry_minutes * 60

        # 0. Grundvoraussetzungen prüfen
        if not all([
            isinstance(wb_power_sensor, str) and wb_power_sensor,
            isinstance(wb_cable_sensor, str) and wb_cable_sensor,
            max_surplus is not None,
        ]):
            _LOGGER.debug("Wallbox configuration incomplete. Skipping wallbox logic.")
            self._wallbox_charge_paused = False
            self._wallbox_cable_was_on = False # Zurücksetzen des Kabelzustands
            return False

        wb_power_sensor_id = cast(str, wb_power_sensor)
        wb_cable_sensor_id = cast(str, wb_cable_sensor)
        try:
            max_surplus_w = float(cast(Any, max_surplus))
        except (TypeError, ValueError):
            _LOGGER.debug("Wallbox max_surplus invalid (%s). Skipping wallbox logic.", max_surplus)
            return False

        if stability_treshold is None:
            stability_threshold_w = float(DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD)
        else:
            try:
                stability_threshold_w = float(cast(Any, stability_treshold))
            except (TypeError, ValueError):
                stability_threshold_w = float(DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD)

        cable_state = self._get_entity_state(wb_cable_sensor_id)

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
        wb_power_state = self._get_entity_state(wb_power_sensor_id)
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
        if wb_power > 100 and self._last_power_direction == PowerDir.DISCHARGE:
            _LOGGER.debug("Wallbox is active, ensuring batteries do not discharge.")
            await self._set_all_batteries_to_zero()
            return True

        # 2. Zustandsprüfung: Ist eine Ladepause für die Wallbox aktiv?
        if self._wallbox_charge_paused:
            # JA, Pause ist aktiv. Prüfe Bedingungen, um die Pause zu BEENDEN.
            _LOGGER.debug("Wallbox pause is currently active. Checking conditions to end pause.")
            # Regel 1.5: Überschuss weggefallen? -> -> Pause beenden (gilt nur, wenn das Auto nicht geladen hat)
            if (real_power >= -max_surplus_w) and (wb_power <= 100):
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

                    if power_spread < stability_threshold_w:
                        _LOGGER.debug(f"Wallbox power has stabilized (Spread < {stability_treshold}W). Releasing batteries.")
                        self._wallbox_charge_paused = False
                        self._wallbox_power_history.clear()
                        return False
                        
            # Regel 4: Auto lädt nicht mehr seit X-Minuten -> Pause beenden
            if wb_power < 100:
                if self._wallbox_wait_start == None:
                    _LOGGER.info(f"Wallbox: start new start-delay timer.")
                    now = datetime.now()
                    self._wallbox_wait_start = now        # Start-Delay-Timer (für den aktuellen Versuch) starten
                elif self._wallbox_wait_start is not None:
                    elapsed = (datetime.now() - self._wallbox_wait_start).total_seconds()
                    if elapsed > start_delay:
                        _LOGGER.info(f"Wallbox did not start charging again in {start_delay}s. Releasing batteries.")
                        self._wallbox_charge_paused = False
                        self._wallbox_power_history.clear()
                        self._wallbox_wait_start = None
                        return False

            # Keine Bedingung zum Beenden erfüllt -> Pause beibehalten
            _LOGGER.debug("Wallbox pause remains active. Batteries set to zero.")
            await self._set_all_batteries_to_zero()
            return True

        # 3. Zustandsprüfung: Keine Ladepause aktiv. Prüfen, ob eine gestartet werden soll.
        else:
            _LOGGER.debug("No wallbox pause active. Checking if conditions to start pause are met.")
            # Regel 2 (Start): Genug Überschuss UND Auto lädt nicht UND Cooldown abgelaufen? -> Pause starten
            if real_power < -max_surplus_w and wb_power <= 100:
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
                # Regel 3 (WB Leistung erhöhen): Genug Überschuss UND Auto lädt UND Cooldown abgelaufen? -> Pause starten um Wallbox Prio zu geben
            elif (real_power - wb_power) < -max_surplus_w and wb_power >= 100:
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
                         _LOGGER.info(f"High surplus ({abs(real_power - wb_power):.0f}W) and charging wallbox. Cooldown elapsed. Starting pause for car (batteries to 0 for {start_delay}s).")
                    else: # is_first_attempt
                         _LOGGER.info(f"High surplus ({abs(real_power - wb_power):.0f}W) and wallbox just connected. Starting initial pause for car (batteries to 0 for {start_delay}s).")
                         
                    self._last_wallbox_pause_attempt = now # Cooldown-Timer (für den nächsten Versuch) starten
                    self._wallbox_wait_start = now        # Start-Delay-Timer (für den aktuellen Versuch) starten
                    self._wallbox_charge_paused = True 
                    await self._set_all_batteries_to_zero() 
                    return True
                else:
                    _LOGGER.debug(f"High surplus, but wallbox pause is on cooldown ({time_since_last_attempt:.0f}s / {retry_seconds}s).")
        
        # In CT-Mode: Nur aktivieren, wenn Kabel eingesteckt ist
        if self._ct_mode:
            _LOGGER.debug("CT-Mode active. Wallbox logic allowed to control only when cable is plugged in.")
            # Cable-Check ist bereits implementiert oben (returns False wenn cable_on=False)
            
        # Kein Grund zur Intervention -> Normale Batterielogik ausführen lassen
        return False

    async def _update_battery_priority_if_needed(
        self,
        real_power: float | None = None,
        *,
        power_direction: PowerDir | None = None,
    ):
        """Check conditions and update battery priority list."""
        
        if power_direction is None:
            if real_power is None:
                return

            # power direction: CHARGE for charging, DISCHARGE for discharging, NEUTRAL for neutral
            power_direction = PowerDir.NEUTRAL

            # decide the new direction
            if real_power < 0:
                power_direction = PowerDir.CHARGE
            elif real_power > 0:
                power_direction = PowerDir.DISCHARGE

        try:
            priority_minutes = float(self.config.get(CONF_PRIORITY_INTERVAL, DEFAULT_PRIORITY_INTERVAL) or DEFAULT_PRIORITY_INTERVAL)
        except (TypeError, ValueError):
            priority_minutes = float(DEFAULT_PRIORITY_INTERVAL)
        priority_interval = timedelta(minutes=priority_minutes)
        time_since_last_update = datetime.now() - self._last_priority_update

        # Rate limit: only allow updates at most once per 10 seconds
        min_update_interval = timedelta(seconds=10)

        # If we have no priority list yet, allow an update immediately so the control loop can start.
        needs_initial_priority = not self._battery_priority

        if (
            power_direction != self._last_power_direction or
            time_since_last_update > priority_interval
        ):
            # Check if enough time has passed since last update
            if needs_initial_priority or time_since_last_update >= min_update_interval:
                _LOGGER.info(f"Recalculating battery priority. Reason: {'Power direction changed' if power_direction != self._last_power_direction else 'Time interval elapsed'}")
                await self._calculate_battery_priority(power_direction)
                self._last_power_direction = power_direction
                self._last_priority_update = datetime.now()
            else:
                _LOGGER.debug(f"Priority update triggered but rate-limited. Will retry in {(min_update_interval - time_since_last_update).total_seconds():.0f}s")

    async def _calculate_battery_priority(self, power_direction: PowerDir):
        """Calculate the sorted list of batteries based on SoC."""
        if power_direction == PowerDir.NEUTRAL:
            self._battery_priority = []
            return

        try:
            min_soc = float(self.config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC) or DEFAULT_MIN_SOC)
        except (TypeError, ValueError):
            min_soc = float(DEFAULT_MIN_SOC)
        try:
            max_soc = float(self.config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC) or DEFAULT_MAX_SOC)
        except (TypeError, ValueError):
            max_soc = float(DEFAULT_MAX_SOC)
        
        available_batteries = []
        for base_entity_id in self._battery_entities:
            soc = self._get_float_state(f"sensor.{base_entity_id}_battery_soc")
            if soc is None:
                continue

            if power_direction == PowerDir.CHARGE and soc < max_soc:
                available_batteries.append({"id": base_entity_id, "soc": soc})
            elif power_direction == PowerDir.DISCHARGE and soc > min_soc:
                available_batteries.append({"id": base_entity_id, "soc": soc})

        is_reverse = (power_direction == PowerDir.DISCHARGE)
        self._battery_priority = sorted(available_batteries, key=lambda x: x['soc'], reverse=is_reverse)
        _LOGGER.debug(f"New battery priority: {self._battery_priority}")

    def _get_desired_number_of_batteries(self, power: float) -> int:
        abs_power = abs(power)
        stage_offset = self.config.get(CONF_POWER_STAGE_OFFSET, 50)
        if self._last_power_direction == PowerDir.DISCHARGE: #Currently Discharging
            stage1 = self.config.get(CONF_POWER_STAGE_DISCHARGE_1)
            stage2 = self.config.get(CONF_POWER_STAGE_DISCHARGE_2)
        else:
            stage1 = self.config.get(CONF_POWER_STAGE_CHARGE_1)
            stage2 = self.config.get(CONF_POWER_STAGE_CHARGE_2)
        
        num_available = len(self._battery_priority)
        
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

        _LOGGER.debug(f"Determined target number of batteries: {target_num_batteries} (Available: {num_available}, Currently Active: {num_currently_active})")
        return target_num_batteries

    async def _distribute_power(self, power: float, target_num_batteries: int = 1, *, from_pid: bool = False):
        """Control battery charge/discharge based on power stages."""
        # Defensive: ensure target_num_batteries is an int and within valid range
        try:
            target_num_batteries = int(target_num_batteries) if target_num_batteries is not None else 0
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid target_num_batteries '%s', defaulting to 0", target_num_batteries)
            target_num_batteries = 0

        if target_num_batteries < 0:
            target_num_batteries = 0
        max_batt = len(self._battery_entities)
        if target_num_batteries > max_batt:
            target_num_batteries = max_batt

        abs_power = abs(power)
        max_discharge_power = self.config.get(CONF_MAX_DISCHARGE_POWER, 2500)
        max_charge_power = self.config.get(CONF_MAX_CHARGE_POWER, 2500)

        if self._last_power_direction == PowerDir.CHARGE:
            pv_power = self._get_pv_power()
            if pv_power is not None:
                pv_power = max(0.0, pv_power)
                if abs_power > pv_power:
                    _LOGGER.debug(
                        "PV cap active. Requested charge=%sW, PV=%sW -> capping to %sW",
                        round(abs_power, 0),
                        round(pv_power, 0),
                        round(pv_power, 0),
                    )
                abs_power = min(abs_power, pv_power)

        min_surplus_for_chargin = self.config.get(CONF_MIN_SURPLUS, 50)
        min_consumption_for_discharging = self.config.get(CONF_MIN_CONSUMPTION, 50)

        # Check minimum thresholds to activate charging/discharging
        if self._last_power_direction == PowerDir.CHARGE and abs_power < min_surplus_for_chargin:
            self._below_min_charge_count += 1
            self._below_min_discharge_count = 0
            _LOGGER.debug(
                "Charging power (%sW) below minimum surplus threshold (%sW). below_min_charge_count=%s/%s",
                round(abs_power, 0),
                min_surplus_for_chargin,
                self._below_min_charge_count,
                BELOW_MIN_CYCLES_TO_ZERO,
            )
            if self._below_min_charge_count >= BELOW_MIN_CYCLES_TO_ZERO:
                _LOGGER.debug(
                    "Charging power below minimum threshold for %s consecutive cycles. Setting all batteries to 0W.",
                    BELOW_MIN_CYCLES_TO_ZERO,
                )
                self._below_min_charge_count = 0
                await self._set_all_batteries_to_zero()

                if from_pid:
                    self._pid_suspended = True
                    self._pid_suspend_direction = PowerDir.CHARGE
                    self._reset_pid_state()
                return
        
        if self._last_power_direction == PowerDir.DISCHARGE and abs_power < min_consumption_for_discharging:
            self._below_min_discharge_count += 1
            self._below_min_charge_count = 0
            _LOGGER.debug(
                "Discharging power (%sW) below minimum consumption threshold (%sW). below_min_discharge_count=%s/%s",
                round(abs_power, 0),
                min_consumption_for_discharging,
                self._below_min_discharge_count,
                BELOW_MIN_CYCLES_TO_ZERO,
            )
            if self._below_min_discharge_count >= BELOW_MIN_CYCLES_TO_ZERO:
                _LOGGER.debug(
                    "Discharging power below minimum threshold for %s consecutive cycles. Setting all batteries to 0W.",
                    BELOW_MIN_CYCLES_TO_ZERO,
                )
                self._below_min_discharge_count = 0
                await self._set_all_batteries_to_zero()

                if from_pid:
                    self._pid_suspended = True
                    self._pid_suspend_direction = PowerDir.DISCHARGE
                    self._reset_pid_state()
                return

        # Reset counters when above minimum thresholds
        if (
            (self._last_power_direction == PowerDir.CHARGE and abs_power >= min_surplus_for_chargin)
            or (self._last_power_direction == PowerDir.DISCHARGE and abs_power >= min_consumption_for_discharging)
        ):
            self._below_min_charge_count = 0
            self._below_min_discharge_count = 0

        # If no batteries should be active, ensure everything is set to 0 and exit.
        if target_num_batteries == 0:
            await self._set_all_batteries_to_zero()
            return

        active_batteries = self._battery_priority[:target_num_batteries]

        # Safety: never command batteries beyond SoC limits, even if priority list is stale.
        # This is intentionally checked every cycle.
        try:
            min_soc = float(self.config.get(CONF_MIN_SOC, DEFAULT_MIN_SOC) or DEFAULT_MIN_SOC)
        except (TypeError, ValueError):
            min_soc = float(DEFAULT_MIN_SOC)
        try:
            max_soc = float(self.config.get(CONF_MAX_SOC, DEFAULT_MAX_SOC) or DEFAULT_MAX_SOC)
        except (TypeError, ValueError):
            max_soc = float(DEFAULT_MAX_SOC)

        if active_batteries:
            eligible: list[dict[str, Any]] = []
            for b in active_batteries:
                base_entity_id = b.get("id") if isinstance(b, dict) else None
                if not isinstance(base_entity_id, str) or not base_entity_id:
                    continue
                soc = self._get_float_state(f"sensor.{base_entity_id}_battery_soc")
                if soc is None:
                    continue
                if self._last_power_direction == PowerDir.CHARGE and soc >= max_soc:
                    _LOGGER.debug(
                        "Excluding battery %s from CHARGE: soc=%s >= max_soc=%s",
                        base_entity_id,
                        soc,
                        max_soc,
                    )
                    continue
                if self._last_power_direction == PowerDir.DISCHARGE and soc <= min_soc:
                    _LOGGER.debug(
                        "Excluding battery %s from DISCHARGE: soc=%s <= min_soc=%s",
                        base_entity_id,
                        soc,
                        min_soc,
                    )
                    continue
                eligible.append(b)
            active_batteries = eligible

        # Safeguard: if active_batteries is empty (priority list empty), set all to zero and return
        if not active_batteries:
            _LOGGER.debug(
                "No eligible batteries in priority list (target: %s). Setting all to zero.",
                target_num_batteries,
            )
            await self._set_all_batteries_to_zero()

            if from_pid:
                self._reset_pid_state()
            return

        power_per_battery = round(abs_power / len(active_batteries))
        # Ensure we do not exceed max charge/discharge power
        if self._last_power_direction == PowerDir.CHARGE:  # Charging
            power_per_battery = min(power_per_battery, max_charge_power)
        elif self._last_power_direction == PowerDir.DISCHARGE:  # Discharging
            power_per_battery = min(power_per_battery, max_discharge_power)

        active_battery_ids = [b["id"] for b in active_batteries]

        _LOGGER.debug(
            "Distributing %sW to %s batteries: %s with %sW each.",
            round(power, 0),
            len(active_battery_ids),
            active_battery_ids,
            power_per_battery,
        )

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
        await self._async_call_cached(
            "switch",
            "turn_on",
            modbus_control_mode,
            "state",
            True,
            {"entity_id": modbus_control_mode},
            blocking=True,
        )
        
        try:
            if direction == 1: #Charging the Batteries
                await self._async_call_cached(
                    "number",
                    "set_value",
                    charge_entity,
                    "value",
                    power,
                    {"entity_id": charge_entity, "value": power},
                    blocking=True,
                )
                await self._async_call_cached(
                    "select",
                    "select_option",
                    force_mode,
                    "option",
                    "charge",
                    {"entity_id": force_mode, "option": "charge"},
                    blocking=True,
                )
            elif direction == -1: #Discharging the Batteries
                await self._async_call_cached(
                    "number",
                    "set_value",
                    discharge_entity,
                    "value",
                    power,
                    {"entity_id": discharge_entity, "value": power},
                    blocking=True,
                )
                await self._async_call_cached(
                    "select",
                    "select_option",
                    force_mode,
                    "option",
                    "discharge",
                    {"entity_id": force_mode, "option": "discharge"},
                    blocking=True,
                )
            else: #Set to 0
                await self._async_call_cached(
                    "number",
                    "set_value",
                    charge_entity,
                    "value",
                    0,
                    {"entity_id": charge_entity, "value": 0},
                    blocking=True,
                )
                await self._async_call_cached(
                    "number",
                    "set_value",
                    discharge_entity,
                    "value",
                    0,
                    {"entity_id": discharge_entity, "value": 0},
                    blocking=True,
                )
                await self._async_call_cached(
                    "select",
                    "select_option",
                    force_mode,
                    "option",
                    "standby",
                    {"entity_id": force_mode, "option": "standby"},
                    blocking=True,
                )

            # Add a small delay to prevent overwhelming the device APIs
            await asyncio.sleep(0.1)
        except Exception as e:
            _LOGGER.error(f"Failed to set power for {base_entity_id}: {e}")

    async def _set_all_batteries_to_zero(self):
        """Set all configured batteries power to 0."""
        _LOGGER.debug("Setting all batteries to 0W.")
        tasks = [self._set_battery_power(b_id, 0, 0) for b_id in self._battery_entities]
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                _LOGGER.debug("Ignored error while setting batteries to 0W: %s", res)

    async def _disable_modbus_control_mode(self, target_num_batteries: int = 1):
        """Disable Modbus RS485 control mode based on power stages and battery priority.
    
        - Power < Stage1: Disable only for highest priority battery, enable for others
        - Stage1 <= Power < Stage2: Disable for top 2 batteries, enable for others
        - Power >= Stage2: Disable for all batteries (full automatic mode)
        - No power direction: Disable for all batteries
        """

        # Get list of batteries that should have Modbus control disabled
        batteries_to_disable_list = [b['id'] for b in self._battery_priority[:target_num_batteries]]

        _LOGGER.debug(f"Disabling Modbus control for {target_num_batteries} batteries: {batteries_to_disable_list}")

        tasks = []
        for battery_base_id in self._battery_entities:
            modbus_control_mode = f"switch.{battery_base_id}_modbus_rs485_control_mode"
            
            if battery_base_id in batteries_to_disable_list:
                # Disable Modbus control (turn off) - set to automatic
                if self.hass.services.has_service("switch", "turn_off"):
                    tasks.append(
                        self.hass.services.async_call(
                            "switch",
                            "turn_off",
                            {"entity_id": modbus_control_mode},
                            blocking=True,
                        )
                    )
            else:
                # Enable Modbus control (turn on) - keep in manual/forcible mode
                if self.hass.services.has_service("switch", "turn_on"):
                    tasks.append(
                        self.hass.services.async_call(
                            "switch",
                            "turn_on",
                            {"entity_id": modbus_control_mode},
                            blocking=True,
                        )
                    )
                tasks.append(self._set_battery_power(battery_base_id, 0, 0)) # Set power to 0 for batteries not in control

        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                _LOGGER.debug("Ignored error while disabling modbus control mode: %s", res)

    def _get_effective_update_interval(self) -> int:
        """Calculate the effective update interval based on CT-Mode and wallbox activity."""
        configured_interval = self.config.get(CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS, 60)
        
        # In CT-Mode, use 10s unless wallbox is active
        if self._ct_mode:
            if self._wallbox_is_active:
                # Wallbox is in control, keep configured interval
                _LOGGER.debug(f"CT-Mode: Wallbox active, using configured interval ({configured_interval}s)")
                return configured_interval
            else:
                # No wallbox activity, use 10s refresh rate
                _LOGGER.debug("CT-Mode: No wallbox activity, using 10s refresh rate")
                return 10
        else:
            # Normal mode: use configured interval
            return configured_interval
