"""Unit tests for the Incident domain model."""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from src.models.incident import Incident, IncidentStatus, SeverityLevel


# ── helpers ────────────────────────────────────────────────────────────────────

def minimal_incident(**overrides) -> dict:
    base = {
        "city": "TestCity",
        "zone_id": "TC-01",
        "severity": SeverityLevel.MEDIUM,
        "risk_score": 0.5,
        "title": "Test flood event",
    }
    base.update(overrides)
    return base


# ── valid construction ─────────────────────────────────────────────────────────

class TestIncidentValid:
    def test_minimal(self):
        inc = Incident(**minimal_incident())
        assert inc.status == IncidentStatus.OPEN
        assert inc.risk_score == 0.5

    def test_boundary_risk_scores(self):
        Incident(**minimal_incident(risk_score=0.0))
        Incident(**minimal_incident(risk_score=1.0))

    def test_affected_zones_with_primary(self):
        inc = Incident(**minimal_incident(
            affected_zone_ids=["TC-01", "TC-02", "TC-03"]
        ))
        assert "TC-01" in inc.affected_zone_ids

    def test_resolved_with_timestamp(self):
        now = datetime.now(timezone.utc)
        inc = Incident(**minimal_incident(
            status=IncidentStatus.RESOLVED,
            resolved_at=now,
        ))
        assert inc.resolved_at == now

    def test_auto_id_uuid(self):
        import uuid
        inc = Incident(**minimal_incident())
        uuid.UUID(inc.id)

    def test_whitespace_stripped(self):
        inc = Incident(**minimal_incident(city="  A  ", zone_id=" Z1 "))
        assert inc.city == "A"
        assert inc.zone_id == "Z1"


# ── invalid construction ───────────────────────────────────────────────────────

class TestIncidentInvalid:
    def test_risk_score_above_1_raises(self):
        with pytest.raises(ValidationError):
            Incident(**minimal_incident(risk_score=1.01))

    def test_risk_score_below_0_raises(self):
        with pytest.raises(ValidationError):
            Incident(**minimal_incident(risk_score=-0.01))

    def test_resolved_at_without_resolved_status_raises(self):
        with pytest.raises(ValidationError, match="resolved_at may only be set"):
            Incident(**minimal_incident(
                status=IncidentStatus.OPEN,
                resolved_at=datetime.now(timezone.utc),
            ))

    def test_primary_zone_missing_from_affected_raises(self):
        with pytest.raises(ValidationError, match="must be in affected_zone_ids"):
            Incident(**minimal_incident(
                zone_id="TC-01",
                affected_zone_ids=["TC-02", "TC-03"],  # TC-01 absent
            ))

    def test_empty_title_raises(self):
        with pytest.raises(ValidationError):
            Incident(**minimal_incident(title=""))

    def test_empty_city_raises(self):
        with pytest.raises(ValidationError):
            Incident(**minimal_incident(city=""))
