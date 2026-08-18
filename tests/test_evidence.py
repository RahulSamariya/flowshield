"""Unit tests for the Evidence domain model."""

import pytest
from pydantic import ValidationError

from src.models.evidence import Evidence, EvidenceSource

# ── helpers ───────────────────────────────────────────────────────────────────

def minimal_evidence(**overrides) -> dict:
    """Return a minimal valid Evidence payload."""
    base = {
        "city": "TestCity",
        "zone_id": "TC-01",
        "source": EvidenceSource.MOCK,
        "rainfall_mm_hr": 10.0,
    }
    base.update(overrides)
    return base


# ── valid construction ─────────────────────────────────────────────────────────

class TestEvidenceValid:
    def test_minimal_fields(self):
        ev = Evidence(**minimal_evidence())
        assert ev.city == "TestCity"
        assert ev.zone_id == "TC-01"
        assert ev.source == EvidenceSource.MOCK
        assert ev.rainfall_mm_hr == 10.0
        assert ev.id  # auto-generated

    def test_auto_id_is_uuid(self):
        import uuid
        ev = Evidence(**minimal_evidence())
        uuid.UUID(ev.id)  # raises if not valid UUID

    def test_all_optional_measurements(self):
        ev = Evidence(**minimal_evidence(
            rainfall_mm_hr=55.0,
            water_level_m=1.2,
            road_blocked=True,
            affected_population=400,
        ))
        assert ev.water_level_m == 1.2
        assert ev.road_blocked is True
        assert ev.affected_population == 400

    def test_road_blocked_alone_is_valid(self):
        ev = Evidence(
            city="Any",
            zone_id="Z1",
            source=EvidenceSource.CITIZEN_REPORT,
            road_blocked=True,
        )
        assert ev.road_blocked is True

    def test_whitespace_stripped_from_city_and_zone(self):
        ev = Evidence(**minimal_evidence(city="  Spaces  ", zone_id=" Z-01 "))
        assert ev.city == "Spaces"
        assert ev.zone_id == "Z-01"

    def test_raw_preserved(self):
        raw = {"original_key": "original_value", "nested": {"a": 1}}
        ev = Evidence(**minimal_evidence(raw=raw))
        assert ev.raw == raw

    def test_zero_rainfall_is_valid(self):
        ev = Evidence(**minimal_evidence(rainfall_mm_hr=0.0))
        assert ev.rainfall_mm_hr == 0.0


# ── invalid construction ───────────────────────────────────────────────────────

class TestEvidenceInvalid:
    def test_no_measurement_raises(self):
        with pytest.raises(ValidationError, match="at least one measurement"):
            Evidence(city="C", zone_id="Z", source=EvidenceSource.MOCK)

    def test_negative_rainfall_raises(self):
        with pytest.raises(ValidationError):
            Evidence(**minimal_evidence(rainfall_mm_hr=-1.0))

    def test_empty_city_raises(self):
        with pytest.raises(ValidationError):
            Evidence(**minimal_evidence(city=""))

    def test_empty_zone_id_raises(self):
        with pytest.raises(ValidationError):
            Evidence(**minimal_evidence(zone_id=""))

    def test_negative_affected_population_raises(self):
        with pytest.raises(ValidationError):
            Evidence(**minimal_evidence(affected_population=-5))

    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            Evidence(**minimal_evidence(unknown_field="oops"))
