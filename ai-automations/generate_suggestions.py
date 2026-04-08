"""
generate_suggestions.py
-----------------------
Parses the report file and saves all suggestions to a JSON file.
Each suggestion includes an approval field (pending/approved/rejected).
"""

import re
import json
from datetime import datetime
from pathlib import Path
from scenario_mapper import process_pattern, process_behaviour

# ─── CONFIG ───────────────────────────────────────────────────────────────────
REPORT_FILE   = "report_20260323_020647.txt"   # ← your report filename here
OUTPUT_FILE   = "suggestions.json"
# ──────────────────────────────────────────────────────────────────────────────


def parse_report(report_path: str) -> dict:
    """Parse patterns and behaviours from the report file."""
    with open(report_path, "r", encoding="utf-8") as f:
        text = f.read()

    patterns    = parse_patterns(text)
    behaviours  = parse_behaviours(text)
    return {"patterns": patterns, "behaviours": behaviours}


def parse_patterns(text: str) -> list:
    """Parse AUTO ready, Strong and Suggest patterns from report text."""
    patterns = []

    # Regex: match one pattern block
    block_re = re.compile(
        r"( AUTO ready| Strong| Suggest)\s*\n"
        r"\s*Entity\s*:\s*(\S+)\s*\n"
        r"\s*Hour\s*:\s*(\S+).*?\n"
        r"\s*Streak.*?:\s*(\d+) consecutive days\s*\n"
        r"\s*Total.*?:\s*[\d,]+ / [\d,]+ days = ([\d.]+)%\s*\n"
        r".*?Frequency\s*:\s*([\d]+)%\s*\n"
        r".*?Day type\s*:\s*(\w+)",
        re.DOTALL
    )

    for m in block_re.finditer(text):
        status, entity, hour, streak, total_pct, freq, day_type = m.groups()

        streak  = int(streak)
        freq    = int(freq)
        hour_n  = int(hour.replace(":00", ""))

        # Build suggestion text
        suggestion = make_suggestion(status, entity, hour, day_type, streak, freq)

        # Action type
        if "AUTO" in status:
            action_type = "automate"
        elif "Strong" in status:
            action_type = "notify"
        else:
            action_type = "observe"

        # Step 1 + 2 — scenario mapping and entity filter
        mapped = process_pattern(entity, hour_n, [entity])

        patterns.append({
            "id"                : f"{entity}_{hour}_{day_type}",
            "type"              : "pattern",
            "status"            : status.strip(),
            "entity"            : entity,
            "hour"              : hour,
            "hour_num"          : hour_n,
            "streak_days"       : streak,
            "frequency"         : freq,
            "day_type"          : day_type,
            "action_type"       : action_type,
            "scenario"          : mapped["scenario"],
            "scenario_desc"     : mapped["scenario_desc"],
            "entities_kept"     : mapped["entities_kept"],
            "entities_removed"  : mapped["entities_removed"],
            "suggestion"        : suggestion,
            "approval"          : "pending",
            "approved_at"       : None,
            "notes"             : ""
        })

    return patterns


def parse_behaviours(text: str) -> list:
    """Parse behaviour blocks from report text."""
    behaviours = []

    block_re = re.compile(
        r" (\w[\w ]+?) —\s*(M\w+(?: \+ M\w+)+)\s*\n"
        r"\s*Areas\s*:.*?\n"
        r"\s*Time\s*:\s*(\d+:\d+)\s*\n"
        r"\s*Occurrences\s*:\s*(\d+)x\s*\n"
        r"\s*Confidence\s*:\s*(\d+)%\s*\n"
        r".*?Day type\s*:\s*(\w+)",
        re.DOTALL
    )

    for m in block_re.finditer(text):
        label, sensors_str, time, occ, conf, day_type = m.groups()

        sensors = [s.strip() for s in sensors_str.split("+")]
        conf_n  = int(conf)
        occ_n   = int(occ)

        suggestion = make_behaviour_suggestion(label, time, conf_n, occ_n, day_type)

        # Step 1 + 2 — scenario mapping and entity filter
        mapped = process_behaviour(int(time.split(":")[0]), sensors)

        behaviours.append({
            "id"                : f"behaviour_{label.replace(' ','_')}_{time}_{day_type}",
            "type"              : "behaviour",
            "label"             : label.strip(),
            "time"              : time,
            "sensors"           : sensors,
            "occurrences"       : occ_n,
            "confidence"        : conf_n,
            "day_type"          : day_type,
            "scenario"          : mapped["scenario"],
            "scenario_desc"     : mapped["scenario_desc"],
            "entities_kept"     : mapped["entities_kept"],
            "entities_removed"  : mapped["entities_removed"],
            "suggestion"        : suggestion,
            "approval"          : "pending",
            "approved_at"       : None,
            "notes"             : ""
        })

    return behaviours


