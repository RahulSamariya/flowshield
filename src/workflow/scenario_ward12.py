"""Ward 12 heavy-rain scenario for the end-to-end workflow.

Provides:
  - 3 rainfall + waterlogging events across W12-N, W12-C, W12-S
  - 5 resources: 2 pumps + 3 rescue crews stationed in or near W12
  - A travel-time matrix between the sub-zones and depot
  - IncidentContext data for priority scoring

Zone layout
-----------
  W12-N   North sub-ward   (school + residential, moderate population)
  W12-C   Central sub-ward (hospital + main road, highest risk)
  W12-S   South sub-ward   (industrial + drain cluster)
  DEPOT   Resource depot outside W12  (25 min from all sub-wards)
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.models.event import RawEvent, RawEventType
from src.models.resource import Resource, ResourceStatus, ResourceType

CITY = "Ahmedabad"

# ── zone IDs ──────────────────────────────────────────────────────────────────
ZONE_NORTH   = "W12-N"
ZONE_CENTRAL = "W12-C"
ZONE_SOUTH   = "W12-S"
ZONE_DEPOT   = "DEPOT"

# ── timestamps ────────────────────────────────────────────────────────────────
T0 = datetime(2025, 7, 10, 14, 0, 0, tzinfo=UTC)
T1 = datetime(2025, 7, 10, 14, 5, 0, tzinfo=UTC)
T2 = datetime(2025, 7, 10, 14, 10, 0, tzinfo=UTC)
T3 = datetime(2025, 7, 10, 14, 12, 0, tzinfo=UTC)
T4 = datetime(2025, 7, 10, 14, 15, 0, tzinfo=UTC)


# ── raw events ────────────────────────────────────────────────────────────────

def make_events() -> list[RawEvent]:
    """Five events: IMD rainfall + citizen waterlogging across three sub-zones."""
    return [
        # Central: very heavy rainfall (IMD feed)
        RawEvent(
            event_type=RawEventType.RAINFALL,
            city=CITY, zone_id=ZONE_CENTRAL, source="imd_api",
            occurred_at=T0,
            payload={"rainfall_mm_hr": 72.0},
        ),
        # Central: waterlogging near hospital (citizen report)
        RawEvent(
            event_type=RawEventType.WATERLOGGING,
            city=CITY, zone_id=ZONE_CENTRAL, source="citizen",
            occurred_at=T1,
            payload={"water_level_m": 2.1, "affected_people": 2800},
        ),
        # North: heavy rain + school area drain blocked
        RawEvent(
            event_type=RawEventType.RAINFALL,
            city=CITY, zone_id=ZONE_NORTH, source="imd_api",
            occurred_at=T2,
            payload={"rainfall_mm_hr": 48.0},
        ),
        # North: waterlogging (citizen report)
        RawEvent(
            event_type=RawEventType.WATERLOGGING,
            city=CITY, zone_id=ZONE_NORTH, source="citizen",
            occurred_at=T3,
            payload={"water_level_m": 0.9, "affected_people": 1100},
        ),
        # South: drain blocked, road closed (sensor)
        RawEvent(
            event_type=RawEventType.DRAIN_BLOCKED,
            city=CITY, zone_id=ZONE_SOUTH, source="sensor",
            occurred_at=T4,
            payload={"water_level_m": 0.6, "drain_id": "W12-S-D3"},
        ),
    ]


# ── resources ─────────────────────────────────────────────────────────────────

def make_resources() -> list[Resource]:
    """2 pumps + 3 rescue crews available at Ward 12 and depot."""
    return [
        Resource(
            id="pump-A",
            name="Pump Unit A — W12 Depot",
            city=CITY, type=ResourceType.PUMP,
            home_zone_id=ZONE_DEPOT, current_zone_id=ZONE_DEPOT,
            capacity=9000, status=ResourceStatus.AVAILABLE,
            notes="High-capacity dewatering pump (9000 L/hr).",
        ),
        Resource(
            id="pump-B",
            name="Pump Unit B — W12 Depot",
            city=CITY, type=ResourceType.PUMP,
            home_zone_id=ZONE_DEPOT, current_zone_id=ZONE_DEPOT,
            capacity=6000, status=ResourceStatus.AVAILABLE,
            notes="Medium-capacity pump (6000 L/hr).",
        ),
        Resource(
            id="crew-alpha",
            name="Rescue Crew Alpha",
            city=CITY, type=ResourceType.RESCUE_TEAM,
            home_zone_id=ZONE_CENTRAL, current_zone_id=ZONE_CENTRAL,
            capacity=6, status=ResourceStatus.AVAILABLE,
            notes="Swift-water rescue. Station: W12 central fire post.",
        ),
        Resource(
            id="crew-beta",
            name="Rescue Crew Beta",
            city=CITY, type=ResourceType.RESCUE_TEAM,
            home_zone_id=ZONE_NORTH, current_zone_id=ZONE_NORTH,
            capacity=6, status=ResourceStatus.AVAILABLE,
            notes="General rescue. Station: W12 north community centre.",
        ),
        Resource(
            id="crew-gamma",
            name="Rescue Crew Gamma",
            city=CITY, type=ResourceType.RESCUE_TEAM,
            home_zone_id=ZONE_DEPOT, current_zone_id=ZONE_DEPOT,
            capacity=8, status=ResourceStatus.STANDBY,
            notes="On standby at depot. Deployable within 5 minutes.",
        ),
    ]


# ── travel-time matrix (minutes) ──────────────────────────────────────────────

DISTANCES: dict[str, dict[str, float]] = {
    ZONE_CENTRAL: {ZONE_NORTH: 8.0,  ZONE_SOUTH: 10.0, ZONE_DEPOT: 25.0, ZONE_CENTRAL: 0.0},
    ZONE_NORTH:   {ZONE_CENTRAL: 8.0, ZONE_SOUTH: 14.0, ZONE_DEPOT: 22.0, ZONE_NORTH: 0.0},
    ZONE_SOUTH:   {ZONE_CENTRAL: 10.0, ZONE_NORTH: 14.0, ZONE_DEPOT: 28.0, ZONE_SOUTH: 0.0},
    ZONE_DEPOT:   {ZONE_CENTRAL: 25.0, ZONE_NORTH: 22.0, ZONE_SOUTH: 28.0, ZONE_DEPOT: 0.0},
}


# ── incident context data for priority scoring ────────────────────────────────
# (populated from domain knowledge — not from events)

INCIDENT_CONTEXT: dict[str, dict] = {
    ZONE_CENTRAL: {
        "critical_facility_count": 3,   # hospital + fire station + evacuation shelter
        "road_blocked": True,
        "affected_population": 2800,
        "hours_until_deadline": 1.5,    # hospital evacuation window
        "infra_dependency_count": 3,    # trunk sewer + pumping station + power sub-station
    },
    ZONE_NORTH: {
        "critical_facility_count": 1,   # school used as shelter
        "road_blocked": False,
        "affected_population": 1100,
        "hours_until_deadline": 4.0,
        "infra_dependency_count": 1,
    },
    ZONE_SOUTH: {
        "critical_facility_count": 0,
        "road_blocked": True,
        "affected_population": 320,
        "hours_until_deadline": None,
        "infra_dependency_count": 2,
    },
}
