import asyncio

from custom_components.marstek_venus_ha.coordinator import (
    MarstekCoordinator,
    PowerDir,
)
from custom_components.marstek_venus_ha.const import (
    CONF_MAX_CHARGE_POWER,
    CONF_MAX_DISCHARGE_POWER,
    CONF_MIN_CONSUMPTION,
    CONF_MIN_SURPLUS,
    CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING,
    CONF_POWER_STAGE_CHARGE_1,
    CONF_POWER_STAGE_CHARGE_2,
    CONF_POWER_STAGE_DISCHARGE_1,
    CONF_POWER_STAGE_DISCHARGE_2,
    CONF_POWER_STAGE_OFFSET,
)


def _mk_coordinator_for_control_logic(*, config: dict, battery_entities: list[str]):
    c = MarstekCoordinator.__new__(MarstekCoordinator)
    c.config = dict(config)
    c._battery_entities = list(battery_entities)
    c._battery_priority = [{"id": b, "soc": 50.0} for b in battery_entities]
    c._below_min_charge_count = 0
    c._below_min_discharge_count = 0
    c._below_min_cycles_to_zero = config.get(CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING, 10)

    async def _noop_async(*args, **kwargs):
        return None

    c._set_all_batteries_to_zero = _noop_async
    c._set_battery_power = _noop_async
    c._get_pv_power = lambda: None
    return c


def test_get_desired_number_of_batteries_charge_upshift_from_single():
    c = _mk_coordinator_for_control_logic(
        config={
            CONF_POWER_STAGE_OFFSET: 100,
            CONF_POWER_STAGE_CHARGE_1: 1800,
            CONF_POWER_STAGE_CHARGE_2: 3600,
        },
        battery_entities=["b1", "b2", "b3"],
    )
    c._last_power_direction = PowerDir.CHARGE

    # No batteries currently active
    c._get_float_state = lambda entity_id: 0.0

    assert c._get_desired_number_of_batteries(1700) == 1
    assert c._get_desired_number_of_batteries(2000) == 2
    assert c._get_desired_number_of_batteries(3800) == 3


def test_get_desired_number_of_batteries_discharge_hysteresis_hold_two():
    c = _mk_coordinator_for_control_logic(
        config={
            CONF_POWER_STAGE_OFFSET: 100,
            CONF_POWER_STAGE_DISCHARGE_1: 1400,
            CONF_POWER_STAGE_DISCHARGE_2: 2000,
        },
        battery_entities=["b1", "b2", "b3"],
    )
    c._last_power_direction = PowerDir.DISCHARGE

    # Two batteries currently active (>
    def _float_state(entity_id: str):
        if entity_id in ("sensor.b1_ac_power", "sensor.b2_ac_power"):
            return 50.0
        return 0.0

    c._get_float_state = _float_state

    # With two active batteries, stay at 2 within hysteresis band:
    # stage1-offset=1300 and stage2+offset=2100
    assert c._get_desired_number_of_batteries(1500) == 2
    assert c._get_desired_number_of_batteries(2050) == 2

    # Drop below stage1-offset -> downshift to 1
    assert c._get_desired_number_of_batteries(1200) == 1

    # Rise above stage2+offset -> upshift to 3
    assert c._get_desired_number_of_batteries(2200) == 3


def test_distribute_power_caps_per_battery_to_configured_max_charge_power():
    calls: list[tuple[str, int, int]] = []

    c = _mk_coordinator_for_control_logic(
        config={
            CONF_MAX_CHARGE_POWER: 2500,
            CONF_MAX_DISCHARGE_POWER: 2500,
            CONF_MIN_SURPLUS: 0,
            CONF_MIN_CONSUMPTION: 0,
            CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING: 10,
        },
        battery_entities=["b1", "b2"],
    )
    c._battery_priority = [{"id": "b1", "soc": 50.0}, {"id": "b2", "soc": 40.0}]
    c._last_power_direction = PowerDir.CHARGE

    async def _set_battery_power(base_entity_id: str, power: int, direction: int):
        calls.append((base_entity_id, power, direction))

    c._set_battery_power = _set_battery_power

    # abs_power=6000, 2 active batteries => 3000 each, but cap to max_charge_power=2500
    asyncio.run(c._distribute_power(power=6000.0, target_num_batteries=2))

    assert ("b1", 2500, PowerDir.CHARGE) in calls
    assert ("b2", 2500, PowerDir.CHARGE) in calls


def test_distribute_power_below_min_threshold_only_zeros_after_n_cycles():
    zero_calls: list[object] = []
    set_calls: list[tuple[str, int, int]] = []

    c = _mk_coordinator_for_control_logic(
        config={
            CONF_MAX_CHARGE_POWER: 2500,
            CONF_MAX_DISCHARGE_POWER: 2500,
            CONF_MIN_SURPLUS: 200,
            CONF_MIN_CONSUMPTION: 200,
            CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING: 10,
        },
        battery_entities=["b1"],
    )
    c._battery_priority = [{"id": "b1", "soc": 50.0}]
    c._last_power_direction = PowerDir.CHARGE

    async def _set_all_batteries_to_zero():
        zero_calls.append(object())

    async def _set_battery_power(base_entity_id: str, power: int, direction: int):
        set_calls.append((base_entity_id, power, direction))

    c._set_all_batteries_to_zero = _set_all_batteries_to_zero
    c._set_battery_power = _set_battery_power

    # Below threshold cycles should not trigger immediate zeroing
    for _ in range(c._below_min_cycles_to_zero - 1):
        asyncio.run(c._distribute_power(power=100.0, target_num_batteries=1))

    assert len(zero_calls) == 0
    assert c._below_min_charge_count == c._below_min_cycles_to_zero - 1

    # Next cycle should trigger zero and reset counter
    set_calls.clear()
    asyncio.run(c._distribute_power(power=100.0, target_num_batteries=1))

    assert len(zero_calls) == 1
    assert c._below_min_charge_count == 0
    assert set_calls == []


def test_distribute_power_resets_below_min_counters_when_above_threshold():
    c = _mk_coordinator_for_control_logic(
        config={
            CONF_MAX_CHARGE_POWER: 2500,
            CONF_MAX_DISCHARGE_POWER: 2500,
            CONF_MIN_SURPLUS: 200,
            CONF_MIN_CONSUMPTION: 200,
            CONF_MAX_LIMIT_BREACHES_BEFORE_ZEROING: 10,
        },
        battery_entities=["b1"],
    )
    c._battery_priority = [{"id": "b1", "soc": 50.0}]
    c._last_power_direction = PowerDir.CHARGE

    async def _noop_async(*args, **kwargs):
        return None

    c._set_all_batteries_to_zero = _noop_async
    c._set_battery_power = _noop_async

    # Build up some below-min count
    for _ in range(3):
        asyncio.run(c._distribute_power(power=100.0, target_num_batteries=1))

    assert c._below_min_charge_count == 3

    # Above threshold should reset
    asyncio.run(c._distribute_power(power=300.0, target_num_batteries=1))

    assert c._below_min_charge_count == 0
    assert c._below_min_discharge_count == 0
