"""
yaml_generator.py
-----------------
Reads approved items from suggestions.json
Generates valid Home Assistant automation YAML (2024+ syntax)
Ready to load into HA directly.

Usage:
    python yaml_generator.py
    python yaml_generator.py --input suggestions_approved.json
    python yaml_generator.py --input suggestions.json --output my_automations.yaml
"""

import json
import time
import argparse
from pathlib import Path
from datetime import datetime


ACTION_MAP = {
    "light": "light.turn_on",
    "switch": "switch.turn_on",
    "media_player": "media_player.turn_on",
    "cover": "cover.open_cover",
    "climate": "climate.set_hvac_mode",
    "binary_sensor": None,
    "sensor": None,
}

WEEKDAY_MAP = {
    "Weekday": ["mon", "tue", "wed", "thu", "fri"],
    "Weekend": ["sat", "sun"],
    "Daily": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
}


def get_domain(entity_id):
    """Extract domain from entity_id."""
    return entity_id.split(".")[0]


def unique_id():
    """Loyd-style unique ID - Unix timestamp in milliseconds."""
    time.sleep(0.001)
    return str(int(time.time() * 1000))


def build_action(entity_id):
    """Build new HA syntax action block."""
    domain = get_domain(entity_id)
    action_svc = ACTION_MAP.get(domain)
    if action_svc is None:
        return None
    block = {
        "action": action_svc,
        "target": {"entity_id": entity_id},
    }
    if domain == "climate":
        block["data"] = {"hvac_mode": "cool"}
    return block


def to_yaml(obj, indent=0):
    """Simple YAML serializer - no external dependency needed."""
    pad = "  " * indent
    out = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.append(to_yaml(v, indent + 1))
            else:
                out.append(f"{pad}{k}: {scalar(v)}")

    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    prefix = f"{pad}- " if first else f"{pad}  "
                    first = False
                    if isinstance(v, (dict, list)):
                        out.append(f"{prefix}{k}:")
                        out.append(to_yaml(v, indent + 2))
                    else:
                        out.append(f"{prefix}{k}: {scalar(v)}")
            else:
                out.append(f"{pad}- {scalar(item)}")

    return "\n".join(out)


def scalar(v):
    """Format a scalar value for YAML."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    needs_quote = any(
        c in str(v) for c in [':', '#', '{', '}', '[', ']', ',', '&', '*', '!', '|', '>']
    )
    return f'"{v}"' if needs_quote else str(v)


def make_automation(alias, description, hour, day_type, actions):
    """Build a complete HA 2024+ automation dict."""
    weekdays = WEEKDAY_MAP.get(day_type, WEEKDAY_MAP["Weekday"])
    return {
        "id": unique_id(),
        "alias": alias,
        "description": description,
        "triggers": [{"trigger": "time", "at": f"{hour:02d}:00:00"}],
        "conditions": [{"condition": "time", "weekday": weekdays}],
        "actions": actions,
        "mode": "single",
    }


def from_pattern(item):
    """Convert approved pattern item to automation dict."""
    entity = item.get("entity", "")
    hour = int(item.get("hour", "00:00").replace(":00", ""))
    day_type = item.get("day_type", "Weekday")
    scenario = item.get("scenario", "")
    streak = item.get("streak_days", 0)
    freq = item.get("frequency", 0)

    action = build_action(entity)
    if action is None:
        return None

    label = entity.split(".")[-1].replace("_", " ")
    alias = f"CASABOT - {scenario} - {label}"
    description = (
        f"Auto-generated | Streak: {streak}d | Freq: {freq}% | {day_type} {hour:02d}:00"
    )
    return make_automation(alias, description, hour, day_type, [action])


def from_behaviour(item):
    """Convert approved behaviour item to automation dict."""
    kept = item.get("entities_kept", [])
    hour = int(item.get("time", "00:00").split(":")[0])
    day_type = item.get("day_type", "Weekday")
    scenario = item.get("scenario", "")
    label = item.get("label", "Behaviour").replace(" (reassigned)", "")
    conf = item.get("confidence", 0)
    occ = item.get("occurrences", 0)

    actions = [build_action(e) for e in kept]
    actions = [a for a in actions if a is not None]
    if not actions:
        return None

    alias = f"CASABOT - {scenario} - {label} routine"
    description = (
        f"Auto-generated | Behaviour | {conf}% conf | {occ}x | {day_type} {hour:02d}:00"
    )
    return make_automation(alias, description, hour, day_type, actions)


def generate(input_path, output_path):
    """Main generator function."""
    print("\n" + "=" * 60)
    print("  CASABOT - YAML GENERATOR")
    print("=" * 60)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_items = data.get("patterns", []) + data.get("behaviours", [])
    approved = [i for i in all_items if i.get("approval") == "approved"]

    print(f"\n  Input   : {input_path}")
    print(f"  Output  : {output_path}")
    print(f"  Approved: {len(approved)} items")

    if not approved:
        print("\n  No approved items. Open index.html, approve, download JSON, run again.")
        return

    automations = []
    skipped = []

    for item in approved:
        auto = from_pattern(item) if item["type"] == "pattern" else from_behaviour(item)
        if auto:
            automations.append((item, auto))
        else:
            skipped.append(item.get("id", "?"))

    print(f"  Generated: {len(automations)} automations")
    if skipped:
        print(f"  Skipped  : {len(skipped)} (read-only entities)")

    lines = [
        "# CASABOT - Generated Automations",
        f"# Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# Source    : {input_path}",
        "# Syntax    : HA 2024+ (triggers/conditions/actions/action:)",
        f"# Total     : {len(automations)} automations",
        "",
    ]

    for i, (item, auto) in enumerate(automations):
        if i > 0:
            lines.append("")
        entity_label = item.get("entity") or item.get("label", "behaviour")
        lines.append(
            f"# [{i+1:03d}] {item.get('scenario','')} | {entity_label} | {item.get('day_type','')}"
        )
        lines.append(to_yaml(auto))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n  Saved: {output_path}")
    print(f"\n  HOW TO LOAD INTO HA:")
    print(f"  Settings -> Automations -> (menu) -> Edit as YAML -> paste")
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CASABOT - YAML Generator")
    parser.add_argument("--input", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.input is None:
        files = sorted(Path(".").glob("suggestions_*.json"), reverse=True)
        if not files:
            print("\n  No suggestions_*.json found. Run main.py first.")
            exit(1)
        args.input = str(files[0])

    if args.output is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"automations_{ts}.yaml"

    generate(args.input, args.output)