"""IncidentContext — input data package for priority scoring.

An IncidentContext bundles the core Incident with the five contextual factors
that the Incident model itself does not carry.  All contextual fields are
optional so that partial information can still produce a valid score — missing
fields simply contribute zero to that factor.

Fields
------
incident
    The Incident being scored.  Required.

critical_facility_count
    Number of critical facilities (hospitals, fire stations, emergency
    shelters, schools used as relief camps) within the affected zone.
    Drives the ``critical_facility`` factor.
    0 = no facilities at risk.  No upper bound — scores are clamped at 1.0.

road_blocked
    True if the primary arterial road serving the zone is blocked.
    Drives the ``road_disruption`` factor.

affected_population
    Estimated number of residents directly affected by this incident.
    Drives the ``population_impact`` factor.
    None = unknown (contributes 0).

hours_until_deadline
    Estimated hours remaining before the situation becomes unrecoverable
    (e.g. residential evacuation window, pumping capacity exceeded).
    None = no deadline pressure (contributes 0).
    Values below ``deadline_critical_hrs`` produce maximum urgency.

infra_dependency_count
    Number of shared infrastructure assets (pumping stations, trunk sewers,
    power sub-stations) whose failure would amplify this incident.
    None / 0 = no shared dependency (contributes 0).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.models.incident import Incident


class IncidentContext(BaseModel):
    """Input bundle for the IncidentPriorityEngine.

    Example::

        ctx = IncidentContext(
            incident=inc,
            critical_facility_count=2,
            road_blocked=True,
            affected_population=1800,
            hours_until_deadline=3.0,
            infra_dependency_count=2,
        )
    """

    incident: Incident

    critical_facility_count: int = Field(
        default=0,
        ge=0,
        description="Critical facilities (hospitals, fire stations, shelters) at risk.",
    )
    road_blocked: bool = Field(
        default=False,
        description="True if the primary road serving this zone is blocked.",
    )
    affected_population: int | None = Field(
        default=None,
        ge=0,
        description="Estimated directly affected residents.",
    )
    hours_until_deadline: float | None = Field(
        default=None,
        ge=0.0,
        description="Hours remaining before situation becomes unrecoverable.",
    )
    infra_dependency_count: int = Field(
        default=0,
        ge=0,
        description="Shared infrastructure assets whose failure would amplify this incident.",
    )

    model_config = {"frozen": False, "extra": "forbid"}
