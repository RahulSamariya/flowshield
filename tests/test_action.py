"""Unit tests for the Action domain model."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.models.action import Action, ActionStatus

# ── helpers ────────────────────────────────────────────────────────────────────

def minimal_action(**overrides) -> dict:
    base = {
        "incident_id": "inc-001",
        "resource_id": "res-001",
        "decided_by": "rule_engine_v1",
        "decision_rationale": "Closest available pump to highest risk zone.",
    }
    base.update(overrides)
    return base


# ── valid construction ─────────────────────────────────────────────────────────

class TestActionValid:
    def test_minimal(self):
        a = Action(**minimal_action())
        assert a.status == ActionStatus.PENDING
        assert a.priority == 1

    def test_done_with_timestamps(self):
        now = datetime.now(UTC)
        started = now - timedelta(hours=2)
        a = Action(**minimal_action(
            status=ActionStatus.DONE,
            started_at=started,
            completed_at=now,
        ))
        assert a.completed_at == now

    def test_auto_id_uuid(self):
        import uuid
        a = Action(**minimal_action())
        uuid.UUID(a.id)

    def test_all_statuses_constructable(self):
        for s in ActionStatus:
            if s in (ActionStatus.DONE, ActionStatus.FAILED, ActionStatus.CANCELLED):
                Action(**minimal_action(
                    status=s,
                    completed_at=datetime.now(UTC),
                ))
            else:
                Action(**minimal_action(status=s))

    def test_high_priority(self):
        a = Action(**minimal_action(priority=99))
        assert a.priority == 99

    def test_whitespace_stripped(self):
        a = Action(**minimal_action(decided_by="  agent  "))
        assert a.decided_by == "agent"


# ── invalid construction ───────────────────────────────────────────────────────

class TestActionInvalid:
    def test_completed_at_without_terminal_status_raises(self):
        with pytest.raises(ValidationError, match="completed_at may only be set"):
            Action(**minimal_action(
                status=ActionStatus.PENDING,
                completed_at=datetime.now(UTC),
            ))

    def test_started_after_completed_raises(self):
        now = datetime.now(UTC)
        with pytest.raises(ValidationError, match="started_at must not be after completed_at"):
            Action(**minimal_action(
                status=ActionStatus.DONE,
                started_at=now + timedelta(hours=1),
                completed_at=now,
            ))

    def test_zero_priority_raises(self):
        with pytest.raises(ValidationError):
            Action(**minimal_action(priority=0))

    def test_empty_rationale_raises(self):
        with pytest.raises(ValidationError):
            Action(**minimal_action(decision_rationale=""))

    def test_empty_incident_id_raises(self):
        with pytest.raises(ValidationError):
            Action(**minimal_action(incident_id=""))
