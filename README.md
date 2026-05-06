# Home Assistant - Intelligent Battery Control for Marstek Venus E

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support%20my%20work-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/huudl)

This is a custom Home Assistant integration for intelligent control of multiple separate battery storage systems. It was originally designed for Marstek Venus E systems, but it can be used with **any battery system** that can be controlled via corresponding entities in Home Assistant.

The integration does not control all batteries at the same time. Instead, it enables them in power levels to maximize efficiency and optimize self-consumption. It includes dynamic battery prioritization based on state of charge (SoC) and an advanced, optional logic for interacting with a wallbox/EV charger.

## Key features

* **Flexible number of batteries**: Control any number of batteries (fully scalable via the UI).
* **Dynamic Power level switching**: Uses one, two, or more batteries depending on demand or surplus. Configurable thresholds determine when to add or remove a battery from the active pool.
* **Dynamic prioritization**: Smart prioritization. When charging, the emptiest battery is preferred; when discharging, the fullest.
* **Explicit Entity Selection**: No strict naming conventions required. Select the exact entities for each battery directly via Home Assistant dropdown menus.
* **Grid power smoothing**: Prevents rapid switching by averaging grid power over a configurable time window.
* **Optional wallbox integration**: Smart pausing of battery charging during high PV surplus. Charging resumes when the car is full or charging at maximum power to avoid wasting energy.
* **Configurable limits**: Set upper and lower SoC limits to protect battery lifespan.
* **Minimum charge/discharge power**: Configurable thresholds that define from which surplus/consumption the batteries start charging/discharging to improve efficiency.
* **Easy configuration**: Fully configurable via the Home Assistant UI config flow.
* **PID control**: Optional PID control for precise power regulation.
* **Service call caching**: Prevents sending the same Home Assistant service call (same entity + same value) too frequently. 
* **Event-driven control loop**: The coordinator runs on relevant sensor updates (instead of a fixed polling loop) and is throttled by a configurable minimum interval.
* **PV-based charge limiting (optional)**: An optional PV power sensor can be configured to cap commanded charging power to current PV production to avoid charging from the grid due to short sensor glitches.

---

## Support

If you find this integration helpful and want to support its further development, I'd highly appreciate a coffee! ☕

<a href="https://www.buymeacoffee.com/huudl" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>


## Important prerequisite

This integration does not control the batteries directly via a vendor-specific API. Instead, **you must already have entities in Home Assistant for each battery** in order to:

1. Read the **state of charge (SoC)** (e.g., `sensor.marstek_l1_battery_soc`).
2. Read the **current AC power** (e.g., `sensor.marstek_l1_ac_power`). A positive value means discharging, a negative value means charging.
3. Control the **charge power value** (e.g., `number.marstek_l1_modbus_set_forcible_charge_power`).
4. Control the **discharge power value** (e.g., `number.marstek_l1_modbus_set_forcible_discharge_power`).
5. Set the **Force Mode** to control current direction (e.g., `select.marstek_l1_modbus_force_mode`).
6. Toggle the **RS485 Control Mode** (e.g., `switch.marstek_l1_modbus_rs485_control_mode`).

During configuration, you will first choose **how many batteries** you want to control. In the next step, the UI will present you with dropdown menus to **explicitly select these 6 entities for every single battery**. Because you select them manually, there is no strict naming convention you need to follow.

As a basis for integrating a Marstek energy storage system, the Modbus integration from https://github.com/ViperRNMC/marstek_venus_modbus was used. Depending on the use case it may be useful to reduce the scan intervals in the Modbus integration settings.

---

## Installation

### Via HACS (recommended)

1. Add this GitHub repository to HACS as a "Custom repository".
2. Search for "Marstek Venus HA" and install the integration.
3. Restart Home Assistant.

### Manual installation

1. Download the folder `custom_components/marstek_venus_ha` from this repository.
2. Copy it into the `custom_components` directory of your Home Assistant installation.
3. Restart Home Assistant.

---

## Configuration

After installation you can add the integration via the Home Assistant UI:

1. Go to **Settings > Devices & Services**.
2. Click **Add integration** and search for "Marstek Venus HA".
3. Follow the configuration dialog. Fields for the wallbox or optional sensors can be left empty to disable the corresponding functionality.

### Configuration parameters

