"""Tool I/O contracts for watsonx Orchestrate.

Every tool in FlowShield has exactly one input model and one output model.
All models use Pydantic v2 with ``extra="forbid"`` so unexpected fields are
rejected at the boundary — watsonx Orchestrate's tool-call schema validation
relies on this.

Serialisation note
------------------
All fields must be JSON-serialisable (str, int, float, bool, list, dict, None).
No engine internal types (Incident, Resource, PriorityResult, etc.) appear here.
Callers and Orchestrate interact solely through these contracts.

Tool boundary map
-----------------
Tool 1 — ingest_incident
    In:  city, zone_id (optional), report_text
    Out: incident_id, zone_id, severity, risk_score, title, evidence_id,
         success, warnings, errors

Tool 2 — calculate_priority
    In:  city, incident_id, zone_id, severity, risk_score, title,
         critical_facility_count, road_blocked, affected_population,
         hours_until_deadline, infra_dependency_count
    Out: incident_id, priority_score, priority_level, reason_codes,
         factor_breakdown

Tool 3 — optimize_resources
    In:  city, priority_results (list of Tool 2 outputs),
         resources (list of ResourceSpec), distances, max_travel_minutes
    Out: assignments (list of AssignmentRecord),
         unassigned_incidents (list of UnassignedRecord),
         assigned_resource_ids

Tool 4 — generate_response_plan
    In:  city, priority_results, assignments, unassigned_incidents,
         resources, use_knowledge_base
    Out: plan_id, city, plan_actions (list of PlanActionRecord),
         gap_count, requires_human_approval, knowledge_citations,
         reasoning_summary, reasoning_source, warnings

Tool 5 — lookup_situation
    In:  city, zone_ids (optional filter list)
    Out: city, overall_severity, zones (list of ZoneSummary),
         open_incident_count, critical_zone_ids
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared sub-models used across multiple tools
# ---------------------------------------------------------------------------

class ResourceSpec(BaseModel):
    """A deployable resource as seen from outside the engine."""
    id: str
    name: str
    city: str
    type: str                    # ResourceType string value
    home_zone_id: str
    current_zone_id: str | None = None
    capacity: int | None = None
    status: str = "available"    # ResourceStatus string value
    notes: str = ""

    model_config = {"extra": "forbid"}


class PriorityResultSpec(BaseModel):
    """Serialised PriorityResult — output of Tool 2, input to Tools 3 & 4."""
    incident_id: str
    priority_score: float
    priority_level: str          # critical / high / medium / low
    reason_codes: list[str]
    factor_breakdown: list[dict] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AssignmentRecord(BaseModel):
    """One resource-to-incident assignment from Tool 3."""
    incident_id: str
    resource_id: str
    incident_zone: str
    resource_zone: str
    estimated_travel_minutes: float
    fit_score: float
    reason_codes: list[str]

    model_config = {"extra": "forbid"}


class UnassignedRecord(BaseModel):
    """An incident that received no resource — from Tool 3."""
    incident_id: str
    priority_score: float
    reason_codes: list[str]

    model_config = {"extra": "forbid"}


class PlanActionRecord(BaseModel):
    """One proposed action from Tool 4."""
    id: str
    incident_id: str
    resource_id: str | None
    action_description: str
    responsible_unit: str
    priority_rank: int
    priority_level: str
    priority_score: float
    target_response_minutes: int
    estimated_travel_minutes: float | None
    reason_codes: list[str]
    evidence_ids: list[str]
    citations: list[str]
    retrieved_chunk_ids: list[str]
    approval_state: str          # auto / required / pending_approval
    reasoning_text: str

    model_config = {"extra": "forbid"}


class ZoneSummary(BaseModel):
    """Per-zone snapshot from Tool 5."""
    zone_id: str
    severity: str
    latest_rainfall_mm_hr: float | None = None
    latest_water_level_m: float | None = None
    road_blocked: bool | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Tool 1 — ingest_incident
# ---------------------------------------------------------------------------

class IngestIncidentInput(BaseModel):
    """Input for the incident ingestion tool.

    ``report_text`` is the raw citizen report or sensor alert text.
    ``zone_id_hint`` is provided when the submission form captures location.
    """
    city: str = Field(..., min_length=1, description="City name (free text).")
    report_text: str = Field(..., min_length=1, description="Raw citizen/sensor report.")
    zone_id_hint: str | None = Field(default=None, description="Zone ID if known.")

    model_config = {"extra": "forbid"}


class IngestIncidentOutput(BaseModel):
    """Output of the incident ingestion tool."""
    success: bool
    incident_id: str | None = None
    zone_id: str | None = None
    severity: str | None = None       # low / medium / high / critical
    risk_score: float | None = None
    title: str | None = None
    description: str | None = None
    evidence_id: str | None = None
    extraction_confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Tool 2 — calculate_priority
# ---------------------------------------------------------------------------

class CalculatePriorityInput(BaseModel):
    """Input for priority calculation.

    Accepts either the full output of Tool 1 (pass incident fields directly)
    or a manually constructed incident specification.
    """
    city: str = Field(..., min_length=1)
    incident_id: str = Field(..., min_length=1)
    zone_id: str = Field(..., min_length=1)
    severity: str = Field(..., description="low / medium / high / critical")
    risk_score: float = Field(..., ge=0.0, le=1.0)
    title: str = Field(..., min_length=1)

    # Contextual enrichment (all optional — zero contribution if absent)
    critical_facility_count: int = Field(default=0, ge=0)
    road_blocked: bool = Field(default=False)
    affected_population: int | None = Field(default=None, ge=0)
    hours_until_deadline: float | None = Field(default=None, ge=0.0)
    infra_dependency_count: int = Field(default=0, ge=0)

    model_config = {"extra": "forbid"}


class CalculatePriorityOutput(BaseModel):
    """Output of the priority calculation tool."""
    incident_id: str
    priority_score: float
    priority_level: str
    reason_codes: list[str]
    factor_breakdown: list[dict]     # [{name, raw_value, contribution, reason_codes}]

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Tool 3 — optimize_resources
# ---------------------------------------------------------------------------

class OptimizeResourcesInput(BaseModel):
    """Input for resource optimisation.

    ``priority_results`` must be the list of CalculatePriorityOutput records.
    ``resources`` is the full list of available ResourceSpec records.
    ``zone_of_incident`` maps incident_id → zone_id (since PriorityResult
    does not carry zone_id directly).
    """
    city: str = Field(..., min_length=1)
    priority_results: list[PriorityResultSpec]
    resources: list[ResourceSpec]
    zone_of_incident: dict[str, str] = Field(
        default_factory=dict,
        description="incident_id → zone_id mapping.",
    )
    distances: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Travel-time matrix: zone_id → {zone_id → minutes}.",
    )
    max_travel_minutes: float = Field(default=60.0, gt=0.0)

    model_config = {"extra": "forbid"}


class OptimizeResourcesOutput(BaseModel):
    """Output of the resource optimisation tool."""
    assignments: list[AssignmentRecord]
    unassigned_incidents: list[UnassignedRecord]
    assigned_resource_ids: list[str]
    assignment_count: int
    gap_count: int

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Tool 4 — generate_response_plan
# ---------------------------------------------------------------------------

class GenerateResponsePlanInput(BaseModel):
    """Input for response plan generation.

    Accepts the serialised outputs of Tools 2 and 3 directly.
    ``use_knowledge_base`` controls whether the built-in SOP library is consulted.
    """
    city: str = Field(..., min_length=1)
    priority_results: list[PriorityResultSpec]
    assignments: list[AssignmentRecord]
    unassigned_incidents: list[UnassignedRecord]
    resources: list[ResourceSpec]
    use_knowledge_base: bool = Field(
        default=True,
        description="If True, retrieve policy context from FLOWSHIELD_KB.",
    )

    model_config = {"extra": "forbid"}


class GenerateResponsePlanOutput(BaseModel):
    """Output of the response plan generation tool."""
    plan_id: str
    city: str
    plan_actions: list[PlanActionRecord]
    gap_count: int
    requires_human_approval: bool
    knowledge_citations: list[str]
    reasoning_summary: str
    reasoning_source: str           # granite / fallback
    warnings: list[str]
    action_count: int
    approval_required_count: int

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Tool 5 — lookup_situation
# ---------------------------------------------------------------------------

class LookupSituationInput(BaseModel):
    """Input for situation lookup.

    Pass the city name and optionally filter to specific zone IDs.
    The underlying engine must already have events ingested for this city.
    When called in the Orchestrate scenario, this is called against the
    in-memory engine snapshot built by the scenario runner.
    """
    city: str = Field(..., min_length=1)
    zone_ids: list[str] | None = Field(
        default=None,
        description="If provided, return only these zones. None = all zones.",
    )

    model_config = {"extra": "forbid"}


class LookupSituationOutput(BaseModel):
    """Output of the situation lookup tool."""
    city: str
    overall_severity: str
    zones: list[ZoneSummary]
    open_incident_count: int
    critical_zone_ids: list[str]
    watch_zone_ids: list[str]

    model_config = {"extra": "forbid"}
