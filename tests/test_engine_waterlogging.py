"""Tests: citizen waterlogging event through the full engine pipeline."""

from datetime import UTC

import pytest

from src.engine.engine import SituationEngine
from src.engine.normalizer import EventNormalizer, NormalizationError
from src.models.event import RawEvent, RawEventType
from src.models.situation import ZoneSeverity
from tests.scenarios.ward12 import CITY, ZONE, make_resources


@pytest.fixture
def engine():
    e = SituationEngine(city=CITY)
    e.resources.update(make_resources())
    return e


def _waterlogging_event(water_level_m: float, affected_people: int) -> RawEvent:
    from datetime import datetime
    return RawEvent(
        event_type=RawEventType.WATERLOGGING,
        city=CITY,
        zone_id=ZONE,
        source="citizen",
        occurred_at=datetime(2025, 7, 10, 9, 0, 0, tzinfo=UTC),
        payload={"water_level_m": water_level_m, "affected_people": affected_people},
    )


# ── normalization ─────────────────────────────────────────────────────────────

class TestWaterloggingNormalization:
    def test_produces_evidence(self):
        normalizer = EventNormalizer()
        event = _waterlogging_event(0.8, 200)
        evidence = normalizer.normalize(event)
        assert evidence is not None
        assert evidence.water_level_m == 0.8
        assert evidence.affected_population == 200

    def test_source_mapped_to_citizen_report(self):
        normalizer = EventNormalizer()
        from src.models.evidence import EvidenceSource
        evidence = normalizer.normalize(_waterlogging_event(0.5, 50))
        assert evidence.source == EvidenceSource.CITIZEN_REPORT

    def test_missing_both_fields_raises(self):
        normalizer = EventNormalizer()
        event = RawEvent(
            event_type=RawEventType.WATERLOGGING,
            city=CITY,
            zone_id=ZONE,
            source="citizen",
            payload={},
        )
        with pytest.raises(NormalizationError, match="requires"):
            normalizer.normalize(event)

    def test_population_only_is_valid(self):
        normalizer = EventNormalizer()
        event = RawEvent(
            event_type=RawEventType.WATERLOGGING,
            city=CITY,
            zone_id=ZONE,
            source="citizen",
            payload={"affected_people": 300},
        )
        evidence = normalizer.normalize(event)
        assert evidence.affected_population == 300
        assert evidence.water_level_m is None


# ── engine pipeline ───────────────────────────────────────────────────────────

class TestWaterloggingEngine:
    def test_low_waterlogging_creates_watch(self, engine):
        # 0.6 m → WATCH (threshold is 0.5)
        engine.process(_waterlogging_event(0.6, 100))
        assert engine.state.zones[ZONE].severity == ZoneSeverity.WATCH

    def test_warning_waterlogging(self, engine):
        # 1.2 m → WARNING
        engine.process(_waterlogging_event(1.2, 500))
        assert engine.state.zones[ZONE].severity == ZoneSeverity.WARNING

    def test_critical_waterlogging(self, engine):
        # 2.1 m → CRITICAL
        engine.process(_waterlogging_event(2.1, 2000))
        assert engine.state.zones[ZONE].severity == ZoneSeverity.CRITICAL

    def test_incident_created_with_population(self, engine):
        engine.process(_waterlogging_event(1.5, 800))
        open_inc = engine.open_incidents()
        assert len(open_inc) == 1
        assert engine.state.zones[ZONE].affected_population == 800

    def test_risk_score_includes_population_contribution(self, engine):
        # No population → base score
        engine_a = SituationEngine(city=CITY)
        engine_a.resources.update(make_resources())
        from datetime import datetime

        from src.models.event import RawEvent
        event_no_pop = RawEvent(
            event_type=RawEventType.WATERLOGGING,
            city=CITY, zone_id=ZONE, source="citizen",
            occurred_at=datetime(2025, 7, 10, 9, 0, tzinfo=UTC),
            payload={"water_level_m": 1.0},
        )
        engine_a.process(event_no_pop)
        score_no_pop = engine_a.open_incidents()[0].risk_score

        engine_b = SituationEngine(city=CITY)
        engine_b.resources.update(make_resources())
        event_pop = RawEvent(
            event_type=RawEventType.WATERLOGGING,
            city=CITY, zone_id=ZONE, source="citizen",
            occurred_at=datetime(2025, 7, 10, 9, 0, tzinfo=UTC),
            payload={"water_level_m": 1.0, "affected_people": 4000},
        )
        engine_b.process(event_pop)
        score_with_pop = engine_b.open_incidents()[0].risk_score

        assert score_with_pop > score_no_pop

    def test_record_has_evidence_id(self, engine):
        record = engine.process(_waterlogging_event(0.8, 100))
        assert record.evidence_id is not None

    def test_history_appended(self, engine):
        engine.process(_waterlogging_event(0.8, 100))
        assert len(engine.history) == 1
