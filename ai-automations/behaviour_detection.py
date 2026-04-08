"""
behaviour_detection.py — ZERO hardcoding
Data source: DataFrame passed in from main.py
             (loaded via database_connection.py — NOT CSV)
"""

import asyncio
import pandas as pd
from collections import defaultdict
from dataclasses import dataclass, field
from typing      import List, Dict, Tuple, Optional


# ── Config ────────────────────────────────────────────────────────────────────
TIME_WINDOW_MINUTES  = 60
MIN_CO_OCCUR_WEEKDAY = 3
MIN_CO_OCCUR_WEEKEND = 2
MIN_CONFIDENCE       = 0.30


# ── Data Class ────────────────────────────────────────────────────────────────
@dataclass
class Behaviour:
    name        : str
    devices     : List[str]
    entities    : List[str]
    hour        : int
    occurrences : int
    confidence  : float
    days        : List[str] = field(default_factory=list)
    is_weekend  : bool = False

    def __str__(self):
        days_str = ", ".join(sorted(set(self.days))) if self.days else "any day"
        day_type = "Weekend" if self.is_weekend else "Weekday"
        return (
            f"   {self.name}\n"
            f"     Areas       : {', '.join(self.devices)}\n"
            f"     Time        : {self.hour:02d}:00\n"
            f"     Occurrences : {self.occurrences}x\n"
            f"     Confidence  : {self.confidence:.0%}\n"
            f"     Days        : {days_str}\n"
            f"     Day type    : {day_type}"
        )


# ── Auto Name Generator ───────────────────────────────────────────────────────
def _auto_name(areas: List[str], hour: int) -> str:
    areas = sorted(areas)
    if   5  <= hour < 9:  time_label = "Morning"
    elif 9  <= hour < 12: time_label = "Late Morning"
    elif 12 <= hour < 14: time_label = "Midday"
    elif 14 <= hour < 17: time_label = "Afternoon"
    elif 17 <= hour < 20: time_label = "Evening"
    elif 20 <= hour < 23: time_label = "Night"
    else:                 time_label = "Late Night"
    area_str = " + ".join(a.replace("_", " ").title() for a in areas)
    return f"{time_label} — {area_str}"


