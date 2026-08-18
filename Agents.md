# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project

FlowShield — modular agentic urban flood situation and decision-support platform.
Built for Gujarat Hackathon 2026 (Challenge 7).

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Data contracts | Pydantic v2 (strict mode via `extra="forbid"`) |
| LLM | IBM Granite (`ibm/granite-3-8b-instruct`) via `src/reasoning/` |
| Tests | pytest |
| Lint | ruff |
| Package manager | pip / pyproject.toml |

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_priority_engine.py -v

# Run a single test by name
pytest tests/test_reasoning.py::TestFallbackSituationSummary::test_source_is_fallback -v

# Run end-to-end workflow (no API key needed — uses deterministic fallback)
python scripts/run_workflow.py

# Lint
ruff check src/ tests/ scripts/

# Lint + auto-fix
ruff check --fix src/ tests/ scripts/
```

## Repository layout

```
src/
  models/         ← Pydantic domain models (stable contracts)
  engine/         ← Deterministic pipeline stages + priority + optimizer
  reasoning/      ← Granite LLM layer (client, prompts, fallback)
  workflow/       ← End-to-end workflow orchestrator + scenario data
  agents/         ← Input agents (CitizenIncidentAgent) + planning agent (ResponsePlanningAgent)
  knowledge/      ← RAG knowledge base (KnowledgeChunk, KnowledgeBase, documents)
  orchestrate/    ← watsonx Orchestrate tool boundary layer (5 tools + registry + scenario runner)
scripts/
  run_workflow.py ← Single-scenario end-to-end runner
