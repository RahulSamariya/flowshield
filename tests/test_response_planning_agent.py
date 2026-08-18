"""Tests for ResponsePlanningAgent, ResponsePlan, PlanAction, and PolicyConfig.

Test class layout
-----------------
TestPolicyConfig               — PolicyConfig defaults, custom values, approval logic
TestPlanActionModel            — PlanAction Pydantic validation (happy + error paths)
TestResponsePlanModel          — ResponsePlan accessors and validators
TestResponsePlanningAgentEmpty — agent with no incidents / no assignments
TestResponsePlanningAgentAssigned — agent with real PriorityResults + OptimizationResult
TestResponsePlanningAgentGaps  — agent with unassigned incidents
TestResponsePlanningAgentApproval — approval logic per policy
TestResponsePlanningAgentReasoningFallback — fallback reasoning when Granite unavailable
TestResponsePlanningAgentCap   — max_actions_per_incident policy cap
TestResponsePlanningAgentAuditTrail — every PlanAction carries required traceability
TestResponsePlanningAgentConstraints — agent must never invent resources
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agents.policy_config import DEFAULT_POLICY, PolicyConfig
from src.agents.response_plan import ApprovalState, PlanAction, ResponsePlan
from src.agents.response_planning_agent import PlanningResult, ResponsePlanningAgent
from src.engine.optimizer_result import (
    OA_BEST_FIT,
    OA_NEAREST,
    UA_NO_RESOURCE,
    Assignment,
    OptimizationResult,
    UnassignedIncident,
)
from src.engine.priority_result import (
    RC_ROAD_BLOCKED,
    RC_SEVERITY_CRITICAL,
    RC_SEVERITY_HIGH,
    FactorScore,
    PriorityLevel,
    PriorityResult,
)
from src.models.incident import Incident, SeverityLevel
from src.models.resource import Resource, ResourceStatus, ResourceType
from src.models.situation import SituationState, ZoneSeverity, ZoneStatus

# ---------------------------------------------------------------------------
# Shared fixtures / builders
# ---------------------------------------------------------------------------

CITY = "TestCity"


def _make_incident(
    zone_id: str = "Z-01",
    severity: SeverityLevel = SeverityLevel.HIGH,
    risk_score: float = 0.70,
    evidence_ids: list[str] | None = None,
) -> Incident:
    return Incident(
        id=f"inc-{zone_id}",
        city=CITY,
        zone_id=zone_id,
        severity=severity,
        risk_score=risk_score,
        title=f"Flood incident {zone_id}",
        evidence_ids=evidence_ids or [f"ev-{zone_id}"],
    )


def _make_resource(
    resource_id: str = "res-01",
    resource_type: ResourceType = ResourceType.PUMP,
    zone_id: str = "Z-01",
) -> Resource:
    return Resource(
        id=resource_id,
        name=f"Resource {resource_id}",
        city=CITY,
        type=resource_type,
        home_zone_id=zone_id,
        current_zone_id=zone_id,
        status=ResourceStatus.AVAILABLE,
    )


def _make_priority_result(
    incident_id: str,
    score: float = 0.70,
    level: PriorityLevel = PriorityLevel.HIGH,
    reason_codes: tuple[str, ...] = (RC_SEVERITY_HIGH,),
) -> PriorityResult:
    factor = FactorScore(
        name="severity",
        raw_value="high",
        normalised=0.70,
        weight=0.30,
        contribution=0.21,
        reason_codes=(RC_SEVERITY_HIGH,),
    )
    return PriorityResult(
        incident_id=incident_id,
        score=score,
        level=level,
        factors=(factor,),
        reason_codes=reason_codes,
    )


def _make_assignment(
    incident_id: str = "inc-Z-01",
    resource_id: str = "res-01",
    incident_zone: str = "Z-01",
    resource_zone: str = "Z-01",
    eta: float = 8.0,
    reason_codes: tuple[str, ...] = (OA_BEST_FIT,),
) -> Assignment:
    return Assignment(
        incident_id=incident_id,
        resource_id=resource_id,
        incident_zone=incident_zone,
        resource_zone=resource_zone,
        estimated_travel_minutes=eta,
        fit_score=0.85,
        reason_codes=reason_codes,
    )


def _make_state(incidents: list[Incident] | None = None) -> SituationState:
    """Build a minimal SituationState and inject incidents via _incidents attr."""
    state = SituationState(
        city=CITY,
        zones={
            "Z-01": ZoneStatus(zone_id="Z-01", severity=ZoneSeverity.WARNING),
            "Z-02": ZoneStatus(zone_id="Z-02", severity=ZoneSeverity.CRITICAL),
        },
    )
    if incidents:
        # inject into private _incidents dict so _find_incident_in_state works
        object.__setattr__(state, "_incidents", {inc.id: inc for inc in incidents})
    return state


# ---------------------------------------------------------------------------
# TestPolicyConfig
# ---------------------------------------------------------------------------

class TestPolicyConfig:

    def test_default_policy_exists(self) -> None:
        assert DEFAULT_POLICY is not None

    def test_default_response_targets_present(self) -> None:
        for level in ("critical", "high", "medium", "low"):
            assert DEFAULT_POLICY.target_minutes(level) > 0

    def test_critical_faster_than_low(self) -> None:
        assert DEFAULT_POLICY.target_minutes("critical") < DEFAULT_POLICY.target_minutes("low")

    def test_unknown_level_returns_default(self) -> None:
        assert DEFAULT_POLICY.target_minutes("unknown") == 60  # dict.get fallback

    def test_responsible_unit_pump(self) -> None:
        assert "Drainage" in DEFAULT_POLICY.responsible_unit("pump")

    def test_responsible_unit_rescue(self) -> None:
        assert "NDRF" in DEFAULT_POLICY.responsible_unit("rescue_team") or \
               "SDRF" in DEFAULT_POLICY.responsible_unit("rescue_team")

    def test_responsible_unit_fallback(self) -> None:
        assert DEFAULT_POLICY.responsible_unit("nonexistent_type") == "Municipal EOC"

    def test_requires_approval_above_threshold(self) -> None:
        policy = PolicyConfig(approval_required_above_priority_score=0.75)
        assert policy.requires_approval(priority_score=0.80, resource_type="pump") is True

    def test_no_approval_below_threshold(self) -> None:
        policy = PolicyConfig(approval_required_above_priority_score=0.75)
        assert policy.requires_approval(priority_score=0.60, resource_type="pump") is False

    def test_rescue_team_always_requires_approval(self) -> None:
        policy = PolicyConfig(approval_required_above_priority_score=0.99)
        # even with very low score, rescue_team triggers approval
        assert policy.requires_approval(priority_score=0.10, resource_type="rescue_team") is True

    def test_custom_approval_resource_types(self) -> None:
        policy = PolicyConfig(
            approval_required_for_resource_types=frozenset({"pump"}),
            approval_required_above_priority_score=0.99,
        )
        assert policy.requires_approval(0.01, "pump") is True
        assert policy.requires_approval(0.01, "rescue_team") is False

    def test_policy_is_frozen(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            DEFAULT_POLICY.approval_required_above_priority_score = 0.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestPlanActionModel
# ---------------------------------------------------------------------------

class TestPlanActionModel:

    def _base_kwargs(self, **overrides) -> dict:
        base = {
            "incident_id": "inc-01",
            "resource_id": "res-01",
            "priority_result_id": "inc-01",
            "action_description": "Deploy pump to zone Z-01.",
            "responsible_unit": "AMC Drainage Department",
            "priority_rank": 1,
            "priority_level": "high",
            "priority_score": 0.70,
            "target_response_minutes": 30,
            "estimated_travel_minutes": 8.0,
            "reason_codes": (RC_SEVERITY_HIGH, OA_BEST_FIT),
            "evidence_ids": ("ev-01",),
            "approval_state": ApprovalState.AUTO,
            "reasoning_text": "High severity zone; pump is nearest eligible resource.",
        }
        base.update(overrides)
        return base

    def test_valid_plan_action(self) -> None:
        pa = PlanAction(**self._base_kwargs())
        assert pa.incident_id == "inc-01"
        assert pa.resource_id == "res-01"
        assert pa.approval_state == ApprovalState.AUTO

    def test_auto_uuid_id(self) -> None:
        pa = PlanAction(**self._base_kwargs())
        assert len(pa.id) == 36  # UUID4

    def test_reason_codes_tuple(self) -> None:
        pa = PlanAction(**self._base_kwargs())
        assert isinstance(pa.reason_codes, tuple)

    def test_evidence_ids_tuple(self) -> None:
        pa = PlanAction(**self._base_kwargs())
        assert isinstance(pa.evidence_ids, tuple)

    def test_gap_action_without_escalation_raises(self) -> None:
        """resource_id=None but no 'escalat' in description → ValidationError."""
        with pytest.raises(Exception):
            PlanAction(**self._base_kwargs(
                resource_id=None,
                action_description="Deploy nothing.",  # missing 'escalat'
            ))

    def test_gap_action_with_escalation_passes(self) -> None:
        pa = PlanAction(**self._base_kwargs(
            resource_id=None,
            action_description="RESOURCE GAP — escalate to EOC: no pump available.",
        ))
        assert pa.resource_id is None

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            PlanAction(**self._base_kwargs(unknown_field="oops"))

    def test_priority_rank_ge_1(self) -> None:
        with pytest.raises(Exception):
            PlanAction(**self._base_kwargs(priority_rank=0))

    def test_priority_score_range(self) -> None:
        with pytest.raises(Exception):
            PlanAction(**self._base_kwargs(priority_score=1.5))

    def test_approval_state_required(self) -> None:
        pa = PlanAction(**self._base_kwargs(approval_state=ApprovalState.REQUIRED))
        assert pa.approval_state == ApprovalState.REQUIRED

    def test_approval_state_pending_is_valid(self) -> None:
        pa = PlanAction(**self._base_kwargs(approval_state=ApprovalState.PENDING_APPROVAL))
        assert pa.approval_state == ApprovalState.PENDING_APPROVAL


# ---------------------------------------------------------------------------
# TestResponsePlanModel
# ---------------------------------------------------------------------------

class TestResponsePlanModel:

    def _make_plan_actions(self, n: int = 2) -> list[PlanAction]:
        actions = []
        for i in range(1, n + 1):
            actions.append(PlanAction(
                incident_id=f"inc-0{i}",
                resource_id=f"res-0{i}",
                priority_result_id=f"inc-0{i}",
                action_description=f"Deploy resource {i} to zone Z-0{i}.",
                responsible_unit="AMC",
                priority_rank=i,
                priority_level="high",
                priority_score=0.70,
                target_response_minutes=30,
                estimated_travel_minutes=float(i * 5),
                reason_codes=(RC_SEVERITY_HIGH,),
                evidence_ids=(f"ev-0{i}",),
                approval_state=ApprovalState.AUTO,
                reasoning_text="High severity.",
            ))
        return actions

    def test_empty_plan_is_valid(self) -> None:
        plan = ResponsePlan(city=CITY)
        assert plan.plan_actions == []
        assert plan.gap_count == 0
        assert plan.requires_human_approval is False

    def test_plan_has_uuid_id(self) -> None:
        plan = ResponsePlan(city=CITY)
        assert len(plan.id) == 36

    def test_plan_has_generated_at(self) -> None:
        plan = ResponsePlan(city=CITY)
        assert plan.generated_at is not None

    def test_action_for_incident_found(self) -> None:
        actions = self._make_plan_actions(2)
        plan = ResponsePlan(city=CITY, plan_actions=actions)
        assert plan.action_for_incident("inc-01") is not None

    def test_action_for_incident_not_found(self) -> None:
        plan = ResponsePlan(city=CITY, plan_actions=self._make_plan_actions(2))
        assert plan.action_for_incident("nonexistent") is None

    def test_approval_required_actions_accessor(self) -> None:
        actions = self._make_plan_actions(2)
        actions[0] = PlanAction(
            **{**actions[0].model_dump(), "approval_state": ApprovalState.REQUIRED}
        )
        plan = ResponsePlan(city=CITY, plan_actions=actions, requires_human_approval=True)
        assert len(plan.approval_required_actions) == 1

    def test_auto_dispatch_accessor(self) -> None:
        actions = self._make_plan_actions(2)
        plan = ResponsePlan(city=CITY, plan_actions=actions)
        assert len(plan.auto_dispatch_actions) == 2

    def test_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            ResponsePlan(city=CITY, surprise_field="oops")


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentEmpty
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentEmpty:

    def test_empty_results_returns_success_false(self) -> None:
        agent = ResponsePlanningAgent(city=CITY)
        state = _make_state()
        opt = OptimizationResult()
        result = agent.plan(
            state=state,
            priority_results=[],
            opt_result=opt,
            resources=[],
        )
        assert result.success is False

    def test_empty_plan_actions_list(self) -> None:
        agent = ResponsePlanningAgent(city=CITY)
        result = agent.plan(
            state=_make_state(),
            priority_results=[],
            opt_result=OptimizationResult(),
            resources=[],
        )
        assert result.plan.plan_actions == []

    def test_empty_plan_gap_count_zero(self) -> None:
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state(), priority_results=[], opt_result=OptimizationResult(), resources=[]
        )
        assert result.plan.gap_count == 0

    def test_empty_plan_no_approval_required(self) -> None:
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state(), priority_results=[], opt_result=OptimizationResult(), resources=[]
        )
        assert result.plan.requires_human_approval is False

    def test_empty_city_raises(self) -> None:
        with pytest.raises(ValueError):
            ResponsePlanningAgent(city="")

    def test_whitespace_city_raises(self) -> None:
        with pytest.raises(ValueError):
            ResponsePlanningAgent(city="   ")

    def test_plan_always_returns_not_raises(self) -> None:
        agent = ResponsePlanningAgent(city=CITY)
        # Even with completely degenerate input, must not raise
        result = agent.plan(
            state=_make_state(),
            priority_results=[],
            opt_result=OptimizationResult(
                assignments=[],
                unassigned_incidents=[],
            ),
            resources=[],
        )
        assert isinstance(result, PlanningResult)


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentAssigned
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentAssigned:

    def _setup(self, n: int = 2):
        incidents = [
            _make_incident(zone_id=f"Z-0{i}", severity=SeverityLevel.HIGH)
            for i in range(1, n + 1)
        ]
        resources = [
            _make_resource(resource_id=f"res-0{i}", zone_id=f"Z-0{i}")
            for i in range(1, n + 1)
        ]
        pr_list = [
            _make_priority_result(
                incident_id=inc.id,
                score=0.60 + i * 0.05,
                level=PriorityLevel.HIGH,
            )
            for i, inc in enumerate(incidents)
        ]
        assignments = [
            _make_assignment(
                incident_id=inc.id,
                resource_id=f"res-0{i + 1}",
                incident_zone=inc.zone_id,
                resource_zone=inc.zone_id,
                eta=float((i + 1) * 8),
            )
            for i, inc in enumerate(incidents)
        ]
        opt = OptimizationResult(assignments=assignments)
        state = _make_state(incidents)
        return incidents, resources, pr_list, opt, state

    def test_success_true_with_assignments(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        assert result.success is True

    def test_plan_action_count_equals_assignments(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        assert len(result.plan.plan_actions) == 2

    def test_plan_actions_ordered_by_rank(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        ranks = [a.priority_rank for a in result.plan.plan_actions]
        assert ranks == sorted(ranks)

    def test_each_action_has_incident_id(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        for pa in result.plan.plan_actions:
            assert pa.incident_id

    def test_each_action_has_resource_id(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        for pa in result.plan.plan_actions:
            assert pa.resource_id is not None

    def test_each_action_has_responsible_unit(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        for pa in result.plan.plan_actions:
            assert pa.responsible_unit

    def test_each_action_has_target_minutes(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        for pa in result.plan.plan_actions:
            assert pa.target_response_minutes >= 1

    def test_each_action_has_reasoning_text(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        for pa in result.plan.plan_actions:
            assert len(pa.reasoning_text) > 0

    def test_reasoning_summary_populated(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        assert len(result.plan.reasoning_summary) > 0

    def test_gap_count_zero_when_all_assigned(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(2)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        assert result.plan.gap_count == 0

    def test_city_propagated_to_plan(self) -> None:
        incs, resources, pr_list, opt, state = self._setup(1)
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=pr_list, opt_result=opt, resources=resources
        )
        assert result.plan.city == CITY


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentGaps
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentGaps:

    def _setup_with_gap(self):
        inc = _make_incident(zone_id="Z-01", severity=SeverityLevel.CRITICAL, risk_score=0.90)
        resource = _make_resource(resource_id="res-01", zone_id="Z-01")
        pr = _make_priority_result(
            incident_id=inc.id,
            score=0.90,
            level=PriorityLevel.CRITICAL,
            reason_codes=(RC_SEVERITY_CRITICAL,),
        )
        unassigned = UnassignedIncident(
            incident_id=inc.id,
            priority_score=0.90,
            reason_codes=(UA_NO_RESOURCE,),
        )
        opt = OptimizationResult(unassigned_incidents=[unassigned])
        state = _make_state([inc])
        return inc, resource, pr, opt, state

    def test_gap_action_created(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert len(result.plan.plan_actions) == 1

    def test_gap_action_has_no_resource_id(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        pa = result.plan.plan_actions[0]
        assert pa.resource_id is None

    def test_gap_action_requires_approval(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        pa = result.plan.plan_actions[0]
        assert pa.approval_state == ApprovalState.REQUIRED

    def test_gap_action_description_contains_escalate(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        pa = result.plan.plan_actions[0]
        assert "escalat" in pa.action_description.lower()

    def test_gap_count_reflects_unassigned(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert result.plan.gap_count == 1

    def test_plan_requires_approval_when_gap_exists(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert result.plan.requires_human_approval is True

    def test_gap_action_incident_id_correct(self) -> None:
        inc, resource, pr, opt, state = self._setup_with_gap()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert result.plan.plan_actions[0].incident_id == inc.id


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentApproval
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentApproval:

    def test_low_score_pump_is_auto(self) -> None:
        """Pump with score below threshold → AUTO."""
        policy = PolicyConfig(
            approval_required_above_priority_score=0.75,
            approval_required_for_resource_types=frozenset({"rescue_team"}),
        )
        inc = _make_incident("Z-01", risk_score=0.40)
        resource = _make_resource("res-01", ResourceType.PUMP)
        pr = _make_priority_result(inc.id, score=0.40, level=PriorityLevel.MEDIUM)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].approval_state == ApprovalState.AUTO

    def test_high_score_pump_requires_approval(self) -> None:
        """Pump with score above threshold → REQUIRED."""
        policy = PolicyConfig(approval_required_above_priority_score=0.75)
        inc = _make_incident("Z-01", risk_score=0.90)
        resource = _make_resource("res-01", ResourceType.PUMP)
        pr = _make_priority_result(inc.id, score=0.90, level=PriorityLevel.CRITICAL)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].approval_state == ApprovalState.REQUIRED

    def test_rescue_team_always_requires_approval(self) -> None:
        """rescue_team always REQUIRED regardless of score."""
        policy = PolicyConfig(approval_required_above_priority_score=0.99)
        inc = _make_incident("Z-01", risk_score=0.20)
        resource = _make_resource("res-01", ResourceType.RESCUE_TEAM)
        pr = _make_priority_result(inc.id, score=0.20, level=PriorityLevel.LOW)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].approval_state == ApprovalState.REQUIRED

    def test_requires_human_approval_flag_set_correctly(self) -> None:
        policy = PolicyConfig(approval_required_above_priority_score=0.75)
        inc = _make_incident("Z-01", risk_score=0.90)
        resource = _make_resource("res-01", ResourceType.PUMP)
        pr = _make_priority_result(inc.id, score=0.90, level=PriorityLevel.CRITICAL)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.requires_human_approval is True

    def test_all_auto_flag_false_when_no_approval_required(self) -> None:
        policy = PolicyConfig(
            approval_required_above_priority_score=0.99,
            approval_required_for_resource_types=frozenset(),
        )
        inc = _make_incident("Z-01", risk_score=0.40)
        resource = _make_resource("res-01", ResourceType.PUMP)
        pr = _make_priority_result(inc.id, score=0.40, level=PriorityLevel.MEDIUM)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.requires_human_approval is False


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentReasoningFallback
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentReasoningFallback:

    def _setup(self):
        inc = _make_incident("Z-01", severity=SeverityLevel.HIGH, risk_score=0.70)
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id, score=0.70, level=PriorityLevel.HIGH)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        return inc, resource, pr, opt, _make_state([inc])

    def test_fallback_reasoning_summary_populated(self) -> None:
        """Even with no Granite, reasoning_summary must be non-empty."""
        inc, resource, pr, opt, state = self._setup()
        agent = ResponsePlanningAgent(city=CITY)
        # Patch the reasoning layer to raise GraniteUnavailable
        from src.reasoning.granite_client import GraniteUnavailable
        agent._reasoning.generate_response_plan_with_kb = MagicMock(
            side_effect=GraniteUnavailable("mocked unavailable")
        )
        result = agent.plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert len(result.plan.reasoning_summary) > 0

    def test_fallback_source_is_fallback(self) -> None:
        inc, resource, pr, opt, state = self._setup()
        agent = ResponsePlanningAgent(city=CITY)
        from src.reasoning.granite_client import GraniteUnavailable
        agent._reasoning.generate_response_plan_with_kb = MagicMock(
            side_effect=GraniteUnavailable("mocked unavailable")
        )
        result = agent.plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert result.plan.reasoning_source == "fallback"

    def test_fallback_adds_warning(self) -> None:
        inc, resource, pr, opt, state = self._setup()
        agent = ResponsePlanningAgent(city=CITY)
        from src.reasoning.granite_client import GraniteUnavailable
        agent._reasoning.generate_response_plan_with_kb = MagicMock(
            side_effect=GraniteUnavailable("mocked unavailable")
        )
        result = agent.plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        assert any("unavailable" in w.lower() for w in result.warnings)

    def test_per_action_reasoning_text_always_deterministic(self) -> None:
        """Per-action reasoning_text must never be empty regardless of Granite."""
        inc, resource, pr, opt, state = self._setup()
        result = ResponsePlanningAgent(city=CITY).plan(
            state=state, priority_results=[pr], opt_result=opt, resources=[resource]
        )
        for pa in result.plan.plan_actions:
            assert len(pa.reasoning_text) > 10


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentCap
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentCap:

    def test_cap_one_action_per_incident(self) -> None:
        """max_actions_per_incident=1 drops duplicates."""
        policy = PolicyConfig(max_actions_per_incident=1)
        inc = _make_incident("Z-01")
        res1 = _make_resource("res-01")
        res2 = _make_resource("res-02")
        pr = _make_priority_result(inc.id, score=0.70)
        # Two assignments for the same incident (edge case)
        opt = OptimizationResult(assignments=[
            _make_assignment(incident_id=inc.id, resource_id="res-01"),
            _make_assignment(incident_id=inc.id, resource_id="res-02"),
        ])
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[res1, res2],
        )
        incident_actions = [a for a in result.plan.plan_actions if a.incident_id == inc.id]
        assert len(incident_actions) == 1

    def test_cap_warning_emitted(self) -> None:
        policy = PolicyConfig(max_actions_per_incident=1)
        inc = _make_incident("Z-01")
        res1 = _make_resource("res-01")
        res2 = _make_resource("res-02")
        pr = _make_priority_result(inc.id, score=0.70)
        opt = OptimizationResult(assignments=[
            _make_assignment(incident_id=inc.id, resource_id="res-01"),
            _make_assignment(incident_id=inc.id, resource_id="res-02"),
        ])
        result = ResponsePlanningAgent(city=CITY, policy=policy).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[res1, res2],
        )
        assert any("max_actions" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentAuditTrail
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentAuditTrail:

    def test_reason_codes_include_priority_codes(self) -> None:
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(
            inc.id,
            reason_codes=(RC_SEVERITY_HIGH, RC_ROAD_BLOCKED),
        )
        opt = OptimizationResult(
            assignments=[_make_assignment(
                incident_id=inc.id,
                resource_id="res-01",
                reason_codes=(OA_NEAREST,),
            )]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        pa = result.plan.plan_actions[0]
        assert RC_SEVERITY_HIGH in pa.reason_codes

    def test_reason_codes_include_optimizer_codes(self) -> None:
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id)
        opt = OptimizationResult(
            assignments=[_make_assignment(
                incident_id=inc.id,
                resource_id="res-01",
                reason_codes=(OA_NEAREST,),
            )]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert OA_NEAREST in result.plan.plan_actions[0].reason_codes

    def test_reason_codes_deduplicated(self) -> None:
        """Same code from both priority + optimizer appears only once."""
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id, reason_codes=(RC_SEVERITY_HIGH,))
        opt = OptimizationResult(
            assignments=[_make_assignment(
                incident_id=inc.id,
                resource_id="res-01",
                reason_codes=(RC_SEVERITY_HIGH,),  # duplicate
            )]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        codes = result.plan.plan_actions[0].reason_codes
        assert codes.count(RC_SEVERITY_HIGH) == 1

    def test_evidence_ids_forwarded(self) -> None:
        ev_id = "ev-abc-123"
        inc = _make_incident("Z-01", evidence_ids=[ev_id])
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert ev_id in result.plan.plan_actions[0].evidence_ids

    def test_priority_score_matches_priority_result(self) -> None:
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id, score=0.83)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].priority_score == pytest.approx(0.83)

    def test_estimated_travel_minutes_from_optimizer(self) -> None:
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01", eta=22.5)]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].estimated_travel_minutes == pytest.approx(22.5)


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentConstraints
# ---------------------------------------------------------------------------

class TestResponsePlanningAgentConstraints:

    def test_agent_skips_assignment_with_unknown_resource_id(self) -> None:
        """Agent must not invent a resource — unknown resource_id → skip + warn."""
        inc = _make_incident("Z-01")
        pr = _make_priority_result(inc.id)
        # Optimizer returns assignment referencing a resource not in resources list
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="ghost-resource")]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[],  # empty — ghost-resource doesn't exist
        )
        # Must not create a PlanAction for the ghost resource
        assert all(a.resource_id != "ghost-resource" for a in result.plan.plan_actions)
        assert any("unknown resource_id" in w for w in result.warnings)

    def test_agent_skips_assignment_with_unknown_incident_id(self) -> None:
        """Agent must not produce an action for an unrecognized incident."""
        resource = _make_resource("res-01")
        # Assignment references an incident that has no PriorityResult
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id="ghost-incident", resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state(),
            priority_results=[],  # no pr for ghost-incident
            opt_result=opt,
            resources=[resource],
        )
        assert all(a.incident_id != "ghost-incident" for a in result.plan.plan_actions)
        assert any("unknown incident_id" in w for w in result.warnings)

    def test_agent_does_not_modify_priority_scores(self) -> None:
        """Priority scores in plan must equal what came from the engine."""
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        original_score = 0.77
        pr = _make_priority_result(inc.id, score=original_score)
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].priority_score == pytest.approx(original_score)

    def test_agent_does_not_modify_travel_times(self) -> None:
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id)
        original_eta = 17.3
        opt = OptimizationResult(
            assignments=[
                _make_assignment(
                    incident_id=inc.id, resource_id="res-01", eta=original_eta
                )
            ]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[resource],
        )
        assert result.plan.plan_actions[0].estimated_travel_minutes == pytest.approx(original_eta)

    def test_plan_actions_is_not_same_object_as_input(self) -> None:
        """Ensure agent does not mutate the input lists."""
        inc = _make_incident("Z-01")
        resource = _make_resource("res-01")
        pr = _make_priority_result(inc.id)
        pr_list_original = [pr]
        opt = OptimizationResult(
            assignments=[_make_assignment(incident_id=inc.id, resource_id="res-01")]
        )
        _ = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=pr_list_original,
            opt_result=opt,
            resources=[resource],
        )
        # Input list must be unchanged
        assert len(pr_list_original) == 1
