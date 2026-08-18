"""Unit tests for the Outcome domain model."""

import pytest
from pydantic import ValidationError

from src.models.outcome import Outcome

# ── helpers ────────────────────────────────────────────────────────────────────

def minimal_outcome(**overrides) -> dict:
    base = {
        "action_id": "act-001",
        "incident_id": "inc-001",
        "success": True,
        "severity_after": "normal",
    }
    base.update(overrides)
    return base


# ── valid construction ─────────────────────────────────────────────────────────

class TestOutcomeValid:
    def test_successful_minimal(self):
        o = Outcome(**minimal_outcome())
        assert o.success is True
        assert o.severity_after == "normal"
        assert o.effectiveness_score is None

    def test_failed_with_notes(self):
        o = Outcome(**minimal_outcome(
            success=False,
            severity_after="critical",
            notes="Pump broke down en route. Backup dispatched.",
        ))
        assert o.success is False
        assert "Pump" in o.notes

    def test_effectiveness_score_boundary_values(self):
        Outcome(**minimal_outcome(effectiveness_score=0.0))
        Outcome(**minimal_outcome(effectiveness_score=1.0))
        Outcome(**minimal_outcome(effectiveness_score=0.75))

    def test_auto_id_uuid(self):
        import uuid
        o = Outcome(**minimal_outcome())
        uuid.UUID(o.id)

    def test_whitespace_stripped(self):
        o = Outcome(**minimal_outcome(severity_after="  warning  "))
        assert o.severity_after == "warning"


# ── invalid construction ───────────────────────────────────────────────────────

class TestOutcomeInvalid:
    def test_failed_without_notes_raises(self):
        with pytest.raises(ValidationError, match="unsuccessful outcome must include notes"):
            Outcome(**minimal_outcome(success=False, notes=""))

    def test_failed_with_whitespace_only_notes_raises(self):
        with pytest.raises(ValidationError, match="unsuccessful outcome must include notes"):
            Outcome(**minimal_outcome(success=False, notes="   "))

    def test_effectiveness_above_1_raises(self):
        with pytest.raises(ValidationError):
            Outcome(**minimal_outcome(effectiveness_score=1.01))

    def test_effectiveness_below_0_raises(self):
        with pytest.raises(ValidationError):
            Outcome(**minimal_outcome(effectiveness_score=-0.01))

    def test_empty_action_id_raises(self):
        with pytest.raises(ValidationError):
            Outcome(**minimal_outcome(action_id=""))

    def test_empty_severity_after_raises(self):
        with pytest.raises(ValidationError):
            Outcome(**minimal_outcome(severity_after=""))

    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            Outcome(**minimal_outcome(surprise="oops"))
