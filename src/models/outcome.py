"""Outcome model — the recorded result of an Action.

Outcomes close the feedback loop.  They capture what actually happened after
a resource was dispatched, enabling the situation state to be updated and
historic patterns to be analysed.

Flow position:
  Evidence → SituationState → Incidents → Priority → Action → **Outcome**
  (Outcome feeds back into SituationState in V2)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class Outcome(BaseModel):
    """The observed result after an Action was executed.

    ``severity_after`` captures the zone's severity at the time the outcome
    was recorded — a snapshot that lets analysts compare before/after
    without replaying the full event log.

    ``effectiveness_score`` is an optional 0–1 float.  In V1 it can be
    set manually or left None.  The V2 feedback loop will compute it
    automatically from severity_before / severity_after.

    Example::

        outcome = Outcome(
            action_id="<uuid>",
            incident_id="<uuid>",
            success=True,
            severity_after="normal",
            notes="Zone dewatered in 3 hours. Road re-opened.",
        )
    """

    # ── identity ──────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── links ─────────────────────────────────────────────────────────────
    action_id: str = Field(..., min_length=1, description="ID of the completed Action.")
    incident_id: str = Field(..., min_length=1, description="ID of the addressed Incident.")

    # ── result ────────────────────────────────────────────────────────────
    success: bool = Field(
        ...,
        description="True if the action achieved its intended goal.",
    )
    severity_after: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Zone severity level observed after action completion.",
    )
    notes: str = Field(
        default="",
        max_length=2000,
        description="Narrative summary: what happened, what changed, lessons learned.",
    )
    effectiveness_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Optional 0–1 effectiveness rating. "
            "None = not yet assessed; 1.0 = fully effective."
        ),
    )

    # ── timestamps ────────────────────────────────────────────────────────
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("action_id", "incident_id", "severity_after", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def failed_outcome_needs_notes(self) -> Outcome:
        """Require notes when an action failed — forces explicit documentation."""
        if not self.success and not self.notes.strip():
            raise ValueError(
                "An unsuccessful outcome must include notes explaining what went wrong."
            )
        return self

    model_config = {"frozen": False, "extra": "forbid"}
