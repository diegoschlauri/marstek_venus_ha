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
from homeassistant.helpers.storage import Store


from .const import (
    DOMAIN,
    SIGNAL_DIAGNOSTICS_UPDATED,
    CONF_CT_MODE,
    CONF_BATTERY_COUNT,
    CONF_GRID_POWER_SENSOR,
    CONF_SMOOTHING_SECONDS,
    CONF_MIN_SURPLUS,
    CONF_MIN_CONSUMPTION,
    CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING,
    CONF_MIN_SOC,
    CONF_MAX_SOC,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MAX_CHARGE_POWER,
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
    CONF_WALLBOX_STABILITY_MIN_POWER_GAP,
    CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS,
    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    CONF_SERVICE_CALL_CACHE_SECONDS,
    CONF_CHARGE_POWER_LEVEL_1,
    CONF_CHARGE_POWER_LEVEL_2,
    CONF_CHARGE_POWER_LEVEL_3,
    CONF_CHARGE_POWER_LEVEL_4,
    CONF_CHARGE_POWER_LEVEL_5,
    CONF_DISCHARGE_POWER_LEVEL_1,
    CONF_DISCHARGE_POWER_LEVEL_2,
    CONF_DISCHARGE_POWER_LEVEL_3,
    CONF_DISCHARGE_POWER_LEVEL_4,
    CONF_DISCHARGE_POWER_LEVEL_5,
    DEFAULT_MAX_DISCHARGE_POWER,
    DEFAULT_MAX_CHARGE_POWER,
    DEFAULT_MIN_SOC,
    DEFAULT_MAX_SOC,
    DEFAULT_PRIORITY_INTERVAL,
    DEFAULT_SMOOTHING_SECONDS,
    DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD,
    DEFAULT_WALLBOX_RESUME_CHECK_SECONDS,
    DEFAULT_WALLBOX_START_DELAY_SECONDS,
    DEFAULT_WALLBOX_STABILITY_MIN_POWER_GAP,
    DEFAULT_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS,
    DEFAULT_SERVICE_CALL_CACHE_SECONDS,
    DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS,
    CONF_PID_ENABLED,
    CONF_PID_KP,
    CONF_PID_KI,
    CONF_PID_KD,
    DEFAULT_PID_ENABLED,
    DEFAULT_PID_KP,
    DEFAULT_PID_KI,
    DEFAULT_PID_KD,
    DEFAULT_CHARGE_POWER_LEVEL_1,
    DEFAULT_CHARGE_POWER_LEVEL_2,
    DEFAULT_CHARGE_POWER_LEVEL_3,
    DEFAULT_CHARGE_POWER_LEVEL_4,
    DEFAULT_CHARGE_POWER_LEVEL_5,
    DEFAULT_DISCHARGE_POWER_LEVEL_1,
    DEFAULT_DISCHARGE_POWER_LEVEL_2,
    DEFAULT_DISCHARGE_POWER_LEVEL_3,
    DEFAULT_DISCHARGE_POWER_LEVEL_4,
    DEFAULT_DISCHARGE_POWER_LEVEL_5,
)

_LOGGER = logging.getLogger(__name__)

