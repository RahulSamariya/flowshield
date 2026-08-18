"""Orchestrate package — watsonx Orchestrate tool/agent boundary layer.

This package exposes the five FlowShield capabilities as callable, registerable
tools for watsonx Orchestrate (or any orchestration framework that consumes
plain Python callables with typed Pydantic I/O).

Tools
-----
ingest_incident        Citizen report text  → Incident + Evidence (JSON)
calculate_priority     Incident JSON        → PriorityResult (JSON)
optimize_resources     Incidents + Resources → Assignments (JSON)
generate_response_plan Assignments + Priorities → ResponsePlan (JSON)
lookup_situation       City + zones         → SituationState summary (JSON)

Design constraints
------------------
- Every tool input is a Pydantic BaseModel (extra="forbid").
- Every tool output is a Pydantic BaseModel (extra="forbid").
- Tools are pure functions — stateless, no side-effects on global state.
- The underlying engine modules are NOT imported at package level; they are
  imported lazily inside each tool so the core remains independently importable.
- The ToolRegistry maps tool name → ToolSpec so Orchestrate can enumerate and
  call tools by name without knowing Python internals.
- The ScenarioRunner chains the five tools for the canonical citizen-report flow.
"""

from src.orchestrate.registry import FLOWSHIELD_REGISTRY, ToolRegistry, ToolSpec
from src.orchestrate.scenario_runner import (
    CitizenReportScenario,
    ScenarioResult,
    run_citizen_report_scenario,
)
from src.orchestrate.tool_contracts import (
    AssignmentRecord,
    CalculatePriorityInput,
    CalculatePriorityOutput,
    GenerateResponsePlanInput,
    GenerateResponsePlanOutput,
    # Inputs
    IngestIncidentInput,
    # Outputs
    IngestIncidentOutput,
    LookupSituationInput,
    LookupSituationOutput,
    OptimizeResourcesInput,
    OptimizeResourcesOutput,
    PlanActionRecord,
    PriorityResultSpec,
    # Shared sub-models
    ResourceSpec,
    UnassignedRecord,
    ZoneSummary,
)
from src.orchestrate.tools import (
    calculate_priority,
    generate_response_plan,
    ingest_incident,
    lookup_situation,
    optimize_resources,
)

__all__ = [
    # contracts — inputs
    "IngestIncidentInput",
    "CalculatePriorityInput",
    "OptimizeResourcesInput",
    "GenerateResponsePlanInput",
    "LookupSituationInput",
    # contracts — outputs
    "IngestIncidentOutput",
    "CalculatePriorityOutput",
    "OptimizeResourcesOutput",
    "GenerateResponsePlanOutput",
    "LookupSituationOutput",
    # contracts — sub-models
    "ResourceSpec",
    "PriorityResultSpec",
    "AssignmentRecord",
    "UnassignedRecord",
    "PlanActionRecord",
    "ZoneSummary",
    # tools
    "ingest_incident",
    "calculate_priority",
    "optimize_resources",
    "generate_response_plan",
    "lookup_situation",
    # registry
    "ToolRegistry",
    "ToolSpec",
    "FLOWSHIELD_REGISTRY",
    # scenario
    "CitizenReportScenario",
    "ScenarioResult",
    "run_citizen_report_scenario",
]