def make_suggestion(status, entity, hour, day_type, streak, freq):
    """Build a human-readable suggestion string."""
    entity_clean = entity.replace("binary_sensor.", "").replace("_", " ").upper()

    if "AUTO" in status:
        return (
            f"[AUTO] {entity_clean} has been consistently active every {day_type.lower()} "
            f"at {hour} for {streak} consecutive days ({freq}% frequency). "
            f"Recommendation: Automatically trigger the linked device at this time?"
        )
    elif "Strong" in status:
        return (
            f"[STRONG] {entity_clean} is consistently active on {day_type.lower()}s "
            f"at {hour} for {streak} days ({freq}% frequency). "
            f"Recommendation: Send a notification or set up automation?"
        )
    else:
        return (
            f"[SUGGEST] {entity_clean} has been observed on {day_type.lower()}s "
            f"at {hour} for {streak} days ({freq}% frequency). "
            f"Recommendation: Keep observing — automate once the streak grows stronger."
        )


def make_behaviour_suggestion(label, time, conf, occ, day_type):
    """Build a human-readable behaviour suggestion string."""
    return (
        f"[BEHAVIOUR] '{label}' pattern detected on {day_type.lower()}s at {time} "
        f"with {occ} occurrences ({conf}% confidence). "
        f"Recommendation: Pre-configure related devices (lights/AC/fan) for this time slot?"
    )


def save_suggestions(data: dict, output_path: str):
    """Save all suggestions to a JSON file."""
    output = {
        "generated_at"   : datetime.now().isoformat(),
        "source_report"  : REPORT_FILE,
        "total_patterns" : len(data["patterns"]),
        "total_behaviours": len(data["behaviours"]),
        "summary": {
            "auto_ready" : sum(1 for p in data["patterns"] if "AUTO" in p["status"]),
            "strong"     : sum(1 for p in data["patterns"] if "Strong" in p["status"]),
            "suggest"    : sum(1 for p in data["patterns"] if "Suggest" in p["status"]),
            "behaviours" : len(data["behaviours"]),
        },
        "approval_stats": {
            "pending"    : 0,
            "approved"   : 0,
            "rejected"   : 0,
        },
        "patterns"   : data["patterns"],
        "behaviours" : data["behaviours"],
    }

    # Count approval statuses
    all_items = data["patterns"] + data["behaviours"]
    for item in all_items:
        output["approval_stats"][item["approval"]] += 1

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return output


def print_summary(output: dict):
    """Print a summary to console."""
    print("\n" + "=" * 60)
    print("   SUGGESTIONS FILE GENERATED")
    print("=" * 60)
    print(f"\n   File        : {OUTPUT_FILE}")
    print(f"   Generated   : {output['generated_at']}")
    print(f"\n   SUMMARY:")
    print(f"   AUTO ready  : {output['summary']['auto_ready']}")
    print(f"   Strong      : {output['summary']['strong']}")
    print(f"   Suggest     : {output['summary']['suggest']}")
    print(f"   Behaviours  : {output['summary']['behaviours']}")
    print(f"\n   Approval Status:")
    print(f"   Pending     : {output['approval_stats']['pending']}")
    print(f"   Approved    : {output['approval_stats']['approved']}")
    print(f"   Rejected    : {output['approval_stats']['rejected']}")
    print("\n" + "=" * 60)
    print("\n  HOW TO APPROVE:")
    print(f'  Open "{OUTPUT_FILE}" and for each item change:')
    print('  "approval": "pending"  →  "approved"  or  "rejected"')
    print('  "notes": ""            →  add your own note (optional)')
    print("\n" + "=" * 60)


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n   Reading report: {REPORT_FILE} ...")

    if not Path(REPORT_FILE).exists():
        print(f"\n   File not found: {REPORT_FILE}")
        print(f"     Make sure the report file is in the same folder as this script.")
        exit(1)

    data    = parse_report(REPORT_FILE)
    output  = save_suggestions(data, OUTPUT_FILE)
    print_summary(output)

    print(f"\n   Done! '{OUTPUT_FILE}' is ready.\n")