"""FloodResponseWorkflow — nine-stage deterministic + Granite workflow.

Stage sequence
--------------
1  ingest_events        RawEvent[]  → EngineRecords, Evidence, SituationState, Incidents
2  build_situation      Read engine.state → capture SituationState snapshot
3  detect_incidents     Read engine.incidents → Incident[] (open only)
4  score_priorities     Incident[] + context → PriorityResult[] (ranked)
5  allocate_resources   PriorityResult[] + Resource[] → OptimizationResult
6  generate_actions     OptimizationResult → Action[] (one per assignment)
7  reason_situation     SituationState + Incidents → Granite/fallback ReasoningResult
8  generate_response    Assignments + Priorities → Granite/fallback operator plan
9  persist_outcomes     Actions → Outcome[] (in-memory store)

The workflow is a plain Python class — no framework, no async.
Each stage method mutates ``self.result`` and returns it for chaining.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from src.engine.engine import SituationEngine
from src.engine.optimizer import GreedyResourceOptimizer
from src.engine.optimizer_request import DEFAULT_CAPABILITIES, OptimizationRequest
from src.engine.priority_context import IncidentContext
from src.engine.priority_engine import IncidentPriorityEngine
from src.models.action import Action, ActionStatus
from src.models.incident import IncidentStatus
from src.models.outcome import Outcome
from src.models.resource import Resource, ResourceStatus
from src.reasoning.reasoning_layer import GraniteReasoningLayer
from src.workflow.workflow_result import WorkflowResult

logger = logging.getLogger(__name__)


class FloodResponseWorkflow:
    """Orchestrates the nine flood-response stages.

    Usage::

        from src.workflow.scenario_ward12 import CITY, make_events, make_resources
        from src.workflow.workflow import FloodResponseWorkflow

        wf = FloodResponseWorkflow(
            scenario_name="Ward 12 Heavy Rain",
            city=CITY,
            events=make_events(),
            resources=make_resources(),
            incident_context=INCIDENT_CONTEXT,
            distances=DISTANCES,
        )
        result = wf.run()
    """

    def __init__(
        self,
        scenario_name: str,
        city: str,
        events: list,
        resources: list[Resource],
        incident_context: dict,       # zone_id → context kwargs dict
        distances: dict,              # zone_id → {zone_id → minutes}
        reasoning_layer: GraniteReasoningLayer | None = None,
        max_travel_minutes: float = 60.0,
    ) -> None:
        self.scenario_name = scenario_name
        self.city = city
        self.events = events
        self.initial_resources = resources
        self.incident_context = incident_context
        self.distances = distances
        self.max_travel_minutes = max_travel_minutes

        # internal components
        self._engine = SituationEngine(city=city)
        self._priority_engine = IncidentPriorityEngine()
        self._optimizer = GreedyResourceOptimizer()
        self._reasoning = reasoning_layer or GraniteReasoningLayer()

        # output accumulator
        self.result = WorkflowResult(
            scenario_name=scenario_name,
            city=city,
        )

    # ── public entry point ────────────────────────────────────────────────────

    def run(self) -> WorkflowResult:
        """Execute all nine stages in order and return the final WorkflowResult."""
        self._load_resources()
        self._stage_1_ingest()
        self._stage_2_situation()
        self._stage_3_incidents()
        self._stage_4_priorities()
        self._stage_5_allocate()
        self._stage_6_actions()
        self._stage_7_granite_reasoning()
        self._stage_8_operator_response()
        self._stage_9_persist_outcomes()
        self.result.completed_at = datetime.now(UTC)
        return self.result

    # ── resource pre-load ─────────────────────────────────────────────────────

    def _load_resources(self) -> None:
        for r in self.initial_resources:
            self._engine.resources[r.id] = r

    # ── Stage 1: Ingest events ────────────────────────────────────────────────

    def _stage_1_ingest(self) -> None:
        records = []
        evidence_ids = []
        for event in self.events:
            record = self._engine.process(event)
            records.append(record)
            if record.evidence_id:
                evidence_ids.append(record.evidence_id)
        self.result.engine_records = records
        self.result.evidence_ids = evidence_ids

    # ── Stage 2: Capture situation state snapshot ─────────────────────────────

    def _stage_2_situation(self) -> None:
        self.result.situation_state = self._engine.state

    # ── Stage 3: Collect open incidents ──────────────────────────────────────

    def _stage_3_incidents(self) -> None:
        self.result.incidents = [
            inc for inc in self._engine.incidents.values()
            if inc.status == IncidentStatus.OPEN
        ]

    # ── Stage 4: Score priorities ─────────────────────────────────────────────

    def _stage_4_priorities(self) -> None:
        contexts: list[IncidentContext] = []
        for inc in self.result.incidents:
            ctx_kwargs = self.incident_context.get(inc.zone_id, {})
            ctx = IncidentContext(incident=inc, **ctx_kwargs)
            contexts.append(ctx)
        ranked = self._priority_engine.rank(contexts)
        self.result.priority_results = ranked

    # ── Stage 5: Allocate resources ───────────────────────────────────────────

    def _stage_5_allocate(self) -> None:
        available = [
            r for r in self._engine.resources.values()
            if r.status in (ResourceStatus.AVAILABLE, ResourceStatus.STANDBY)
        ]
        self.result.resources_used = available

        incident_zones = {inc.id: inc.zone_id for inc in self.result.incidents}
        resource_zones = {
            r.id: (r.current_zone_id or r.home_zone_id)
            for r in available
        }

        request = OptimizationRequest(
            prioritized_incidents=self.result.priority_results,
            available_resources=available,
            incident_zones=incident_zones,
            resource_zones=resource_zones,
            capabilities=list(DEFAULT_CAPABILITIES),
            distances=self.distances,
            max_travel_minutes=self.max_travel_minutes,
        )
        self.result.optimization_result = self._optimizer.optimize(request)

    # ── Stage 6: Generate Action objects ─────────────────────────────────────

    def _stage_6_actions(self) -> None:
        if self.result.optimization_result is None:
            return
        actions: list[Action] = []
        for assignment in self.result.optimization_result.assignments:
            action = Action(
                id=str(uuid.uuid4()),
                incident_id=assignment.incident_id,
                resource_id=assignment.resource_id,
                decided_by="flowshield_greedy_v1",
                decision_rationale=(
                    f"Assigned by GreedyResourceOptimizer. "
                    f"Reason: {', '.join(assignment.reason_codes)}. "
                    f"Fit score: {assignment.fit_score:.3f}. "
                    f"ETA: {assignment.estimated_travel_minutes} min."
                ),
                priority=1,
                status=ActionStatus.PENDING,
            )
            actions.append(action)
        self.result.actions = actions

    # ── Stage 7: Granite reasoning (situation + priorities + assignments) ─────

    def _stage_7_granite_reasoning(self) -> None:
        state = self.result.situation_state
        incidents = self.result.incidents
        pr = self.result.priority_results
        opt = self.result.optimization_result
        resources = self.result.resources_used

        self.result.reasoning_situation = self._reasoning.summarize_situation(
            state, incidents
        )
        self.result.reasoning_priorities = self._reasoning.explain_priorities(
            pr, incidents
        )
        if opt is not None:
            self.result.reasoning_assignments = self._reasoning.explain_assignments(
                opt, resources
            )

    # ── Stage 8: Operator response plan ──────────────────────────────────────

    def _stage_8_operator_response(self) -> None:
        if self.result.optimization_result is None:
            return
        self.result.operator_response = self._reasoning.generate_response_plan(
            self.result.optimization_result,
            self.result.priority_results,
            self.result.incidents,
        )

    # ── Stage 9: Persist outcomes ─────────────────────────────────────────────

    def _stage_9_persist_outcomes(self) -> None:
        """Create one Outcome per Action (status: pending → in_progress recorded)."""
        outcomes: list[Outcome] = []
        inc_map = {inc.id: inc for inc in self.result.incidents}
        pr_map = {pr.incident_id: pr for pr in self.result.priority_results}

        for action in self.result.actions:
            inc = inc_map.get(action.incident_id)
            pr = pr_map.get(action.incident_id)
            severity_before = inc.severity if inc else "unknown"
            level = pr.level if pr else "unknown"
            outcome = Outcome(
                id=str(uuid.uuid4()),
                action_id=action.id,
                incident_id=action.incident_id,
                success=True,         # optimistic — workflow records intent, not result
                severity_after=severity_before,  # unchanged at dispatch time; updated on resolution
                notes=(
                    f"Action dispatched by workflow. "
                    f"Priority level: {level}. "
                    f"Awaiting field confirmation."
                ),
                effectiveness_score=None,  # to be filled on resolution
            )
            outcomes.append(outcome)
        self.result.outcomes = outcomes
