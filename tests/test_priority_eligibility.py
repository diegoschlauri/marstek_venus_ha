import asyncio
from datetime import datetime, timedelta

from homeassistant.core import State

from custom_components.marstek_venus_ha.coordinator import (
    ELIGIBILITY_RECALC_MIN_SECONDS,
    MarstekCoordinator,
    PowerDir,
)
from custom_components.marstek_venus_ha.const import (
    CONF_MAX_SOC,
    CONF_MIN_SOC,
    CONF_PRIORITY_INTERVAL,
)


class _States(dict):
    def get(self, entity_id):
        return dict.get(self, entity_id)


class _Hass:
    def __init__(self):
        self.states = _States()


def _mk_coordinator(socs: list[float], *, min_soc=14, priority_interval=20):
    c = MarstekCoordinator.__new__(MarstekCoordinator)
    c.hass = _Hass()
    c.config = {
        CONF_MIN_SOC: min_soc,
        CONF_MAX_SOC: 100,
        CONF_PRIORITY_INTERVAL: priority_interval,
    }
    c._batteries = []
    for i, soc in enumerate(socs, start=1):
        c._batteries.append(
            {"id": f"b{i}", "soc": f"sensor.soc_{i}", "max_soc_entity": f"number.max_soc_{i}"}
        )
        c.hass.states[f"sensor.soc_{i}"] = State(str(soc))
        c.hass.states[f"number.max_soc_{i}"] = State("100")
    c._allow_charging = True
    c._allow_discharging = True
    c._battery_priority = []
    c._last_priority_update = datetime.min
    c._last_eligibility_recalc = datetime.min
    c._last_power_direction = PowerDir.DISCHARGE
    c._priority_list_power_direction = None
    c._power_direction_change_start = None
    return c


def _set_soc(c, index: int, soc) -> None:
    c.hass.states[f"sensor.soc_{index}"] = State(str(soc))


def _ids(c) -> list[str]:
    return [b["id"] for b in c._battery_priority]


def _run(c) -> None:
    asyncio.run(c._update_battery_priority_if_needed())


def test_battery_dropping_below_min_soc_is_removed_before_interval_elapses():
    c = _mk_coordinator([50, 40, 30])
    _run(c)
    assert _ids(c) == ["b1", "b2", "b3"]

    # b1 drops below min SoC shortly after the list was built
    _set_soc(c, 1, 13)
    _run(c)

    assert _ids(c) == ["b2", "b3"]


def test_battery_recharged_above_min_soc_is_readded():
    c = _mk_coordinator([13, 40, 30])
    _run(c)
    assert _ids(c) == ["b2", "b3"]

    # firmware recharged b1 above min SoC
    _set_soc(c, 1, 15)
    _run(c)

    assert _ids(c) == ["b2", "b3", "b1"]


def test_no_recalculation_while_usable_set_is_unchanged():
    c = _mk_coordinator([50, 40, 30])
    _run(c)
    first_update = c._last_priority_update

    # SoC values change, but every battery is still above min SoC:
    # order is only re-evaluated when the priority interval elapses
    _set_soc(c, 1, 20)
    _run(c)

    assert c._last_priority_update == first_update
    assert _ids(c) == ["b1", "b2", "b3"]


def test_eligibility_recalculation_is_rate_limited():
    c = _mk_coordinator([50, 40, 30])
    _run(c)

    _set_soc(c, 1, 13)
    _run(c)
    assert _ids(c) == ["b2", "b3"]

    # flapping around the limit within the rate limit window is ignored
    _set_soc(c, 1, 14)
    _run(c)
    assert _ids(c) == ["b2", "b3"]

    # after the window the change is picked up (discharge order: highest SoC first)
    c._last_eligibility_recalc -= timedelta(seconds=ELIGIBILITY_RECALC_MIN_SECONDS)
    _run(c)
    assert _ids(c) == ["b2", "b3", "b1"]


def test_unavailable_soc_is_handled_like_in_priority_calculation():
    c = _mk_coordinator([50, 40, 30])
    _run(c)

    # b3 becomes unavailable: _calculate_battery_priority() skips batteries
    # without SoC, so the eligibility check does the same and rebuilds the list
    _set_soc(c, 3, "unavailable")
    _run(c)
    assert _ids(c) == ["b1", "b2"]

    # while it stays unavailable nothing else changes
    first_update = c._last_priority_update
    c._last_eligibility_recalc = datetime.min
    _run(c)
    assert c._last_priority_update == first_update


def test_charge_direction_respects_battery_max_soc():
    c = _mk_coordinator([50, 99, 30])
    c._last_power_direction = PowerDir.CHARGE
    _run(c)
    assert _ids(c) == ["b3", "b1", "b2"]

    # b2 reaches its max SoC
    c.hass.states["number.max_soc_2"] = State("98")
    _run(c)

    assert _ids(c) == ["b3", "b1"]


def test_no_eligibility_check_during_direction_change():
    c = _mk_coordinator([50, 40, 30])
    _run(c)
    first_update = c._last_priority_update

    # direction just flipped (not yet sustained): the eligibility check must not
    # rebuild the list for the new direction prematurely
    c._last_power_direction = PowerDir.CHARGE
    _run(c)

    assert c._last_priority_update == first_update
    assert _ids(c) == ["b1", "b2", "b3"]