# ── DataFrame Preparation ─────────────────────────────────────────────────────
def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived columns to raw states DataFrame.
    Input:  entity_id, state, last_changed
    Output: adds hour, date, day_name, is_weekend, category
    """
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["last_changed"]):
        df["last_changed"] = pd.to_datetime(
            df["last_changed"], format="mixed", utc=True
        )
    df["hour"]       = df["last_changed"].dt.hour
    df["date"]       = df["last_changed"].dt.date
    df["day_name"]   = df["last_changed"].dt.day_name()
    df["is_weekend"] = df["last_changed"].dt.dayofweek >= 5
    df["category"]   = df["entity_id"].str.split(".").str[0]
    return df


# ── Core Detection ────────────────────────────────────────────────────────────
async def detect_behaviours(
    df: pd.DataFrame,
    entity_area_map: Optional[Dict[str, str]] = None
) -> List["Behaviour"]:
    """
    Detect CORE behaviours — no combinatorial explosion.
    Denis requirement: ONE behaviour per time slot, not 120 combos.

    Algorithm:
      Step 1: Per (date, hour) collect full area group
      Step 2: Per hour slot find CORE areas (iterative trim)
      Step 3: Build Behaviour objects
    """
    loop = asyncio.get_event_loop()

    def _detect():
        # ── Step 0: Filter to active states ───────────────────────────────
        active_cats = ["switch", "light", "media_player",
                       "binary_sensor", "climate", "cover", "lock"]
        active_df = df[df["category"].isin(active_cats)].copy()

        on_rows = []
        for cat, grp in active_df.groupby("category"):
            if cat in ["switch", "light", "binary_sensor"]:
                on_rows.append(grp[grp["state"] == "on"])
            elif cat == "media_player":
                active_states = set(grp["state"].unique()) - {
                    "off", "unavailable", "unknown", "idle"}
                on_rows.append(grp[grp["state"].isin(active_states)])
            elif cat == "climate":
                on_rows.append(grp[grp["state"] != "off"])
            elif cat == "cover":
                on_rows.append(grp[grp["state"] == "open"])
            elif cat == "lock":
                on_rows.append(grp[grp["state"] == "unlocked"])

        if not on_rows:
            return []

        active_df = pd.concat(on_rows).copy()

        # ── Area label — FIXED: use entity name, not full id ──────────────
        # "media_player.sonos_kitchen" → "sonos_kitchen" → "sonos"
        # "light.corridor_k29_light_0" → "corridor_k29_light_0" → "corridor"
        # "cover.kids_bathroom_shutter" → "kids_bathroom_shutter" → "kids"
        def _get_area(entity_id: str) -> str:
            if entity_area_map and entity_id in entity_area_map:
                return entity_area_map[entity_id]
            entity_name = entity_id.split(".", 1)[-1]   # after domain dot
            return entity_name.split("_")[0]             # first word

        active_df["area"] = active_df["entity_id"].apply(_get_area)
        active_days       = active_df["date"].nunique()

        # ── Step 1: Per (date, hour) → full area group ────────────────────
        hour_slots: Dict = defaultdict(dict)

        for (dt, hour), grp in active_df.groupby(["date", "hour"]):
            areas      = set(grp["area"].unique())
            entities   = list(grp["entity_id"].unique())
            is_weekend = bool(grp["is_weekend"].iloc[0])
            day        = grp["day_name"].iloc[0]

            if len(areas) < 2:
                continue

            slot_key = (hour, is_weekend)
            hour_slots[slot_key][dt] = {
                "areas"   : areas,
                "entities": entities,
                "day"     : day,
            }

        # ── Step 2: Find CORE areas per hour slot ─────────────────────────
        # Iteratively remove least-frequent area until core_dates >= threshold
        # This handles: {kids,steps,corridor} always together but
        #               {kitchen,table} only sometimes → remove them
        behaviours = []

        for (hour, is_wknd), date_map in hour_slots.items():
            threshold = MIN_CO_OCCUR_WEEKEND if is_wknd else MIN_CO_OCCUR_WEEKDAY

            if len(date_map) < threshold:
                continue

            # Count days each area appeared at this hour
            area_day_count: Dict[str, int] = defaultdict(int)
            for dt, record in date_map.items():
                for area in record["areas"]:
                    area_day_count[area] += 1

            # Start with areas that appeared >= threshold days
            candidate_areas = {
                a for a, c in area_day_count.items() if c >= threshold
            }

            if len(candidate_areas) < 2:
                continue

            # Trim until all candidates co-occur on >= threshold days together
            while len(candidate_areas) >= 2:
                core_dates = [
                    dt for dt, rec in date_map.items()
                    if candidate_areas.issubset(rec["areas"])
                ]
                if len(core_dates) >= threshold:
                    break
                least = min(candidate_areas, key=lambda a: area_day_count[a])
                candidate_areas.discard(least)

            if len(candidate_areas) < 2:
                continue

            # Final count
            core_dates = [
                dt for dt, rec in date_map.items()
                if candidate_areas.issubset(rec["areas"])
            ]
            count = len(core_dates)
            if count < threshold:
                continue

            # Confidence = core days / days this hour was active
            # NOT total dataset days — that unfairly penalizes rare hours
            slot_days = len(date_map)
            conf = min(count / max(slot_days, 1), 0.95)
            if conf < MIN_CONFIDENCE:
                continue

            days     = [date_map[dt]["day"] for dt in core_dates]
            entities = list({
                e
                for dt in core_dates
                for e in date_map[dt]["entities"]
            })
            name = _auto_name(list(candidate_areas), hour)

            behaviours.append(Behaviour(
                name        = name,
                devices     = sorted(candidate_areas),
                entities    = sorted(entities),
                hour        = hour,
                occurrences = count,
                confidence  = conf,
                days        = days,
                is_weekend  = is_wknd,
            ))

        return sorted(behaviours, key=lambda x: x.confidence, reverse=True)

    return await loop.run_in_executor(None, _detect)


async def run_behaviour_detection(
    df: pd.DataFrame,
    entity_area_map: Optional[Dict[str, str]] = None
) -> List[Behaviour]:
    print("=" * 60)
    print("  BEHAVIOUR DETECTION — ZERO HARDCODING")
    print("=" * 60)
    print(f"   {len(df):,} rows | {df['date'].nunique()} days")
    print("\n   Detecting behaviours...")
    behaviours = await detect_behaviours(df, entity_area_map)
    print(f"   Found {len(behaviours)} behaviours")
    weekday_b = [b for b in behaviours if not b.is_weekend]
    weekend_b = [b for b in behaviours if b.is_weekend]
    print(f"\n  Weekday : {len(weekday_b)}")
    print(f"  Weekend : {len(weekend_b)}")
    for i, b in enumerate(weekday_b, 1):
        print(f"\n  [{i:03d}] {b}")
    return behaviours


if __name__ == "__main__":
    from database_connection import HADatabase
    with HADatabase() as db:
        raw_df = db.get_states(real_only=True)
    df = prepare_dataframe(raw_df)
    asyncio.run(run_behaviour_detection(df))