tests/
pyproject.toml
Agents.md
```

## Critical non-obvious rules

### Models

- `city` is always **free-text `str`** — never an enum. Do not hardcode city names.
- `ZoneSeverity` (used in `ZoneStatus`) levels: `normal, watch, warning, critical`.
  `SeverityLevel` (used in `Incident`) levels: `low, medium, high, critical`.
  They are **separate enums** — do not mix them.
- Every model uses `extra="forbid"` — passing unknown fields raises `ValidationError`.
- `SituationState.overall_severity` is a **read-only `@property`** — not in `model_dump()`.
- `Evidence` requires **at least one measurement** field (enforced by `@model_validator`).
  Pass `road_blocked=False` directly — **never** `road_blocked=ext.road_blocked or None`
  (that converts `False → None`, breaking the validator since `False is not None → True`).
- A `Resource` with `status=DEPLOYED` **must** have `current_zone_id` set.
- An `Outcome` with `success=False` **must** have non-empty `notes`.

### Engine

- `SituationEngine.incidents` is keyed by `zone_id`, not incident ID. Only one active incident per zone.
- `IncidentPriorityEngine.rank()` accepts `list[IncidentContext]` — wrap each `Incident` first.
- `GreedyResourceOptimizer` reads severity from `PriorityResult.factor("severity").raw_value` — never pass raw incidents directly.
- `OptimizationRequest.resources_per_incident` defaults to 1 — multi-resource assignment not supported in V1.

### Agents (`src/agents/`)

- `CitizenIncidentAgent` **only** produces `Incident` + `Evidence` — it never assigns resources.
- `ExtractionResult` is a plain `@dataclass` (not Pydantic) — no `extra="forbid"` guard.
- `CitizenReportParser` tries Granite first; falls back to keyword regex if Granite is unavailable or returns malformed JSON.
- `AgentResult.incident` is `None` on failure — always check `AgentResult.errors` before using `.incident`.
- `CitizenIncidentAgent` accepts an optional `zone_id_hint` — used when the report contains no zone signal.

### ResponsePlanningAgent (`src/agents/response_planning_agent.py`)

- Accepts: `SituationState`, `list[PriorityResult]`, `OptimizationResult`, `list[Resource]`.
- Returns a `PlanningResult` containing a `ResponsePlan` — never raises.
- **MUST NOT** invent resources: unknown `resource_id` / `incident_id` in assignments → skip + warn.
- `PlanAction.resource_id` is `None` for unassigned gap incidents; `action_description` MUST contain "escalat" (enforced by model validator).
- Gap actions always get `ApprovalState.REQUIRED` regardless of score.
- `PolicyConfig` is a frozen dataclass (`extra` field assignment raises); `DEFAULT_POLICY` is module-level.
- `PolicyConfig.requires_approval(score, resource_type)` checks both score threshold AND `approval_required_for_resource_types`.
- Per-action `reasoning_text` is always deterministic (never depends on Granite); only `reasoning_summary` calls the reasoning layer.
- `ResponsePlanningAgent._find_incident_in_state()` reads `state._incidents` (a dict injected by `_make_state()` in tests); returns `None` in production if the engine's incidents aren't injected — agent uses a stub.
- Priority scores and travel times are forwarded verbatim from `PriorityResult` / `Assignment` — agent never recalculates them.
- When `knowledge_base` is passed, each `PlanAction` gets `citations` (source_ref strings) and `retrieved_chunk_ids`; `ResponsePlan.knowledge_citations` aggregates uniques across all actions.
- KB query is built from incident title + resource type + priority level + reason codes — never includes live sensor values.
- Gap actions use `category_hint="escalation"` for KB retrieval; assigned actions use unrestricted retrieval (top 3 chunks).

### Knowledge Layer (`src/knowledge/`)

- `KnowledgeChunk` is a frozen dataclass — immutable; `source_ref` is shown in citations.
- `KnowledgeBase` uses BM25-style keyword retrieval (stdlib only, no numpy/scikit-learn). Built on construction; index cannot be updated at runtime.
- Tags are weighted **3×**, title **2×**, body **1×** in the inverted index — add domain synonyms to `tags` when adding chunks.
- `FLOWSHIELD_KB` (`src/knowledge/documents.py`) is the pre-built singleton — inject it into agents; do not re-build it in production code.
- Chunks **MUST NOT** contain live sensor values, resource counts, or any real-time operational data — policy/SOP text only.
- `RetrievalResult.citations` deduplicates `source_ref` strings in hit order; use this for display.
- `RetrievalResult.hits` may be empty if no chunk scores > 0 — always handle the empty case.

### Reasoning (Granite)

- `GraniteReasoningLayer` always returns a valid `ReasoningResult` — it never raises.
- Check `result.source` to distinguish Granite from fallback output.
- Granite credentials are read from `GRANITE_API_URL`, `GRANITE_API_KEY`, `GRANITE_MODEL_ID` env vars.
- If `GRANITE_API_KEY` is empty, the client raises `GraniteUnavailable` immediately (no network call).
- Every prompt contains an explicit `MUST NOT` block — do not remove it when editing templates.

### Workflow

- `FloodResponseWorkflow.run()` mutates `self.result` in place across 9 stages.
- Stage 4 requires `incident_context` dict keyed by `zone_id` matching engine incident zones.
- Stage 6 generates `Action` objects with `status=PENDING` — not yet dispatched.
- Stage 9 Outcomes are optimistic (`success=True`) at dispatch time; update on field resolution.

### Import pattern

Always import models from the package surface:
```python
from src.models import Evidence, Incident, SituationState   # correct
from src.models.evidence import Evidence                     # avoid
```

### Permanent pipeline flow (do not reorder stages)

```
Evidence → SituationState → Incidents → Priority/Risk → Action → Outcome
```

### V1 scope boundary

Do NOT add: auth, database, GIS, live sensors, LangGraph, ML training, Docker, mobile UI.
Do NOT hardcode city names anywhere in model or pipeline code.

### Orchestrate layer (`src/orchestrate/`)

- **Tool boundary rule**: no internal engine types (`Incident`, `PriorityResult`, `Resource`, etc.) cross tool boundaries — only the Pydantic contracts in `tool_contracts.py`.
- Five tools with their single-step responsibilities:

  | Tool | Calls | Stateless? |
  |---|---|---|
  | `ingest_incident` | `CitizenIncidentAgent.process()` | Yes |
  | `calculate_priority` | `IncidentPriorityEngine.score()` | Yes |
  | `optimize_resources` | `GreedyResourceOptimizer.optimize()` | Yes |
  | `generate_response_plan` | `ResponsePlanningAgent.plan()` | Yes |
  | `lookup_situation` | `SituationEngine.state` (read-only) | Requires `engine=` kwarg |

- `lookup_situation` needs a live `SituationEngine` passed via `engine=` kwarg — returns an empty snapshot if `engine=None`.
- `ScenarioRunner` catches `pydantic.ValidationError` at the tool boundary and returns `ScenarioResult(success=False)` — never propagates.
- `FLOWSHIELD_REGISTRY.to_orchestrate_manifest()` returns a list of dicts in Orchestrate tool-registration format (name, description, parameters schema, returns schema).
- Core modules remain fully importable and usable without importing `src.orchestrate`.

### Windows dev environment

- Set `$env:PYTHONIOENCODING="utf-8"` before running any script that prints Unicode (e.g. `run_workflow.py`).
- All deterministic fallback strings use ASCII only (`[OK]`, `[--]`, `->`) for cp1252 compatibility.
