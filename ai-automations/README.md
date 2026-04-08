# CASABOT - AI Home

> Smart Home Automation powered by real usage patterns — no AI API needed.

CASABOT learns from your Home Assistant database history and automatically generates
automation suggestions based on your actual behaviour. It detects patterns like
"kitchen light is turned on every weekday at 8:00 AM" and creates HA automations for you.

---

## How It Works

```
HA Database (real usage history)
        |
        v
Pattern Detection (behaviour_detection.py + learning_cycle.py)
        |
        v
Scenario Mapping (scenario_mapper.py)
        |
        v
Automations injected into automations.yaml (disabled by default)
        |
        v
HA Notification sent to user
        |
        v
User enables / deletes automations in HA UI
```

---

## Features

- Detects recurring patterns from real HA database (13+ days of history)
- Groups patterns into named scenarios (Morning wake, Evening comfort, Dinner time, etc.)
- Generates valid HA automation YAML automatically
- Supports MariaDB (production) and SQLite (local/Docker)
- Sends HA persistent notification when new suggestions are ready
- No cloud API needed — runs fully local inside HA

---

## Installation

### Step 1 — Copy plugin files

Copy the `casabot` folder into your HA config directory:

```
/config/custom_components/casabot/
```

Your folder should look like this:

```
custom_components/
    casabot/
        __init__.py
        manifest.json
        coordinator.py
        sensor.py
        config_flow.py
        behaviour_detection.py
        learning_cycle.py
        scenario_mapper.py
        yaml_generator.py
        casabot_config.json
```

### Step 2 — Configure database credentials

Edit `casabot_config.json` with your MariaDB details:

```json
{
  "db_host": "your-mariadb-host-or-ip",
  "db_port": 3307,
  "db_user": "root",
  "db_password": "your-password",
  "db_name": "homeassistant"
}
```

If you are using a local Docker HA instance on Windows, use:

```json
{
  "db_host": "host.docker.internal",
  "db_port": 3307,
  "db_user": "root",
  "db_password": "",
  "db_name": "homeassistant"
}
```

### Step 3 — Restart Home Assistant

```
Settings -> System -> Restart
```

### Step 4 — Add Integration

```
Settings -> Devices & Services -> Add Integration -> CASABOT
```

---

## Data Sources (Priority Order)

| Priority | Source | When Used |
|----------|--------|-----------|
| 1 | MariaDB | casabot_config.json host is set |
| 2 | SQLite | HA built-in database found |
| 3 | CSV | ha_synthetic_data.csv present (test mode) |

---

## Scenarios Detected

| Scenario | Time Range | Device Types |
|----------|-----------|--------------|
| Morning wake | 05:00 - 08:00 | lights, covers, media |
| Late morning routine | 09:00 - 12:00 | lights, climate, media |
| Afternoon routine | 13:00 - 16:00 | lights, climate, covers |
| Sunset approaching | 17:00 - 19:00 | lights, covers, media |
| Dinner time | 18:00 - 21:00 | switches, lights |
| Evening comfort | 17:00 - 21:00 | climate |
| Evening entertainment | 18:00 - 22:00 | media players |
| Bedtime routine | 20:00 - 23:00 | lights, covers, climate |
| Night movement | 00:00 - 04:00 | lights |

---

## Pattern Thresholds

| Status | Streak Required | Meaning |
|--------|----------------|---------|
| AUTO ready | 14+ days | Very consistent — safe to automate |
| Strong | 7+ days | Consistent — consider automating |
| Suggest | 3+ days | Emerging pattern — keep watching |

---

## Sensor

After installation, CASABOT creates a sensor:

```
sensor.casabot_suggestions
```

Attributes:

```yaml
auto_ready: 9
strong: 5
behaviours: 12
pending: 54
approved: 0
last_error: null
```

---

## Automations

CASABOT injects automations into `automations.yaml` every 24 hours.

All generated automations are prefixed with `CASABOT -` for easy identification.

To enable an automation:

```
Settings -> Automations & Scenes -> find CASABOT automation -> toggle ON
```

To delete unwanted automations:

```
Settings -> Automations & Scenes -> find CASABOT automation -> Delete
```

---

## File Structure

```
casabot/
    __init__.py             HA integration entry point
    manifest.json           HACS / HA integration metadata
    coordinator.py          Core logic - data loading + pattern detection
    sensor.py               HA sensor entity
    config_flow.py          Setup UI (Settings -> Add Integration)
    behaviour_detection.py  Detects co-occurrence behaviour groups
    learning_cycle.py       Detects time-based recurring patterns
    scenario_mapper.py      Maps patterns to named scenarios
    yaml_generator.py       Standalone YAML generator (optional CLI use)
    casabot_config.json     Database credentials
```

---

## Requirements

- Home Assistant 2023.5 or later
- Python packages: `pandas`, `pymysql`, `pyyaml`
- MariaDB or SQLite database with HA state history

---

## For Denis / Integration into Core

CASABOT runs as a standard HA custom integration inside the Docker container.
It reads directly from the HA MariaDB database and writes to `automations.yaml`.

To add to HA core build:
1. Place `custom_components/casabot/` in the HA core custom_components path
2. User adds via Settings -> Add Integration -> CASABOT
3. CASABOT runs every 24 hours automatically

---

## License

MIT License — free to use, modify, and distribute.
