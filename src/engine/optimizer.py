"""ResourceOptimizer — interface and greedy implementation.

Interface
---------
``ResourceOptimizer`` is a ``typing.Protocol``.  Any class that implements
``optimize(request: OptimizationRequest) -> OptimizationResult`` satisfies it.
The greedy implementation below is the V1 default.  A future ILP or ML-based
optimizer can be swapped in without touching any caller.

GreedyResourceOptimizer — algorithm
------------------------------------
Process incidents in priority-score order (highest first).  For each incident:

  1. Filter candidates
     Keep only resources that are:
     - not yet assigned in this run
     - capable of handling the incident's severity
     - within max_travel_minutes of the incident zone

  2. Compute fit_score per candidate
     fit_score = capability_weight * 1.0
               + proximity_weight  * (1 - travel / max_travel)
     where:
       capability_weight = 0.40
       proximity_weight  = 0.60

  3. Select best candidate
     The resource with the highest fit_score wins.
     Tie-break: alphabetical resource_id (stable, reproducible).

  4. Emit Assignment or UnassignedIncident
     Assignment carries reason code(s):
       OA_BEST_FIT       — normal case (≥ 2 eligible candidates)
       OA_ONLY_AVAILABLE — only one eligible candidate
       OA_NEAREST        — all candidates had equal capability; proximity decided
     UnassignedIncident carries one of:
       UA_NO_RESOURCE          — resource list is empty
       UA_NO_CAPABLE_RESOURCE  — no resource can handle this severity
       UA_ALL_TOO_FAR          — capable resources exist but all exceed travel limit
       UA_CAPACITY_EXHAUSTED   — resources_per_incident cap reached (future use)

Travel time
-----------
``distances[zone_a][zone_b]`` = minutes (symmetric matrix supplied by caller).
Same-zone travel = 0 minutes.
Missing pairs → ``max_travel_minutes`` (treated as unreachable).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.engine.optimizer_request import OptimizationRequest
from src.engine.optimizer_result import (
    OA_BEST_FIT,
    OA_NEAREST,
    OA_ONLY_AVAILABLE,
    UA_ALL_TOO_FAR,
    UA_NO_CAPABLE_RESOURCE,
    UA_NO_RESOURCE,
    Assignment,
    OptimizationResult,
    UnassignedIncident,
)
from src.models.incident import SeverityLevel
from src.models.resource import Resource, ResourceType

# ── interface ─────────────────────────────────────────────────────────────────

@runtime_checkable
class ResourceOptimizer(Protocol):
    """Protocol satisfied by any optimizer implementation.

    Callers depend only on this interface.  To swap implementations::

        optimizer: ResourceOptimizer = GreedyResourceOptimizer()
        # later:
        optimizer = ILPResourceOptimizer()   # V2 — same interface
    """

    def optimize(self, request: OptimizationRequest) -> OptimizationResult:
        """Assign available resources to prioritised incidents.

        Parameters
        ----------
        request:
            Full input bundle (incidents, resources, capabilities, distances).

        Returns
        -------
        OptimizationResult
            All assignments and all unassigned incidents, with reason codes.
        """
        ...


# ── fit scoring constants ─────────────────────────────────────────────────────

_W_CAPABILITY = 0.40
_W_PROXIMITY  = 0.60


# ── greedy implementation ─────────────────────────────────────────────────────

class GreedyResourceOptimizer:
    """Deterministic greedy optimizer — O(I × R) per run.

    Processes incidents from highest to lowest priority score.
    For each incident, picks the best available resource by fit_score.

    Stateless: a single instance can be reused across many ``optimize()`` calls.
    """

    def optimize(self, request: OptimizationRequest) -> OptimizationResult:
        result = OptimizationResult()

        # Build fast capability lookup: ResourceType → ResourceCapability
        cap_map = {c.resource_type: c for c in request.capabilities}

        # Track which resources are consumed in this run
        consumed: set[str] = set()

        # Track how many resources have been assigned per incident
        incident_assignment_count: dict[str, int] = {}

        for priority_result in request.prioritized_incidents:
            incident_id = priority_result.incident_id
            incident_zone = request.incident_zones.get(incident_id, "")

            # Resolve severity from the incident — we need it for capability filtering.
            # PriorityResult carries the incident_id but not severity directly; we
            # identify severity from the factor breakdown to stay decoupled.
            severity = _severity_from_priority_result(priority_result)

            # ── check resources_per_incident cap ─────────────────────────────
            already_assigned = incident_assignment_count.get(incident_id, 0)
            if already_assigned >= request.resources_per_incident:
                # Should not occur in V1 (cap=1), kept for future multi-resource mode
                continue

            # ── filter candidates ─────────────────────────────────────────────
            candidates = _filter_candidates(
                incident_id=incident_id,
                incident_zone=incident_zone,
                severity=severity,
                available=request.available_resources,
                consumed=consumed,
                cap_map=cap_map,
                distances=request.distances,
                max_travel=request.max_travel_minutes,
            )

            if not candidates:
                reason = _unassigned_reason(
                    incident_id=incident_id,
                    severity=severity,
                    available=request.available_resources,
                    consumed=consumed,
                    cap_map=cap_map,
                    incident_zone=incident_zone,
                    distances=request.distances,
                    max_travel=request.max_travel_minutes,
                )
                result.unassigned_incidents.append(
                    UnassignedIncident(
                        incident_id=incident_id,
                        priority_score=priority_result.score,
                        reason_codes=(reason,),
                    )
                )
                continue

            # ── score candidates ──────────────────────────────────────────────
            scored = [
                (res, _fit_score(res, incident_zone, request))
                for res in candidates
            ]
            # Stable sort: score desc, then resource_id asc for tie-breaking
            scored.sort(key=lambda x: (-x[1], x[0].id))

            best_resource, best_score = scored[0]
            travel = _travel_minutes(
                request.resource_zones.get(best_resource.id, ""),
                incident_zone,
                request.distances,
                request.max_travel_minutes,
            )

            # ── choose reason code ────────────────────────────────────────────
            reason_codes = _assignment_reason(scored, incident_zone, request)

            assignment = Assignment(
                incident_id=incident_id,
                resource_id=best_resource.id,
                incident_zone=incident_zone,
                resource_zone=request.resource_zones.get(best_resource.id, ""),
                estimated_travel_minutes=round(travel, 2),
                fit_score=round(best_score, 4),
                reason_codes=reason_codes,
            )
            result.assignments.append(assignment)
            consumed.add(best_resource.id)
            incident_assignment_count[incident_id] = already_assigned + 1

        # Sort unassigned by priority_score descending (most critical gap first)
        result.unassigned_incidents.sort(
            key=lambda u: u.priority_score, reverse=True
        )
        return result


# ── helpers ───────────────────────────────────────────────────────────────────

def _severity_from_priority_result(pr) -> SeverityLevel:
    """Extract severity from the 'severity' factor in PriorityResult.

    Falls back to CRITICAL if the factor is absent (defensive).
    """
    f = pr.factor("severity") if hasattr(pr, "factor") else None
    if f is None:
        return SeverityLevel.CRITICAL
    raw = f.raw_value
    try:
        return SeverityLevel(str(raw).lower())
    except ValueError:
        return SeverityLevel.CRITICAL


def _travel_minutes(
    from_zone: str,
    to_zone: str,
    distances: dict[str, dict[str, float]],
    default: float,
) -> float:
    """Return travel time between two zones; 0 for same zone."""
    if from_zone == to_zone:
        return 0.0
    return distances.get(from_zone, {}).get(to_zone, default)


def _fit_score(
    resource: Resource,
    incident_zone: str,
    request: OptimizationRequest,
) -> float:
    """Compute fit_score for one resource/incident pair."""
    travel = _travel_minutes(
        request.resource_zones.get(resource.id, ""),
        incident_zone,
        request.distances,
        request.max_travel_minutes,
    )
    proximity = 1.0 - (travel / request.max_travel_minutes)
    return _W_CAPABILITY * 1.0 + _W_PROXIMITY * proximity


def _filter_candidates(
    incident_id: str,
    incident_zone: str,
    severity: SeverityLevel,
    available: list[Resource],
    consumed: set[str],
    cap_map: dict[ResourceType, object],
    distances: dict[str, dict[str, float]],
    max_travel: float,
) -> list[Resource]:
    result = []
    for res in available:
        if res.id in consumed:
            continue
        cap = cap_map.get(res.type)
        if cap is None or not cap.can_handle(severity):
            continue
        travel = _travel_minutes(
            res.current_zone_id or res.home_zone_id,
            incident_zone,
            distances,
            max_travel,
        )
        if travel > max_travel:
            continue
        result.append(res)
    return result


def _unassigned_reason(
    incident_id: str,
    severity: SeverityLevel,
    available: list[Resource],
    consumed: set[str],
    cap_map: dict[ResourceType, object],
    incident_zone: str,
    distances: dict[str, dict[str, float]],
    max_travel: float,
) -> str:
    """Determine the precise reason no resource could be assigned."""
    unconsumed = [r for r in available if r.id not in consumed]
    if not unconsumed:
        return UA_NO_RESOURCE

    capable = [
        r for r in unconsumed
        if (c := cap_map.get(r.type)) is not None and c.can_handle(severity)
    ]
    if not capable:
        return UA_NO_CAPABLE_RESOURCE

    # Capable resources exist — check distance
    reachable = [
        r for r in capable
        if _travel_minutes(
            r.current_zone_id or r.home_zone_id,
            incident_zone,
            distances,
            max_travel,
        ) <= max_travel
    ]
    if not reachable:
        return UA_ALL_TOO_FAR

    return UA_NO_RESOURCE  # fallback (should not be reached)


def _assignment_reason(
    scored: list[tuple[Resource, float]],
    incident_zone: str,
    request: OptimizationRequest,
) -> tuple[str, ...]:
    """Pick the appropriate reason code for a successful assignment."""
    if len(scored) == 1:
        return (OA_ONLY_AVAILABLE,)

    # Check if proximity was the deciding factor (all top candidates same capability)
    best_score = scored[0][1]
    runner_up_score = scored[1][1] if len(scored) > 1 else -1.0

    best_travel = _travel_minutes(
        request.resource_zones.get(scored[0][0].id, ""),
        incident_zone,
        request.distances,
        request.max_travel_minutes,
    )
    # If scores differ only due to proximity contribution
    scores_equal_capability = abs(best_score - runner_up_score) <= _W_PROXIMITY * 0.01
    if scores_equal_capability and best_travel == 0.0:
        return (OA_NEAREST,)

    return (OA_BEST_FIT,)
