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
| Tests | pytest |
| Lint | ruff |
| Package manager | pip / pyproject.toml |

## Commands

```bash
# Install (from repo root)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_evidence.py -v

# Run a single test by name
pytest tests/test_evidence.py::TestEvidenceValid::test_minimal -v

# Lint
ruff check src/ tests/

# Lint + auto-fix
ruff check --fix src/ tests/
```

## Repository layout

```
src/
  __init__.py
  models/
    __init__.py      ← public re-export of all models
    evidence.py
    situation.py
    incident.py
    resource.py
    action.py
    outcome.py
tests/
  test_evidence.py
  test_situation.py
  test_incident.py
  test_resource.py
  test_action.py
  test_outcome.py
pyproject.toml
Agents.md
```

## Critical non-obvious rules

### Models

- `city` is always **free-text `str`** — never an enum. Do not hardcode city names.
- `ZoneSeverity` (used in `ZoneStatus`) has four levels: `normal, watch, warning, critical`.  
  `SeverityLevel` (used in `Incident`) also has four levels: `low, medium, high, critical`.  
  They are **separate enums** — do not mix them.
- Every model uses `extra="forbid"` — passing unknown fields raises `ValidationError`.
- `SituationState.overall_severity` is a **read-only `@property`** — it is not a stored field
  and will not appear in `model_dump()`.
- `Evidence` requires **at least one measurement** field to be non-None (enforced by
  `@model_validator`). An evidence record with no readings is rejected.
- A `Resource` with `status=DEPLOYED` **must** have `current_zone_id` set.
- An `Outcome` with `success=False` **must** have non-empty `notes`.
- `Action.completed_at` may only be set when `status` is `DONE`, `FAILED`, or `CANCELLED`.
- `Incident.resolved_at` may only be set when `status` is `RESOLVED` or `CANCELLED`.
- `Incident.affected_zone_ids` — if non-empty, the primary `zone_id` must appear in it.
- `SituationState.zones` dict keys must equal the embedded `zone.zone_id` (validated on construction).

### Import pattern

Always import models from the package surface, never from sub-modules directly:

```python
# correct
from src.models import Evidence, Incident, SituationState

# avoid
from src.models.evidence import Evidence
```

### Permanent pipeline flow (do not reorder stages)

```
Evidence → SituationState → Incidents → Priority/Risk → Action → Outcome
```

Each stage will live in `src/pipeline/` (not yet implemented).  
The models are the contracts between stages — keep them stable.

### V1 scope boundary

Do NOT add: auth, database, GIS, live sensors, LangGraph, ML training, Docker, mobile UI.  
Do NOT hardcode city names anywhere in model or pipeline code.
