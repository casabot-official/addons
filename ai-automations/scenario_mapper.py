"""
scenario_mapper.py
------------------
Step 1 — Named Scenario Mapping
    Maps detected patterns/behaviours to a named scenario
    based on time of day and entity types present.

Step 2 — Entity Filter Per Scenario
    Removes irrelevant entities from each scenario group.
    Works automatically for any new entity — no hardcoding needed.
    Only entity TYPE matters (light, cover, climate, etc.)
"""


# ── SCENARIO DEFINITIONS ──────────────────────────────────────────────────────
# Each scenario defines:
#   time_range      : (start_hour, end_hour) inclusive
#   allowed_types   : entity types allowed in this scenario
#   description     : human readable label

SCENARIOS = [
    {
        "name"          : "Morning wake",
        "time_range"    : (5, 8),
        "allowed_types" : ["light", "media_player", "switch", "cover"],
        "description"   : "Morning routine — lights, music, blinds open",
    },
    {
        "name"          : "Late morning routine",
        "time_range"    : (9, 12),
        "allowed_types" : ["light", "media_player", "climate", "switch"],
        "description"   : "Late morning activity — AC, music, lights",
    },
    {
        "name"          : "Afternoon routine",
        "time_range"    : (13, 16),
        "allowed_types" : ["light", "climate", "media_player", "cover", "switch"],
        "description"   : "Afternoon — kids home, AC, lights",
    },
    {
        "name"          : "Sunset approaching",
        "time_range"    : (17, 19),
        "allowed_types" : ["light", "cover", "media_player"],
        "description"   : "Evening — hallway and lounge lights, blinds",
    },
    {
        "name"          : "Evening entertainment",
        "time_range"    : (18, 22),
        "allowed_types" : ["media_player"],
        "description"   : "Evening — TV, music, entertainment",
    },
    {
        "name"          : "Dinner time",
        "time_range"    : (18, 21),
        "allowed_types" : ["switch", "light"],
        "description"   : "Dinner — kitchen fan, cooking lights",
    },
    {
        "name"          : "Evening comfort",
        "time_range"    : (17, 21),
        "allowed_types" : ["climate"],
        "description"   : "Evening — AC comfort before bedtime",
    },
    {
        "name"          : "Bedtime routine",
        "time_range"    : (20, 23),
        "allowed_types" : ["light", "cover", "climate"],
        "description"   : "Night — lights off, blinds closed, AC set",
    },
    {
        "name"          : "Night movement",
        "time_range"    : (0, 4),
        "allowed_types" : ["light"],
        "description"   : "Late night — minimal lights only",
    },
]

# Special scenario — triggered by entity TYPE combination, not time
SPECIAL_SCENARIOS = [
    {
        "name"             : "Window open + AC",
        "required_types"   : ["climate", "cover"],
        "allowed_types"    : ["climate", "cover"],
        "description"      : "Window open — pause AC",
    },
    {
        "name"             : "Away mode",
        "required_types"   : ["light", "climate"],
        "allowed_types"    : ["light", "climate", "cover", "switch"],
        "description"      : "Everyone left — turn off everything",
    },
]


# ── STEP 1 — SCENARIO MAPPING ─────────────────────────────────────────────────

def get_entity_type(entity_id: str) -> str:
    """Extract entity type from entity_id — works for any new entity."""
    return entity_id.split(".")[0]


def map_scenario(entity_id: str, hour: int, all_entities: list = None) -> dict:
    """
    Step 1: Map a single entity + time to the best matching scenario.

    Args:
        entity_id   : e.g. "light.corridor"
        hour        : hour of day (0-23)
        all_entities: full group of entities (for special scenario detection)

    Returns:
        matched scenario dict
    """
    entity_types = set()
    if all_entities:
        entity_types = {get_entity_type(e) for e in all_entities}

    # Check special scenarios first (type-combination based)
    for special in SPECIAL_SCENARIOS:
        required = set(special["required_types"])
        if required.issubset(entity_types):
            return special

    # Then check time-based scenarios
    for scenario in SCENARIOS:
        start, end = scenario["time_range"]
        if start <= hour <= end:
            return scenario

    # Fallback — no match found
    return {
        "name"          : "Unclassified pattern",
        "allowed_types" : list(entity_types) if entity_types else ["light"],
        "description"   : "Pattern detected — needs manual classification",
    }


