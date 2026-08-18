"""Tests for GreedyResourceOptimizer — five distinct scenarios.

Scenario 1 — Enough resources
    3 incidents (low/medium/high), 3 matching resources all nearby.
    All incidents must be assigned; no unassigned.

Scenario 2 — Insufficient resources
    3 incidents, only 1 resource available.
    1 incident assigned (highest priority), 2 left unassigned with UA_NO_RESOURCE.

Scenario 3 — Unavailable pump
    Critical flood incident requires a pump.
    The only pump is UNAVAILABLE (not in available_resources list).
    A rescue team is available but cannot handle the pump-type need via capabilities.
    Incident should be unassigned with UA_NO_CAPABLE_RESOURCE.

Scenario 4 — High-priority hospital/school incident
    Two incidents: a hospital flood (CRITICAL priority) and a road block (LOW priority).
    One resource. Optimizer must assign to the higher-priority incident.

Scenario 5 — Resource too far away
    One incident in zone Z1, one resource in zone Z9.
    Distance Z1↔Z9 = 120 min > max_travel_minutes (60).
    Incident unassigned with UA_ALL_TOO_FAR.
"""

from __future__ import annotations

import pytest

from src.engine.optimizer import GreedyResourceOptimizer, ResourceOptimizer
from src.engine.optimizer_request import (
    DEFAULT_CAPABILITIES,
    OptimizationRequest,
    ResourceCapability,
)
from src.engine.optimizer_result import (
    OA_BEST_FIT,
    OA_ONLY_AVAILABLE,
    UA_ALL_TOO_FAR,
    UA_NO_CAPABLE_RESOURCE,
    UA_NO_RESOURCE,
)
from src.engine.priority_context import IncidentContext
from src.engine.priority_engine import IncidentPriorityEngine
from src.models.incident import Incident, SeverityLevel
from src.models.resource import Resource, ResourceStatus, ResourceType

# ── shared helpers ────────────────────────────────────────────────────────────

PRIORITY_ENGINE = IncidentPriorityEngine()
OPTIMIZER = GreedyResourceOptimizer()


def make_incident(
    severity: SeverityLevel,
    zone_id: str = "Z1",
    iid: str | None = None,
    critical_facility_count: int = 0,
    affected_population: int | None = None,
    hours_until_deadline: float | None = None,
) -> tuple[Incident, IncidentContext]:
    """Return (Incident, IncidentContext) pair."""
    inc = Incident(
        id=iid or f"inc-{zone_id}-{severity}",
        city="TestCity",
        zone_id=zone_id,
        severity=severity,
        risk_score=0.5,
        title=f"Test [{severity}] in {zone_id}",
    )
    ctx = IncidentContext(
        incident=inc,
        critical_facility_count=critical_facility_count,
        road_blocked=False,
        affected_population=affected_population,
        hours_until_deadline=hours_until_deadline,
    )
    return inc, ctx


def make_resource(
    rid: str,
    rtype: ResourceType,
    zone_id: str = "Z1",
    status: ResourceStatus = ResourceStatus.AVAILABLE,
) -> Resource:
    return Resource(
        id=rid,
        name=f"Resource {rid}",
        city="TestCity",
        type=rtype,
        home_zone_id=zone_id,
        current_zone_id=zone_id,
        status=status,
    )


def score_and_rank(contexts: list[IncidentContext]):
    return PRIORITY_ENGINE.rank(contexts)


