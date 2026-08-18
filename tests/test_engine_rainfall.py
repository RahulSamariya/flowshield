"""Tests: rainfall events through the full engine pipeline."""

import pytest

from src.engine.engine import SituationEngine
from src.models.event import RawEvent, RawEventType
from src.models.incident import IncidentStatus, SeverityLevel
from src.models.situation import ZoneSeverity
from tests.scenarios.ward12 import (
    CITY, ZONE,
    make_resources,
    SCENARIO_LIGHT_RAIN,
    SCENARIO_MODERATE_RAIN,
    SCENARIO_HEAVY_RAIN,
    SCENARIO_EXTREME_RAIN,
)


@pytest.fixture
def engine():
    e = SituationEngine(city=CITY)
    e.resources.update(make_resources())
    return e


# ── light rain — stays NORMAL, no incidents ───────────────────────────────────

class TestLightRain:
    def test_severity_stays_normal(self, engine):
        for event in SCENARIO_LIGHT_RAIN:
            engine.process(event)
        zone = engine.state.zones.get(ZONE)
        assert zone is not None
        assert zone.severity == ZoneSeverity.NORMAL

    def test_no_open_incidents(self, engine):
        for event in SCENARIO_LIGHT_RAIN:
            engine.process(event)
        assert engine.open_incidents() == []

    def test_history_has_one_record_per_event(self, engine):
        for event in SCENARIO_LIGHT_RAIN:
            engine.process(event)
        assert len(engine.history) == len(SCENARIO_LIGHT_RAIN)

    def test_evidence_count_increments(self, engine):
        for event in SCENARIO_LIGHT_RAIN:
            engine.process(event)
        zone = engine.state.zones[ZONE]
        assert zone.evidence_count == len(SCENARIO_LIGHT_RAIN)


# ── moderate rain — WATCH, low-severity incident ──────────────────────────────

class TestModerateRain:
    def test_severity_is_watch(self, engine):
        for event in SCENARIO_MODERATE_RAIN:
            engine.process(event)
        assert engine.state.zones[ZONE].severity == ZoneSeverity.WATCH

    def test_one_open_incident_created(self, engine):
        for event in SCENARIO_MODERATE_RAIN:
            engine.process(event)
        open_inc = engine.open_incidents()
        assert len(open_inc) == 1

    def test_incident_severity_is_low(self, engine):
        for event in SCENARIO_MODERATE_RAIN:
            engine.process(event)
        assert engine.open_incidents()[0].severity == SeverityLevel.LOW

    def test_risk_score_is_nonzero(self, engine):
        for event in SCENARIO_MODERATE_RAIN:
            engine.process(event)
        score = engine.open_incidents()[0].risk_score
        assert 0.0 < score < 1.0

    def test_record_captures_severity_transition(self, engine):
        records = [engine.process(e) for e in SCENARIO_MODERATE_RAIN]
        # First event: None → watch
        assert records[0].zone_severity_before is None
        assert records[0].zone_severity_after == ZoneSeverity.WATCH

    def test_latest_rainfall_stored_in_zone(self, engine):
        for event in SCENARIO_MODERATE_RAIN:
            engine.process(event)
        # Last reading is 22.0
        assert engine.state.zones[ZONE].latest_rainfall_mm_hr == 22.0


# ── heavy rain — WARNING, medium incident ────────────────────────────────────

class TestHeavyRain:
    def test_severity_is_warning(self, engine):
        for event in SCENARIO_HEAVY_RAIN:
            engine.process(event)
        assert engine.state.zones[ZONE].severity == ZoneSeverity.WARNING

    def test_incident_severity_is_medium(self, engine):
        for event in SCENARIO_HEAVY_RAIN:
            engine.process(event)
        assert engine.open_incidents()[0].severity == SeverityLevel.MEDIUM

    def test_overall_state_severity_is_warning(self, engine):
        for event in SCENARIO_HEAVY_RAIN:
            engine.process(event)
        assert engine.state.overall_severity == ZoneSeverity.WARNING


# ── extreme rain — CRITICAL ───────────────────────────────────────────────────

class TestExtremeRain:
    def test_severity_is_critical(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        assert engine.state.zones[ZONE].severity == ZoneSeverity.CRITICAL

    def test_incident_severity_is_critical(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        assert engine.open_incidents()[0].severity == SeverityLevel.CRITICAL

    def test_risk_score_high(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        # rainfall 70 (0.4×0.7=0.28) + water 2.5 (0.3×0.833=0.25) + pop 3000 (0.2×0.6=0.12) = 0.65
        score = engine.open_incidents()[0].risk_score
        assert score >= 0.60

    def test_water_level_stored(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        assert engine.state.zones[ZONE].latest_water_level_m == 2.5

    def test_affected_population_stored(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        assert engine.state.zones[ZONE].affected_population == 3000

    def test_history_records_created(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        assert len(engine.history) == len(SCENARIO_EXTREME_RAIN)

    def test_overall_severity_critical(self, engine):
        for event in SCENARIO_EXTREME_RAIN:
            engine.process(event)
        assert engine.state.overall_severity == ZoneSeverity.CRITICAL

    def test_first_record_creates_incident(self, engine):
        record = engine.process(SCENARIO_EXTREME_RAIN[0])
        assert len(record.incidents_created) == 1
