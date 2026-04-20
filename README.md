# FVE Optimization Script

## Overview

This script is designed to optimize the usage of surplus energy (e.g. from a photovoltaic system) by dynamically controlling load devices (such as boilers) via Home Assistant.

It periodically:

* Fetches states from Home Assistant
* Evaluates available energy
* Decides which devices should run
* Applies changes back to Home Assistant

---

## Features

* Fail-fast configuration validation
* Home Assistant state caching
* Dynamic load distribution based on available power
* Support for low tariff logic
* Temperature-based control of devices
* Device-level configuration
* Safe fallback handling for missing/invalid HA values

---

## Requirements

* Python 3+
* Home Assistant instance with API access
* Python packages:

  * `requests`
  * `PyYAML`

Install dependencies:

```bash
pip install requests pyyaml
```

---

## Configuration

### Main configuration (`fveconfig.yaml`)

Required keys:

```yaml
hass_base_url: "http://homeassistant.local:8123"
hass_token: "YOUR_LONG_LIVED_ACCESS_TOKEN"

low_tariff_entity: "sensor.low_tariff"
hass_current_entity: "sensor.current_power"

general_max_entity: "input_number.general_max_temp"
ha_export_entity: "sensor.export_power"

ha_battery_voltage_entity: "sensor.battery_voltage"
ha_max_charge_current_entity: "sensor.max_charge_current"
```

---

### Device configuration (`devices.yaml`)

```yaml
load_devices:
  - id: 1
    jmeno: "Boiler"
    spotreba: 2000
    sunday_boost: 5

    ha_endpoint_teplota_min: "input_number.boiler_min"
    ha_endpoint_teplota_max: "input_number.boiler_max"
    ha_endpoint_teplota_aktualni: "sensor.boiler_temp"

    ha_endpoint_ctrl: "switch.boiler"
    ha_endpoint_dovolena: "input_boolean.boiler_disable"
```

---

## How It Works

### 1. Initialization

* Loads and validates configuration files
* Builds list of devices

### 2. State Fetching

* Fetches all Home Assistant states in one request
* Stores them in an internal cache

### 3. Device State Preparation

For each device:

* Reads current temperature
* Reads min/max thresholds
* Adjusts thresholds based on:

  * Time of day
  * Sunday boost

---

### 4. Decision Logic

#### Low Tariff Mode

If low tariff is active:

* Devices may be turned on even without surplus energy
* Ensures minimum temperature is reached

#### Distribution Mode

* Iterates through devices
* Skips disabled devices
* Skips already running devices
* Checks temperature limits
* Checks available energy
* Turns devices ON if conditions are met

---

### 5. Energy Rebalance (Rerun)

If excess energy remains after battery export:

* Re-runs distribution with relaxed max temperature

---

### 6. Apply Changes

* Sends `turn_on` / `turn_off` commands via HA API
* Only updates devices whose state has changed

---

## Runtime Behavior

The script runs in an infinite loop:

```python
while running:
    main()
    time.sleep(10)
```

* Executes every 10 seconds
* Gracefully exits on `Ctrl+C`

---

## CLI Arguments

```bash
--current_power INT     Override current power (for testing)
--device-config PATH    Path to devices.yaml
--main-config PATH      Path to main config
--debug                 Enable debug logging
```

---

## Logging

* Default level: INFO
* Debug mode: `--debug`

Example:

```bash
python script.py --debug
```

---

## Safety & Design Notes

* Fail-fast configuration validation
* Safe handling of missing HA values (`None` → fallback)
* Avoids unnecessary API calls via caching
* Designed for idempotent repeated execution

---

## Known Limitations

* No prioritization of devices (order = priority)
* No explicit hysteresis (handled implicitly via system inertia)
* No retry/backoff for HA failures

---

## Future Improvements

* Device prioritization
* Hysteresis control
* Unit tests and simulation mode
* Better HA failure handling (backoff/retry)

---

## License

GPL-3.0 license
---

## Author

Petos / pyFVE
