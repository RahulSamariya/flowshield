"""FlowShield Orchestrate tools — thin adapters over existing engine modules.

Each function is a self-contained, stateless callable:
  - Takes one typed input model (from tool_contracts.py).
  - Calls the appropriate existing engine/agent module.
  - Returns one typed output model.
  - Never raises — returns error information in the output model.

The five tools map to the five FlowShield pipeline stages:

  ingest_incident        CitizenIncidentAgent.process()
  calculate_priority     IncidentPriorityEngine.score()
  optimize_resources     GreedyResourceOptimizer.optimize()
  generate_response_plan ResponsePlanningAgent.plan()
  lookup_situation       SituationEngine.state (read-only snapshot)

State isolation
---------------
``ingest_incident``, ``calculate_priority``, and ``optimize_resources`` are
fully stateless — they create engine instances internally and discard them.

``lookup_situation`` requires a SituationEngine snapshot to be passed in via
the ``engine`` parameter (keyword-only).  In the ScenarioRunner this is
provided automatically.  When called standalone, callers must supply one.

``generate_response_plan`` is stateless — it reconstructs its inputs from
the serialised Pydantic models in GenerateResponsePlanInput.

Internal type reconstruction
----------------------------
Tools reconstruct internal engine types (Incident, Resource, PriorityResult,
OptimizationResult, etc.) from the serialised JSON contracts.  This is the
only place where the impedance mismatch between JSON-safe contracts and typed
engine models is resolved.  No other file performs this translation.
"""

from __future__ import annotations

import logging
from typing import Any