# Versioning for your storage file
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_settings"

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
        # Store for persisting settings or state if needed
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        # Default Values
        self._allow_charging = True
        self._allow_discharging = True
        self._block_discharging_while_carcharging = True
        self._wallbox_priority = True

        # Version will be loaded asynchronously
        self._manifest_version = "unknown"

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
        self._last_grid_power_raw: float | None = None
        self._below_min_cycles_to_zero = self.config.get(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, 10)

        
        # Wallbox state (persisted via ConfigEntry options key "wallbox_priority")
        self._wallbox_charge_paused = False
        self._wallbox_power_is_stable = False
        self._wallbox_wait_start: datetime | None = None
        self._wallbox_stabilization_start: datetime | None = None
        self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))
        self._wallbox_power_gap_history = deque(maxlen=self._get_deque_size("wallbox_power_gap"))
        self._wallbox_min_power: int = 0
        self._wallbox_max_power: int = 0
        self._wallbox_power_difference: int = 0
        self._wallbox_free_power: int = 0
        self._last_wallbox_pause_attempt = datetime.min # For 60-minute cooldown
        self._wallbox_wait_start = None # Initialisiert: Timer für den Start-Delay
        self._wallbox_stabilization_start = None # Initialisiert: Startzeitpunkt der Stabilisierung nach Start-Delay
        self._wallbox_cable_was_on = False # Trackt den vorherigen Kabelzustand
        self._last_wallbox_power = 0.0
        # CT-Mode state
        self._ct_mode = self.config.get(CONF_CT_MODE, False)
        self._wallbox_is_active = False  # Track if wallbox currently controls

        # Counters for minimum threshold gating in method _check_min_thresholds
        self._below_min_charge_count = 0
        self._below_min_discharge_count = 0
        # Status for the Schmitt-Trigger-Hysterese
        self._charge_suspended = False
        self._discharge_suspended = False

        # Collect battery entities
        self._battery_count = int(self.config.get(CONF_BATTERY_COUNT, 1))
        self._batteries = []

        for i in range(1, self._battery_count + 1):
            # Hole die vom Nutzer ausgewählte Entität
            ac_power_ent = self.config.get(f"battery_{i}_ac_power_entity")
            
            # Wenn sie existiert, füge das komplette Batterie-Set hinzu
            if ac_power_ent:
                self._batteries.append({
                    "id": f"battery_{i}",  # Eine interne ID, nur fürs Logging und die Prio-Liste
                    "ac_power": ac_power_ent,
                    "soc": self.config.get(f"battery_{i}_soc_entity"),
                    "charge_power": self.config.get(f"battery_{i}_charge_power_entity"),
                    "discharge_power": self.config.get(f"battery_{i}_discharge_power_entity"),
                    "force_mode": self.config.get(f"battery_{i}_force_mode_entity"),
                    "rs485_mode": self.config.get(f"battery_{i}_rs485_mode_entity"),
                })
    
    async def async_load_settings(self) -> None:
        """Fetch settings from the Store helper."""
        stored_data = await self._store.async_load()
        if stored_data:
            # Get values with defaults if they don't exist in the JSON
            self._allow_charging = stored_data.get("allow_charging", True)
            self._allow_discharging = stored_data.get("allow_discharging", True)
            self._block_discharging_while_carcharging = stored_data.get("block_discharging_while_carcharging", True)
            self._wallbox_priority = stored_data.get("wallbox_priority", True)
        else:
            # If no store exists yet, use your defaults
            self._allow_charging = True
            self._allow_discharging = True
            self._block_discharging_while_carcharging = True
            self._wallbox_priority = True

    async def async_save_settings(self) -> None:
        """Save current settings to store."""
        await self._store.async_save({
            "allow_charging": self._allow_charging,
            "allow_discharging": self._allow_discharging,
            "block_discharging_while_carcharging": self._block_discharging_while_carcharging,
            "wallbox_priority": self._wallbox_priority,
            # include all other persisted flags here
        })


    async def async_load_manifest_version(self) -> None:
        """Load version from manifest.json file asynchronously."""
        try:
            import json
            manifest_path = __file__.replace("coordinator.py", "manifest.json")
            
            def _load_sync() -> str:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    return manifest.get("version", "unknown")
            
            self._manifest_version = await asyncio.to_thread(_load_sync)
        except Exception as err:
            _LOGGER.warning("Could not load manifest version: %s", err)
            self._manifest_version = "unknown"

    def _get_deque_size(self, mode: str):
        # Previously we treated the configured seconds value as the number
        # of samples for the deque. That means if the coordinator runs
        # every 3s and the user configured 300, the deque kept 300 samples
        # -> covering 900s in time. Instead, convert seconds -> samples
        # using the coordinator update interval so maxlen equals the
        # number of samples covering the requested time window.
        if mode == "smoothing":
            seconds = self.config.get(CONF_SMOOTHING_SECONDS, DEFAULT_SMOOTHING_SECONDS)
        elif mode == "wallbox":
            seconds = self.config.get(CONF_WALLBOX_RESUME_CHECK_SECONDS, DEFAULT_WALLBOX_RESUME_CHECK_SECONDS)
        elif mode == "wallbox_power_gap":
            seconds = self.config.get(CONF_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS, DEFAULT_WALLBOX_STABILITY_MIN_GAP_DURATION_SECONDS)
        else:
            return 1

        try:
            seconds_int = int(seconds or 0)
        except (TypeError, ValueError):
            seconds_int = 0

        try:
            interval_seconds = int(
                self.config.get(
                    CONF_COORDINATOR_UPDATE_INTERVAL_SECONDS,
                    DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS,
                )
                or DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS
            )
        except (TypeError, ValueError):
            interval_seconds = int(DEFAULT_COORDINATOR_UPDATE_INTERVAL_SECONDS)

        if interval_seconds <= 0:
            interval_seconds = 1

        # Compute number of samples that cover the requested seconds (round up)
        samples = max(1, (seconds_int + interval_seconds - 1) // interval_seconds)
        return samples

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def allow_charging(self) -> bool:
        return self._allow_charging

    @property
    def allow_discharging(self) -> bool:
        return self._allow_discharging

    @property
    def block_discharging_while_carcharging(self) -> bool:
        return self._block_discharging_while_carcharging

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
    def wallbox_power_is_stable(self) -> bool:
        return bool(self._wallbox_power_is_stable)

    @property
    def wallbox_min_power(self) -> int:
        return self._wallbox_min_power
    
    @property
    def wallbox_max_power(self) -> int:
        return self._wallbox_max_power

    @property
    def wallbox_power_difference(self) -> int:
        return self._wallbox_power_difference

    @property
    def wallbox_free_power(self) -> int:
        return self._wallbox_free_power

    @property
    def wallbox_cable_was_on(self) -> bool:
        return bool(self._wallbox_cable_was_on)
    
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
    def wallbox_stabilization_start_iso(self) -> str | None:
        value = self.wallbox_stabilization_start
        if value is None:
            return None
        return value.isoformat()

    @property
    def wallbox_stabilization_start(self) -> datetime | None:
        return self._as_aware_datetime(self._wallbox_stabilization_start)

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
            await asyncio.wait_for(
                self.hass.services.async_call(domain, service, service_data, blocking=blocking),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Service call %s.%s timed out for %s",
                domain,
                service,
                entity_id,
            )
            return
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
            new_state = event.data.get("new_state")
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
        # Load the persisted values before adding entities
        await self.async_load_settings()
        
        if self._is_running or self._unsub_listeners or self._update_task is not None:
            await self.async_stop_listening()

        self._pid_suspended = False
        self._pid_suspend_direction = PowerDir.NEUTRAL
        
        # 1. Initialize caches and deques
        self._service_call_cache.clear()
        _LOGGER.debug(f"Running version {self._manifest_version}")
        self._below_min_charge_count = 0
        self._below_min_discharge_count = 0
        self._power_history = deque(maxlen=self._get_deque_size("smoothing"))
        self._wallbox_power_history = deque(maxlen=self._get_deque_size("wallbox"))
        self._last_wallbox_pause_attempt = datetime.min
        
        # 2. Register state-change listeners (to ensure we don't miss sensor updates)
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
            self.hass.loop.call_soon_threadsafe(_schedule_update)

        if trigger_entities:
            remove = async_track_state_change_event(self.hass, trigger_entities, _on_state_change)
            self._unsub_listeners.append(remove)

        self._is_running = True
        
        # 3. Temporarily block the logic for a clean startup
        self._ready_to_command = False

        async def _delayed_startup_routine():
            _LOGGER.info("Waiting for Modbus entities to become available...")
            
            # Wait for the ac_power sensors of all configured batteries
            wait_tasks = []
            for batt in self._batteries:
                if batt.get("ac_power"):
                    wait_tasks.append(self.wait_for_entity_available(batt["ac_power"], timeout=30))
            
            if wait_tasks:
                await asyncio.gather(*wait_tasks)
                
            # Tiny buffer to ensure switches/selects are also ready after the sensor becomes available
            await asyncio.sleep(2)
            
            _LOGGER.info("Modbus entities are ready. Starting Marstek Venus control logic.")
            
            # We are now ready to send commands!
            self._ready_to_command = True
            
            # Initially set all batteries to 0W
            await self._set_all_batteries_to_zero()
            
            # CT-Mode Check
            if self._ct_mode:
                _LOGGER.info("CT-Mode enabled. Disabling RS485 Modbus control mode.")
                for batt in self._batteries:
                    modbus_control_mode = batt.get("rs485_mode")
                    if modbus_control_mode:
                        try:
                            await self.hass.services.async_call("switch", "turn_off", {"entity_id": modbus_control_mode}, blocking=True)
                        except Exception as e:
                            _LOGGER.debug(f"Could not disable RS485 mode for {batt['id']}: {e}")
            else:
                _LOGGER.info("CT-Mode disabled. Batteries remain in manual/forcible mode.")
                
            # Request initial update
            await self.async_request_update(reason="startup")

        # Start the intelligent startup routine in the background
        self.hass.async_create_task(_delayed_startup_routine())

        coordinator_update_interval = self._get_effective_update_interval()
        _LOGGER.info(
            "Marstek Venus HA Integration coordinator started (id=%s, min interval: %ss).", 
            self._instance_id, coordinator_update_interval
        )

    async def async_request_update(self, *, reason: str = "manual") -> None:
        """Request a coordinator update.

        This is safe to call from automations/services or state-change listeners.
        It enforces a minimum interval between updates and prevents concurrent runs.
        """
        # Blocking updates, while startup or startdelay
        if not self._is_running or not getattr(self, "_ready_to_command", True):
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
        try:
            await asyncio.wait_for(self._async_update(), timeout=60.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("Coordinator update timed out (%s).", reason)
        except Exception as err:
            _LOGGER.exception("Coordinator update failed (%s): %s", reason, err)
        finally:
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
        
        # check if power is below thresholds for too long and if so, set all batteries to 0W and suspend PID if active
        is_below_threshold = await self._check_power_thresholds(real_power)
        if is_below_threshold:
            _LOGGER.debug("Power below threshold for too many cycles. Forcing all batteries to 0W.")
            await self._set_all_batteries_to_zero()
            
            # Reset PID state and suspend if enabled, to prevent integral windup and unnecessary switching when we are at 0W for an extended period.
            if self._pid_enabled:
                self._pid_suspended = True
                self._pid_suspend_direction = PowerDir.CHARGE if real_power < 0 else PowerDir.DISCHARGE
                self._reset_pid_state()
                
            return # Stop further processing until power goes above the threshold again for declared number of cycles.

        if not self._ct_mode and self._pid_enabled:
            if self._pid_suspended:
                min_surplus_for_charging = self.config.get(CONF_MIN_SURPLUS, 50)
                min_consumption_for_discharging = self.config.get(CONF_MIN_CONSUMPTION, 50)

                should_resume = False
                if self._pid_suspend_direction == PowerDir.CHARGE:
                    should_resume = real_power < -float(min_surplus_for_charging)
                elif self._pid_suspend_direction == PowerDir.DISCHARGE:
                    should_resume = real_power > float(min_consumption_for_discharging)

                opposite_direction_valid = False
                if self._pid_suspend_direction == PowerDir.CHARGE:
                    opposite_direction_valid = real_power > float(min_consumption_for_discharging)
                elif self._pid_suspend_direction == PowerDir.DISCHARGE:
                    opposite_direction_valid = real_power < -float(min_surplus_for_charging)

                if not should_resume and not opposite_direction_valid:
                    # Keep batteries at 0 and keep PID state reset until load crosses the threshold again.
                    await self._set_all_batteries_to_zero()
                    return

                _LOGGER.debug("PID suspension released (direction=%s)", self._pid_suspend_direction.name)
                self._pid_suspended = False
                self._pid_suspend_direction = PowerDir.NEUTRAL

            _LOGGER.debug("PID input grid power: %sW (target=0W)", round(smoothed_grid_power, 2))
            await self._pid_control_step(smoothed_grid_power, real_power)
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

    async def _pid_control_step(self, smoothed_grid_power: float, real_power: float) -> None:
        """Run one PID control step to drive smoothed_grid_power towards 0W."""
        # Error is defined such that:
        # - Surplus (smoothed_grid_power < 0) -> positive error -> positive output -> charging
        # - Import  (smoothed_grid_power > 0) -> negative error -> negative output -> discharging
        error = -float(smoothed_grid_power)
        now = datetime.now()

        min_surplus_for_charging = self.config.get(CONF_MIN_SURPLUS, 50)
        min_consumption_for_discharging = self.config.get(CONF_MIN_CONSUMPTION, 50)

        if self._pid_prev_ts is None:
            dt = 0.0
        else:
            dt = max(0.0, (now - self._pid_prev_ts).total_seconds())

        derivative = 0.0
        if dt > 0 and self._pid_prev_error is not None:
            derivative = (error - self._pid_prev_error) / dt

        # NEU: Die Richtung wird NICHT mehr vom Error bestimmt, 
        # sondern vom tatsächlichen Fluss am Hausanschluss - Batterien.
        intended_direction = PowerDir.NEUTRAL
        if real_power < -float(min_surplus_for_charging):  # Tatsächlicher Überschuss (Einspeisung) -> Laden
            intended_direction = PowerDir.CHARGE
        elif real_power > float(min_consumption_for_discharging): # Tatsächlicher Bezug -> Entladen
            intended_direction = PowerDir.DISCHARGE
        else:
            # Wenn wir sehr nah an 0 sind, behalten wir die letzte Richtung bei,
            # um "Zappeln" der Prioritätsliste zu vermeiden.
            intended_direction = self._last_power_direction

        # Ensure priority is up to date for this direction
        await self._update_battery_priority_if_needed(power_direction=intended_direction)

        # If no batteries are available for the intended direction, reset PID and exit.
        if not self._battery_priority:
            _LOGGER.debug("PID: no available batteries for direction %s — resetting PID state.", intended_direction.name)
            self._reset_pid_state()
            await self._set_all_batteries_to_zero()  # Ensure batteries are at 0 if PID cannot operate
            return

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

        self._last_grid_power_raw = current_power
            
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
            batt["id"]: self._get_float_state(batt["ac_power"]) for batt in self._batteries
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
        stability_threshold = self.config.get(CONF_WALLBOX_POWER_STABILITY_THRESHOLD)
        wallbox_stability_min_power_gap: int = self.config.get(CONF_WALLBOX_STABILITY_MIN_POWER_GAP, DEFAULT_WALLBOX_STABILITY_MIN_POWER_GAP)
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

        if stability_threshold is None:
            stability_threshold_w = float(DEFAULT_WALLBOX_POWER_STABILITY_THRESHOLD)
        else:
            try:
                stability_threshold_w = float(cast(Any, stability_threshold))
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
                self._wallbox_power_gap_history.clear()
                self._wallbox_wait_start = None
                self._wallbox_cable_was_on = False
                self._last_wallbox_pause_attempt = datetime.min # Reset cooldown on unplug
                self._wallbox_power_is_stable = False # Reset Stabilitätsstatus, da Auto nicht geladen hat
                self._wallbox_stabilization_start = None # Reset Stabilisierungstimer, da Auto nicht geladen hat
            return False
        
        self._wallbox_cable_was_on = True # Kabel ist jetzt eingesteckt
            
        wb_power = 0.0
        wb_power_state = self._get_entity_state(wb_power_sensor_id)
        if wb_power_state:
            try:
                wb_power = float(wb_power_state.state)
                unit = wb_power_state.attributes.get("unit_of_measurement")
                if unit and unit.lower() == 'kw':
                    wb_power *= 1000
                if wb_power != self._last_wallbox_power:
                    _LOGGER.debug(f"Wallbox power: {wb_power}W")
                self._last_wallbox_power = wb_power
            except (ValueError, TypeError):
                _LOGGER.warning(f"Could not parse state of '{wb_power_sensor}' as float: '{wb_power_state.state}'")
    
        self._wallbox_power_history.append(wb_power)
        if real_power <= 0:
            # Nur negative Werte in die Gap-History aufnehmen
            self._wallbox_power_gap_history.append(real_power)
        if real_power > 0:
            self._wallbox_power_gap_history.append(0) # If positive, add 0 to gap history to keep it updated and comparable

        # Calculate new power direction
        if real_power < 0:
            self._last_power_direction = PowerDir.CHARGE
        elif real_power >= 0:
            self._last_power_direction = PowerDir.DISCHARGE

        # 1. Höchste Priorität: Entladeschutz, wenn Wallbox aktiv ist und Blockierung aktiviert ist
        if wb_power > 100 and self._last_power_direction == PowerDir.DISCHARGE and self._block_discharging_while_carcharging:
            _LOGGER.debug("Wallbox is active, blocking is on, ensuring batteries do not discharge.")
            await self._set_all_batteries_to_zero()
            return True
        
        if wb_power > 100 and self._last_power_direction == PowerDir.DISCHARGE and not self._block_discharging_while_carcharging:
            _LOGGER.debug("Wallbox is active, but blocking is off. Allowing discharge but checking for max surplus.")
            return False
        
        # Neue Wallbox Priority Switch Logik
        if self._wallbox_priority is False:
            _LOGGER.debug("Wallbox priority switch is OFF. Skipping wallbox logic.")
            self._wallbox_charge_paused = False
            self._wallbox_power_is_stable = False # Reset Stabilitätsstatus, da Priorität ausgeschaltet ist
            self._wallbox_stabilization_start = None # Reset Stabilisierungstimer, da
            self._wallbox_power_history.clear() # Clear history to avoid stale data if priority is re-enabled
            self._wallbox_power_gap_history.clear() # Clear gap history to avoid stale data if priority is re-enabled
            # Reset min/max/threshold
            self._wallbox_min_power = 0 
            self._wallbox_max_power = 0
            self._wallbox_power_difference = 0
            self._last_wallbox_pause_attempt = datetime.min # Reset cooldown when priority is turned off
            self._wallbox_wait_start = None # Reset wait timer when priority is turned off
            return False

        # 2. Zustandsprüfung: Ist eine Ladepause für die Wallbox aktiv?
        if self._wallbox_charge_paused:
            # JA, Pause ist aktiv. Prüfe Bedingungen, um die Pause zu BEENDEN.
            _LOGGER.debug("Wallbox pause is currently active. Checking conditions to end pause.")

            # Regel (Timeout): Auto hat nicht angefangen zu laden? -> Pause beenden
            if self._wallbox_wait_start is not None:
                elapsed = (datetime.now() - self._wallbox_wait_start).total_seconds()
                if elapsed > start_delay and wb_power <= 100:
                    _LOGGER.info(f"Wallbox did not start charging in {start_delay}s. Releasing batteries.")
                    self._wallbox_charge_paused = False
                    self._wallbox_power_is_stable = False # Reset Stabilitätsstatus, da Auto nicht geladen hat
                    self._wallbox_stabilization_start = None # Reset Stabilisierungstimer, da Auto nicht geladen hat
                    self._wallbox_power_history.clear()
                    self._wallbox_power_gap_history.clear()
                    # Reset min/max/threshold
                    self._wallbox_min_power = 0 
                    self._wallbox_max_power = 0
                    self._wallbox_power_difference = 0
                    self._wallbox_wait_start = None
                    return False

            # Regel: Auto lädt, ist die Leistung stabil? -> Pause beenden
            if wb_power > 100:
                self._wallbox_wait_start = None # Timer wird irrelevant, sobald das Auto lädt
                if (len(self._wallbox_power_history) == self._wallbox_power_history.maxlen) and (len(self._wallbox_power_gap_history) == self._wallbox_power_gap_history.maxlen):
                    # NEUE LOGIK: Prüfe die Spanne (Min/Max) der History
                    min_power = min(self._wallbox_power_history)
                    self._wallbox_min_power = min_power # Für Debugging-Zwecke speichern
                    max_power = max(self._wallbox_power_history)
                    self._wallbox_max_power = max_power # Für Debugging-Zwecke speichern
                    power_spread = max_power - min_power # Die Differenz zwischen Min und Max
                    self._wallbox_power_difference = power_spread # Für Debugging-Zwecke speichern
                    self._wallbox_free_power = abs(max(self._wallbox_power_gap_history))
                    _LOGGER.debug(f"Wallbox resume check: Min={min_power:.0f}W, Max={max_power:.0f}W, Spread={power_spread:.0f}W, free power={self._wallbox_free_power:.0f}W")

                    if power_spread < stability_threshold_w and self._wallbox_free_power > wallbox_stability_min_power_gap:
                        _LOGGER.debug(f"Wallbox power has stabilized (Spread < {stability_threshold_w}W and free power > {wallbox_stability_min_power_gap}W). Releasing batteries.")
                        self._wallbox_stabilization_start = datetime.now() # Stabilization-Timer starten (für den aktuellen Versuch)
                        self._wallbox_power_is_stable = True
                        self._wallbox_charge_paused = False
                        return False
                    else:
                        _LOGGER.debug(f"Wallbox power not yet stable (Spread >= {stability_threshold_w}W or free power <= {wallbox_stability_min_power_gap}W). Keeping pause active.")
                        self._wallbox_power_is_stable = False
                        self._wallbox_stabilization_start = None # Reset the stabilization timer zurücksetzen, da Leistung nicht stabil ist
                        
            # Regel: Auto lädt nicht mehr seit X-Minuten -> Pause beenden
            if wb_power < 100:
                if self._wallbox_wait_start is None:
                    _LOGGER.info("Wallbox: start new start-delay timer.")
                    now = datetime.now()
                    self._wallbox_wait_start = now        # Start-Delay-Timer (für den aktuellen Versuch) starten
                elif self._wallbox_wait_start is not None:
                    elapsed = (datetime.now() - self._wallbox_wait_start).total_seconds()
                    if elapsed > start_delay:
                        _LOGGER.info(f"Wallbox did not start charging again in {start_delay}s. Releasing batteries.")
                        self._wallbox_charge_paused = False
                        self._wallbox_power_history.clear()
                        self._wallbox_power_gap_history.clear()
                        # Reset min/max/threshold
                        self._wallbox_min_power = 0 
                        self._wallbox_max_power = 0
                        self._wallbox_power_difference = 0
                        self._wallbox_wait_start = None
                        return False

            # Keine Bedingung zum Beenden erfüllt -> Pause beibehalten
            _LOGGER.debug("Wallbox pause remains active. Batteries set to zero.")
            self._wallbox_charge_paused = True
            self._wallbox_power_is_stable = False # Reset Stabilitätsstatus, da Pause beibehalten wird
            self._wallbox_stabilization_start = None # Reset Stabilisierungstimer, da Pause beibehalten wird
            await self._set_all_batteries_to_zero()
            return True

        # 3. Zustandsprüfung: Keine Ladepause aktiv. Prüfen, ob eine gestartet werden soll.
        else:
            #_LOGGER.debug("No wallbox pause active. Checking if conditions to start pause are met.")
            # Regel (Start): Genug Überschuss UND Auto lädt nicht UND Cooldown abgelaufen? -> Pause starten
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
                    self._wallbox_power_is_stable = False # Reset Stabilitätsstatus für den neuen Versuch
                    self._wallbox_stabilization_start = None # Reset Stabilisierungstimer für den neuen Versuch
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
                    self._wallbox_power_is_stable = False # Reset Stabilitätsstatus für den neuen Versuch
                    self._wallbox_stabilization_start = None # Reset Stabilisierungstimer für den neuen Versuch 
                    await self._set_all_batteries_to_zero() 
                    return True
                else:
                    _LOGGER.debug(f"High surplus, but wallbox pause is on cooldown ({time_since_last_attempt:.0f}s / {retry_seconds}s).")
        
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
            time_since_last_update > priority_interval or
            needs_initial_priority
        ):
            # Check if enough time has passed since last update
            direction_changed = power_direction != self._last_power_direction
            if direction_changed or needs_initial_priority or time_since_last_update >= min_update_interval:
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
        
        # If charging or discharging is not allowed, set priority to empty to prevent any battery from being used in that direction.
        if self._allow_charging is False and power_direction == PowerDir.CHARGE:
            self._battery_priority = []
            _LOGGER.debug("Charging is disabled. Setting battery priority to empty for charging.")
            return
        if self._allow_discharging is False and power_direction == PowerDir.DISCHARGE:
            self._battery_priority = []
            _LOGGER.debug("Discharging is disabled. Setting battery priority to empty for discharging.")
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
        missing_soc: list[str] = []
        for batt in self._batteries:
            soc = self._get_float_state(batt["soc"])
            if soc is None:
                missing_soc.append(batt["id"])
                continue

            batt_copy = dict(batt)
            batt_copy["current_soc"] = soc

            if power_direction == PowerDir.CHARGE and soc <= max_soc:
                available_batteries.append(batt_copy)
            elif power_direction == PowerDir.DISCHARGE and soc >= min_soc:
                available_batteries.append(batt_copy)

        is_reverse = (power_direction == PowerDir.DISCHARGE)
        self._battery_priority = sorted(available_batteries, key=lambda x: x['current_soc'], reverse=is_reverse)
        _LOGGER.debug(f"New battery priority: {self._battery_priority}")
        if missing_soc:
            _LOGGER.debug("Battery SoC unavailable for priority calculation: %s", missing_soc)

    def _get_desired_number_of_batteries(self, power: float) -> int:
        # Get the current allow_charging and allow_discharging states
        abs_power = abs(power)
        
        num_available = len(self._battery_priority)
        if num_available == 0:
            _LOGGER.debug("No available batteries in priority list. Returning 0 target batteries.")
            return 0
        
        # 1. Ermittle die Anzahl der Batterien, die aktuell Leistung liefern/aufnehmen
        num_currently_active = 0
        for batt in self._batteries:
            power_state = self._get_float_state(batt["ac_power"])
            if power_state is not None and abs(power_state) > 10:
                num_currently_active += 1

        _LOGGER.debug(f"Hysteresis check: num_available={num_available}, num_currently_active={num_currently_active}, abs_power={abs_power:.0f}W")

        # Startwert ist die aktuell aktive Anzahl (mindestens 1)
        target_num_batteries = max(1, num_currently_active)
        stage_offset = self.config.get(CONF_POWER_STAGE_OFFSET, 500)
        
        # 2. Hysterese-Logik dynamisch anwenden

        # HOCHSCHALTEN: Prüfen, ob wir mehr Batterien brauchen
        while target_num_batteries < num_available:
            # Hole den dynamischen Schwellenwert (Fallback: i * 1500)
            threshold = self.config.get(f"powerstage_{target_num_batteries}_to_{target_num_batteries+1}")
            if threshold is None:
                threshold = target_num_batteries * 1500
            
            # Schwelle = STUFE + OFFSET
            if abs_power > (threshold + stage_offset):
                target_num_batteries += 1
            else:
                break # Wenn die Leistung nicht reicht, brechen wir das Hochschalten ab

        # RUNTERSCHALTEN: Prüfen, ob wir weniger Batterien brauchen
        while target_num_batteries > 1:
            # Hole den Schwellenwert der darunterliegenden Stufe
            threshold = self.config.get(f"powerstage_{target_num_batteries-1}_to_{target_num_batteries}")
            if threshold is None:
                threshold = (target_num_batteries - 1) * 1500
                
            # Schwelle = STUFE - OFFSET
            if abs_power < (threshold - stage_offset):
                target_num_batteries -= 1
            else:
                break # Wenn die Leistung noch zu hoch ist, bleiben wir auf dieser Stufe

        _LOGGER.debug(f"Determined target number of batteries: {target_num_batteries} (Available: {num_available}, Currently Active: {num_currently_active})")
        # Consider per-battery SoC-based caps: if the selected number of
        # batteries cannot supply the requested power because of their
        # per-battery caps, increase the number of batteries until the
        # requested power can be supplied or we exhaust available batteries.
        try:
            charge_levels = [
                int(self.config.get(CONF_CHARGE_POWER_LEVEL_1, DEFAULT_CHARGE_POWER_LEVEL_1)),
                int(self.config.get(CONF_CHARGE_POWER_LEVEL_2, DEFAULT_CHARGE_POWER_LEVEL_2)),
                int(self.config.get(CONF_CHARGE_POWER_LEVEL_3, DEFAULT_CHARGE_POWER_LEVEL_3)),
                int(self.config.get(CONF_CHARGE_POWER_LEVEL_4, DEFAULT_CHARGE_POWER_LEVEL_4)),
                int(self.config.get(CONF_CHARGE_POWER_LEVEL_5, DEFAULT_CHARGE_POWER_LEVEL_5)),
            ]
            discharge_levels = [
                int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_1, DEFAULT_DISCHARGE_POWER_LEVEL_1)),
                int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_2, DEFAULT_DISCHARGE_POWER_LEVEL_2)),
                int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_3, DEFAULT_DISCHARGE_POWER_LEVEL_3)),
                int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_4, DEFAULT_DISCHARGE_POWER_LEVEL_4)),
                int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_5, DEFAULT_DISCHARGE_POWER_LEVEL_5)),
            ]
        except Exception:
            charge_levels = [DEFAULT_CHARGE_POWER_LEVEL_1, DEFAULT_CHARGE_POWER_LEVEL_2, DEFAULT_CHARGE_POWER_LEVEL_3, DEFAULT_CHARGE_POWER_LEVEL_4, DEFAULT_CHARGE_POWER_LEVEL_5]
            discharge_levels = [DEFAULT_DISCHARGE_POWER_LEVEL_1, DEFAULT_DISCHARGE_POWER_LEVEL_2, DEFAULT_DISCHARGE_POWER_LEVEL_3, DEFAULT_DISCHARGE_POWER_LEVEL_4, DEFAULT_DISCHARGE_POWER_LEVEL_5]

        # Get the maximum power limits from config, with defaults
        max_discharge_power = self.config.get(CONF_MAX_DISCHARGE_POWER, 2500)
        max_charge_power = self.config.get(CONF_MAX_CHARGE_POWER, 2500)
        # Determine intended direction from the provided power if possible
        direction = self._last_power_direction
        if power is not None:
            try:
                if float(power) < 0:
                    direction = PowerDir.CHARGE
                elif float(power) > 0:
                    direction = PowerDir.DISCHARGE
            except Exception:
                pass

        # Helper to compute cap for a battery based on its SoC and direction
        def _cap_for_batt(batt_id: str) -> int:
            batt = next((b for b in self._batteries if b["id"] == batt_id), None)
            if not batt:
                return int(max_charge_power) if direction == PowerDir.CHARGE else int(max_discharge_power)
            soc = self._get_float_state(batt["soc"])            
            if soc is None:
                return int(max_charge_power) if direction == PowerDir.CHARGE else int(max_discharge_power)
            if direction == PowerDir.CHARGE:
                if soc >= 98:
                    cap = charge_levels[0]
                elif soc >= 95:
                    cap = charge_levels[1]
                elif soc >= 91:
                    cap = charge_levels[2]
                elif soc >= 86:
                    cap = charge_levels[3]
                elif soc >= 80:
                    cap = charge_levels[4]
                else:
                    cap = int(max_charge_power)
                return min(cap, int(max_charge_power))
            else:
                if soc <= 13:
                    cap = discharge_levels[0]
                elif soc <= 15:
                    cap = discharge_levels[1]
                elif soc <= 19:
                    cap = discharge_levels[2]
                elif soc <= 25:
                    cap = discharge_levels[3]
                elif soc <= 30:
                    cap = discharge_levels[4]
                else:
                    cap = int(max_discharge_power)
                return min(cap, int(max_discharge_power))

        # Try increasing the number of batteries if needed to meet the requested power
        requested = abs_power
        curr_target = target_num_batteries
        # Build list of available battery ids according to current priority
        # Only include batteries that have a string `id` value; cast for typing
        available_ids: list[str] = [cast(str, b.get("id")) for b in self._battery_priority if isinstance(b, dict) and isinstance(b.get("id"), str)]
        while curr_target < len(available_ids):
            # Sum caps of top curr_target batteries
            top_ids: list[str] = available_ids[:curr_target]
            total_cap = sum(_cap_for_batt(bid) for bid in top_ids)
            if total_cap >= requested:
                break
            curr_target += 1

        # Ensure curr_target is not greater than allowed by available batteries
        curr_target = min(curr_target, len(available_ids))
        _LOGGER.debug(f"Adjusted target batteries considering per-battery caps: {curr_target}")
        return curr_target
    
    async def _check_power_thresholds(self, real_power: float) -> bool:
        """Check if power is below thresholds using a Schmitt-Trigger logic to prevent toggling."""        
        abs_power = abs(real_power)
        
        # Declare powerdirection (at 0 it keeps the last direction)
        if real_power > 0:
            direction = PowerDir.DISCHARGE
        elif real_power < 0:
            direction = PowerDir.CHARGE
        else:
            direction = self._last_power_direction
            
        try:
            min_surplus = float(self.config.get(CONF_MIN_SURPLUS, 50))
            min_cons = float(self.config.get(CONF_MIN_CONSUMPTION, 50))
            max_cycles = int(self.config.get(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, 10))
        except (ValueError, TypeError):
            min_surplus, min_cons, max_cycles = 50.0, 50.0, 10

        if direction == PowerDir.CHARGE:
            self._below_min_discharge_count = 0  # Reset counter for the other direction
            self._discharge_suspended = False    # Reset suspension state for the other direction
            if abs_power < min_surplus:
                self._below_min_charge_count += 1
            else:
                # HYSTERESE: Slowly decrease the counter instead of resetting immediately to 0
                self._below_min_charge_count = max(0, self._below_min_charge_count - 1)
            
            # Declare Max Counts times 2 to not increase to high
            self._below_min_charge_count = min(self._below_min_charge_count, 2*(max_cycles))
                
            # --- SCHMITT-TRIGGER (Zustands-Hysterese) ---
            if self._below_min_charge_count >= max_cycles:
                self._charge_suspended = True    # stop charging
            elif self._below_min_charge_count == 0:
                self._charge_suspended = False   # charging allowed again
                
            count = self._below_min_charge_count
            is_suspended = self._charge_suspended
            
        else: # DISCHARGE
            self._below_min_charge_count = 0  # Reset counter for the other direction
            self._charge_suspended = False    # Reset suspension state for the other direction
            if abs_power < min_cons:
                self._below_min_discharge_count += 1
            else:
                # HYSTERESE: Slowly decrease the counter instead of resetting immediately to 0
                self._below_min_discharge_count = max(0, self._below_min_discharge_count - 1)
            
            # Declare Max Counts times 2 to not increase to high
            self._below_min_discharge_count = min(self._below_min_discharge_count, 2*(max_cycles))
            
            # --- SCHMITT-TRIGGER (Zustands-Hysterese) ---
            if self._below_min_discharge_count >= max_cycles:
                self._discharge_suspended = True   # stop discharging
            elif self._below_min_discharge_count == 0:
                self._discharge_suspended = False  # discharging allowed again

            count = self._below_min_discharge_count
            is_suspended = self._discharge_suspended

        _LOGGER.debug(f"Threshold check: direction={direction.name}, power={abs_power:.0f}W, counter={count}/{max_cycles}")

        # Return whether the current direction is suspended due to being below thresholds for too long
        return is_suspended

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
        max_batt = len(self._batteries)
        if target_num_batteries > max_batt:
            target_num_batteries = max_batt

        requested_abs_power = abs(power)
        abs_power = requested_abs_power
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