| Parameter | Description | Example |
| :--- | :--- | :--- |
| **Number of batteries** | Choose how many battery systems you want to control. | `6` |
| **CT Mode** | When CT mode is enabled, power regulation by the script is disabled and relies on the default Marstek logic. Only the wallbox logic remains active to override the batteries when the car is charging. | `False` |
| **Grid power sensor** | The sensor ID that measures current grid import (+) or export (-) in watts. | `sensor.power_meter_power` |
| **PV power sensor (optional)** | The sensor ID that measures current PV production power in watts. Used to cap battery charging power to avoid grid import glitches. | `sensor.pv_power` |
| **Smoothing window** | Time window (seconds) used to compute the average grid power. Set to 0 to disable smoothing. | `0` |
| **Minimum surplus** | Minimum power surplus in watts required to start charging. | `200` |
| **Minimum consumption** | Minimum consumption in watts required to start discharging. | `200` |
| **Max. limit breaches** | Max consecutive cycles below minimum limits before setting batteries to 0W. | `10` |
| **Battery X: [Entity Type]** | Dropdown fields to select the specific AC Power, SOC, Charge, Discharge, Force Mode, and RS485 entities for each battery. | *(Selected via UI)* |
| **Minimum state of charge (%)** | Batteries will no longer discharge once their SoC reaches this value. | `10` |
| **Maximum state of charge (%)** | Batteries will no longer charge once their SoC reaches this value. | `100` |
| **Max Discharge Power (W)** | Maximum discharge power sent to a single battery. | `2500` |
| **Max Charge Power (W)** | Maximum charge power sent to a single battery. | `2500` |
| **Power threshold: X to Y batteries** | Absolute power threshold (W) at which the system steps up to use more batteries. | `1500` |
| **Power stage offset / hysteresis** | Offset used to switch power levels with less toggling (e.g., jump to 2 batteries at Threshold + Offset, drop to 1 at Threshold - Offset). | `300` |
| **Priority interval** | Interval in minutes at which battery priorities are re-evaluated based on SoC. | `15` |
| **Wallbox power sensor (optional)**| Sensor that measures wallbox charging power. | `sensor.wallbox_power` |
| **Wallbox minimum surplus (W)**| If PV surplus exceeds this value, battery charging is paused for car charging. | `1500` |
| **Wallbox cable connected (optional)**| A binary sensor (`on`/`off`) that indicates whether a charging cable is connected. | `binary_sensor.wallbox_cable` |
| **Wallbox stability settings**| Various thresholds and delays to determine if the wallbox power is stable enough to allow home batteries to resume charging. | *(See UI for details)* |
| **Coordinator update interval**| Minimum seconds between executions of the logic update cycle. | `3` |
| **Service call cache TTL** | Seconds to cache identical service calls to prevent spamming the battery API. | `30` |
| **PID control enabled** | Enables PID-based power control to continuously adjust battery power to drive the *real grid power* towards `0W`. | `False` |

---

## Per-SoC charge/discharge caps

You can configure up to 5 charge-level caps and 5 discharge-level caps to limit the maximum power commanded to each battery depending on its State of Charge (SoC). This helps protect battery lifetime by reducing charge/discharge currents near the top and bottom of the SoC range.

Default example values (configurable via the integration options):

- **Charge caps** (applied when charging, checked from highest SoC down):
  - `Level 1` (SOC >= 98%): 1500 W
  - `Level 2` (SOC >= 95%): 1800 W
  - `Level 3` (SOC >= 91%): 2000 W
  - `Level 4` (SOC >= 86%): 2200 W
  - `Level 5` (SOC >= 80%): 2400 W

- **Discharge caps** (applied when discharging, checked from lowest SoC up):
  - `Level 1` (SOC <= 13%): 1500 W
  - `Level 2` (SOC <= 15%): 1800 W
  - `Level 3` (SOC <= 19%): 2000 W
  - `Level 4` (SOC <= 25%): 2200 W
  - `Level 5` (SOC <= 30%): 2400 W

**How these caps are used:**
During distribution, the coordinator computes a per-battery cap from these values based on each battery's current SoC. The requested power is allocated among the active batteries respecting these caps. If a battery reaches its absolute SoC limit, the priority list is immediately recalculated and the next available battery takes over.

## PID control (what it is and how the parameters work)

PID control is a feedback control method. In this integration, it is used to continuously adjust the battery charge/discharge power so that the measured *real grid power* approaches a target value of `0W`.

* When you have **PV surplus** (grid export), the controller will increase charging power.
* When you have **grid import**, the controller will increase discharging power.

The three gains influence how the controller reacts:

1. **P (Kp)** reacts to the current error.
2. **I (Ki)** reacts to the accumulated error over time (removes steady-state offset).
3. **D (Kd)** reacts to the rate of change of the error (damping).

Practical tuning guidance:
* Start with `Kd = 0`.
* Increase `Kp` until the response is fast but not oscillating.
* Add a small `Ki` to reduce residual import/export.
* If you see oscillations, reduce `Kp` and/or `Ki`.

## How it works (in detail)

### Priority calculation
* **When discharging (grid import)**: The battery with the **highest** SoC has the highest priority.
* **When charging (grid export)**: The battery with the **lowest** SoC has the highest priority.
* A battery is removed from the priority list when it reaches its upper/lower SoC limit.

### Power Stage Control (Hysteresis)
The absolute grid power determines the number of active batteries. Instead of constantly turning batteries on and off, the integration uses a dynamic offset (hysteresis) based on your configured `powerstage_X_to_Y` thresholds:
1. **Step Up:** If the requested power is greater than `Threshold + Offset`, an additional battery is activated.
2. **Step Down:** If the requested power is less than `Threshold - Offset`, a battery is deactivated.

### Wallbox logic (only active when wallbox parameters are configured)
* **Discharge protection**: As soon as the wallbox draws power, discharging of **all** batteries is stopped immediately to prevent the home battery from draining into the car.
* **Charging priority for the car**: If the real PV surplus exceeds the configured threshold, home battery charging is paused to prioritize the EV.
* **Intelligent charge resume**: Battery charging is released again when the EV stops drawing fluctuating power (e.g., because the car is full or has hit its max charging speed). Discharging remains blocked as long as the wallbox is charging.

### Control Switches
The integration provides dedicated switches in Home Assistant to manually override behaviors:
* **Control Batteries** (`switch.*._control_switch`): Master switch to enable/disable all battery control logic. When disabled, all batteries are set to 0W and the integration becomes idle.
* **Charging Allowed** (`switch.*._charging_switch`): Manually allow/block the batteries from charging.
* **Discharging Allowed** (`switch.*._discharging_switch`): Manually allow/block the batteries from discharging into the house.
* **Wallbox Priority** (`switch.*._wallbox_priority_switch`): Enable/disable the logic that prioritizes the EV over home batteries.
* **Block battery discharge while car charging** (`switch.*._discharge_blocker_cc_switch`): Standard protection. If disabled, your home batteries are allowed to discharge into your EV.