def map_behaviour_scenario(hour: int, sensors: list) -> dict:
    """
    Step 1: Map a behaviour group to a scenario.
    Uses sensor count as hint — large groups = whole-home scenarios.
    """
    sensor_count = len(sensors) if sensors else 0

    # Large group = whole home active
    if sensor_count >= 10:
        for scenario in SCENARIOS:
            start, end = scenario["time_range"]
            if start <= hour <= end:
                return scenario

    # Small group = specific area
    return map_scenario("", hour)


# ── STEP 2 — ENTITY FILTER ────────────────────────────────────────────────────

def filter_entities(entities: list, scenario: dict) -> dict:
    """
    Step 2: Filter entities — keep only those whose type
    is allowed in the given scenario.

    Works automatically for any new entity — no hardcoding.

    Returns:
        {
          "kept"   : [...],   entities that belong
          "removed": [...],   entities filtered out
        }
    """
    allowed = set(scenario.get("allowed_types", []))
    kept    = []
    removed = []

    for entity in entities:
        etype = get_entity_type(entity)
        if etype in allowed:
            kept.append(entity)
        else:
            removed.append(entity)

    return {"kept": kept, "removed": removed}


# ── COMBINED — MAP + FILTER ───────────────────────────────────────────────────

def process_pattern(entity_id: str, hour: int, all_entities: list = None) -> dict:
    """
    Run Step 1 + Step 2 together for a single pattern.

    Logic:
      1. Get entity type from entity_id
      2. Find scenario where BOTH time AND entity type match
      3. If time matches but type NOT allowed → Unclassified
      4. If no time match at all → Unclassified
    """
    entities    = all_entities or [entity_id]
    entity_type = get_entity_type(entity_id)

    time_matched_scenario = None
    best_scenario         = None

    for scenario in SCENARIOS:
        start, end = scenario["time_range"]
        if start <= hour <= end:
            time_matched_scenario = scenario   # time matches
            if entity_type in scenario.get("allowed_types", []):
                best_scenario = scenario        # time + type both match
                break

    # Time matched but type not allowed → Unclassified
    if time_matched_scenario and not best_scenario:
        best_scenario = {
            "name"          : "Unclassified pattern",
            "allowed_types" : [],
            "description"   : (
                f"{entity_type} at {hour:02d}:00 — "
                f"not relevant to '{time_matched_scenario['name']}'"
            ),
        }

    # No time match at all → Unclassified
    if not best_scenario:
        best_scenario = {
            "name"          : "Unclassified pattern",
            "allowed_types" : [],
            "description"   : f"No scenario found for {entity_type} at {hour:02d}:00",
        }

    # Step 2 — filter
    # For single entity: mark as kept or removed based on scenario
    if entity_type in best_scenario.get("allowed_types", []):
        kept    = [entity_id]
        removed = []
    else:
        kept    = []
        removed = [entity_id]

    return {
        "scenario"          : best_scenario["name"],
        "scenario_desc"     : best_scenario["description"],
        "entities_kept"     : kept,
        "entities_removed"  : removed,
    }


def process_behaviour(hour: int, sensors: list) -> dict:
    """
    Run Step 1 + Step 2 for a behaviour group.
    """
    # Step 1
    scenario = map_behaviour_scenario(hour, sensors)

    # Step 2
    filtered = filter_entities(sensors, scenario)

    return {
        "scenario"          : scenario["name"],
        "scenario_desc"     : scenario["description"],
        "entities_kept"     : filtered["kept"],
        "entities_removed"  : filtered["removed"],
    }