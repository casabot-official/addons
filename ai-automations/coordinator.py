"""
coordinator.py
--------------
CASABOT core coordinator.

Flow:
  1. Read data - MariaDB (production) / SQLite (fallback) / CSV (test)
  2. Run behaviour_detection + learning_cycle
  3. Run scenario_mapper
  4. Generate YAML and inject into HA automations
  5. Send HA notification
"""

import logging
import asyncio
import os
import time
import json
import yaml
import pandas as pd
from datetime import timedelta
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .behaviour_detection import detect_behaviours, prepare_dataframe
from .learning_cycle import detect_patterns
from .scenario_mapper import process_pattern, process_behaviour

_LOGGER = logging.getLogger(__name__)

DOMAIN = "casabot"
# SCAN_INTERVAL = timedelta(hours=24)
SCAN_INTERVAL = timedelta(minutes=1)


# ── YAML helpers ──────────────────────────────────────────────────────────────

ACTION_MAP = {
    "light": "light.turn_on",
    "switch": "switch.turn_on",
    "media_player": "media_player.turn_on",
    "cover": "cover.open_cover",
    "climate": "climate.set_hvac_mode",
}

WEEKDAY_MAP = {
    "Weekday": ["mon", "tue", "wed", "thu", "fri"],
    "Weekend": ["sat", "sun"],
}


def _unique_id():
    """Generate a unique timestamp-based ID."""
    time.sleep(0.001)
    return str(int(time.time() * 1000))


def _build_action(entity_id):
    """Build HA action block for a given entity."""
    domain = entity_id.split(".")[0]
    service = ACTION_MAP.get(domain)
    if not service:
        return None
    block = {"action": service, "target": {"entity_id": entity_id}}
    if domain == "climate":
        block["data"] = {"hvac_mode": "cool"}
    return block


def _make_automation(alias, description, hour, day_type, actions):
    """Build a complete HA automation dict."""
    weekdays = WEEKDAY_MAP.get(day_type, WEEKDAY_MAP["Weekday"])
    return {
        "id": _unique_id(),
        "alias": alias,
        "description": description,
        "triggers": [{"trigger": "time", "at": f"{hour:02d}:00:00"}],
        "conditions": [{"condition": "time", "weekday": weekdays}],
        "actions": actions,
        "mode": "single",
    }


def _suggestion_to_automation(suggestion):
    """Convert a suggestion dict to HA automation dict."""
    stype = suggestion.get("type")
    day_type = suggestion.get("day_type", "Weekday")

    if stype == "pattern":
        entity = suggestion.get("entity", "")
        hour = int(suggestion.get("hour", 0))
        action = _build_action(entity)
        if not action:
            return None
        label = entity.split(".")[-1].replace("_", " ")
        alias = f"CASABOT - {suggestion.get('scenario', '')} - {label}"
        desc = (
            f"Auto-generated | Streak: {suggestion.get('streak_days', 0)}d "
            f"| Freq: {suggestion.get('frequency', 0)}% | {day_type} {hour:02d}:00"
        )
        return _make_automation(alias, desc, hour, day_type, [action])

    elif stype == "behaviour":
        kept = suggestion.get("entities_kept", [])
        hour = int(suggestion.get("time", "00:00").split(":")[0])
        label = suggestion.get("label", "Behaviour").replace(" (reassigned)", "")
        actions = [_build_action(e) for e in kept]
        actions = [a for a in actions if a]
        if not actions:
            return None
        alias = f"CASABOT - {suggestion.get('scenario', '')} - {label} routine"
        desc = (
            f"Auto-generated | Behaviour | "
            f"{suggestion.get('confidence', 0)}% conf | {day_type} {hour:02d}:00"
        )
        return _make_automation(alias, desc, hour, day_type, actions)

    return None


# ── Coordinator ───────────────────────────────────────────────────────────────

