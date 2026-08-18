"""Scenario dataset for Ward 12.

Provides:
  - CITY / ZONE constants
  - 5 drains  (Resource type=OTHER)
  - 3 crews   (Resource type=RESCUE_TEAM)
  - 2 pumps   (Resource type=PUMP)
  - 5 pre-defined incident templates  (for reference / testing)
  - Rainfall scenario sequences  (lists of RawEvents)

All IDs are stable strings so tests can reference them directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.models.event import RawEvent, RawEventType
from src.models.resource import Resource, ResourceStatus, ResourceType

# ── city / zone constants ─────────────────────────────────────────────────────

CITY = "TestCity"
ZONE = "W12"  # Ward 12

# Sub-zones used in multi-event scenarios
ZONE_NORTH = "W12-N"
ZONE_SOUTH = "W12-S"

# ── stable resource IDs ───────────────────────────────────────────────────────

DRAIN_IDS = ["drain-01", "drain-02", "drain-03", "drain-04", "drain-05"]
CREW_IDS  = ["crew-alpha", "crew-beta", "crew-gamma"]
PUMP_IDS  = ["pump-01", "pump-02"]


# ── resource factory ──────────────────────────────────────────────────────────

def make_resources() -> dict[str, Resource]:
    """Return the full Ward 12 resource registry keyed by resource ID."""
    resources: dict[str, Resource] = {}

    # 5 drains (storm-water drains — modelled as OTHER assets)
    for i, did in enumerate(DRAIN_IDS, start=1):
        r = Resource(
            id=did,
            name=f"Storm Drain {i} — Ward 12",
            city=CITY,
            type=ResourceType.OTHER,
            home_zone_id=ZONE,
            current_zone_id=ZONE,
            status=ResourceStatus.AVAILABLE,
            notes=f"Drain capacity: {1500 + i * 200} L/hr",
        )
        resources[did] = r

    # 3 rescue crews
    for cid, label in zip(CREW_IDS, ["Alpha", "Beta", "Gamma"]):
        r = Resource(
            id=cid,
            name=f"Rescue Crew {label}",
            city=CITY,
            type=ResourceType.RESCUE_TEAM,
            home_zone_id=ZONE,
            capacity=6,
            status=ResourceStatus.AVAILABLE,
            notes="6-person team. Equipped for swift-water rescue.",
        )
        resources[cid] = r

    # 2 dewatering pumps
    for pid, capacity in zip(PUMP_IDS, [8000, 5000]):
        r = Resource(
            id=pid,
            name=f"Pump Unit {'A' if capacity > 6000 else 'B'}",
            city=CITY,
            type=ResourceType.PUMP,
            home_zone_id=ZONE,
            capacity=capacity,
            status=ResourceStatus.AVAILABLE,
            notes=f"Rated {capacity} L/hr.",
        )
        resources[pid] = r

    return resources


# ── rainfall scenarios ────────────────────────────────────────────────────────
# Each scenario is a list of RawEvents in chronological order.

def _evt(
    event_type: RawEventType,
    payload: dict,
    zone: str = ZONE,
    source: str = "mock",
    minute: int = 0,
) -> RawEvent:
    return RawEvent(
        event_type=event_type,
        city=CITY,
        zone_id=zone,
        source=source,
        occurred_at=datetime(2025, 7, 10, 8, minute, 0, tzinfo=UTC),
        payload=payload,
    )


# Scenario 1 — light rain, stays at NORMAL
SCENARIO_LIGHT_RAIN: list[RawEvent] = [
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 5.0},  minute=0),
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 8.0},  minute=15),
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 6.5},  minute=30),
]

# Scenario 2 — moderate rain → WATCH
SCENARIO_MODERATE_RAIN: list[RawEvent] = [
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 18.0}, minute=0),
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 22.0}, minute=15),
]

# Scenario 3 — heavy rain → WARNING
SCENARIO_HEAVY_RAIN: list[RawEvent] = [
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 40.0}, minute=0),
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 55.0}, minute=15),
]

# Scenario 4 — extreme rain → CRITICAL
SCENARIO_EXTREME_RAIN: list[RawEvent] = [
    _evt(RawEventType.RAINFALL, {"rainfall_mm_hr": 70.0}, minute=0),
    _evt(RawEventType.WATER_LEVEL, {"water_level_m": 2.5},  minute=10),
    _evt(RawEventType.WATERLOGGING,
         {"water_level_m": 2.5, "affected_people": 3000}, minute=20),
]

# Scenario 5 — blocked drain + citizen waterlogging report
SCENARIO_BLOCKED_DRAIN: list[RawEvent] = [
    _evt(RawEventType.DRAIN_BLOCKED,
         {"drain_id": "drain-02", "water_level_m": 0.6}, minute=0),
    _evt(RawEventType.WATERLOGGING,
         {"water_level_m": 0.8, "affected_people": 150}, minute=5,
         source="citizen"),
]

# ── 5 pre-defined incident templates (titles / descriptions) ──────────────────
# These are purely reference strings used to label expected incidents in tests.

INCIDENT_TEMPLATES = [
    {
        "id": "tmpl-1",
        "title": "Flash flood — Ward 12 main road",
        "zone": ZONE,
        "trigger": "rainfall >= 64.5 mm/hr",
    },
    {
        "id": "tmpl-2",
        "title": "Waterlogging — residential block north",
        "zone": ZONE_NORTH,
        "trigger": "water_level >= 1.0 m",
    },
    {
        "id": "tmpl-3",
        "title": "Drain blockage — drain-02 overflow",
        "zone": ZONE,
        "trigger": "drain_blocked + water_level >= 0.5 m",
    },
    {
        "id": "tmpl-4",
        "title": "Road closure — secondary arterial",
        "zone": ZONE_SOUTH,
        "trigger": "road_blocked = True",
    },
    {
        "id": "tmpl-5",
        "title": "Multi-zone compound flood",
        "zone": ZONE,
        "trigger": "rainfall >= 35.5 mm/hr + water_level >= 1.0 m",
    },
]
