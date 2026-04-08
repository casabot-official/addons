"""
convert_synthetic.py
--------------------
Loads the UAE synthetic dataset (ha_synthetic_data.csv)
in the same format as the real HA database output.
"""

import pandas as pd
from pathlib import Path

SYNTHETIC_FILE = "ha_synthetic_data.csv"

# Entity categories — same logic as behaviour_detection.py
VALID_CATEGORIES = {"light", "cover", "switch", "media_player", "climate", "binary_sensor"}


def load_synthetic() -> pd.DataFrame:
    fpath = Path(SYNTHETIC_FILE)

    if not fpath.exists():
        print(f"\n   File not found: {SYNTHETIC_FILE}")
        print(f"     Run generate_ha_data.py first to create it.")
        return pd.DataFrame()

    df = pd.read_csv(fpath)
    df["last_changed"] = pd.to_datetime(df["last_changed"])

    # Keep only valid entity categories
    df["category"] = df["entity_id"].str.split(".").str[0]
    df = df[df["category"].isin(VALID_CATEGORIES)].copy()
    df.drop(columns=["category"], inplace=True)

    # Print summary
    print(f"\n  ==================================================")
    print(f"  Synthetic dataset ready")
    print(f"  Rows     : {len(df):,}")
    print(f"  Entities : {df['entity_id'].nunique()}")
    print(f"  Range    : {df['last_changed'].min().date()} -> {df['last_changed'].max().date()}")
    print(f"  Days     : {df['last_changed'].dt.date.nunique()}")
    print(f"  ==================================================")

    return df