class CasabotCoordinator(DataUpdateCoordinator):
    """Runs CASABOT algorithm and stores results."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.entry = entry
        self.hass = hass
        self.suggestions = []

    async def _async_update_data(self) -> dict:
        """Main function - HA calls this on schedule."""
        try:
            _LOGGER.info("CASABOT - Starting pattern detection...")

            raw_df = await self.hass.async_add_executor_job(self._load_data)

            if raw_df is None or raw_df.empty:
                _LOGGER.warning("CASABOT - No data loaded")
                return self._empty_result()

            df = prepare_dataframe(raw_df)
            _LOGGER.info(f"CASABOT - {len(df):,} rows | {df['date'].nunique()} days")

            behaviours, patterns = await asyncio.gather(
                detect_behaviours(df),
                detect_patterns(df),
            )
            _LOGGER.info(f"CASABOT - {len(behaviours)} behaviours | {len(patterns)} patterns")

            # Build suggestions list
            suggestions = []

            for p in patterns:
                mapped = process_pattern(p.entity_id, p.hour, [p.entity_id])
                suggestions.append({
                    "id": f"{p.entity_id}_{p.hour}_{p.cycle}",
                    "type": "pattern",
                    "entity": p.entity_id,
                    "hour": p.hour,
                    "day_type": "Weekend" if p.is_weekend else "Weekday",
                    "streak_days": p.streak,
                    "frequency": round(p.frequency * 100),
                    "status": p.status,
                    "scenario": mapped["scenario"],
                    "scenario_desc": mapped["scenario_desc"],
                    "approval": "pending",
                    "approved_at": None,
                    "notes": "",
                })

            for b in behaviours:
                mapped = process_behaviour(b.hour, b.entities)
                suggestions.append({
                    "id": f"behaviour_{b.name}_{b.hour}",
                    "type": "behaviour",
                    "label": b.name,
                    "time": f"{b.hour:02d}:00",
                    "entities_kept": mapped["entities_kept"],
                    "occurrences": b.occurrences,
                    "confidence": round(b.confidence * 100),
                    "day_type": "Weekend" if b.is_weekend else "Weekday",
                    "scenario": mapped["scenario"],
                    "scenario_desc": mapped["scenario_desc"],
                    "approval": "pending",
                    "approved_at": None,
                    "notes": "",
                })

            self.suggestions = suggestions

            auto = sum(1 for s in suggestions if "AUTO" in s.get("status", ""))
            strong = sum(1 for s in suggestions if "Strong" in s.get("status", ""))
            beh = sum(1 for s in suggestions if s["type"] == "behaviour")

            _LOGGER.info(f"CASABOT - Done: {len(suggestions)} suggestions")

            # Inject YAML into HA automations
            await self.hass.async_add_executor_job(
                self._inject_automations, suggestions
            )

            # Reload automations
            await self.hass.services.async_call("automation", "reload")

            # Send notification
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "CASABOT - Suggestions Ready",
                    "message": (
                        f"{len(suggestions)} suggestions found!\n\n"
                        f"AUTO ready : {auto}\n"
                        f"Strong     : {strong}\n"
                        f"Behaviours : {beh}\n\n"
                        f"Go to Settings -> Automations to enable."
                    ),
                    "notification_id": "casabot_suggestions",
                }
            )

            return {
                "total": len(suggestions),
                "auto_ready": auto,
                "strong": strong,
                "behaviours": beh,
                "suggestions": suggestions,
                "last_error": None,
            }

        except Exception as e:
            _LOGGER.error(f"CASABOT - Error: {e}")
            raise UpdateFailed(f"CASABOT update failed: {e}")

    def _inject_automations(self, suggestions: list):
        """Inject CASABOT automations into HA automations.yaml."""
        automations_path = self.hass.config.path("automations.yaml")

        # Load existing automations
        existing = []
        if os.path.exists(automations_path):
            try:
                with open(automations_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, list):
                        existing = data
            except Exception as e:
                _LOGGER.error(f"CASABOT - Could not read automations.yaml: {e}")

        # Remove old CASABOT automations
        existing = [
            a for a in existing
            if not str(a.get("alias", "")).startswith("CASABOT -")
        ]

        # Build new automations
        new_autos = []
        for s in suggestions:
            auto = _suggestion_to_automation(s)
            if auto:
                new_autos.append(auto)

        # Merge and save
        final = existing + new_autos
        try:
            class NoAliasDumper(yaml.Dumper):
                def ignore_aliases(self, data):
                    return True

            with open(automations_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    final, f,
                    Dumper=NoAliasDumper,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
            _LOGGER.info(f"CASABOT - Injected {len(new_autos)} automations")
        except Exception as e:
            _LOGGER.error(f"CASABOT - Could not write automations.yaml: {e}")

    def _load_data(self) -> pd.DataFrame:
        """Load data - tries MariaDB, then SQLite, then CSV."""

        # Read config from casabot_config.json if present
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "casabot_config.json"
        )
        cfg = {}
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    cfg = json.load(f)
                _LOGGER.info(f"CASABOT - Config loaded: {cfg.get('db_host')}")
            except Exception as e:
                _LOGGER.error(f"CASABOT - Config read error: {e}")

        # Mode 1: MariaDB
        try:
            import pymysql
            _LOGGER.info("CASABOT - Connecting MariaDB...")
            conn = pymysql.connect(
                host=cfg.get("db_host", "host.docker.internal"),
                port=int(cfg.get("db_port", 3307)),
                user=cfg.get("db_user", "root"),
                password=cfg.get("db_password", ""),
                database=cfg.get("db_name", "homeassistant"),
                connect_timeout=10,
            )
            query = """
                SELECT sm.entity_id, s.state,
                       FROM_UNIXTIME(s.last_changed_ts) AS last_changed
                FROM states s
                JOIN states_meta sm ON s.metadata_id = sm.metadata_id
                WHERE s.state IS NOT NULL
                  AND s.state NOT IN ('unavailable', 'unknown')
                  AND s.last_changed_ts IS NOT NULL
                ORDER BY s.last_changed_ts ASC
                LIMIT 500000
            """
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            df = pd.DataFrame(rows, columns=cols)
            cursor.close()
            conn.close()
            if not df.empty:
                df["last_changed"] = pd.to_datetime(df["last_changed"])
                _LOGGER.info(f"CASABOT - MariaDB loaded: {len(df):,} rows")
                return df
        except Exception as e:
            _LOGGER.error(f"CASABOT - MariaDB error: {e}")

        # Mode 2: SQLite
        try:
            import sqlite3
            db_path = self.hass.config.path("home-assistant_v2.db")
            if os.path.exists(db_path):
                _LOGGER.info(f"CASABOT - Loading SQLite: {db_path}")
                conn = sqlite3.connect(db_path)
                query = """
                    SELECT s.entity_id, s.state, s.last_changed
                    FROM states s
                    JOIN states_meta sm ON s.metadata_id = sm.metadata_id
                    WHERE s.last_changed IS NOT NULL
                      AND s.state NOT IN ('unavailable', 'unknown')
                    ORDER BY s.last_changed DESC
                    LIMIT 500000
                """
                df = pd.read_sql_query(query, conn)
                conn.close()
                if not df.empty:
                    df["last_changed"] = pd.to_datetime(df["last_changed"])
                    _LOGGER.info(f"CASABOT - SQLite loaded: {len(df):,} rows")
                    return df
        except Exception as e:
            _LOGGER.error(f"CASABOT - SQLite error: {e}")

        # Mode 3: CSV (test/synthetic)
        csv_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "ha_synthetic_data.csv"
        )
        if os.path.exists(csv_path):
            try:
                _LOGGER.info(f"CASABOT - Loading CSV: {csv_path}")
                df = pd.read_csv(csv_path)
                df["last_changed"] = pd.to_datetime(df["last_changed"])
                _LOGGER.info(f"CASABOT - CSV loaded: {len(df):,} rows")
                return df
            except Exception as e:
                _LOGGER.error(f"CASABOT - CSV error: {e}")

        return pd.DataFrame()

    def _empty_result(self) -> dict:
        """Return empty result dict."""
        return {
            "total": 0,
            "auto_ready": 0,
            "strong": 0,
            "behaviours": 0,
            "suggestions": [],
            "last_error": "No data available",
        }