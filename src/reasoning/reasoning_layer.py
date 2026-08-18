"""GraniteReasoningLayer — the single entry point for all LLM reasoning.

This layer sits between the deterministic engine outputs and the operator
interface.  It:

  1. Accepts typed engine outputs (SituationState, Incident list,
     PriorityResult list, OptimizationResult, Resource list).
  2. Serialises them to plain JSON dicts (no raw model internals).
  3. Builds a strict prompt via prompt_templates.py.
  4. Calls GraniteClient.generate().
  5. Parses the JSON response into a ReasoningResult.
  6. If Granite is unavailable (GraniteUnavailable), returns a deterministic
     fallback built entirely from the engine data — no LLM required.

What Granite NEVER does here
-----------------------------
- Calculates or changes any score, distance, or rank.
- Accesses the internet, databases, or any external system.
- Receives anything other than the structured engine outputs.

Fallback contract
-----------------
Every public method guarantees a valid ReasoningResult even when Granite is
completely unreachable.  The fallback text is concise and informative but is
explicitly labelled ``source="fallback"`` so operators know it was not LLM-generated.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.engine.optimizer_result import (
    UA_ALL_TOO_FAR,
    UA_NO_CAPABLE_RESOURCE,
    UA_NO_RESOURCE,
    Assignment,
    OptimizationResult,
    UnassignedIncident,
)
from src.engine.priority_result import PriorityResult
from src.models.incident import Incident
from src.models.resource import Resource
from src.models.situation import SituationState
from src.reasoning.granite_client import GraniteClient, GraniteUnavailable
from src.reasoning.prompt_templates import (
    build_assignment_explanation_prompt,
    build_missing_information_prompt,
    build_priority_explanation_prompt,
    build_response_plan_prompt,
    build_response_plan_with_kb_prompt,
    build_situation_summary_prompt,
)
from src.reasoning.reasoning_result import (
    ReasoningResult,
    ReasoningSource,
    ReasoningTask,
)

logger = logging.getLogger(__name__)

# ── reason code → plain English ───────────────────────────────────────────────
_UA_MESSAGES: dict[str, str] = {
    UA_NO_RESOURCE:         "No resources are currently available.",
    UA_NO_CAPABLE_RESOURCE: "No available resource can handle this severity level.",
    UA_ALL_TOO_FAR:         "All capable resources exceed the maximum travel time.",
}


# ── serialisation helpers ─────────────────────────────────────────────────────

def _state_to_dict(state: SituationState) -> dict[str, Any]:
    zones = {
        zid: {
            "zone_id": z.zone_id,
            "severity": z.severity,
            "latest_rainfall_mm_hr": z.latest_rainfall_mm_hr,
            "latest_water_level_m": z.latest_water_level_m,
            "road_blocked": z.road_blocked,
            "affected_population": z.affected_population,
            "evidence_count": z.evidence_count,
        }
        for zid, z in state.zones.items()
    }
    return {
        "city": state.city,
        "updated_at": str(state.updated_at),
        "overall_severity": state.overall_severity,
        "zones": zones,
    }


def _incident_to_dict(inc: Incident) -> dict[str, Any]:
    return {
        "id": inc.id,
        "city": inc.city,
        "zone_id": inc.zone_id,
        "severity": inc.severity,
        "risk_score": inc.risk_score,
        "title": inc.title,
        "status": inc.status,
        "description": inc.description,
        "affected_zone_ids": inc.affected_zone_ids,
    }


def _priority_to_dict(pr: PriorityResult) -> dict[str, Any]:
    return {
        "incident_id": pr.incident_id,
        "score": pr.score,
        "level": pr.level,
        "reason_codes": list(pr.reason_codes),
        "factors": [
            {
                "name": f.name,
                "raw_value": f.raw_value,
                "normalised": f.normalised,
                "contribution": f.contribution,
            }
            for f in pr.factors
        ],
    }


def _assignment_to_dict(a: Assignment) -> dict[str, Any]:
    return {
        "incident_id": a.incident_id,
        "resource_id": a.resource_id,
        "incident_zone": a.incident_zone,
        "resource_zone": a.resource_zone,
        "estimated_travel_minutes": a.estimated_travel_minutes,
        "fit_score": a.fit_score,
        "reason_codes": list(a.reason_codes),
    }


def _unassigned_to_dict(u: UnassignedIncident) -> dict[str, Any]:
    return {
        "incident_id": u.incident_id,
        "priority_score": u.priority_score,
        "reason_codes": list(u.reason_codes),
    }


def _resource_to_dict(r: Resource) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "type": r.type,
        "status": r.status,
        "city": r.city,
        "home_zone_id": r.home_zone_id,
        "current_zone_id": r.current_zone_id,
        "capacity": r.capacity,
    }


def _parse_json_response(text: str) -> dict[str, Any]:
    """Best-effort parse of Granite's JSON response.

    Granite sometimes wraps the JSON in markdown fences.  Strip them before
    parsing.  Returns an empty dict on any parse failure.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()
    try:
        result = json.loads(stripped)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


