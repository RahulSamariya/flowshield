"""Incident model — a discrete flood event in one zone.

Incidents are created by the detector stage from a SituationState.
Each incident tracks a single flood event from detection through resolution.

Flow position:
  Evidence → SituationState → **Incidents** → Priority → Action → Outcome
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class SeverityLevel(StrEnum):
    """Incident severity — aligned with ZoneSeverity but independent.

    Incidents use the same four levels so they map cleanly to ZoneStatus, but
    they are defined separately because incident severity may diverge from
    zone severity in future pipeline versions (e.g. compound events).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    """Lifecycle status of an incident."""

    OPEN = "open"           # Detected, no action assigned yet
    ASSIGNED = "assigned"   # At least one Action is in progress
    RESOLVED = "resolved"   # Outcome recorded, zone back to normal
    CANCELLED = "cancelled" # False positive or duplicate — closed without action


class Incident(BaseModel):
    """A discrete flood event affecting one zone.

    ``risk_score`` is a normalised float in [0.0, 1.0] computed by the
    prioritizer.  It drives the ordering of the decision queue.

    ``affected_zone_ids`` supports multi-zone incidents (e.g. a blocked river
    channel spanning three wards) while keeping a single primary ``zone_id``.

    Example::

        inc = Incident(
            city="Vadodara",
            zone_id="VDR-N03",
            severity=SeverityLevel.HIGH,
            risk_score=0.78,
            title="Flash flood — north ward 3",
        )
    """

    # ── identity ──────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── provenance ────────────────────────────────────────────────────────
    city: str = Field(..., min_length=1, max_length=100)
    zone_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Primary zone where the incident was detected.",
    )
    affected_zone_ids: list[str] = Field(
        default_factory=list,
        description="All zones affected, including the primary zone.",
    )

    # ── classification ────────────────────────────────────────────────────
    severity: SeverityLevel = Field(..., description="Classified severity level.")
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalised risk score in [0, 1]. Higher = more urgent.",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Short human-readable description of the incident.",
    )
    description: str = Field(
        default="",
        max_length=2000,
        description="Extended narrative; populated by the detector or planner.",
    )

    # ── lifecycle ─────────────────────────────────────────────────────────
    status: IncidentStatus = Field(default=IncidentStatus.OPEN)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = Field(default=None)

    # ── source traceability ───────────────────────────────────────────────
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="IDs of Evidence records that triggered this incident.",
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("city", "zone_id", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def resolved_at_requires_resolved_status(self) -> "Incident":
        if self.resolved_at is not None and self.status not in (
            IncidentStatus.RESOLVED,
            IncidentStatus.CANCELLED,
        ):
            raise ValueError(
                "resolved_at may only be set when status is RESOLVED or CANCELLED."
            )
        return self

    @model_validator(mode="after")
    def primary_zone_in_affected(self) -> "Incident":
        """Primary zone_id must appear in affected_zone_ids when that list is non-empty."""
        if self.affected_zone_ids and self.zone_id not in self.affected_zone_ids:
            raise ValueError(
                f"Primary zone_id '{self.zone_id}' must be in affected_zone_ids."
            )
        return self

    model_config = {"frozen": False, "extra": "forbid"}
