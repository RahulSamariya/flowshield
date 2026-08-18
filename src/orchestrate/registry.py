"""ToolRegistry — catalogue of all FlowShield Orchestrate tools.

watsonx Orchestrate discovers tools through a registry.  Each ToolSpec carries
the metadata Orchestrate needs:

  name         Unique tool identifier (snake_case).
  description  One-sentence description for LLM tool-selection.
  input_schema JSON Schema dict derived from the input Pydantic model.
  output_schema JSON Schema dict derived from the output Pydantic model.
  invoke       Callable — the actual tool function.

FLOWSHIELD_REGISTRY is the pre-built singleton containing all five tools.
Inject it into the Orchestrate agent configuration.

Orchestrate integration notes
------------------------------
When registering tools in watsonx Orchestrate:
1. Export each ToolSpec.input_schema as the tool's parameter schema.
2. Export each ToolSpec.output_schema as the tool's response schema.
3. Map ToolSpec.invoke to the tool's implementation endpoint.
4. Use ToolSpec.description as the tool summary in the Orchestrate catalogue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolSpec:
    """Metadata and implementation for one Orchestrate tool.

    Attributes
    ----------
    name
        Unique snake_case identifier.
    description
        One-sentence plain-English description for LLM tool selection.
    input_model
        Pydantic BaseModel class for the tool's input.
    output_model
        Pydantic BaseModel class for the tool's output.
    invoke
        The callable that takes one input model instance and returns one output
        model instance.  Must be deterministic and never raise.
    """
    name: str
    description: str
    input_model: type
    output_model: type
    invoke: Callable[[Any], Any]

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool input (watsonx Orchestrate parameter schema)."""
        return self.input_model.model_json_schema()

    @property
    def output_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool output (watsonx Orchestrate response schema)."""
        return self.output_model.model_json_schema()

    def to_orchestrate_spec(self) -> dict[str, Any]:
        """Serialise to the dict format expected by watsonx Orchestrate tool registration."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
            "returns": self.output_schema,
        }


class ToolRegistry:
    """Ordered collection of ToolSpec entries.

    Usage::

        registry = ToolRegistry([spec1, spec2, ...])
        spec = registry.get("ingest_incident")
        result = spec.invoke(input_model_instance)

        # Export all specs for Orchestrate registration
        all_specs = registry.to_orchestrate_manifest()
    """

    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {s.name: s for s in specs}
        self._order: list[str] = [s.name for s in specs]

    def get(self, name: str) -> ToolSpec | None:
        """Return the ToolSpec for a given name, or None."""
        return self._specs.get(name)

    def invoke(self, name: str, input_data: Any) -> Any:
        """Find and invoke a tool by name.  Raises KeyError if not found."""
        spec = self._specs[name]
        return spec.invoke(input_data)

    @property
    def names(self) -> list[str]:
        """Ordered list of all registered tool names."""
        return list(self._order)

    def __len__(self) -> int:
        return len(self._specs)

    def to_orchestrate_manifest(self) -> list[dict[str, Any]]:
        """Return a list of tool specs in Orchestrate registration format."""
        return [self._specs[name].to_orchestrate_spec() for name in self._order]


# ---------------------------------------------------------------------------
# Pre-built registry
# ---------------------------------------------------------------------------

def _build_registry() -> ToolRegistry:
    from src.orchestrate.tool_contracts import (
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
    )
    from src.orchestrate.tools import (
        calculate_priority,
        generate_response_plan,
        ingest_incident,
        lookup_situation,
        optimize_resources,
    )

    return ToolRegistry([
        ToolSpec(
            name="ingest_incident",
            description=(
                "Convert a citizen flood report or sensor alert into a validated "
                "Incident record with severity and risk score."
            ),
            input_model=IngestIncidentInput,
            output_model=IngestIncidentOutput,
            invoke=ingest_incident,
        ),
        ToolSpec(
            name="calculate_priority",
            description=(
                "Score and prioritise one flood incident using the six-factor "
                "deterministic engine.  Returns a priority score and reason codes."
            ),
            input_model=CalculatePriorityInput,
            output_model=CalculatePriorityOutput,
            invoke=calculate_priority,
        ),
        ToolSpec(
            name="optimize_resources",
            description=(
                "Assign available municipal resources to prioritised flood incidents "
                "using the greedy optimiser.  Returns assignments and any resource gaps."
            ),
            input_model=OptimizeResourcesInput,
            output_model=OptimizeResourcesOutput,
            invoke=optimize_resources,
        ),
        ToolSpec(
            name="generate_response_plan",
            description=(
                "Build a structured, policy-grounded response plan from resource "
                "assignments.  Returns ordered actions with citations and approval flags."
            ),
            input_model=GenerateResponsePlanInput,
            output_model=GenerateResponsePlanOutput,
            invoke=generate_response_plan,
        ),
        ToolSpec(
            name="lookup_situation",
            description=(
                "Return the current flood situation state for a city: zone severities, "
                "open incident count, and critical zone identifiers."
            ),
            input_model=LookupSituationInput,
            output_model=LookupSituationOutput,
            invoke=lookup_situation,
        ),
    ])


#: Pre-built registry — inject into watsonx Orchestrate agent configuration.
FLOWSHIELD_REGISTRY: ToolRegistry = _build_registry()
