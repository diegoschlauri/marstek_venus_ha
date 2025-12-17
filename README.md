# Home Assistant - Intelligente Batteriesteuerung für Marstek Venus E

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

This is a custom Home Assistant integration for intelligent control of up to three separate battery storage systems. It was originally designed for Marstek Venus E systems, but it can be used with **any battery system** that can be controlled via corresponding entities in Home Assistant.

The integration does not control all batteries at the same time. Instead, it enables them in power levels to maximize efficiency and optimize self-consumption. It includes dynamic battery prioritization based on state of charge (SoC) and an advanced, optional logic for interacting with a wallbox/EV charger.

This is a fork of https://github.com/diegoschlauri/marstek_venus_ha with added PID control logic and caching of the HA service calls to avoid too many calls to the batteries. I also translated the README to English to make it easier for non-German speakers to understand.
Parts of the writing and coding was done with the help of AI tools.

## Key features

* **Flexible number of batteries**: Control one, two, or three batteries.
* **Power level switching**: Uses one, two, or three batteries depending on demand or surplus.
* **Dynamic prioritization**: Smart prioritization. When charging, the emptiest battery is preferred; when discharging, the fullest.
* **Grid power smoothing**: Prevents rapid switching by averaging grid power over a configurable time window.
* **Optional wallbox integration**: Smart pausing of battery charging during high PV surplus. Charging resumes when the car is full or charging at maximum power to avoid wasting energy.
* **Configurable limits**: Set upper and lower SoC limits to protect battery lifespan.
* **Minimum charge/discharge power**: Configurable thresholds that define from which surplus/consumption the batteries start charging/discharging to improve efficiency.
* **Easy configuration**: Fully configurable via the Home Assistant UI config flow.

---

## Important prerequisite

This integration does not control the batteries directly via a vendor-specific API. Instead, **you must already have entities in Home Assistant for each battery** in order to:

1.  Read the **state of charge (SoC)** (e.g. `sensor.marstek_l1_battery_soc`).
2.  Read the **current charge/discharge power** (e.g. `sensor.marstek_l1_ac_power`). A positive value means discharging, a negative value means charging.
3.  Control the **charge power** (e.g. `number.marstek_l1_modbus_set_forcible_charge_power`) (the ID must be adjusted manually if multiple batteries are used via the Modbus integration).
4.  Control the **discharge power** (e.g. `number.marstek_l1_modbus_set_forcible_discharge_power`) (the ID must be adjusted manually if multiple batteries are used via the Modbus integration).
5.  The select for **Force Mode** to control current direction (e.g. `select.marstek_l1_modbus_force_mode`) (the ID must be adjusted manually if multiple batteries are used via the Modbus integration).
6.  The switch to enable **RS485 Mode** (e.g. `switch.marstek_l1_modbus_rs485_control_mode`) (the ID must be adjusted manually if multiple batteries are used via the Modbus integration).


During configuration you provide the **base entity name** for each battery (e.g. `marstek_l1`). The integration derives the names of the required entities by expecting the suffixes `_battery_soc`, `_ac_power`, `_modbus_set_forcible_charge_power`, `_modbus_set_forcible_discharge_power`, `_modbus_force_mode`, and `_modbus_rs485_control_mode`.

Enable the Local API port 3000 on the batteries via https://rweijnen.github.io/marstek-venus-monitor/latest/

As a basis for integrating a Marstek energy storage system, the Modbus integration from https://github.com/ViperRNMC/marstek_venus_modbus was used.
Depending on the use case it may be useful to reduce the scan intervals (in the settings of the Marstek Venus Modbus integration).
If multiple batteries are used, this can be done either with multiple Modbus adapters and separate IP addresses.

