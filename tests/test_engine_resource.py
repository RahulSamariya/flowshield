"""Tests: resource becoming unavailable (RESOURCE_STATUS + INFRASTRUCTURE events)."""

import pytest
from datetime import datetime, timezone

from src.engine.engine import SituationEngine
from src.models.event import RawEvent, RawEventType
from src.models.resource import ResourceStatus
from tests.scenarios.ward12 import (
    CITY, ZONE, make_resources,
    PUMP_IDS, CREW_IDS, DRAIN_IDS,
)


@pytest.fixture
def engine():
    e = SituationEngine(city=CITY)
    e.resources.update(make_resources())
    return e


def _resource_status_event(resource_id: str, status: str, zone_id: str | None = None) -> RawEvent:
    payload: dict = {"resource_id": resource_id, "status": status}
    if zone_id:
        payload["zone_id"] = zone_id
    return RawEvent(
        event_type=RawEventType.RESOURCE_STATUS,
        city=CITY,
        zone_id=ZONE,
        source="mock",
        occurred_at=datetime(2025, 7, 10, 11, 0, tzinfo=timezone.utc),
        payload=payload,
    )


def _infra_event(asset_id: str, blocked: bool) -> RawEvent:
    return RawEvent(
        event_type=RawEventType.INFRASTRUCTURE,
        city=CITY,
        zone_id=ZONE,
        source="mock",
        occurred_at=datetime(2025, 7, 10, 11, 0, tzinfo=timezone.utc),
        payload={"asset_id": asset_id, "blocked": blocked},
    )


# ── RESOURCE_STATUS events ────────────────────────────────────────────────────

class TestResourceStatusEvent:
    def test_pump_becomes_deployed(self, engine):
        record = engine.process(_resource_status_event(PUMP_IDS[0], "deployed", ZONE))
        pump = engine.resources[PUMP_IDS[0]]
        assert pump.status == ResourceStatus.DEPLOYED
        assert pump.current_zone_id == ZONE

    def test_pump_becomes_unavailable(self, engine):
        record = engine.process(_resource_status_event(PUMP_IDS[0], "unavailable"))
        pump = engine.resources[PUMP_IDS[0]]
        assert pump.status == ResourceStatus.UNAVAILABLE

    def test_crew_becomes_deployed(self, engine):
        engine.process(_resource_status_event(CREW_IDS[0], "deployed", ZONE))
        assert engine.resources[CREW_IDS[0]].status == ResourceStatus.DEPLOYED

    def test_unknown_resource_id_is_silently_ignored(self, engine):
        # Should not raise
        engine.process(_resource_status_event("does-not-exist", "unavailable"))

    def test_record_captures_status_change(self, engine):
        record = engine.process(_resource_status_event(PUMP_IDS[1], "unavailable"))
        assert record.resource_id == PUMP_IDS[1]
        assert record.resource_status_before == ResourceStatus.AVAILABLE
        assert record.resource_status_after == ResourceStatus.UNAVAILABLE

    def test_available_resources_count_decreases(self, engine):
        before = len(engine.available_resources("pump"))
        engine.process(_resource_status_event(PUMP_IDS[0], "unavailable"))
        after = len(engine.available_resources("pump"))
        assert after == before - 1

    def test_all_pumps_unavailable(self, engine):
        for pid in PUMP_IDS:
            engine.process(_resource_status_event(pid, "unavailable"))
        assert engine.available_resources("pump") == []

    def test_resource_returns_to_available(self, engine):
        engine.process(_resource_status_event(PUMP_IDS[0], "unavailable"))
        engine.process(_resource_status_event(PUMP_IDS[0], "available"))
        assert engine.resources[PUMP_IDS[0]].status == ResourceStatus.AVAILABLE

    def test_history_appended_for_resource_event(self, engine):
        engine.process(_resource_status_event(PUMP_IDS[0], "deployed", ZONE))
        assert len(engine.history) == 1

    def test_no_evidence_produced_for_resource_event(self, engine):
        record = engine.process(_resource_status_event(PUMP_IDS[0], "unavailable"))
        assert record.evidence_id is None

    def test_no_incident_created_for_resource_event(self, engine):
        engine.process(_resource_status_event(PUMP_IDS[0], "unavailable"))
        assert engine.open_incidents() == []


# ── INFRASTRUCTURE events ─────────────────────────────────────────────────────

class TestInfrastructureEvent:
    def test_drain_blocked_marks_unavailable(self, engine):
        engine.process(_infra_event(DRAIN_IDS[0], blocked=True))
        assert engine.resources[DRAIN_IDS[0]].status == ResourceStatus.UNAVAILABLE

    def test_drain_unblocked_marks_available(self, engine):
        engine.process(_infra_event(DRAIN_IDS[0], blocked=True))
        engine.process(_infra_event(DRAIN_IDS[0], blocked=False))
        assert engine.resources[DRAIN_IDS[0]].status == ResourceStatus.AVAILABLE

    def test_record_captures_infra_change(self, engine):
        record = engine.process(_infra_event(DRAIN_IDS[2], blocked=True))
        assert record.resource_id == DRAIN_IDS[2]
        assert record.resource_status_before == ResourceStatus.AVAILABLE
        assert record.resource_status_after == ResourceStatus.UNAVAILABLE

    def test_multiple_drains_blocked(self, engine):
        for did in DRAIN_IDS[:3]:
            engine.process(_infra_event(did, blocked=True))
        unavailable = [
            r for r in engine.resources.values()
            if r.status == ResourceStatus.UNAVAILABLE
        ]
        assert len(unavailable) == 3

    def test_unknown_asset_silently_ignored(self, engine):
        engine.process(_infra_event("no-such-drain", blocked=True))
        # No error, nothing changed
        assert len(engine.history) == 1


# ── combined scenario ─────────────────────────────────────────────────────────

class TestCombinedResourceScenario:
    def test_flood_event_then_resource_unavailable(self, engine):
        """Heavy rain creates incident; pump-01 breaks down; available_resources reflects it."""
        from src.models.event import RawEvent, RawEventType
        rainfall_event = RawEvent(
            event_type=RawEventType.RAINFALL,
            city=CITY,
            zone_id=ZONE,
            source="mock",
            occurred_at=datetime(2025, 7, 10, 11, 0, tzinfo=timezone.utc),
            payload={"rainfall_mm_hr": 50.0},
        )
        engine.process(rainfall_event)
        assert len(engine.open_incidents()) == 1

        engine.process(_resource_status_event(PUMP_IDS[0], "unavailable"))
        pumps = engine.available_resources("pump")
        assert len(pumps) == 1
        assert pumps[0].id == PUMP_IDS[1]