# detect real battery to grid export by looking for negative grid import
# allow some slack for grid import, but not too much
# if too much just limit the requested discharge by the current grid export (new import)
        if self._last_power_direction == PowerDir.DISCHARGE:
            if self._last_grid_power_raw is not None:
                try:
                    grid_power = float(self._last_grid_power_raw)
                except (TypeError, ValueError):
                    grid_power = 0.0

                battery_powers: dict[str, float | None] = {
                    b["id"]: self._get_float_state(b["ac_power"]) for b in self._batteries
                }
                total_battery_power = sum(p for p in battery_powers.values() if p is not None)

                grid_import = max(0.0, grid_power)
                grid_export = max(0.0, -grid_power)

                export_slack_w = 100.0
                real_power = grid_power + total_battery_power
                allowed_discharge = max(0.0, real_power + export_slack_w)

                if grid_export > export_slack_w or abs_power > allowed_discharge:
                    capped = min(abs_power, allowed_discharge)
                    _LOGGER.debug(
                        "Grid export prevention active. Requested discharge=%sW, grid_import=%sW, grid_export=%sW, batt_total=%sW, real=%sW, slack=%sW -> capping to %sW",
                        round(abs_power, 0),
                        round(grid_import, 0),
                        round(grid_export, 0),
                        round(total_battery_power, 0),
                        round(real_power, 0),
                        round(export_slack_w, 0),
                        round(capped, 0),
                    )
                    abs_power = capped

        if abs_power != requested_abs_power:
            _LOGGER.debug(
                "Effective %s power after caps: requested=%sW -> effective=%sW",
                self._last_power_direction.name,
                round(requested_abs_power, 0),
                round(abs_power, 0),
            )

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
            # Try to filter out batteries that are at SoC limits. If any battery
            # is excluded due to reaching min/max SoC, immediately recalculate
            # the battery priority and retry distribution (up to a few attempts)
            # so the system can adapt within the same update cycle.
            max_attempts = 3
            for attempt in range(max_attempts):
                excluded_due_to_soc = False
                eligible: list[dict[str, Any]] = []
                for b in active_batteries:
                    soc = self._get_float_state(b["soc"])
                    if soc is None:
                        continue
                    if self._last_power_direction == PowerDir.CHARGE and soc >= max_soc:
                        _LOGGER.debug(
                            "Excluding battery %s from CHARGE: soc=%s >= max_soc=%s",
                            b["id"],
                            soc,
                            max_soc,
                        )
                        excluded_due_to_soc = True
                        continue
                    if self._last_power_direction == PowerDir.DISCHARGE and soc <= min_soc:
                        _LOGGER.debug(
                            "Excluding battery %s from DISCHARGE: soc=%s <= min_soc=%s",
                            b["id"],
                            soc,
                            min_soc,
                        )
                        excluded_due_to_soc = True
                        continue
                    eligible.append(b)

                active_batteries = eligible

                if not excluded_due_to_soc:
                    break

                # If any battery hit a limit, recalculate the overall priority and
                # rebuild the candidate list. This allows switching to the next
                # suitable battery immediately in the same update.
                _LOGGER.debug("Battery reached SoC limit; recalculating priority (attempt %s/%s)", attempt + 1, max_attempts)
                await self._calculate_battery_priority(self._last_power_direction)
                active_batteries = self._battery_priority[:target_num_batteries]

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

        # Determine per-battery caps based on SoC-level tables (configurable)
        # Charge levels: check high SoC ranges first (>=98, >=95, >=91, >=86, >=80), below -> use max_charge_power
        # Discharge levels: check low SoC ranges first (<=13, <=15, <=19, <=25, <=30), above -> use max_discharge_power
        charge_levels = [
            int(self.config.get(CONF_CHARGE_POWER_LEVEL_1, DEFAULT_CHARGE_POWER_LEVEL_1)),
            int(self.config.get(CONF_CHARGE_POWER_LEVEL_2, DEFAULT_CHARGE_POWER_LEVEL_2)),
            int(self.config.get(CONF_CHARGE_POWER_LEVEL_3, DEFAULT_CHARGE_POWER_LEVEL_3)),
            int(self.config.get(CONF_CHARGE_POWER_LEVEL_4, DEFAULT_CHARGE_POWER_LEVEL_4)),
            int(self.config.get(CONF_CHARGE_POWER_LEVEL_5, DEFAULT_CHARGE_POWER_LEVEL_5)),
        ]
        discharge_levels = [
            int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_1, DEFAULT_DISCHARGE_POWER_LEVEL_1)),
            int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_2, DEFAULT_DISCHARGE_POWER_LEVEL_2)),
            int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_3, DEFAULT_DISCHARGE_POWER_LEVEL_3)),
            int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_4, DEFAULT_DISCHARGE_POWER_LEVEL_4)),
            int(self.config.get(CONF_DISCHARGE_POWER_LEVEL_5, DEFAULT_DISCHARGE_POWER_LEVEL_5)),
        ]

        active_battery_ids = [b["id"] for b in active_batteries]

        per_batt_cap: dict[str, int] = {}
        for b_id in active_battery_ids:
            batt = next((b for b in self._batteries if b["id"] == b_id), None)
            soc = self._get_float_state(batt["soc"]) if batt else None
            if soc is None:
                # If SoC unknown, allow full configured max
                cap = int(max_charge_power) if self._last_power_direction == PowerDir.CHARGE else int(max_discharge_power)
            else:
                if self._last_power_direction == PowerDir.CHARGE:
                    if soc >= 98:
                        cap = charge_levels[0]
                    elif soc >= 95:
                        cap = charge_levels[1]
                    elif soc >= 91:
                        cap = charge_levels[2]
                    elif soc >= 86:
                        cap = charge_levels[3]
                    elif soc >= 80:
                        cap = charge_levels[4]
                    else:
                        cap = int(max_charge_power)
                    cap = min(cap, int(max_charge_power))
                else:
                    # Discharge
                    if soc <= 13:
                        cap = discharge_levels[0]
                    elif soc <= 15:
                        cap = discharge_levels[1]
                    elif soc <= 19:
                        cap = discharge_levels[2]
                    elif soc <= 25:
                        cap = discharge_levels[3]
                    elif soc <= 30:
                        cap = discharge_levels[4]
                    else:
                        cap = int(max_discharge_power)
                    cap = min(cap, int(max_discharge_power))
            per_batt_cap[b_id] = max(0, int(cap))

        # Allocate requested power among active batteries respecting per-battery caps using iterative water-filling
        remaining = int(round(abs_power))
        remaining_caps = dict(per_batt_cap)
        allocations: dict[str, int] = {b: 0 for b in active_battery_ids}

        while remaining > 0 and any(c > 0 for c in remaining_caps.values()):
            # distribute evenly among batteries that still have cap
            avail = [b for b, c in remaining_caps.items() if c > 0]
            if not avail:
                break
            share = max(1, remaining // len(avail))
            progress = False
            for b in avail:
                give = min(share, remaining_caps[b], remaining)
                if give <= 0:
                    continue
                allocations[b] += give
                remaining_caps[b] -= give
                remaining -= give
                progress = True
            if not progress:
                break

        _LOGGER.debug(
            "Distributing %sW (%s requested) to %s batteries: %s with allocations=%s",
            round(abs_power, 0),
            round(requested_abs_power, 0),
            len(active_battery_ids),
            active_battery_ids,
            allocations,
        )

        for batt in self._batteries:
            batt_id = batt["id"]
            if batt_id in allocations and allocations[batt_id] > 0:
                await self._set_battery_power(batt, allocations[batt_id], self._last_power_direction)
            else:
                await self._set_battery_power(batt, 0, 0)

    async def _set_battery_power(self, batt: dict, power: int, direction: int):
        """Set the charge or discharge power for a single battery."""
        charge_entity = batt["charge_power"]
        discharge_entity = batt["discharge_power"]
        force_mode = batt["force_mode"]
        modbus_control_mode = batt["rs485_mode"]
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
                    "stop",
                    {"entity_id": force_mode, "option": "stop"},
                    blocking=True,
                )

            # Add a small delay to prevent overwhelming the device APIs
            await asyncio.sleep(0.1)
        except Exception as e:
            _LOGGER.error(f"Failed to set power for {batt['id']}: {e}")

    async def _set_all_batteries_to_zero(self):
        """Set all configured batteries power to 0."""
        _LOGGER.debug("Setting all batteries to 0W.")
        tasks = [self._set_battery_power(batt, 0, 0) for batt in self._batteries]
        if not tasks:
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                _LOGGER.debug("Ignored error while setting batteries to 0W: %s", res)

    async def _disable_modbus_control_mode(self, target_num_batteries: int = 1):
        """Disable Modbus RS485 control mode based on power stages and battery priority with Make-Before-Break logic.
        1. Identifies batteries that need to be ADDED to automatic mode.
        2. Identifies batteries that need to be REMOVED from automatic mode.
        3. Activates new batteries first, waits 15s, then deactivates old ones.
        """


        # Aktuelle Prioritätsliste IDs
        target_ids = [b['id'] for b in self._battery_priority[:target_num_batteries]]

        # 1. Bestimme, welche Batterien aktuell im Automatik-Modus sind (Modbus Switch OFF)
        current_auto_ids = []
        for batt in self._batteries:
            state = self.hass.states.get(batt["rs485_mode"])
            if state and state.state == "off":
                current_auto_ids.append(batt["id"])

        # Batterien, die NEU in den Automatik-Modus sollen
        to_activate_auto = [bid for bid in target_ids if bid not in current_auto_ids]
        # Batterien, die aus dem Automatik-Modus RAUS sollen (zurück auf Manual/Forcible)
        to_deactivate_auto = [bid for bid in current_auto_ids if bid not in target_ids]


        # --- SCHRITT 1: Neue Batterien zuerst aktivieren ---
        if to_activate_auto:
            _LOGGER.debug("CT-Mode: Activating additional batteries for automatic mode: %s", to_activate_auto)
            for batt_id in to_activate_auto:
                batt = next((b for b in self._batteries if b["id"] == batt_id), None)
                if batt:
                    await self.hass.services.async_call("switch", "turn_off", {"entity_id": batt["rs485_mode"]}, blocking=True)
            # Wenn wir Batterien hinzugefügt haben, warten wir 10 Sekunden, bevor wir andere abschalten
            if to_deactivate_auto:
                _LOGGER.debug("CT-Mode: Waiting 10s for power stabilization before deactivating old batteries...")
                await asyncio.sleep(15)

        # --- SCHRITT 2: Alte Batterien deaktivieren (auf Manual/Forcible zurücksetzen) ---
        if to_deactivate_auto:
            _LOGGER.debug("CT-Mode: Returning batteries to manual/forcible mode: %s", to_deactivate_auto)
            for batt_id in to_deactivate_auto:
                batt = next((b for b in self._batteries if b["id"] == batt_id), None)
                if batt:
                    await self.hass.services.async_call("switch", "turn_on", {"entity_id": batt["rs485_mode"]}, blocking=True)
                    await self._set_battery_power(batt, 0, 0)

        _LOGGER.debug(f"CT-Mode distribution finished. Active in Auto: {target_ids}")

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