**Example:**
If you specify `marstek_l1` as the entity base for the first battery, the integration must be able to find the following entities:
* `sensor.marstek_l1_battery_soc`
* `sensor.marstek_l1_ac_power` **(Wichtig für die Wallbox-Logik)**
* `number.marstek_l1_modbus_set_forcible_charge_power`
* `number.marstek_l1_modbus_set_forcible_discharge_power`
* `select.marstek_l1_modbus_force_mode`
* `switch.marstek_l1_modbus_rs485_control_mode`


Make sure these entities exist and are working before setting up the integration.

---

## Installation

### Via HACS (recommended)

1.  Add this GitHub repository to HACS as a "Custom repository".
2.  Search for "Intelligent Battery Control" and install the integration.
3.  Restart Home Assistant.

### Manual installation

1.  Download the folder `custom_components/marstek_intelligent_battery` from this repository.
2.  Copy it into the `custom_components` directory of your Home Assistant installation.
3.  Restart Home Assistant.

---

## Configuration

After installation you can add the integration via the Home Assistant UI:

1.  Go to **Settings > Devices & Services**.
2.  Click **Add integration** and search for "Marstek Intelligent Battery Control".
3.  Follow the configuration dialog. Fields for the wallbox or for batteries 2 and 3 can be left empty to disable the corresponding functionality.

### Configuration parameters

| Parameter | Beschreibung | Beispiel |
| --- | --- | --- |
| **CT Mode** | When CT mode is enabled, the power regulation by the Python script is disabled. Only the wallbox logic remains active. If there is enough surplus (> `wallbox_max_surplus`) and a car is present, the controller takes over battery control. Otherwise, control runs via the default Marstek logic. Only enable this parameter if a CT is also configured in the Marstek app. The update interval automatically changes to 10s in CT mode. The power level logic is also active in CT mode. The RS485 parameter controls how many batteries are enabled. | `False` |
| **Grid connection power sensor ID** | The sensor ID that measures current grid import (+) or export (-) in watts. | `sensor.power_meter_power` |
| **Power smoothing in seconds** | Time window (seconds) used to compute the average grid power. If set to 0, no smoothing is applied and the latest value is used. | `0` |
| **Minimum surplus** | Minimum power surplus in watts required to start charging. | `200` |
| **Minimum import** | Minimum consumption in watts required to start discharging. | `200` |
| **First battery entity** | Base name of the entities for the first battery. | `marstek_l1` |
| **Second battery entity (optional)** | Base name for the second battery. Leave empty if not available. | `marstek_l2` |
| **Third battery entity (optional)** | Base name for the third battery. Leave empty if not available. | `marstek_l3` |
| **Lower discharge limit of the batteries (%)** | Batteries will no longer discharge once their SoC reaches this value. | `10` |
| **Upper charge limit of the batteries (%)** | Batteries will no longer charge once their SoC reaches this value. | `100` |
| **Max Discharge Power (W)** | Maximum discharge power sent to a battery. | `2500` |
| **Max Charge Power (W)** | Maximum charge power sent to a battery. | `2500` |
| **First discharge power level (W)** | Grid import at which a second battery is enabled. | `600` |
| **Second discharge power level (W)** | Grid import at which a third battery is enabled. | `1200` |
| **First charge power level (W)** | Grid export at which a second battery is enabled. | `2000` |
| **Second charge power level (W)** | Grid export at which a third battery is enabled. | `4000` |
| **Power level offset (W)** | Offset used to switch power levels with less toggling. | `100` |
| **Priority evaluation interval (minutes)** | Interval at which battery priorities are re-evaluated. | `15` |
| **Wallbox power sensor ID (optional)**| Sensor that measures wallbox charging power. | `sensor.wallbox_power` |
| **Wallbox maximum surplus (W) (optional)**| If PV surplus exceeds this value, battery charging is paused. | `1500` |
| **Wallbox sensor for plugged-in cable (optional)**| A binary sensor (`on`/`off`) that indicates whether a charging cable is connected. | `binary_sensor.wallbox_cable_plugged_in` |
| **Wallbox power fluctuation (W) for enabling battery charging (optional)**| Tolerance for wallbox power fluctuations. If wallbox power has not increased by more than this value over the last X seconds, battery charging is allowed again. | `200` |
| **Wallbox update time for enabling battery charging in seconds (optional)**| Number of seconds until batteries are released for charging again if the power fluctuation threshold is not exceeded. | `300` |
| **Wallbox start time in seconds (optional)**| Number of seconds to wait before releasing the batteries again. This is used when a car is plugged in but does not start charging. This value is also relevant for phase switching of the wallbox. | `120` |
| **Wallbox retry in minutes (optional)**| If a wallbox session ends and the cable remains plugged in, after this number of minutes and with sufficient surplus (> wallbox surplus parameter), the batteries are paused for the wallbox start time to allow charging. | `60` |
| **Coordinator update interval**| Number of seconds between executions of the logic update cycle. | `3` |
| **Service call cache time (seconds)** | Prevents sending the same Home Assistant service call (same entity + same value) too frequently. If set to a value > 0, identical calls are skipped for that many seconds. If set to `0`, identical calls are skipped indefinitely (until the requested value changes). | `30` |
| **PID control enabled** | Enables PID-based power control (only active when **CT Mode** is `False`). When enabled, the integration continuously adjusts battery charge/discharge power to drive the *real grid power* towards `0W` (minimizing import/export). | `False` |
| **PID Kp** | Proportional gain. Higher values react stronger to the current error (difference to the target of `0W`). Too high can cause oscillation. | `0.6` |
| **PID Ki** | Integral gain. Eliminates long-term steady-state error by integrating error over time. Too high can cause slow oscillations (“windup”). | `0.02` |
| **PID Kd** | Derivative gain. Reacts to how fast the error changes and can dampen oscillations. Too high can amplify noise from sensors. | `0.0` |

