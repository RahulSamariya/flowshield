"""Tests: blocked drain event through the full engine pipeline."""

from datetime import UTC, datetime

import pytest

from src.engine.engine import SituationEngine
from src.engine.normalizer import EventNormalizer
from src.models.event import RawEvent, RawEventType
from src.models.evidence import EvidenceSource
from src.models.incident import SeverityLevel
from src.models.situation import ZoneSeverity
from tests.scenarios.ward12 import (
    CITY,
    SCENARIO_BLOCKED_DRAIN,
    ZONE,
    make_resources,
)


@pytest.fixture
def engine():
    e = SituationEngine(city=CITY)
    e.resources.update(make_resources())
    return e


def _drain_event(water_level_m: float | None = None, source: str = "sensor") -> RawEvent:
    payload: dict = {}
    if water_level_m is not None:
        payload["water_level_m"] = water_level_m
    return RawEvent(
        event_type=RawEventType.DRAIN_BLOCKED,
        city=CITY,
        zone_id=ZONE,
        source=source,
        occurred_at=datetime(2025, 7, 10, 10, 0, tzinfo=UTC),
        payload=payload,
    )


# ── normalization ─────────────────────────────────────────────────────────────

class TestDrainBlockedNormalization:
    def test_sets_road_blocked_true(self):
        normalizer = EventNormalizer()
        evidence = normalizer.normalize(_drain_event())
        assert evidence.road_blocked is True

    def test_with_water_level(self):
        normalizer = EventNormalizer()
        evidence = normalizer.normalize(_drain_event(water_level_m=0.7))
        assert evidence.road_blocked is True
        assert evidence.water_level_m == 0.7

    def test_without_water_level_still_valid(self):
        normalizer = EventNormalizer()
        evidence = normalizer.normalize(_drain_event())
        assert evidence is not None
        assert evidence.water_level_m is None

    def test_source_mapped(self):
        normalizer = EventNormalizer()
        evidence = normalizer.normalize(_drain_event(source="sensor"))
        assert evidence.source == EvidenceSource.SENSOR


# ── engine pipeline ───────────────────────────────────────────────────────────

class TestDrainBlockedEngine:
    def test_road_blocked_flag_set_in_zone(self, engine):
        engine.process(_drain_event())
        assert engine.state.zones[ZONE].road_blocked is True

    def test_road_blocked_alone_gives_watch(self, engine):
        # No rainfall, no water level → blocked road → minimum WATCH
        engine.process(_drain_event())
        assert engine.state.zones[ZONE].severity == ZoneSeverity.WATCH

    def test_drain_with_water_level_can_reach_warning(self, engine):
        engine.process(_drain_event(water_level_m=1.2))
        assert engine.state.zones[ZONE].severity == ZoneSeverity.WARNING

    def test_incident_created_on_drain_block(self, engine):
        engine.process(_drain_event())
        assert len(engine.open_incidents()) == 1

    def test_scenario_blocked_drain_creates_incident(self, engine):
        """Full 2-event scenario: drain blocked then citizen waterlogging."""
        for event in SCENARIO_BLOCKED_DRAIN:
            engine.process(event)

        zone = engine.state.zones[ZONE]
        # drain_blocked=True + water_level=0.8 → WATCH (WARNING threshold is 1.0 m)
        assert zone.severity == ZoneSeverity.WATCH
        assert zone.road_blocked is True
        assert zone.latest_water_level_m == 0.8
        assert zone.affected_population == 150

        open_inc = engine.open_incidents()
        assert len(open_inc) == 1
        assert open_inc[0].severity == SeverityLevel.LOW

    def test_history_records_both_events(self, engine):
        for event in SCENARIO_BLOCKED_DRAIN:
            engine.process(event)
        assert len(engine.history) == len(SCENARIO_BLOCKED_DRAIN)

    def test_evidence_ids_in_history(self, engine):
        records = [engine.process(e) for e in SCENARIO_BLOCKED_DRAIN]
        for record in records:
            assert record.evidence_id is not None

    def test_second_event_updates_incident_not_creates(self, engine):
        """Two events on the same zone should update, not duplicate the incident."""
        records = [engine.process(e) for e in SCENARIO_BLOCKED_DRAIN]
        # First record creates the incident
        assert len(records[0].incidents_created) == 1
        # Second record updates it (same zone, same open incident)
        assert len(records[1].incidents_created) == 0
