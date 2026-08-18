"""Optimizer input contracts.

OptimizationRequest is the single input to ResourceOptimizer.optimize().
It bundles everything the optimizer needs without importing engine internals.

Key design choices
------------------
- ``prioritized_incidents`` is already scored + ordered by the caller
  (IncidentPriorityEngine).  The optimizer never re-scores.

- ``distances`` is a symmetric travel-time matrix expressed as
  ``dict[zone_id → dict[zone_id → minutes]]``.
  Missing pairs default to ``max_travel_minutes`` (treated as unreachable).

- ``capabilities`` maps each ResourceType to the set of SeverityLevel values
  it can handle.  A resource that cannot handle an incident's severity is
  never assigned to it, regardless of availability or proximity.

- Constraints live directly on the request so they can be varied per-run
  without touching resource data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.engine.priority_result import PriorityResult
from src.models.incident import SeverityLevel
from src.models.resource import Resource, ResourceType


@dataclass(frozen=True)
class ResourceCapability:
    """Declares which severity levels a resource type can respond to.

    Example — a pump can handle any severity, but a rescue team cannot
    respond to a LOW/WATCH waterlogging without specific equipment::

        ResourceCapability(
            resource_type=ResourceType.PUMP,
            handles_severities=frozenset({
                SeverityLevel.LOW,
                SeverityLevel.MEDIUM,
                SeverityLevel.HIGH,
                SeverityLevel.CRITICAL,
            }),
        )
    """

    resource_type: ResourceType
    handles_severities: frozenset[SeverityLevel]

    def can_handle(self, severity: SeverityLevel) -> bool:
        return severity in self.handles_severities


# ── default capability table ──────────────────────────────────────────────────
# Callers can override by supplying their own capabilities list.

ALL_SEVERITIES: frozenset[SeverityLevel] = frozenset(SeverityLevel)

DEFAULT_CAPABILITIES: list[ResourceCapability] = [
    ResourceCapability(ResourceType.PUMP,         ALL_SEVERITIES),
    ResourceCapability(ResourceType.RESCUE_TEAM,  ALL_SEVERITIES),
    ResourceCapability(ResourceType.VEHICLE,       ALL_SEVERITIES),
    ResourceCapability(ResourceType.SHELTER,       frozenset({
        SeverityLevel.LOW, SeverityLevel.MEDIUM,
        SeverityLevel.HIGH, SeverityLevel.CRITICAL,
    })),
    ResourceCapability(ResourceType.MEDICAL,      ALL_SEVERITIES),
    ResourceCapability(ResourceType.OTHER,         frozenset({
        SeverityLevel.LOW, SeverityLevel.MEDIUM,
    })),
]


@dataclass
class OptimizationRequest:
    """Everything the optimizer needs to produce an assignment plan.

    Parameters
    ----------
    prioritized_incidents:
        Pre-scored PriorityResults, highest priority first.
        The optimizer processes them in this order.

    available_resources:
        Resources that are currently AVAILABLE (or STANDBY).
        The optimizer only assigns from this list.

    incident_zones:
        Mapping of incident_id → zone_id.  Required because PriorityResult
        does not carry zone_id directly.

    resource_zones:
        Mapping of resource_id → current zone_id.

    capabilities:
        One ResourceCapability per ResourceType.  Defaults to
        ``DEFAULT_CAPABILITIES`` if not supplied.

    distances:
        Travel-time matrix: ``distances[zone_a][zone_b]`` = minutes.
        Missing pairs are treated as ``max_travel_minutes``.
        An empty dict means "all zones equidistant".

    max_travel_minutes:
        Resources further away than this are ineligible for assignment.
        Default: 60 minutes.

    resources_per_incident:
        Maximum number of resources that may be assigned to one incident.
        Default: 1 (single-resource assignments only in V1).
    """

    prioritized_incidents: list[PriorityResult]
    available_resources: list[Resource]
    incident_zones: dict[str, str]           # incident_id → zone_id
    resource_zones: dict[str, str]           # resource_id → zone_id
    capabilities: list[ResourceCapability] = field(
        default_factory=lambda: list(DEFAULT_CAPABILITIES)
    )
    distances: dict[str, dict[str, float]] = field(default_factory=dict)
    max_travel_minutes: float = 60.0
    resources_per_incident: int = 1