from src.orchestrate.tool_contracts import (
    AssignmentRecord,
    CalculatePriorityInput,
    CalculatePriorityOutput,
    GenerateResponsePlanInput,
    GenerateResponsePlanOutput,
    IngestIncidentInput,
    IngestIncidentOutput,
    LookupSituationInput,
    LookupSituationOutput,
    OptimizeResourcesInput,
    OptimizeResourcesOutput,
    PlanActionRecord,
    UnassignedRecord,
    ZoneSummary,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool 1: ingest_incident
# ---------------------------------------------------------------------------

def ingest_incident(inp: IngestIncidentInput) -> IngestIncidentOutput:
    """Convert a citizen report or sensor alert into a validated Incident.

    Calls CitizenIncidentAgent.process() — no resource assignment, no routing.
    Returns success=False with errors populated if validation fails.
    """
    from src.agents.citizen_incident_agent import CitizenIncidentAgent

    agent = CitizenIncidentAgent(city=inp.city)
    result = agent.process(report=inp.report_text, zone_id_hint=inp.zone_id_hint)

    if not result.success or result.incident is None:
        return IngestIncidentOutput(
            success=False,
            warnings=result.warnings,
            errors=result.errors,
        )

    inc = result.incident
    ev = result.evidence
    return IngestIncidentOutput(
        success=True,
        incident_id=inc.id,
        zone_id=inc.zone_id,
        severity=str(inc.severity),
        risk_score=inc.risk_score,
        title=inc.title,
        description=inc.description,
        evidence_id=ev.id if ev else None,
        extraction_confidence=result.extraction.confidence if result.extraction else None,
        warnings=result.warnings,
        errors=[],
    )


# ---------------------------------------------------------------------------
# Tool 2: calculate_priority
# ---------------------------------------------------------------------------

def calculate_priority(inp: CalculatePriorityInput) -> CalculatePriorityOutput:
    """Score and prioritise one incident.

    Reconstructs an Incident and IncidentContext from the serialised input,
    then calls IncidentPriorityEngine.score().  Fully stateless.
    """
    from src.engine.priority_context import IncidentContext
    from src.engine.priority_engine import IncidentPriorityEngine
    from src.models.incident import Incident, SeverityLevel

    incident = Incident(
        id=inp.incident_id,
        city=inp.city,
        zone_id=inp.zone_id,
        severity=SeverityLevel(inp.severity),
        risk_score=inp.risk_score,
        title=inp.title,
    )
    ctx = IncidentContext(
        incident=incident,
        critical_facility_count=inp.critical_facility_count,
        road_blocked=inp.road_blocked,
        affected_population=inp.affected_population,
        hours_until_deadline=inp.hours_until_deadline,
        infra_dependency_count=inp.infra_dependency_count,
    )
    pr = IncidentPriorityEngine().score(ctx)

    factor_breakdown = [
        {
            "name": f.name,
            "raw_value": f.raw_value,
            "normalised": f.normalised,
            "weight": f.weight,
            "contribution": f.contribution,
            "reason_codes": list(f.reason_codes),
        }
        for f in pr.factors
    ]
    return CalculatePriorityOutput(
        incident_id=pr.incident_id,
        priority_score=pr.score,
        priority_level=str(pr.level),
        reason_codes=list(pr.reason_codes),
        factor_breakdown=factor_breakdown,
    )


# ---------------------------------------------------------------------------
# Tool 3: optimize_resources
# ---------------------------------------------------------------------------

def optimize_resources(inp: OptimizeResourcesInput) -> OptimizeResourcesOutput:
    """Assign available resources to prioritised incidents.

    Reconstructs PriorityResult and Resource objects from the serialised input,
    then calls GreedyResourceOptimizer.optimize().  Fully stateless.
    """
    from src.engine.optimizer import GreedyResourceOptimizer
    from src.engine.optimizer_request import DEFAULT_CAPABILITIES, OptimizationRequest
    from src.engine.priority_result import FactorScore, PriorityLevel, PriorityResult
    from src.models.resource import Resource, ResourceStatus, ResourceType

    # Reconstruct PriorityResult objects
    priority_results = []
    for spec in inp.priority_results:
        factors = tuple(
            FactorScore(
                name=f.get("name", ""),
                raw_value=f.get("raw_value"),
                normalised=f.get("normalised", 0.0),
                weight=f.get("weight", 0.0),
                contribution=f.get("contribution", 0.0),
                reason_codes=tuple(f.get("reason_codes", [])),
            )
            for f in spec.factor_breakdown
        )
        pr = PriorityResult(
            incident_id=spec.incident_id,
            score=spec.priority_score,
            level=PriorityLevel(spec.priority_level),
            factors=factors,
            reason_codes=tuple(spec.reason_codes),
        )
        priority_results.append(pr)

    # Sort highest priority first (optimizer expects this order)
    priority_results.sort(key=lambda x: x.score, reverse=True)

    # Reconstruct Resource objects
    resources = []
    for spec in inp.resources:
        try:
            r = Resource(
                id=spec.id,
                name=spec.name,
                city=spec.city,
                type=ResourceType(spec.type),
                home_zone_id=spec.home_zone_id,
                current_zone_id=spec.current_zone_id,
                capacity=spec.capacity,
                status=ResourceStatus(spec.status),
                notes=spec.notes,
            )
            resources.append(r)
        except Exception as exc:
            logger.warning("optimize_resources: skipping resource '%s': %s", spec.id, exc)

    # Filter to available/standby only
    from src.models.resource import ResourceStatus as RS
    available = [r for r in resources if r.status in (RS.AVAILABLE, RS.STANDBY)]

    incident_zones = inp.zone_of_incident
    resource_zones = {
        r.id: (r.current_zone_id or r.home_zone_id)
        for r in available
    }

    opt_request = OptimizationRequest(
        prioritized_incidents=priority_results,
        available_resources=available,
        incident_zones=incident_zones,
        resource_zones=resource_zones,
        capabilities=list(DEFAULT_CAPABILITIES),
        distances=inp.distances,
        max_travel_minutes=inp.max_travel_minutes,
    )
    opt_result = GreedyResourceOptimizer().optimize(opt_request)

    assignments = [
        AssignmentRecord(
            incident_id=a.incident_id,
            resource_id=a.resource_id,
            incident_zone=a.incident_zone,
            resource_zone=a.resource_zone,
            estimated_travel_minutes=a.estimated_travel_minutes,
            fit_score=a.fit_score,
            reason_codes=list(a.reason_codes),
        )
        for a in opt_result.assignments
    ]
    unassigned = [
        UnassignedRecord(
            incident_id=u.incident_id,
            priority_score=u.priority_score,
            reason_codes=list(u.reason_codes),
        )
        for u in opt_result.unassigned_incidents
    ]
    return OptimizeResourcesOutput(
        assignments=assignments,
        unassigned_incidents=unassigned,
        assigned_resource_ids=list(opt_result.assigned_resource_ids),
        assignment_count=len(assignments),
        gap_count=len(unassigned),
    )


# ---------------------------------------------------------------------------
# Tool 4: generate_response_plan
# ---------------------------------------------------------------------------

def generate_response_plan(inp: GenerateResponsePlanInput) -> GenerateResponsePlanOutput:
    """Build a structured response plan with policy grounding.

    Reconstructs engine types from the serialised input, then calls
    ResponsePlanningAgent.plan().  Uses FLOWSHIELD_KB when
    ``use_knowledge_base=True`` (default).
    """
    from src.agents.response_planning_agent import ResponsePlanningAgent
    from src.engine.optimizer_result import (
        Assignment,
        OptimizationResult,
        UnassignedIncident,
    )
    from src.engine.priority_result import FactorScore, PriorityLevel, PriorityResult
    from src.models.resource import Resource, ResourceStatus, ResourceType
    from src.models.situation import SituationState, ZoneSeverity, ZoneStatus

    # Reconstruct PriorityResult list
    priority_results = []
    for spec in inp.priority_results:
        factors = tuple(
            FactorScore(
                name=f.get("name", ""),
                raw_value=f.get("raw_value"),
                normalised=f.get("normalised", 0.0),
                weight=f.get("weight", 0.0),
                contribution=f.get("contribution", 0.0),
                reason_codes=tuple(f.get("reason_codes", [])),
            )
            for f in spec.factor_breakdown
        )
        priority_results.append(PriorityResult(
            incident_id=spec.incident_id,
            score=spec.priority_score,
            level=PriorityLevel(spec.priority_level),
            factors=factors,
            reason_codes=tuple(spec.reason_codes),
        ))

    # Reconstruct OptimizationResult
    assignments = [
        Assignment(
            incident_id=a.incident_id,
            resource_id=a.resource_id,
            incident_zone=a.incident_zone,
            resource_zone=a.resource_zone,
            estimated_travel_minutes=a.estimated_travel_minutes,
            fit_score=a.fit_score,
            reason_codes=tuple(a.reason_codes),
        )
        for a in inp.assignments
    ]
    unassigned_incidents = [
        UnassignedIncident(
            incident_id=u.incident_id,
            priority_score=u.priority_score,
            reason_codes=tuple(u.reason_codes),
        )
        for u in inp.unassigned_incidents
    ]
    opt_result = OptimizationResult(
        assignments=assignments,
        unassigned_incidents=unassigned_incidents,
    )

    # Reconstruct Resource list
    resources = []
    for spec in inp.resources:
        try:
            resources.append(Resource(
                id=spec.id,
                name=spec.name,
                city=spec.city,
                type=ResourceType(spec.type),
                home_zone_id=spec.home_zone_id,
                current_zone_id=spec.current_zone_id,
                capacity=spec.capacity,
                status=ResourceStatus(spec.status),
                notes=spec.notes,
            ))
        except Exception as exc:
            logger.warning("generate_response_plan: skipping resource '%s': %s", spec.id, exc)

    # Build a minimal SituationState — no live zone data at this tool boundary
    # (lookup_situation is the dedicated tool for that).
    # Collect zone IDs from assignments to build a skeleton state.
    zone_ids = {a.incident_zone for a in assignments}
    zone_ids |= {u.incident_id for u in unassigned_incidents}
    zones = {
        zid: ZoneStatus(zone_id=zid, severity=ZoneSeverity.WARNING)
        for zid in zone_ids
    }
    state = SituationState(city=inp.city, zones=zones)

    # Optional knowledge base
    kb = None
    if inp.use_knowledge_base:
        try:
            from src.knowledge.documents import FLOWSHIELD_KB
            kb = FLOWSHIELD_KB
        except Exception as exc:
            logger.warning("generate_response_plan: KB unavailable: %s", exc)

    agent = ResponsePlanningAgent(city=inp.city, knowledge_base=kb)
    planning_result = agent.plan(
        state=state,
        priority_results=priority_results,
        opt_result=opt_result,
        resources=resources,
    )
    plan = planning_result.plan

    plan_actions = [
        PlanActionRecord(
            id=pa.id,
            incident_id=pa.incident_id,
            resource_id=pa.resource_id,
            action_description=pa.action_description,
            responsible_unit=pa.responsible_unit,
            priority_rank=pa.priority_rank,
            priority_level=pa.priority_level,
            priority_score=pa.priority_score,
            target_response_minutes=pa.target_response_minutes,
            estimated_travel_minutes=pa.estimated_travel_minutes,
            reason_codes=list(pa.reason_codes),
            evidence_ids=list(pa.evidence_ids),
            citations=list(pa.citations),
            retrieved_chunk_ids=list(pa.retrieved_chunk_ids),
            approval_state=str(pa.approval_state),
            reasoning_text=pa.reasoning_text,
        )
        for pa in plan.plan_actions
    ]

    approval_count = sum(
        1 for pa in plan.plan_actions
        if pa.approval_state.value in ("required", "pending_approval")
    )

    return GenerateResponsePlanOutput(
        plan_id=plan.id,
        city=plan.city,
        plan_actions=plan_actions,
        gap_count=plan.gap_count,
        requires_human_approval=plan.requires_human_approval,
        knowledge_citations=list(plan.knowledge_citations),
        reasoning_summary=plan.reasoning_summary,
        reasoning_source=plan.reasoning_source,
        warnings=plan.warnings,
        action_count=len(plan_actions),
        approval_required_count=approval_count,
    )


# ---------------------------------------------------------------------------
# Tool 5: lookup_situation
# ---------------------------------------------------------------------------

def lookup_situation(
    inp: LookupSituationInput,
    *,
    engine: Any | None = None,
) -> LookupSituationOutput:
    """Return a snapshot of the current situation state.

    Parameters
    ----------
    inp:
        City and optional zone filter.
    engine:
        A live SituationEngine instance.  Required — this tool has no side-effects
        but needs a populated engine to read from.  In the ScenarioRunner this is
        provided automatically.  When calling standalone, pass ``engine=my_engine``.

    Returns a flat, JSON-safe summary of all zones.
    """
    from src.models.situation import ZoneSeverity

    if engine is None:
        # Return empty snapshot — no engine available
        return LookupSituationOutput(
            city=inp.city,
            overall_severity="normal",
            zones=[],
            open_incident_count=0,
            critical_zone_ids=[],
            watch_zone_ids=[],
        )

    state = engine.state
    all_zones = list(state.zones.values())
    if inp.zone_ids is not None:
        all_zones = [z for z in all_zones if z.zone_id in inp.zone_ids]

    zone_summaries = [
        ZoneSummary(
            zone_id=z.zone_id,
            severity=str(z.severity),
            latest_rainfall_mm_hr=z.latest_rainfall_mm_hr,
            latest_water_level_m=z.latest_water_level_m,
            road_blocked=z.road_blocked,
        )
        for z in all_zones
    ]

    critical_ids = [z.zone_id for z in all_zones if z.severity == ZoneSeverity.CRITICAL]
    watch_ids = [z.zone_id for z in all_zones if z.severity == ZoneSeverity.WATCH]

    open_incidents = engine.open_incidents()

    return LookupSituationOutput(
        city=inp.city,
        overall_severity=str(state.overall_severity),
        zones=zone_summaries,
        open_incident_count=len(open_incidents),
        critical_zone_ids=critical_ids,
        watch_zone_ids=watch_ids,
    )
