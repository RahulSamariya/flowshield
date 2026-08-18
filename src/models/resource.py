"""Resource model — a deployable asset (pump, team, vehicle, shelter).

Resources are managed by the planner stage.  The planner matches available
resources to open incidents and produces Actions.

Flow position:
  Evidence → SituationState → Incidents → Priority → **Resources** (input to planner)
  → Action → Outcome
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class ResourceType(StrEnum):
    """Broad categories of deployable flood-response assets."""

    PUMP = "pump"                   # Dewatering pump unit
    RESCUE_TEAM = "rescue_team"     # Search-and-rescue personnel
    VEHICLE = "vehicle"             # Boat, truck, or ambulance
    SHELTER = "shelter"             # Evacuation centre or relief camp
    MEDICAL = "medical"             # Medical unit or first-aid team
    OTHER = "other"


class ResourceStatus(StrEnum):
    """Availability lifecycle of a resource."""

    AVAILABLE = "available"         # Ready to be assigned
    DEPLOYED = "deployed"           # Currently assigned to an incident
    UNAVAILABLE = "unavailable"     # Out of service / maintenance
    STANDBY = "standby"             # On alert but not yet dispatched


class Resource(BaseModel):
    """A single deployable flood-response asset.

    ``capacity`` semantics depend on type:
    - PUMP: litres per hour
    - RESCUE_TEAM / MEDICAL: number of personnel
    - VEHICLE: number of passengers / tonne payload
    - SHELTER: maximum occupancy (persons)
    - OTHER: context-dependent

    ``current_zone_id`` is nullable because a resource may be in transit or
    at a depot not assigned to any zone.

    Example::

        pump = Resource(
            city="Rajkot",
            type=ResourceType.PUMP,
            name="Pump Unit 4 — South Depot",
            capacity=5000,
            current_zone_id="RJK-S02",
        )
    """

    # ── identity ──────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Human-readable label (e.g. 'Rescue Team Alpha').",
    )

    # ── provenance ────────────────────────────────────────────────────────
    city: str = Field(..., min_length=1, max_length=100)
    type: ResourceType = Field(..., description="Category of this resource.")

    # ── location ──────────────────────────────────────────────────────────
    home_zone_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Zone where this resource is normally stationed.",
    )
    current_zone_id: str | None = Field(
        default=None,
        description="Zone where the resource is right now; None if in transit.",
    )

    # ── capacity ──────────────────────────────────────────────────────────
    capacity: int | None = Field(
        default=None,
        ge=1,
        description="Numeric capacity; units depend on resource type.",
    )

    # ── lifecycle ─────────────────────────────────────────────────────────
    status: ResourceStatus = Field(default=ResourceStatus.AVAILABLE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # ── metadata ──────────────────────────────────────────────────────────
    notes: str = Field(
        default="",
        max_length=1000,
        description="Free-text operational notes (condition, restrictions, etc.).",
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("city", "home_zone_id", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def deployed_requires_current_zone(self) -> Resource:
        """A deployed resource must know its current zone."""
        if self.status == ResourceStatus.DEPLOYED and self.current_zone_id is None:
            raise ValueError(
                "A resource with status DEPLOYED must have a current_zone_id."
            )
        return self

    model_config = {"frozen": False, "extra": "forbid"}
