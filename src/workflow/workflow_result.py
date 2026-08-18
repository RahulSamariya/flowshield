"""WorkflowResult — typed container for every stage of the flood response workflow.

Each stage populates its own field.  Downstream stages read from earlier fields,
so the entire data lineage is visible in one object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.engine.history import EngineRecord
from src.engine.optimizer_result import OptimizationResult
from src.engine.priority_result import PriorityResult
from src.models.action import Action
from src.models.incident import Incident
from src.models.outcome import Outcome
from src.models.resource import Resource
from src.models.situation import SituationState
from src.reasoning.reasoning_result import ReasoningResult


@dataclass
class WorkflowResult:
    """Snapshot of a complete flood-response workflow run.

    Fields are populated sequentially by FloodResponseWorkflow.run().
    Any field that is None was not reached (e.g. early failure).
    """

    # metadata
    scenario_name: str = ""
    city: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    # Stage 1 — ingestion
    engine_records: list[EngineRecord] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    # Stage 2 — situation state
    situation_state: SituationState | None = None

    # Stage 3 — incidents
    incidents: list[Incident] = field(default_factory=list)

    # Stage 4 — priorities
    priority_results: list[PriorityResult] = field(default_factory=list)

    # Stage 5 — resource allocation
    optimization_result: OptimizationResult | None = None
    resources_used: list[Resource] = field(default_factory=list)

    # Stage 6 — actions
    actions: list[Action] = field(default_factory=list)

    # Stage 7 — Granite reasoning (all tasks)
    reasoning_situation: ReasoningResult | None = None
    reasoning_priorities: ReasoningResult | None = None
    reasoning_assignments: ReasoningResult | None = None

    # Stage 8 — operator response plan
    operator_response: ReasoningResult | None = None

    # Stage 9 — persisted outcomes
    outcomes: list[Outcome] = field(default_factory=list)

    # errors encountered (non-fatal)
    warnings: list[str] = field(default_factory=list)
