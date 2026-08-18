"""ResponsePlan and PlanAction — the structured output of the ResponsePlanningAgent.

Citations
---------
When a KnowledgeBase is connected to the ResponsePlanningAgent, each PlanAction
carries:
  ``citations``         — list of source_ref strings (human-readable, show in UI)
  ``retrieved_chunks``  — list of chunk IDs that grounded this action (audit trail)

ResponsePlan.knowledge_citations aggregates all unique citations across the plan.


These are the stable data contracts for agent output.  They must be consumed
by downstream stages (workflow, operator UI, Granite reasoning) without
modification.

ApprovalState
-------------
APPROVED         Human sign-off given (or not required by policy).
REQUIRED         Policy says a human must approve before dispatch.
PENDING_APPROVAL Synonymous alias — use this when creating new plan actions.
AUTO             Not required; the system will auto-dispatch.

PlanAction
----------
One proposed action for exactly one incident.  Mirrors Action closely but
has no lifecycle timestamps (it is a *proposal*, not a dispatch record).

Every PlanAction MUST carry:
- incident_id           — traceability to Incident
- resource_id           — traceability to Resource (None for resource-gap rows)
- reason_codes          — forwarded verbatim from PriorityResult / optimizer
- evidence_ids          — forwarded verbatim from Incident.evidence_ids
- approval_state        — derived from PolicyConfig

ResponsePlan
------------
The complete output of one ResponsePlanningAgent.plan() call.
Contains the ordered list of PlanActions plus a Granite/fallback reasoning
text and a machine-readable summary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ApprovalState(StrEnum):
    """Whether human approval is required before this action is dispatched."""

    AUTO             = "auto"              # policy allows auto-dispatch
    REQUIRED         = "required"          # human must approve
    PENDING_APPROVAL = "pending_approval"  # waiting for review (same semantic as REQUIRED)


class PlanAction(BaseModel):
    """A single proposed action inside a ResponsePlan.

    ``resource_id`` is None when no resource could be assigned
    (the action represents a gap / escalation request).

    ``action_description`` is a deterministic one-line summary produced by the
    agent, separate from the Granite reasoning narrative.

    ``reasoning_text`` is the Granite (or fallback) explanation for why this
    specific action is proposed.  It is always populated — never empty.

    Example::

        pa = PlanAction(
            incident_id="<uuid>",
            resource_id="<uuid>",
            action_description="Deploy Pump-2 to drain W12-N (ETA 8 min).",
            responsible_unit="AMC Drainage Department",
            priority_rank=1,
            target_response_minutes=15,
            reason_codes=("SEVERITY_CRITICAL", "ROAD_BLOCKED"),
            evidence_ids=["<uuid>"],
            approval_state=ApprovalState.AUTO,
            reasoning_text="Highest priority zone; only available pump.",
        )
    """

    # ── identity ──────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # ── traceability ──────────────────────────────────────────────────────
    incident_id: str = Field(
        ...,
        min_length=1,
        description="ID of the Incident this action addresses.",
    )
    resource_id: str | None = Field(
        default=None,
        description="ID of the assigned Resource.  None = resource gap.",
    )
    priority_result_id: str = Field(
        ...,
        min_length=1,
        description="ID of the PriorityResult that drove this action's rank.",
    )

    # ── action description ────────────────────────────────────────────────
    action_description: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Deterministic one-line description of the proposed action.",
    )
    responsible_unit: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Municipal unit responsible for executing this action.",
    )

    # ── priority and timing ───────────────────────────────────────────────
    priority_rank: int = Field(
        ...,
        ge=1,
        description="Rank within this plan (1 = most urgent).",
    )
    priority_level: str = Field(
        ...,
        min_length=1,
        description="PriorityLevel string: critical / high / medium / low.",
    )
    priority_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Raw PriorityResult.score for this incident.",
    )
    target_response_minutes: int = Field(
        ...,
        ge=1,
        description="Target response time in minutes (from PolicyConfig).",
    )
    estimated_travel_minutes: float | None = Field(
        default=None,
        ge=0.0,
        description="ETA from optimizer (None if no resource assigned).",
    )

    # ── audit trail ───────────────────────────────────────────────────────
    reason_codes: tuple[str, ...] = Field(
        default=(),
        description="All reason codes from PriorityResult + optimizer Assignment.",
    )
    evidence_ids: tuple[str, ...] = Field(
        default=(),
        description="Evidence IDs forwarded from Incident.evidence_ids.",
    )

    # ── knowledge citations ───────────────────────────────────────────────
    citations: tuple[str, ...] = Field(
        default=(),
        description=(
            "Source references from retrieved knowledge chunks "
            "(e.g. 'AMC Flood SOP 2023, Sec 3.1')."
        ),
    )
    retrieved_chunk_ids: tuple[str, ...] = Field(
        default=(),
        description="IDs of knowledge chunks that grounded this action (for audit).",
    )

    # ── approval ──────────────────────────────────────────────────────────
    approval_state: ApprovalState = Field(
        ...,
        description="Whether human approval is required before dispatch.",
    )

    # ── Granite reasoning ─────────────────────────────────────────────────
    reasoning_text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Granite (or fallback) explanation for this action.",
    )

    # ── validators ────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def resource_gap_has_escalation_desc(self) -> PlanAction:
        """Gap actions (no resource) must mention escalation in their description."""
        if self.resource_id is None and "escalat" not in self.action_description.lower():
            raise ValueError(
                "PlanAction with resource_id=None must include 'escalat' in "
                "action_description to flag the resource gap clearly."
            )
        return self

    model_config = {"frozen": False, "extra": "forbid"}


class ResponsePlan(BaseModel):
    """The complete output of one ResponsePlanningAgent.plan() call.

    ``plan_actions`` is ordered by ``priority_rank`` (ascending).
    ``gap_count`` reflects incidents that have no assignable resource.
    ``requires_human_approval`` is True if ANY action has
    ``approval_state == REQUIRED / PENDING_APPROVAL``.
    ``reasoning_summary`` is the Granite/fallback narrative covering the
    whole plan — individual per-action reasoning is in each PlanAction.
    ``generated_at`` is a UTC timestamp set by the agent, not by callers.
    """

    # ── identity ──────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    city: str = Field(..., min_length=1, max_length=100)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )

    # ── content ───────────────────────────────────────────────────────────
    plan_actions: list[PlanAction] = Field(
        default_factory=list,
        description="Ordered (by priority_rank) list of proposed actions.",
    )
    gap_count: int = Field(
        default=0,
        ge=0,
        description="Number of incidents with no resource assignment.",
    )
    requires_human_approval: bool = Field(
        default=False,
        description="True if any PlanAction requires human approval.",
    )

    # ── knowledge citations (plan-level aggregate) ────────────────────────
    knowledge_citations: tuple[str, ...] = Field(
        default=(),
        description="Unique source references used across all PlanActions in this plan.",
    )

    # ── Granite reasoning ─────────────────────────────────────────────────
    reasoning_summary: str = Field(
        default="",
        max_length=4000,
        description="Granite or fallback overall narrative for the plan.",
    )
    reasoning_source: str = Field(
        default="fallback",
        description="'granite' or 'fallback'.",
    )

    # ── metadata ──────────────────────────────────────────────────────────
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues noted during plan generation.",
    )

    # ── convenience accessors ─────────────────────────────────────────────

    @property
    def approval_required_actions(self) -> list[PlanAction]:
        """All PlanActions that require human approval."""
        return [
            a for a in self.plan_actions
            if a.approval_state in (ApprovalState.REQUIRED, ApprovalState.PENDING_APPROVAL)
        ]

    @property
    def auto_dispatch_actions(self) -> list[PlanAction]:
        """All PlanActions that can be auto-dispatched."""
        return [a for a in self.plan_actions if a.approval_state == ApprovalState.AUTO]

    def action_for_incident(self, incident_id: str) -> PlanAction | None:
        """Return the PlanAction for a given incident, or None."""
        for a in self.plan_actions:
            if a.incident_id == incident_id:
                return a
        return None

    model_config = {"frozen": False, "extra": "forbid"}
