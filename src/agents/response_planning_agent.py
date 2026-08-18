"""ResponsePlanningAgent — converts prioritized incidents + assignments into a structured plan.

Responsibilities
----------------
1. Accept SituationState, prioritized PriorityResults, OptimizationResult,
   Resource list, PolicyConfig, and optional KnowledgeBase.
2. Build one PlanAction per assigned incident (and one gap action per unassigned).
3. Apply PolicyConfig to determine: responsible_unit, target_response_minutes,
   and approval_state.
4. When a KnowledgeBase is provided: retrieve relevant policy chunks per action
   and attach ``citations`` + ``retrieved_chunk_ids`` to each PlanAction.
5. Call GraniteReasoningLayer.generate_response_plan() with retrieved policy
   context injected into the prompt (via build_response_plan_with_kb_prompt).
6. Build per-action reasoning text deterministically — never depends on Granite.
7. Return a ResponsePlan — never raise.

What this agent MUST NOT do
----------------------------
- Invent resources not present in the OptimizationResult or Resource list.
- Override any score, travel time, or assignment from the optimizer.
- Modify any Incident, Resource, or PriorityResult.
- Create Actions (dispatched records) — it only produces PlanActions (proposals).
- Access zone registries, sensor feeds, or routing APIs.
- Put live sensor data or numeric thresholds into the knowledge queries.

Knowledge retrieval
--------------------
The query sent to KnowledgeBase.retrieve() is built from:
  - incident title (stripped to key words)
  - resource type
  - priority level
  - reason codes from PriorityResult

Retrieved chunk text is appended to the Granite prompt as "POLICY CONTEXT".
Citations (source_ref strings) are forwarded to PlanAction.citations.
If no KnowledgeBase is provided, citations remain empty — all other behaviour
is unchanged.

Approval rules (delegated to PolicyConfig)
-------------------------------------------
- Any incident whose PriorityResult.score > policy.approval_required_above_priority_score
  → ApprovalState.REQUIRED
- Any resource with type in policy.approval_required_for_resource_types
  → ApprovalState.REQUIRED
- Otherwise → ApprovalState.AUTO

Gap actions (unassigned incidents)
------------------------------------
When the optimizer could not assign a resource, the agent emits a PlanAction
with resource_id=None, action_description containing "escalat" (required by
PlanAction validator), and approval_state=REQUIRED (gaps always need a human).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.agents.policy_config import DEFAULT_POLICY, PolicyConfig
from src.agents.response_plan import ApprovalState, PlanAction, ResponsePlan
from src.engine.optimizer_result import OptimizationResult
from src.engine.priority_result import PriorityResult
from src.knowledge.knowledge_base import KnowledgeBase, RetrievalResult
from src.models.incident import Incident
from src.models.resource import Resource
from src.models.situation import SituationState
from src.reasoning.granite_client import GraniteUnavailable
from src.reasoning.reasoning_layer import GraniteReasoningLayer
from src.reasoning.reasoning_result import ReasoningSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PlanningResult (top-level output container)
# ---------------------------------------------------------------------------

@dataclass
class PlanningResult:
    """Output of one ResponsePlanningAgent.plan() call.

    Attributes
    ----------
    plan
        The structured ResponsePlan.  Always present.
    success
        True if the plan contains at least one PlanAction.
    warnings
        Non-fatal issues accumulated during planning.
    errors
        Fatal issues that prevented plan generation.  If non-empty, plan may
        be partial or empty — always check success.
    """
    plan: ResponsePlan
    success: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_action_description(
    incident: Incident,
    resource: Resource | None,
    priority_level: str,
    estimated_travel_minutes: float | None,
) -> str:
    """Build a deterministic one-line action description."""
    level_tag = f"[{priority_level.upper()}]"
    if resource is None:
        return (
            f"{level_tag} RESOURCE GAP — escalate to EOC: "
            f"No resource available for {incident.title} (zone {incident.zone_id})."
        )
    eta_str = (
        f" ETA {estimated_travel_minutes:.0f} min"
        if estimated_travel_minutes is not None else ""
    )
    return (
        f"{level_tag} Deploy {resource.name} ({resource.type}) "
        f"to zone {incident.zone_id}{eta_str}: {incident.title[:120]}"
    )[:500]


def _build_action_reasoning(
    incident: Incident,
    resource: Resource | None,
    priority_result: PriorityResult,
    optimizer_reason_codes: tuple[str, ...],
) -> str:
    """Build a deterministic per-action reasoning paragraph."""
    lines: list[str] = []

    # priority justification
    pr_codes = ", ".join(priority_result.reason_codes) or "none"
    lines.append(
        f"Priority score {priority_result.score:.3f} ({priority_result.level.upper()}). "
        f"Driving factors: {pr_codes}."
    )

    # factor breakdown — top 2 non-zero contributors
    ranked = sorted(
        [f for f in priority_result.factors if f.contribution > 0.0],
        key=lambda f: f.contribution,
        reverse=True,
    )
    for factor in ranked[:2]:
        lines.append(
            f"  - {factor.name}: raw={factor.raw_value!r}, "
            f"contribution={factor.contribution:.3f} (weight {factor.weight:.2f})"
        )

    # assignment justification
    if resource is not None:
        opt_codes = ", ".join(optimizer_reason_codes) or "none"
        lines.append(
            f"Assigned resource '{resource.name}' [{resource.type}]. "
            f"Optimizer: {opt_codes}."
        )
    else:
        codes = ", ".join(optimizer_reason_codes) or "none"
        lines.append(
            f"No resource assigned. Optimizer reason: {codes}. "
            "Manual escalation required."
        )

    return " | ".join(lines)[:2000]


def _merge_reason_codes(
    priority_codes: tuple[str, ...],
    optimizer_codes: tuple[str, ...],
) -> tuple[str, ...]:
    """Combine and deduplicate priority + optimizer reason codes."""
    seen: set[str] = set()
    merged: list[str] = []
    for code in (*priority_codes, *optimizer_codes):
        if code not in seen:
            seen.add(code)
            merged.append(code)
    return tuple(merged)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ResponsePlanningAgent:
    """Converts prioritized incidents and resource assignments into a structured plan.

    This agent has NO authority to:
    - Invent or modify resource assignments
    - Change any priority score or travel time
    - Access any external data source

    It ONLY:
    - Reads the deterministic outputs (PriorityResult[], OptimizationResult, Resources)
    - Applies PolicyConfig rules to derive approval, timing, and responsible unit
    - Calls Granite for a reasoning narrative (degrades gracefully to fallback)
    - Assembles and returns a validated ResponsePlan

    Usage::

        agent = ResponsePlanningAgent(city="Ahmedabad")
        result = agent.plan(
            state=situation_state,
            priority_results=ranked_results,
            opt_result=optimization_result,
            resources=available_resources,
        )
        if result.success:
            for action in result.plan.plan_actions:
                print(action.priority_rank, action.action_description)
    """

    def __init__(
        self,
        city: str,
        policy: PolicyConfig | None = None,
        reasoning_layer: GraniteReasoningLayer | None = None,
        knowledge_base: KnowledgeBase | None = None,
    ) -> None:
        if not city or not city.strip():
            raise ValueError("city must be a non-empty string.")
        self.city = city.strip()
        self.policy = policy or DEFAULT_POLICY
        self._reasoning = reasoning_layer or GraniteReasoningLayer()
        self._kb: KnowledgeBase | None = knowledge_base

    # ── public entry point ────────────────────────────────────────────────

    def plan(
        self,
        state: SituationState,
        priority_results: list[PriorityResult],
        opt_result: OptimizationResult,
        resources: list[Resource],
    ) -> PlanningResult:
        """Generate a structured ResponsePlan from deterministic engine outputs.

        Parameters
        ----------
        state:
            Current SituationState snapshot.
        priority_results:
            Ranked PriorityResult list from IncidentPriorityEngine.rank().
        opt_result:
            OptimizationResult from ResourceOptimizer.optimize().
        resources:
            Available Resource objects (same list passed to the optimizer).

        Returns
        -------
        PlanningResult
            Always returned — never raises.  Check .success and .errors.
        """
        warnings: list[str] = []
        errors: list[str] = []

        # ── build lookup maps ─────────────────────────────────────────────
        resource_map: dict[str, Resource] = {r.id: r for r in resources}
        pr_map: dict[str, PriorityResult] = {pr.incident_id: pr for pr in priority_results}

        # Incidents come from priority_results (they carry incident_id).
        # We reconstruct a minimal incident registry from assignments +
        # unassigned so we always have incident_id → PriorityResult.
        if not priority_results:
            warnings.append("No priority_results provided — plan will be empty.")

        plan_actions: list[PlanAction] = []
        rank = 0

        # ── assigned incidents ────────────────────────────────────────────
        for assignment in opt_result.assignments:
            rank += 1
            pr = pr_map.get(assignment.incident_id)
            if pr is None:
                warnings.append(
                    f"Assignment references unknown incident_id "
                    f"'{assignment.incident_id}' — skipped."
                )
                continue

            resource = resource_map.get(assignment.resource_id)
            if resource is None:
                warnings.append(
                    f"Assignment references unknown resource_id "
                    f"'{assignment.resource_id}' — skipped."
                )
                continue

            # ── traceability: find incident to get evidence_ids ───────────
            # We get evidence_ids from the state if the incident is there,
            # otherwise from the assignment (incident zone is enough for V1).
            evidence_ids: tuple[str, ...] = ()
            incident_obj = self._find_incident_in_state(state, assignment.incident_id)
            if incident_obj is not None:
                evidence_ids = tuple(incident_obj.evidence_ids)

            # ── policy: approval + timing + unit ─────────────────────────
            needs_approval = self.policy.requires_approval(
                priority_score=pr.score,
                resource_type=resource.type,
            )
            approval = ApprovalState.REQUIRED if needs_approval else ApprovalState.AUTO
            target_mins = self.policy.target_minutes(pr.level)
            unit = self.policy.responsible_unit(resource.type)

            # ── build descriptions ────────────────────────────────────────
            inc_stub = incident_obj or _IncidentStub(  # type: ignore[call-arg]
                id=assignment.incident_id,
                zone_id=assignment.incident_zone,
                title=f"Incident {assignment.incident_id[:8]}",
                evidence_ids=[],
            )
            action_desc = _build_action_description(
                incident=inc_stub,
                resource=resource,
                priority_level=str(pr.level),
                estimated_travel_minutes=assignment.estimated_travel_minutes,
            )
            reason_text = _build_action_reasoning(
                incident=inc_stub,
                resource=resource,
                priority_result=pr,
                optimizer_reason_codes=assignment.reason_codes,
            )
            merged_codes = _merge_reason_codes(pr.reason_codes, assignment.reason_codes)

            # ── knowledge retrieval ───────────────────────────────────────
            kb_result = self._retrieve_for_action(
                incident_title=inc_stub.title,
                resource_type=str(resource.type),
                priority_level=str(pr.level),
                reason_codes=pr.reason_codes,
            )
            citations = tuple(kb_result.citations)
            chunk_ids = tuple(h.chunk.id for h in kb_result.hits)

            plan_actions.append(
                PlanAction(
                    incident_id=assignment.incident_id,
                    resource_id=assignment.resource_id,
                    priority_result_id=assignment.incident_id,  # same key
                    action_description=action_desc,
                    responsible_unit=unit,
                    priority_rank=rank,
                    priority_level=str(pr.level),
                    priority_score=pr.score,
                    target_response_minutes=target_mins,
                    estimated_travel_minutes=assignment.estimated_travel_minutes,
                    reason_codes=merged_codes,
                    evidence_ids=evidence_ids,
                    citations=citations,
                    retrieved_chunk_ids=chunk_ids,
                    approval_state=approval,
                    reasoning_text=reason_text,
                )
            )

        # ── unassigned incidents (gap actions) ────────────────────────────
        for unassigned in opt_result.unassigned_incidents:
            rank += 1
            pr = pr_map.get(unassigned.incident_id)
            priority_level = str(pr.level) if pr else "unknown"
            priority_score = pr.score if pr else unassigned.priority_score
            target_mins = self.policy.target_minutes(priority_level)

            incident_obj = self._find_incident_in_state(state, unassigned.incident_id)
            evidence_ids = tuple(incident_obj.evidence_ids) if incident_obj else ()
            zone_id = incident_obj.zone_id if incident_obj else "unknown"
            title = incident_obj.title if incident_obj else f"Incident {unassigned.incident_id[:8]}"

            gap_desc = (
                f"[{priority_level.upper()}] RESOURCE GAP — escalate to EOC: "
                f"No resource available for {title} (zone {zone_id}). "
                f"Optimizer: {', '.join(unassigned.reason_codes) or 'unknown'}."
            )[:500]

            gap_reasoning = (
                f"No resource could be assigned. "
                f"Priority score {priority_score:.3f}. "
                f"Optimizer codes: {', '.join(unassigned.reason_codes) or 'none'}. "
                f"Escalation to EOC / mutual-aid required."
            )

            merged_codes = _merge_reason_codes(
                pr.reason_codes if pr else (),
                unassigned.reason_codes,
            )

            # ── knowledge retrieval for gap ───────────────────────────────
            gap_kb = self._retrieve_for_action(
                incident_title=title,
                resource_type="",
                priority_level=priority_level,
                reason_codes=pr.reason_codes if pr else (),
                category_hint="escalation",
            )
            gap_citations = tuple(gap_kb.citations)
            gap_chunk_ids = tuple(h.chunk.id for h in gap_kb.hits)

            plan_actions.append(
                PlanAction(
                    incident_id=unassigned.incident_id,
                    resource_id=None,
                    priority_result_id=unassigned.incident_id,
                    action_description=gap_desc,
                    responsible_unit="Municipal EOC",
                    priority_rank=rank,
                    priority_level=priority_level,
                    priority_score=priority_score,
                    target_response_minutes=target_mins,
                    estimated_travel_minutes=None,
                    reason_codes=merged_codes,
                    evidence_ids=evidence_ids,
                    citations=gap_citations,
                    retrieved_chunk_ids=gap_chunk_ids,
                    approval_state=ApprovalState.REQUIRED,
                    reasoning_text=gap_reasoning,
                )
            )

        # ── plan-level Granite reasoning ──────────────────────────────────
        # Build a synthetic incident list for the reasoning layer from
        # what we have (priority results give us incident IDs, state gives bodies).
        incidents_for_reasoning: list[Incident] = []
        for pr in priority_results:
            obj = self._find_incident_in_state(state, pr.incident_id)
            if obj is not None:
                incidents_for_reasoning.append(obj)

        # Aggregate unique citations + KB context block for Granite prompt
        all_citations: list[str] = []
        seen_cites: set[str] = set()
        kb_context_blocks: list[str] = []
        for pa in plan_actions:
            for cid in pa.retrieved_chunk_ids:
                if self._kb:
                    chunk = self._kb.get(cid)
                    if chunk and chunk.source_ref not in seen_cites:
                        seen_cites.add(chunk.source_ref or chunk.id)
                        all_citations.append(chunk.source_ref or chunk.title)
                        kb_context_blocks.append(
                            f"[{chunk.source_ref or chunk.title}]\n{chunk.text}"
                        )
            for cite in pa.citations:
                if cite not in seen_cites:
                    seen_cites.add(cite)
                    all_citations.append(cite)

        reasoning_summary = ""
        reasoning_source = "fallback"
        try:
            rr = self._reasoning.generate_response_plan_with_kb(
                opt_result=opt_result,
                priority_results=priority_results,
                incidents=incidents_for_reasoning,
                kb_context=kb_context_blocks,
            )
            reasoning_summary = rr.text
            reasoning_source = (
                "granite" if rr.source == ReasoningSource.GRANITE else "fallback"
            )
        except (GraniteUnavailable, Exception) as exc:  # noqa: BLE001
            logger.warning("ResponsePlanningAgent: reasoning failed: %s", exc)
            reasoning_summary = self._deterministic_plan_summary(plan_actions)
            warnings.append(f"Reasoning layer unavailable: {exc}")

        # ── enforce max_actions_per_incident cap ──────────────────────────
        plan_actions = self._apply_action_cap(plan_actions, warnings)

        # ── derive plan-level flags ───────────────────────────────────────
        requires_approval = any(
            a.approval_state in (ApprovalState.REQUIRED, ApprovalState.PENDING_APPROVAL)
            for a in plan_actions
        )
        gap_count = sum(1 for a in plan_actions if a.resource_id is None)

        plan = ResponsePlan(
            city=self.city,
            plan_actions=plan_actions,
            gap_count=gap_count,
            requires_human_approval=requires_approval,
            knowledge_citations=tuple(all_citations),
            reasoning_summary=reasoning_summary,
            reasoning_source=reasoning_source,
            warnings=warnings,
        )

        return PlanningResult(
            plan=plan,
            success=len(plan_actions) > 0,
            warnings=warnings,
            errors=errors,
        )

    # ── internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _find_incident_in_state(
        state: SituationState,
        incident_id: str,
    ) -> Incident | None:
        """Walk state.zones to locate an Incident matching incident_id.

        SituationState.zones is a dict[zone_id, ZoneStatus].  ZoneStatus holds
        the most recent evidence snapshot, not Incident objects directly.
        We can't retrieve the Incident from SituationState alone — callers must
        pass a populated state where zone metadata is set, OR the incident_id
        will not be found and the agent uses a stub.

        In practice the workflow always calls plan() after stage 3 (detect
        incidents), so this is only None in unit tests that omit state zones.
        """
        # SituationState does not store Incident objects — they live in the
        # engine.  We inspect _incidents if callers have injected them into the
        # state's internal dict (not part of the model contract).
        # Fallback: return None and let the caller use the stub.
        incidents = getattr(state, "_incidents", None)
        if isinstance(incidents, dict):
            return incidents.get(incident_id)
        return None

    def _apply_action_cap(
        self,
        actions: list[PlanAction],
        warnings: list[str],
    ) -> list[PlanAction]:
        """Enforce max_actions_per_incident policy cap."""
        counts: dict[str, int] = {}
        result: list[PlanAction] = []
        cap = self.policy.max_actions_per_incident
        for a in actions:
            count = counts.get(a.incident_id, 0)
            if count >= cap:
                warnings.append(
                    f"Incident '{a.incident_id[:8]}' exceeds max_actions_per_incident "
                    f"({cap}) — action at rank {a.priority_rank} dropped."
                )
                continue
            counts[a.incident_id] = count + 1
            result.append(a)
        return result

    def _retrieve_for_action(
        self,
        incident_title: str,
        resource_type: str,
        priority_level: str,
        reason_codes: tuple[str, ...],
        category_hint: str | None = None,
    ) -> RetrievalResult:
        """Retrieve relevant KB chunks for one planned action.

        Query is built from incident title + resource type + priority level +
        reason codes.  No live sensor data or numeric thresholds are included.

        Returns an empty RetrievalResult when no KB is configured.
        """
        from src.knowledge.knowledge_base import RetrievalResult
        from src.knowledge.knowledge_chunk import KnowledgeCategory

        if self._kb is None:
            return RetrievalResult(query="", hits=[])

        # Build a descriptive query from structured signals
        query_parts: list[str] = [incident_title, resource_type, priority_level]
        query_parts.extend(c.lower().replace("_", " ") for c in reason_codes)
        if category_hint:
            query_parts.append(category_hint)
        query = " ".join(p for p in query_parts if p)

        cat_filter: KnowledgeCategory | None = None
        if category_hint:
            try:
                cat_filter = KnowledgeCategory(category_hint)
            except ValueError:
                pass

        return self._kb.retrieve(query=query, top_k=3, category_filter=cat_filter)

    @staticmethod
    def _deterministic_plan_summary(actions: list[PlanAction]) -> str:
        """Fallback plan summary when Granite is unavailable."""
        if not actions:
            return "No actions generated — no incidents or resources available."
        lines = [f"Flood Response Plan — {len(actions)} action(s):"]
        for a in actions:
            flag = " [APPROVAL REQUIRED]" if a.approval_state != ApprovalState.AUTO else ""
            lines.append(f"  {a.priority_rank}. {a.action_description}{flag}")
        gaps = sum(1 for a in actions if a.resource_id is None)
        if gaps:
            lines.append(f"{gaps} resource gap(s) — escalation to EOC required.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# _IncidentStub — lightweight stand-in used when Incident is not in state
# ---------------------------------------------------------------------------

class _IncidentStub:
    """Minimal duck-type stand-in for Incident when the object isn't available."""

    def __init__(self, id: str, zone_id: str, title: str, evidence_ids: list[str]) -> None:
        self.id = id
        self.zone_id = zone_id
        self.title = title
        self.evidence_ids = evidence_ids
