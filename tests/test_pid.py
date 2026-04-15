from custom_components.marstek_venus_ha.coordinator import MarstekCoordinator


def _mk_coordinator(*, kp=0.0, ki=1.0, kd=0.0, integral=0.0):
    c = MarstekCoordinator.__new__(MarstekCoordinator)
    c._pid_kp = kp
    c._pid_ki = ki
    c._pid_kd = kd
    c._pid_integral = integral
    return c


def test_pid_apply_anti_windup_ki_zero_clamps_output():
    c = _mk_coordinator(kp=1.0, ki=0.0, kd=0.0)

    # output = kp*error; clamp to sat_pos
    out = c._pid_apply_anti_windup(
        error=100.0,
        dt=1.0,
        derivative=0.0,
        sat_pos=10.0,
        sat_neg=10.0,
    )

    assert out == 10.0


def test_pid_apply_anti_windup_dt_zero_does_not_integrate():
    c = _mk_coordinator(kp=0.0, ki=1.0, kd=0.0, integral=5.0)

    out = c._pid_apply_anti_windup(
        error=3.0,
        dt=0.0,
        derivative=0.0,
        sat_pos=1000.0,
        sat_neg=1000.0,
    )

    assert c._pid_integral == 5.0
    assert out == 5.0


def test_pid_apply_anti_windup_unsaturated_updates_integral_and_output():
    c = _mk_coordinator(kp=0.0, ki=1.0, kd=0.0, integral=0.0)

    out = c._pid_apply_anti_windup(
        error=2.0,
        dt=3.0,
        derivative=0.0,
        sat_pos=1000.0,
        sat_neg=1000.0,
    )

    # I += error*dt
    assert c._pid_integral == 6.0
    # u = ki*I
    assert out == 6.0


def test_pid_apply_anti_windup_saturated_positive_back_calculates_integral():
    c = _mk_coordinator(kp=0.0, ki=1.0, kd=0.0, integral=0.0)

    out = c._pid_apply_anti_windup(
        error=100.0,
        dt=1.0,
        derivative=0.0,
        sat_pos=10.0,
        sat_neg=10.0,
    )

    assert out == 10.0
    # Tracking anti-windup should pull I such that ki*I == sat_pos
    assert c._pid_integral == 10.0


def test_pid_apply_anti_windup_saturated_negative_back_calculates_integral():
    c = _mk_coordinator(kp=0.0, ki=2.0, kd=0.0, integral=0.0)

    out = c._pid_apply_anti_windup(
        error=-100.0,
        dt=1.0,
        derivative=0.0,
        sat_pos=10.0,
        sat_neg=10.0,
    )

    assert out == -10.0
    # With ki=2, we expect I to be pulled so that 2*I == -10
    assert c._pid_integral == -5.0