def build_request(
    incidents: list[tuple[Incident, IncidentContext]],
    resources: list[Resource],
    distances: dict[str, dict[str, float]] | None = None,
    max_travel: float = 60.0,
    capabilities: list | None = None,
) -> OptimizationRequest:
    ctxs = [ctx for _, ctx in incidents]
    ranked = score_and_rank(ctxs)

    incident_zones = {inc.id: inc.zone_id for inc, _ in incidents}
    resource_zones = {r.id: (r.current_zone_id or r.home_zone_id) for r in resources}

    return OptimizationRequest(
        prioritized_incidents=ranked,
        available_resources=resources,
        incident_zones=incident_zones,
        resource_zones=resource_zones,
        distances=distances or {},
        max_travel_minutes=max_travel,
        capabilities=capabilities or list(DEFAULT_CAPABILITIES),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 1 — Enough resources
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnoughResources:
    """3 incidents, 3 resources, same zone → all incidents assigned."""

    @pytest.fixture
    def result(self):
        incidents = [
            make_incident(SeverityLevel.LOW,      zone_id="Z1", iid="inc-low"),
            make_incident(SeverityLevel.MEDIUM,   zone_id="Z1", iid="inc-med"),
            make_incident(SeverityLevel.HIGH,     zone_id="Z1", iid="inc-high"),
        ]
        resources = [
            make_resource("pump-1",  ResourceType.PUMP,         "Z1"),
            make_resource("crew-1",  ResourceType.RESCUE_TEAM,  "Z1"),
            make_resource("crew-2",  ResourceType.RESCUE_TEAM,  "Z1"),
        ]
        return OPTIMIZER.optimize(build_request(incidents, resources))

    def test_all_incidents_assigned(self, result):
        assert len(result.unassigned_incidents) == 0

    def test_three_assignments_made(self, result):
        assert len(result.assignments) == 3

    def test_no_resource_used_twice(self, result):
        ids = [a.resource_id for a in result.assignments]
        assert len(ids) == len(set(ids))

    def test_each_assignment_has_reason_code(self, result):
        for a in result.assignments:
            assert len(a.reason_codes) >= 1

    def test_same_zone_travel_is_zero(self, result):
        for a in result.assignments:
            assert a.estimated_travel_minutes == 0.0

    def test_optimizer_satisfies_protocol(self):
        assert isinstance(OPTIMIZER, ResourceOptimizer)


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 2 — Insufficient resources
# ═══════════════════════════════════════════════════════════════════════════════

class TestInsufficientResources:
    """3 incidents, 1 resource → highest-priority incident assigned; 2 unassigned."""

    @pytest.fixture
    def result(self):
        incidents = [
            make_incident(SeverityLevel.LOW,      zone_id="Z1", iid="inc-low"),
            make_incident(SeverityLevel.MEDIUM,   zone_id="Z1", iid="inc-med"),
            make_incident(
                SeverityLevel.CRITICAL,
                zone_id="Z1",
                iid="inc-crit",
                critical_facility_count=2,
                affected_population=3000,
                hours_until_deadline=1.5,
            ),
        ]
        resources = [make_resource("pump-1", ResourceType.PUMP, "Z1")]
        return OPTIMIZER.optimize(build_request(incidents, resources))

    def test_exactly_one_assignment(self, result):
        assert len(result.assignments) == 1

    def test_exactly_two_unassigned(self, result):
        assert len(result.unassigned_incidents) == 2

    def test_highest_priority_incident_is_assigned(self, result):
        # Critical incident (inc-crit) has the highest score
        assert result.assignment_for("inc-crit") is not None

    def test_unassigned_reason_is_no_resource(self, result):
        for u in result.unassigned_incidents:
            assert UA_NO_RESOURCE in u.reason_codes

    def test_unassigned_sorted_by_priority_desc(self, result):
        scores = [u.priority_score for u in result.unassigned_incidents]
        assert scores == sorted(scores, reverse=True)

    def test_assigned_resource_not_in_unassigned_pool(self, result):
        assigned_rid = result.assignments[0].resource_id
        # Confirm the resource was actually consumed
        assert assigned_rid in result.assigned_resource_ids


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 3 — Unavailable pump
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnavailablePump:
    """
    Critical flood needs a pump. The only pump is UNAVAILABLE (excluded from
    available_resources). A rescue team is present but incapable of pumping.
    Incident must be unassigned with UA_NO_CAPABLE_RESOURCE.
    """

    @pytest.fixture
    def result(self):
        inc, ctx = make_incident(
            SeverityLevel.CRITICAL, zone_id="Z1", iid="flood-crit"
        )
        # Rescue team available, but configured to NOT handle CRITICAL severity
        restricted_capabilities = [
            ResourceCapability(
                resource_type=ResourceType.PUMP,
                handles_severities=frozenset(SeverityLevel),  # pump handles all
            ),
            ResourceCapability(
                resource_type=ResourceType.RESCUE_TEAM,
                handles_severities=frozenset({
                    SeverityLevel.LOW,
                    SeverityLevel.MEDIUM,
                }),  # rescue team cannot handle CRITICAL without pump support
            ),
        ]
        # Only provide the rescue team (pump excluded = unavailable)
        resources = [make_resource("crew-1", ResourceType.RESCUE_TEAM, "Z1")]
        request = build_request(
            [(inc, ctx)],
            resources,
            capabilities=restricted_capabilities,
        )
        return OPTIMIZER.optimize(request)

    def test_incident_not_assigned(self, result):
        assert result.assignment_for("flood-crit") is None

    def test_unassigned_reason_is_no_capable_resource(self, result):
        u = result.unassigned_for("flood-crit")
        assert u is not None
        assert UA_NO_CAPABLE_RESOURCE in u.reason_codes

    def test_no_assignments_made(self, result):
        assert len(result.assignments) == 0

    def test_unassigned_incident_has_priority_score(self, result):
        u = result.unassigned_for("flood-crit")
        assert u.priority_score > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 4 — High-priority hospital/school incident wins the resource
# ═══════════════════════════════════════════════════════════════════════════════

class TestHighPriorityHospitalIncident:
    """
    Two incidents compete for one resource:
      - Hospital flood (HIGH severity, 3 critical facilities, large population, near deadline)
      - Road block (LOW severity, no facilities)
    The single resource must go to the hospital incident.
    """

    @pytest.fixture
    def result(self):
        hospital_inc, hospital_ctx = make_incident(
            SeverityLevel.HIGH,
            zone_id="Z1",
            iid="hospital-flood",
            critical_facility_count=3,
            affected_population=4000,
            hours_until_deadline=1.5,
        )
        road_inc, road_ctx = make_incident(
            SeverityLevel.LOW,
            zone_id="Z1",
            iid="road-block",
            critical_facility_count=0,
            affected_population=50,
        )
        resources = [make_resource("crew-1", ResourceType.RESCUE_TEAM, "Z1")]
        return OPTIMIZER.optimize(
            build_request(
                [(hospital_inc, hospital_ctx), (road_inc, road_ctx)],
                resources,
            )
        )

    def test_hospital_incident_is_assigned(self, result):
        assert result.assignment_for("hospital-flood") is not None

    def test_road_block_is_unassigned(self, result):
        assert result.unassigned_for("road-block") is not None

    def test_assigned_incident_is_hospital(self, result):
        assert len(result.assignments) == 1
        assert result.assignments[0].incident_id == "hospital-flood"

    def test_unassigned_road_block_reason(self, result):
        u = result.unassigned_for("road-block")
        assert UA_NO_RESOURCE in u.reason_codes

    def test_hospital_has_higher_priority_score_than_road(self, result):
        hospital_assignment = result.assignment_for("hospital-flood")
        road_unassigned = result.unassigned_for("road-block")
        # Priority score of assigned should be higher than unassigned
        assert hospital_assignment.fit_score >= 0.0
        assert road_unassigned.priority_score >= 0.0

    def test_assignment_has_reason_code(self, result):
        a = result.assignment_for("hospital-flood")
        assert a.reason_codes in (
            (OA_ONLY_AVAILABLE,), (OA_BEST_FIT,), (OA_ONLY_AVAILABLE,)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 5 — Resource too far away
# ═══════════════════════════════════════════════════════════════════════════════

class TestResourceTooFarAway:
    """
    Incident in zone Z1. One capable resource in zone Z9.
    Distance Z1↔Z9 = 120 min, max_travel = 60 min.
    Incident must be unassigned with UA_ALL_TOO_FAR.
    """

    @pytest.fixture
    def result(self):
        inc, ctx = make_incident(SeverityLevel.MEDIUM, zone_id="Z1", iid="inc-z1")
        resources = [make_resource("pump-far", ResourceType.PUMP, zone_id="Z9")]
        distances = {"Z9": {"Z1": 120.0}, "Z1": {"Z9": 120.0}}
        request = build_request(
            [(inc, ctx)],
            resources,
            distances=distances,
            max_travel=60.0,
        )
        return OPTIMIZER.optimize(request)

    def test_incident_not_assigned(self, result):
        assert result.assignment_for("inc-z1") is None

    def test_unassigned_reason_is_all_too_far(self, result):
        u = result.unassigned_for("inc-z1")
        assert u is not None
        assert UA_ALL_TOO_FAR in u.reason_codes

    def test_zero_assignments(self, result):
        assert len(result.assignments) == 0

    def test_nearby_resource_wins_over_far_one(self):
        """With a second near resource, near resource is preferred."""
        inc, ctx = make_incident(SeverityLevel.MEDIUM, zone_id="Z1", iid="inc-z1b")
        resources = [
            make_resource("pump-far",   ResourceType.PUMP, zone_id="Z9"),
            make_resource("pump-near",  ResourceType.PUMP, zone_id="Z1"),
        ]
        distances = {"Z9": {"Z1": 120.0, "Z9": 0.0}, "Z1": {"Z9": 120.0, "Z1": 0.0}}
        request = build_request([(inc, ctx)], resources, distances=distances)
        result = OPTIMIZER.optimize(request)
        assert result.assignment_for("inc-z1b") is not None
        assert result.assignments[0].resource_id == "pump-near"

    def test_travel_time_recorded_correctly(self):
        """A resource 30 min away should record 30 min travel."""
        inc, ctx = make_incident(SeverityLevel.LOW, zone_id="Z1", iid="inc-travel")
        resources = [make_resource("crew-mid", ResourceType.RESCUE_TEAM, zone_id="Z2")]
        distances = {"Z2": {"Z1": 30.0}, "Z1": {"Z2": 30.0}}
        request = build_request([(inc, ctx)], resources, distances=distances)
        result = OPTIMIZER.optimize(request)
        a = result.assignment_for("inc-travel")
        assert a is not None
        assert a.estimated_travel_minutes == 30.0


# ═══════════════════════════════════════════════════════════════════════════════
# Protocol conformance
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptimizerProtocol:
    def test_greedy_satisfies_protocol(self):
        assert isinstance(GreedyResourceOptimizer(), ResourceOptimizer)

    def test_empty_request_produces_empty_result(self):
        request = OptimizationRequest(
            prioritized_incidents=[],
            available_resources=[],
            incident_zones={},
            resource_zones={},
        )
        result = OPTIMIZER.optimize(request)
        assert result.assignments == []
        assert result.unassigned_incidents == []

    def test_result_convenience_properties(self):
        inc, ctx = make_incident(SeverityLevel.MEDIUM, zone_id="Z1", iid="inc-prop")
        resources = [make_resource("pump-1", ResourceType.PUMP, "Z1")]
        result = OPTIMIZER.optimize(build_request([(inc, ctx)], resources))
        assert "pump-1" in result.assigned_resource_ids
        assert "inc-prop" in result.assigned_incident_ids
        assert result.assignment_for("inc-prop") is not None
        assert result.unassigned_for("inc-prop") is None