---

## PID control (what it is and how the parameters work)

PID control is a feedback control method. In this integration it is used to continuously adjust the battery charge/discharge power so that the measured *real grid power* approaches a target value of `0W`.

* When you have **PV surplus** (grid export), the controller will increase charging power.
* When you have **grid import**, the controller will increase discharging power.

The three gains influence how the controller reacts:

1. **P (Kp)** reacts to the current error.
2. **I (Ki)** reacts to the accumulated error over time (removes steady-state offset).
3. **D (Kd)** reacts to the rate of change of the error (damping).

Practical tuning guidance:

* Start with `Kd = 0`.
* Increase `Kp` until the response is fast but not oscillating.
* Add a small `Ki` to reduce residual import/export (steady-state error).
* If you see oscillations, reduce `Kp` and/or `Ki`, or consider adding a small `Kd`.

## How it works (in detail)

### Priority calculation

* **When discharging (grid import)**: The battery with the **highest** SoC has the highest priority.
* **When charging (grid export)**: The battery with the **lowest** SoC has the highest priority.
* A battery is removed from the priority list when it reaches its upper/lower SoC limit.

### Power control

The absolute grid power (`abs(power)`) determines the number of active batteries:
1.  **`Power <= level 1`**: Only the highest-priority battery is used.
2.  **`level 1 < Power <= level 2`**: Power is distributed evenly across the two highest-priority batteries.
3.  **`Power > level 2`**: Power is distributed evenly across all available batteries.

### Wallbox logic (only active when all wallbox parameters are configured)

* **Discharge protection**: As soon as the wallbox draws power (`Power > 10W`), discharging of **all** batteries is stopped immediately.
* **Charging priority for the car**: If the **real PV surplus** (grid export + current battery charging power) exceeds the configured threshold, charging the home batteries is paused to prioritize the car.
* **Intelligent charge resume**: Battery charging is released again when wallbox charging power stagnates for X seconds (e.g. because the car is full or has reached its maximum charging power). Discharging remains blocked as long as the wallbox is charging.
