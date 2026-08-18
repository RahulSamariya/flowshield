"""Unit tests for the SituationState and ZoneStatus domain models."""

import pytest
from pydantic import ValidationError

from src.models.situation import SituationState, ZoneSeverity, ZoneStatus

# ── ZoneStatus ─────────────────────────────────────────────────────────────────

class TestZoneStatus:
    def test_defaults(self):
        zs = ZoneStatus(zone_id="Z1")
        assert zs.severity == ZoneSeverity.NORMAL
        assert zs.road_blocked is False
        assert zs.evidence_count == 0

    def test_critical_severity(self):
        zs = ZoneStatus(zone_id="Z2", severity=ZoneSeverity.CRITICAL, latest_rainfall_mm_hr=90.0)
        assert zs.severity == ZoneSeverity.CRITICAL

    def test_negative_rainfall_raises(self):
        with pytest.raises(ValidationError):
            ZoneStatus(zone_id="Z3", latest_rainfall_mm_hr=-0.1)


# ── SituationState ─────────────────────────────────────────────────────────────

class TestSituationState:
    def test_empty_state(self):
        state = SituationState(city="TestCity")
        assert state.city == "TestCity"
        assert state.zones == {}
        assert state.overall_severity == ZoneSeverity.NORMAL

    def test_overall_severity_picks_highest(self):
        state = SituationState(city="TestCity", zones={
            "Z1": ZoneStatus(zone_id="Z1", severity=ZoneSeverity.WATCH),
            "Z2": ZoneStatus(zone_id="Z2", severity=ZoneSeverity.CRITICAL),
            "Z3": ZoneStatus(zone_id="Z3", severity=ZoneSeverity.WARNING),
        })
        assert state.overall_severity == ZoneSeverity.CRITICAL

    def test_overall_severity_single_zone(self):
        state = SituationState(city="C", zones={
            "Z1": ZoneStatus(zone_id="Z1", severity=ZoneSeverity.WARNING),
        })
        assert state.overall_severity == ZoneSeverity.WARNING

    def test_zone_key_mismatch_raises(self):
        with pytest.raises(ValidationError, match="does not match zone.zone_id"):
            SituationState(city="C", zones={
                "WRONG_KEY": ZoneStatus(zone_id="Z1", severity=ZoneSeverity.NORMAL),
            })

    def test_whitespace_stripped_from_city(self):
        state = SituationState(city="  MyCity  ")
        assert state.city == "MyCity"

    def test_auto_id(self):
        import uuid
        state = SituationState(city="C")
        uuid.UUID(state.id)

    def test_add_zone_post_construction(self):
        state = SituationState(city="C")
        state.zones["Z9"] = ZoneStatus(zone_id="Z9", severity=ZoneSeverity.WARNING)
        assert state.overall_severity == ZoneSeverity.WARNING
