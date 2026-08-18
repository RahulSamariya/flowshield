"""Optimizer output contracts.

OptimizationResult is returned by ResourceOptimizer.optimize().
Every decision is recorded with its rationale — no silent assignments.

Assignment reason codes
-----------------------
OA_BEST_FIT         Resource was the highest-scoring eligible candidate.
OA_ONLY_AVAILABLE   Resource was the only eligible available option.
OA_NEAREST          Resource was the nearest eligible option.

Unassigned reason codes
-----------------------
UA_NO_RESOURCE          No available resource of any capable type.
UA_NO_CAPABLE_RESOURCE  Available resources exist but none can handle severity.
UA_ALL_TOO_FAR          Capable resources exist but all exceed max_travel_minutes.
UA_CAPACITY_EXHAUSTED   resources_per_incident limit reached for this incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── assignment reason codes ────────────────────────────────────────────────────
OA_BEST_FIT         = "OA_BEST_FIT"
OA_ONLY_AVAILABLE   = "OA_ONLY_AVAILABLE"
OA_NEAREST          = "OA_NEAREST"

# ── unassigned reason codes ───────────────────────────────────────────────────
UA_NO_RESOURCE          = "UA_NO_RESOURCE"
UA_NO_CAPABLE_RESOURCE  = "UA_NO_CAPABLE_RESOURCE"
UA_ALL_TOO_FAR          = "UA_ALL_TOO_FAR"
UA_CAPACITY_EXHAUSTED   = "UA_CAPACITY_EXHAUSTED"


@dataclass(frozen=True)
class Assignment:
    """A single resource-to-incident assignment decision.

    Attributes
    ----------
    incident_id
        ID of the incident being addressed.
    resource_id
        ID of the assigned resource.
    incident_zone
        Zone of the incident.
    resource_zone
        Zone the resource is coming from.
    estimated_travel_minutes
        Estimated travel time from resource zone to incident zone.
    fit_score
        Internal score used to select this resource [0.0, 1.0].
        Higher = better fit.  Useful for audit / explanation.
    reason_codes
        Why this resource was chosen for this incident.
    """

    incident_id: str
    resource_id: str
    incident_zone: str
    resource_zone: str
    estimated_travel_minutes: float
    fit_score: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class UnassignedIncident:
    """An incident that could not be assigned any resource.

    Attributes
    ----------
    incident_id
        ID of the unserviced incident.
    priority_score
        The incident's priority score (higher = more critical gap).
    reason_codes
        Why no assignment was possible.
    """

    incident_id: str
    priority_score: float
    reason_codes: tuple[str, ...]


@dataclass
class OptimizationResult:
    """The complete output of one optimizer run.

    Attributes
    ----------
    assignments
        All successful resource-to-incident assignments.
    unassigned_incidents
        Incidents that received no resource, ordered by priority_score desc.
    assigned_resource_ids
        Set of resource IDs consumed by this plan (convenience accessor).
    """

    assignments: list[Assignment] = field(default_factory=list)
    unassigned_incidents: list[UnassignedIncident] = field(default_factory=list)

    @property
    def assigned_resource_ids(self) -> frozenset[str]:
        return frozenset(a.resource_id for a in self.assignments)

    @property
    def assigned_incident_ids(self) -> frozenset[str]:
        return frozenset(a.incident_id for a in self.assignments)

    def assignment_for(self, incident_id: str) -> Assignment | None:
        """Return the Assignment for the given incident, or None."""
        for a in self.assignments:
            if a.incident_id == incident_id:
                return a
        return None

    def unassigned_for(self, incident_id: str) -> UnassignedIncident | None:
        """Return the UnassignedIncident record, or None if it was assigned."""
        for u in self.unassigned_incidents:
            if u.incident_id == incident_id:
                return u
        return None