# ── main layer ────────────────────────────────────────────────────────────────

class GraniteReasoningLayer:
    """Translates deterministic engine outputs into human-readable explanations.

    All methods return a :class:`ReasoningResult` with ``source`` indicating
    whether the response came from Granite (``"granite"``) or the deterministic
    fallback (``"fallback"``).

    Usage::

        layer = GraniteReasoningLayer()          # reads GRANITE_API_* from env
        result = layer.summarize_situation(state, incidents)
        print(result.source, result.text)
    """

    def __init__(self, client: GraniteClient | None = None) -> None:
        self._client = client or GraniteClient()

    # ── Task 1: Situation Summary ─────────────────────────────────────────────

    def summarize_situation(
        self,
        state: SituationState,
        incidents: list[Incident],
    ) -> ReasoningResult:
        """Produce a plain-English situation overview.

        Fallback: builds summary from zone severities and incident counts.
        """
        state_d = _state_to_dict(state)
        incs_d = [_incident_to_dict(i) for i in incidents]
        prompt = build_situation_summary_prompt(state_d, incs_d)

        try:
            raw = self._client.generate(prompt)
            structured = _parse_json_response(raw)
            text = structured.get("summary", raw)
            return ReasoningResult(
                task=ReasoningTask.SITUATION_SUMMARY,
                source=ReasoningSource.GRANITE,
                text=text,
                structured=structured,
            )
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for situation_summary: %s", exc)
            return self._fallback_situation_summary(state, incidents)

    def _fallback_situation_summary(
        self,
        state: SituationState,
        incidents: list[Incident],
    ) -> ReasoningResult:
        overall = state.overall_severity
        n_zones = len(state.zones)
        n_inc = len(incidents)
        at_risk = [
            zid for zid, z in state.zones.items()
            if z.severity not in ("normal",)
        ]
        text = (
            f"City: {state.city}. Overall severity: {overall.upper()}. "
            f"{n_zones} zone(s) monitored, {len(at_risk)} at elevated risk. "
            f"{n_inc} active incident(s) open."
        )
        structured = {
            "summary": text,
            "overall_severity": overall,
            "zones_at_risk": at_risk,
            "key_concerns": [
                f"{z}: {s.severity} severity"
                for z, s in state.zones.items()
                if s.severity not in ("normal",)
            ][:4],
        }
        return ReasoningResult(
            task=ReasoningTask.SITUATION_SUMMARY,
            source=ReasoningSource.FALLBACK,
            text=text,
            structured=structured,
        )

    # ── Task 2: Priority Explanation ──────────────────────────────────────────

    def explain_priorities(
        self,
        priority_results: list[PriorityResult],
        incidents: list[Incident],
    ) -> ReasoningResult:
        """Explain why incidents are ranked as they are.

        Fallback: generates one-line explanations from reason_codes.
        """
        pr_d = [_priority_to_dict(p) for p in priority_results]
        inc_map = {i.id: i for i in incidents}
        incs_d = [_incident_to_dict(inc_map[p.incident_id])
                  for p in priority_results if p.incident_id in inc_map]
        prompt = build_priority_explanation_prompt(pr_d, incs_d)

        try:
            raw = self._client.generate(prompt)
            structured = _parse_json_response(raw)
            explanations = structured.get("explanations", [])
            text = "\n".join(
                f"[{e.get('rank', i+1)}] {e.get('explanation', '')}"
                for i, e in enumerate(explanations)
            ) or raw
            return ReasoningResult(
                task=ReasoningTask.PRIORITY_EXPLANATION,
                source=ReasoningSource.GRANITE,
                text=text,
                structured=structured,
            )
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for explain_priorities: %s", exc)
            return self._fallback_priority_explanation(priority_results, incidents)

    def _fallback_priority_explanation(
        self,
        priority_results: list[PriorityResult],
        incidents: list[Incident],
    ) -> ReasoningResult:
        inc_map = {i.id: i for i in incidents}
        explanations = []
        lines = []
        for rank, pr in enumerate(priority_results, 1):
            inc = inc_map.get(pr.incident_id)
            title = inc.title if inc else pr.incident_id
            codes = ", ".join(pr.reason_codes) if pr.reason_codes else "standard severity"
            explanation = (
                f"Ranked #{rank} ({pr.level.upper()}, score {pr.score:.2f}): "
                f"{title}. Driven by: {codes}."
            )
            explanations.append({
                "incident_id": pr.incident_id,
                "rank": rank,
                "level": pr.level,
                "explanation": explanation,
            })
            lines.append(explanation)
        text = "\n".join(lines) or "No active incidents to prioritise."
        return ReasoningResult(
            task=ReasoningTask.PRIORITY_EXPLANATION,
            source=ReasoningSource.FALLBACK,
            text=text,
            structured={"explanations": explanations},
        )

    # ── Task 3: Assignment Explanation ────────────────────────────────────────

    def explain_assignments(
        self,
        opt_result: OptimizationResult,
        resources: list[Resource],
    ) -> ReasoningResult:
        """Explain resource-allocation decisions.

        Fallback: translates reason codes to plain English.
        """
        assigns_d = [_assignment_to_dict(a) for a in opt_result.assignments]
        unassigned_d = [_unassigned_to_dict(u) for u in opt_result.unassigned_incidents]
        res_d = [_resource_to_dict(r) for r in resources]
        prompt = build_assignment_explanation_prompt(assigns_d, unassigned_d, res_d)

        try:
            raw = self._client.generate(prompt)
            structured = _parse_json_response(raw)
            parts: list[str] = []
            for item in structured.get("assignments", []):
                parts.append(f"Assigned: {item.get('explanation', '')}")
            for item in structured.get("unassigned", []):
                parts.append(f"Unassigned: {item.get('explanation', '')}")
            text = "\n".join(parts) or raw
            return ReasoningResult(
                task=ReasoningTask.ASSIGNMENT_EXPLANATION,
                source=ReasoningSource.GRANITE,
                text=text,
                structured=structured,
            )
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for explain_assignments: %s", exc)
            return self._fallback_assignment_explanation(opt_result, resources)

    def _fallback_assignment_explanation(
        self,
        opt_result: OptimizationResult,
        resources: list[Resource],
    ) -> ReasoningResult:
        res_map = {r.id: r for r in resources}
        assign_items = []
        lines = []

        for a in opt_result.assignments:
            res = res_map.get(a.resource_id)
            res_name = res.name if res else a.resource_id
            codes = ", ".join(a.reason_codes)
            explanation = (
                f"{res_name} assigned to incident {a.incident_id} "
                f"(zone {a.incident_zone}, ETA {a.estimated_travel_minutes} min). "
                f"Reason: {codes}."
            )
            assign_items.append({
                "incident_id": a.incident_id,
                "resource_id": a.resource_id,
                "explanation": explanation,
            })
            lines.append(f"[OK] {explanation}")

        unassigned_items = []
        for u in opt_result.unassigned_incidents:
            reason_text = _UA_MESSAGES.get(
                u.reason_codes[0] if u.reason_codes else "",
                "Reason unknown.",
            )
            explanation = (
                f"Incident {u.incident_id} unassigned "
                f"(priority score {u.priority_score:.2f}). {reason_text}"
            )
            unassigned_items.append({
                "incident_id": u.incident_id,
                "explanation": explanation,
            })
            lines.append(f"[--] {explanation}")

        text = "\n".join(lines) or "No assignments to explain."
        return ReasoningResult(
            task=ReasoningTask.ASSIGNMENT_EXPLANATION,
            source=ReasoningSource.FALLBACK,
            text=text,
            structured={"assignments": assign_items, "unassigned": unassigned_items},
        )

    # ── Task 4: Response Plan ─────────────────────────────────────────────────

    def generate_response_plan(
        self,
        opt_result: OptimizationResult,
        priority_results: list[PriorityResult],
        incidents: list[Incident],
    ) -> ReasoningResult:
        """Generate a numbered operator action plan.

        Fallback: numbered list from assignments in priority order.
        """
        assigns_d = [_assignment_to_dict(a) for a in opt_result.assignments]
        pr_d = [_priority_to_dict(p) for p in priority_results]
        incs_d = [_incident_to_dict(i) for i in incidents]
        prompt = build_response_plan_prompt(assigns_d, pr_d, incs_d)

        try:
            raw = self._client.generate(prompt)
            structured = _parse_json_response(raw)
            steps = structured.get("steps", [])
            lines = [structured.get("plan_title", "Response Plan")]
            for s in steps:
                lines.append(
                    f"  {s.get('step', '?')}. [{s.get('priority_level','').upper()}] "
                    f"{s.get('action', '')}"
                )
            note = structured.get("coverage_note", "")
            if note:
                lines.append(note)
            text = "\n".join(lines)
            return ReasoningResult(
                task=ReasoningTask.RESPONSE_PLAN,
                source=ReasoningSource.GRANITE,
                text=text,
                structured=structured,
            )
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for generate_response_plan: %s", exc)
            return self._fallback_response_plan(opt_result, priority_results, incidents)

    def _fallback_response_plan(
        self,
        opt_result: OptimizationResult,
        priority_results: list[PriorityResult],
        incidents: list[Incident],
    ) -> ReasoningResult:
        inc_map = {i.id: i for i in incidents}
        pr_map = {p.incident_id: p for p in priority_results}

        steps = []
        lines = ["Flood Response Plan"]
        for step_n, a in enumerate(opt_result.assignments, 1):
            inc = inc_map.get(a.incident_id)
            pr = pr_map.get(a.incident_id)
            title = inc.title if inc else a.incident_id
            level = pr.level if pr else "unknown"
            action = (
                f"Deploy resource {a.resource_id} -> zone {a.incident_zone} "
                f"(ETA {a.estimated_travel_minutes} min): {title}"
            )
            steps.append({
                "step": step_n,
                "incident_id": a.incident_id,
                "action": action,
                "priority_level": level,
                "estimated_travel_minutes": a.estimated_travel_minutes,
            })
            lines.append(f"  {step_n}. [{level.upper()}] {action}")

        n_unassigned = len(opt_result.unassigned_incidents)
        coverage_note = (
            "All incidents covered."
            if n_unassigned == 0
            else f"{n_unassigned} incident(s) could not be assigned due to resource constraints."
        )
        lines.append(coverage_note)
        text = "\n".join(lines)

        return ReasoningResult(
            task=ReasoningTask.RESPONSE_PLAN,
            source=ReasoningSource.FALLBACK,
            text=text,
            structured={
                "plan_title": "Flood Response Plan",
                "steps": steps,
                "coverage_note": coverage_note,
            },
        )

    def generate_response_plan_with_kb(
        self,
        opt_result: OptimizationResult,
        priority_results: list[PriorityResult],
        incidents: list[Incident],
        kb_context: list[str],
    ) -> ReasoningResult:
        """Generate an operator response plan grounded by retrieved policy context.

        ``kb_context`` is a list of pre-formatted policy text blocks produced by
        KnowledgeBase.retrieve() and formatted by the caller.  Each element is
        formatted as "[<source_ref>]\\n<text>".

        Granite is instructed to cite source refs where relevant.
        Fallback: delegates to ``_fallback_response_plan`` (same as original).
        """
        assigns_d = [_assignment_to_dict(a) for a in opt_result.assignments]
        pr_d = [_priority_to_dict(p) for p in priority_results]
        incs_d = [_incident_to_dict(i) for i in incidents]
        prompt = build_response_plan_with_kb_prompt(assigns_d, pr_d, incs_d, kb_context)

        try:
            raw = self._client.generate(prompt)
            structured = _parse_json_response(raw)
            steps = structured.get("steps", [])
            lines = [structured.get("plan_title", "Response Plan (Policy-Grounded)")]
            for s in steps:
                policy_note = s.get("policy_note") or ""
                lines.append(
                    f"  {s.get('step', '?')}. [{s.get('priority_level','').upper()}] "
                    f"{s.get('action', '')}"
                    + (f" | Policy: {policy_note}" if policy_note else "")
                )
            note = structured.get("coverage_note", "")
            if note:
                lines.append(note)
            cites = structured.get("policy_citations", [])
            if cites:
                lines.append("Citations: " + "; ".join(cites))
            text = "\n".join(lines)
            return ReasoningResult(
                task=ReasoningTask.RESPONSE_PLAN,
                source=ReasoningSource.GRANITE,
                text=text,
                structured=structured,
            )
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for generate_response_plan_with_kb: %s", exc)
            return self._fallback_response_plan(opt_result, priority_results, incidents)

    # ── Task 5: Missing Information ───────────────────────────────────────────

    def identify_missing_information(
        self,
        state: SituationState,
        incidents: list[Incident],
        resources: list[Resource],
    ) -> ReasoningResult:
        """Identify data gaps that would improve response decisions.

        Fallback: scans for null/None fields deterministically.
        """
        state_d = _state_to_dict(state)
        incs_d = [_incident_to_dict(i) for i in incidents]
        res_d = [_resource_to_dict(r) for r in resources]
        prompt = build_missing_information_prompt(state_d, incs_d, res_d)

        try:
            raw = self._client.generate(prompt)
            structured = _parse_json_response(raw)
            gaps = structured.get("gaps", [])
            lines = [f"• {g.get('field','?')} ({g.get('context','?')}): {g.get('impact','')}"
                     for g in gaps]
            summary = structured.get("summary", "")
            text = (summary + "\n" + "\n".join(lines)).strip()
            return ReasoningResult(
                task=ReasoningTask.MISSING_INFORMATION,
                source=ReasoningSource.GRANITE,
                text=text,
                structured=structured,
            )
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for identify_missing_information: %s", exc)
            return self._fallback_missing_information(state, incidents, resources)

    def _fallback_missing_information(
        self,
        state: SituationState,
        incidents: list[Incident],
        resources: list[Resource],
    ) -> ReasoningResult:
        gaps: list[dict[str, str]] = []

        for zid, z in state.zones.items():
            if z.latest_rainfall_mm_hr is None:
                gaps.append({
                    "field": "latest_rainfall_mm_hr",
                    "context": f"zone {zid}",
                    "impact": "Cannot assess rainfall-driven severity without this reading.",
                })
            if z.latest_water_level_m is None:
                gaps.append({
                    "field": "latest_water_level_m",
                    "context": f"zone {zid}",
                    "impact": "Water level is required for flood depth assessment.",
                })
            if z.affected_population is None:
                gaps.append({
                    "field": "affected_population",
                    "context": f"zone {zid}",
                    "impact": "Population impact score cannot be computed.",
                })

        for inc in incidents:
            if not inc.description:
                gaps.append({
                    "field": "description",
                    "context": f"incident {inc.id}",
                    "impact": "Operators lack narrative context for this incident.",
                })

        for res in resources:
            if res.current_zone_id is None:
                gaps.append({
                    "field": "current_zone_id",
                    "context": f"resource {res.id} ({res.name})",
                    "impact": "Travel time cannot be estimated without a known location.",
                })

        n = len(gaps)
        summary = (
            f"{n} data gap(s) identified. "
            + ("Data completeness is good." if n == 0
               else "Filling these gaps would improve response accuracy.")
        )
        lines = [
            f"• {g['field']} ({g['context']}): {g['impact']}"
            for g in gaps
        ]
        text = (summary + ("\n" + "\n".join(lines) if lines else "")).strip()

        return ReasoningResult(
            task=ReasoningTask.MISSING_INFORMATION,
            source=ReasoningSource.FALLBACK,
            text=text,
            structured={"gaps": gaps, "summary": summary},
        )
