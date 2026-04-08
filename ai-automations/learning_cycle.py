"""
learning_cycle.py — Fixed per Denis meeting:
  - Streak = IN A ROW (lagatar din)
  - Total occurrences = scattered count in full year
  - Yearly frequency = X / total dataset days
  - Both shown clearly in output

Data source: DataFrame passed in from main.py
             (loaded via database_connection.py — NOT CSV)
"""

import asyncio
import pandas as pd
from dataclasses import dataclass, field
from typing      import List
from datetime    import date


# ── Config ────────────────────────────────────────────────────────────────────
GAP_TOLERANCE   = 2     # miss 2 din — still counts as in a row
TIME_WINDOW_HRS = 1     # ±1 hour flexibility
MIN_FREQUENCY   = 0.30  # 30% of active days
MIN_STREAK      = 3     # minimum in-a-row days


# ── Data Class ────────────────────────────────────────────────────────────────
@dataclass
class Pattern:
    entity_id        : str
    hour             : int
    cycle            : str
    streak           : int    # IN A ROW (lagatar din)
    frequency        : float  # entity ke active days mein se
    confidence       : float
    is_weekend       : bool
    last_date        : date
    active_days      : int    # entity ki apni active range
    total_occurrences: int    # poore dataset mein kitni baar (scattered)
    total_days       : int    # full dataset days
    status           : str = ""

    def __post_init__(self):
        if   self.streak >= 14: self.status = " AUTO ready"
        elif self.streak >=  7: self.status = " Strong"
        elif self.streak >=  3: self.status = " Suggest"
        else:                   self.status = "  Observe"

    def __str__(self):
        day_type   = "Weekend" if self.is_weekend else "Weekday"
        yearly_pct = (self.total_occurrences / max(self.total_days, 1)) * 100
        return (
            f"  {self.status}\n"
            f"     Entity            : {self.entity_id}\n"
            f"     Hour              : {self.hour:02d}:00 (±{TIME_WINDOW_HRS}hr window)\n"
            f"     Streak (in a row) : {self.streak} consecutive days\n"
            f"     Total in year     : {self.total_occurrences} / {self.total_days} days = {yearly_pct:.1f}%\n"
            f"     Active days base  : {self.active_days} days\n"
            f"     Frequency         : {self.frequency:.0%}\n"
            f"     Last seen         : {self.last_date}\n"
            f"     Day type          : {day_type}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_active_df(df: pd.DataFrame) -> pd.DataFrame:
    results = []
    for cat, grp in df.groupby("category"):
        if cat in ["switch", "light", "binary_sensor"]:
            results.append(grp[grp["state"] == "on"])
        elif cat == "media_player":
            active = set(grp["state"].unique()) - {"off", "unavailable", "unknown", "idle"}
            results.append(grp[grp["state"].isin(active)])
        elif cat == "climate":
            results.append(grp[grp["state"] != "off"])
        elif cat == "cover":
            results.append(grp[grp["state"] == "open"])
        elif cat == "lock":
            results.append(grp[grp["state"] == "unlocked"])
    return pd.concat(results) if results else pd.DataFrame()


def _to_date(d) -> date:
    return pd.Timestamp(d).date() if not isinstance(d, date) else d


def _streak_with_gap(dates: List[date], gap: int) -> int:
    """
    IN A ROW streak — lagatar din count karo.
    Gap tolerance: miss 2 din = still counts.
    e.g. Mon Tue [Wed miss] Thu Fri = streak 4
    """
    if not dates:
        return 0
    dates      = sorted(set(dates))
    max_streak = cur = 1
    for i in range(1, len(dates)):
        diff = (dates[i] - dates[i-1]).days
        cur  = cur + 1 if diff <= gap + 1 else 1
        max_streak = max(max_streak, cur)
    return max_streak


def _active_day_range(dates: List[date]) -> int:
    if not dates:
        return 1
    dates = sorted(set(dates))
    return max((dates[-1] - dates[0]).days + 1, 1)


# ── Core Detection ────────────────────────────────────────────────────────────


async def detect_patterns(df: pd.DataFrame) -> List[Pattern]:
    loop = asyncio.get_event_loop()
    def _detect():
        active_df = _get_active_df(df)
        if active_df.empty:
            return []

        active_df = active_df.copy()
        active_df["hour_window"] = (
            active_df["hour"] // TIME_WINDOW_HRS
        ) * TIME_WINDOW_HRS

        # Total dataset days — for yearly frequency
        total_days = df["date"].nunique()

        patterns = []

        for entity in active_df["entity_id"].unique():
            e_df = active_df[active_df["entity_id"] == entity]

            for is_weekend in [False, True]:
                subset = e_df[e_df["is_weekend"] == is_weekend]
                if len(subset) < MIN_STREAK:
                    continue

                all_dates = [_to_date(d) for d in subset["date"].unique()]
                day_range = _active_day_range(all_dates)

                for hour, h_df in subset.groupby("hour_window"):
                    dates = [_to_date(d) for d in h_df["date"].unique()]
                    if len(dates) < MIN_STREAK:
                        continue

                    # IN A ROW streak
                    streak = _streak_with_gap(dates, GAP_TOLERANCE)
                    if streak < MIN_STREAK:
                        continue

                    # Frequency based on active days
                    freq = len(dates) / day_range

                    if freq < MIN_FREQUENCY and streak < MIN_STREAK:
                        continue

                    conf = min((streak / 14) * 0.6 + freq * 0.4, 0.95)

                    if   streak >= 14: cycle = "14_day"
                    elif streak >=  7: cycle = "7_day"
                    else:              cycle = "3_day"

                    patterns.append(Pattern(
                        entity_id         = entity,
                        hour              = hour,
                        cycle             = cycle,
                        streak            = streak,
                        frequency         = freq,
                        confidence        = conf,
                        is_weekend        = is_weekend,
                        last_date         = max(dates),
                        active_days       = day_range,
                        total_occurrences = len(dates),   # scattered total
                        total_days        = total_days,   # full dataset
                    ))

        return sorted(
            patterns,
            key=lambda x: (x.streak, x.frequency),
            reverse=True
        )

    return await loop.run_in_executor(None, _detect)


async def run_learning_cycle(df: pd.DataFrame) -> List[Pattern]:
    print("=" * 60)
    print("  LEARNING CYCLE — 3 / 7 / 14 DAY")
    print("=" * 60)
    print(f"\n  Config:")
    print(f"  Gap tolerance : {GAP_TOLERANCE} days (in a row with gaps)")
    print(f"  Time window   : ±{TIME_WINDOW_HRS} hour")
    print(f"  Min frequency : {MIN_FREQUENCY:.0%} of active days")

    print(f"\n   {len(df):,} rows | {df['date'].nunique()} days")
    print(f"   Range : {df['date'].min()} → {df['date'].max()}")

    print("\n   Detecting patterns...")
    patterns = await detect_patterns(df)

    for cycle_key in ["3_day", "7_day", "14_day"]:
        cp    = [p for p in patterns if p.cycle == cycle_key]
        label = cycle_key.replace("_", " ").upper()
        print(f"\n  {'─'*55}")
        print(f"   {label} PATTERNS ({len(cp)} found)")
        print(f"  {'─'*55}")

        if not cp:
            print("  None found.")
            continue

        wd = [p for p in cp if not p.is_weekend]
        we = [p for p in cp if p.is_weekend]

        if wd:
            print(f"\n  Weekday ({len(wd)}):")
            for p in wd[:5]:
                print(p)
                print()
        if we:
            print(f"\n  Weekend ({len(we)}):")
            for p in we[:5]:
                print(p)
                print()

    auto    = [p for p in patterns if "AUTO"    in p.status]
    strong  = [p for p in patterns if "Strong"  in p.status]
    suggest = [p for p in patterns if "Suggest" in p.status]

    print(f"\n  {'═'*55}")
    print(f"  SUMMARY")
    print(f"  {'═'*55}")
    print(f"   AUTO ready : {len(auto)}")
    print(f"   Strong     : {len(strong)}")
    print(f"   Suggest    : {len(suggest)}")
    print(f"  Total         : {len(patterns)}")

    return patterns


if __name__ == "__main__":
    # Standalone test — uses database
    from database_connection import HADatabase
    from behaviour_detection import prepare_dataframe
    with HADatabase() as db:
        raw_df = db.get_states(real_only=True)
    df = prepare_dataframe(raw_df)
    asyncio.run(run_learning_cycle(df))