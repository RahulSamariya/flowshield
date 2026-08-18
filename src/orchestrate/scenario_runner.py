"""CitizenReportScenario — end-to-end Orchestrate scenario for one citizen report.

This module implements the minimal orchestration design for the canonical
FlowShield citizen-report flow:

  1. ingest_incident       — parse the report, create Incident + Evidence
  2. calculate_priority    — score the incident
  3. optimize_resources    — assign best available resource (or flag gap)
  4. generate_response_plan — produce a policy-grounded plan with citations
  5. lookup_situation      — return the current zone situation summary

All five steps use the FLOWSHIELD_REGISTRY tools.  The scenario runner is:
  - Stateless between runs (a fresh SituationEngine is created per run
    for the lookup_situation call if no engine is supplied).
  - Short-circuit safe: if ingestion fails, steps 2–5 are skipped and
    ScenarioResult.success=False with errors populated.
  - Serialisation-safe: all intermediate values are the Pydantic output
    models from the tools — no internal engine types cross between steps.

Usage::

    from src.orchestrate.scenario_runner import run_citizen_report_scenario, CitizenReportScenario

    result = run_citizen_report_scenario(
        CitizenReportScenario(
            city="Ahmedabad",
            report_text="Water is knee deep near the school, road is blocked.",
            zone_id_hint="W12-N",
            resources=[...],          # list of ResourceSpec dicts or objects
            distances={"W12-N": {"W12-S": 12.0}},
        )
    )
    print(result.response_plan.plan_actions[0].action_description)
    for cite in result.response_plan.knowledge_citations:
        print("Policy:", cite)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.orchestrate.tool_contracts import (
    CalculatePriorityInput,
    GenerateResponsePlanInput,
    GenerateResponsePlanOutput,
    IngestIncidentOutput,
    LookupSituationInput,
    LookupSituationOutput,
    OptimizeResourcesInput,
    OptimizeResourcesOutput,
    PriorityResultSpec,
    ResourceSpec,
)
from src.orchestrate.tools import (
    calculate_priority,
    generate_response_plan,
    ingest_incident,
    lookup_situation,
    optimize_resources,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scenario input
# ---------------------------------------------------------------------------

@dataclass
class CitizenReportScenario:
    """All inputs needed to run the end-to-end citizen-report scenario.

    Attributes
    ----------
    city
        City name (free text, e.g. "Ahmedabad").
    report_text
        Raw citizen report text.
    zone_id_hint
        Optional zone ID from the submission form's location picker.
    resources
        List of ResourceSpec objects (or dicts that construct them) available
        for assignment.  If empty, all incidents will become resource gaps.
    distances
        Travel-time matrix: zone_id → {zone_id → minutes}.
        Leave empty to treat all zones as equidistant (same-zone = 0).
    max_travel_minutes
        Resources beyond this ETA are ineligible.  Default: 60.
    use_knowledge_base
        If True (default), attach FLOWSHIELD_KB for policy citations.
    priority_context
        Optional dict of extra priority scoring inputs:
        critical_facility_count, road_blocked, affected_population,
        hours_until_deadline, infra_dependency_count.
        Values supplement what the ingestion agent extracts.
    engine
        Optional pre-populated SituationEngine for the lookup_situation step.
        If None, a fresh engine is created with the ingested incident only.
    """
    city: str
    report_text: str
    zone_id_hint: str | None = None
    resources: list[ResourceSpec | dict] = field(default_factory=list)
    distances: dict[str, dict[str, float]] = field(default_factory=dict)
    max_travel_minutes: float = 60.0
    use_knowledge_base: bool = True
    priority_context: dict = field(default_factory=dict)
    engine: object = None  # SituationEngine | None


# ---------------------------------------------------------------------------
# Scenario output
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    """The complete output of one citizen-report scenario run.

    ``success`` is True only if all five steps completed without error.
    Individual step outputs are always populated when their step ran,
    even if a later step failed.

    Attributes
    ----------
    success
        True if ingestion succeeded and the plan was generated.
    ingestion
        Output of ingest_incident (step 1).  Always present when run.
    priority
        Output of calculate_priority (step 2).  None if ingestion failed.
    optimization
        Output of optimize_resources (step 3).  None if priority failed.
    response_plan
        Output of generate_response_plan (step 4).  None if optimization failed.
    situation
        Output of lookup_situation (step 5).  Always attempted regardless.
    errors
        Fatal errors accumulated across steps.
    warnings
        Non-fatal warnings from all steps.
    step_trace
        Ordered list of step names that were executed (for debugging).
    """
    success: bool = False
    ingestion: IngestIncidentOutput | None = None
    priority: object | None = None           # CalculatePriorityOutput
    optimization: OptimizeResourcesOutput | None = None
    response_plan: GenerateResponsePlanOutput | None = None
    situation: LookupSituationOutput | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    step_trace: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------

def run_citizen_report_scenario(scenario: CitizenReportScenario) -> ScenarioResult:
    """Execute all five tools in sequence for one citizen report.

    The function is orchestrator-agnostic: it calls the tools directly as
    plain Python functions.  When deployed on watsonx Orchestrate, the
    Orchestrate runtime calls the same tools via the FLOWSHIELD_REGISTRY.

    Short-circuit behaviour:
    - Step 1 (ingest) failure → populate errors, skip steps 2–4, still run step 5.
    - Any step 2–4 failure → populate errors, skip remaining steps, still run step 5.
    - Step 5 (lookup) always runs and never blocks success.
    """
    result = ScenarioResult()
    warnings = result.warnings
    errors = result.errors

    # Normalise resource specs
    resources: list[ResourceSpec] = []
    for r in scenario.resources:
        if isinstance(r, dict):
            try:
                resources.append(ResourceSpec(**r))
            except Exception as exc:
                warnings.append(f"Skipping malformed resource spec: {exc}")
        else:
            resources.append(r)

    # ── Step 1: ingest_incident ───────────────────────────────────────────
    result.step_trace.append("ingest_incident")
    from pydantic import ValidationError as _PydanticError

    from src.orchestrate.tool_contracts import IngestIncidentInput
    try:
        ingest_inp = IngestIncidentInput(
            city=scenario.city,
            report_text=scenario.report_text,
            zone_id_hint=scenario.zone_id_hint,
        )
        ingest_out = ingest_incident(ingest_inp)
    except _PydanticError as exc:
        # Input validation failed at the tool boundary — treat as ingestion failure
        empty_out = IngestIncidentOutput(
            success=False,
            errors=[f"Input validation failed: {exc}"],
        )
        result.ingestion = empty_out
        errors.extend(empty_out.errors)
        result.situation = _run_lookup(scenario, result)
        result.step_trace.append("lookup_situation")
        return result

    result.ingestion = ingest_out
    warnings.extend(ingest_out.warnings)

    if not ingest_out.success or ingest_out.incident_id is None:
        errors.extend(ingest_out.errors or ["Ingestion returned no incident."])
        # Still run situation lookup before returning
        result.situation = _run_lookup(scenario, result)
        result.step_trace.append("lookup_situation")
        return result

    # ── Step 2: calculate_priority ────────────────────────────────────────
    result.step_trace.append("calculate_priority")
    ctx = scenario.priority_context
    priority_out = calculate_priority(CalculatePriorityInput(
        city=scenario.city,
        incident_id=ingest_out.incident_id,
        zone_id=ingest_out.zone_id or scenario.zone_id_hint or f"UNKNOWN-{scenario.city}",
        severity=ingest_out.severity or "low",
        risk_score=ingest_out.risk_score or 0.0,
        title=ingest_out.title or "Untitled incident",
        critical_facility_count=ctx.get("critical_facility_count", 0),
        road_blocked=ctx.get("road_blocked", False),
        affected_population=ctx.get("affected_population"),
        hours_until_deadline=ctx.get("hours_until_deadline"),
        infra_dependency_count=ctx.get("infra_dependency_count", 0),
    ))
    result.priority = priority_out

    # ── Step 3: optimize_resources ────────────────────────────────────────
    result.step_trace.append("optimize_resources")
    zone_of_incident = {
        ingest_out.incident_id: (
            ingest_out.zone_id or scenario.zone_id_hint or f"UNKNOWN-{scenario.city}"
        )
    }
    pr_spec = PriorityResultSpec(
        incident_id=priority_out.incident_id,
        priority_score=priority_out.priority_score,
        priority_level=priority_out.priority_level,
        reason_codes=priority_out.reason_codes,
        factor_breakdown=priority_out.factor_breakdown,
    )
    opt_out = optimize_resources(OptimizeResourcesInput(
        city=scenario.city,
        priority_results=[pr_spec],
        resources=resources,
        zone_of_incident=zone_of_incident,
        distances=scenario.distances,
        max_travel_minutes=scenario.max_travel_minutes,
    ))
    result.optimization = opt_out

    # ── Step 4: generate_response_plan ────────────────────────────────────
    result.step_trace.append("generate_response_plan")
    plan_out = generate_response_plan(GenerateResponsePlanInput(
        city=scenario.city,
        priority_results=[pr_spec],
        assignments=opt_out.assignments,
        unassigned_incidents=opt_out.unassigned_incidents,
        resources=resources,
        use_knowledge_base=scenario.use_knowledge_base,
    ))
    result.response_plan = plan_out
    warnings.extend(plan_out.warnings)

    # ── Step 5: lookup_situation ──────────────────────────────────────────
    result.step_trace.append("lookup_situation")
    result.situation = _run_lookup(scenario, result)

    result.success = True
    return result


def _run_lookup(scenario: CitizenReportScenario, result: ScenarioResult) -> LookupSituationOutput:
    """Run the lookup_situation tool, always returning a valid output."""
    try:
        zone_ids = None
        if result.ingestion and result.ingestion.zone_id:
            zone_ids = [result.ingestion.zone_id]
        return lookup_situation(
            LookupSituationInput(city=scenario.city, zone_ids=zone_ids),
            engine=scenario.engine,
        )
    except Exception as exc:
        logger.warning("lookup_situation failed: %s", exc)
        return LookupSituationOutput(
            city=scenario.city,
            overall_severity="normal",
            zones=[],
            open_incident_count=0,
            critical_zone_ids=[],
            watch_zone_ids=[],
        )
