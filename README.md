# FlowShield

**Agentic urban flood situation and decision-support platform.**

FlowShield is a modular, agentic flood-response intelligence system built for Gujarat Hackathon 2026 (Challenge 7). It takes raw environmental signals (rainfall feeds, citizen reports, drain sensors), builds a shared per-zone situation state, detects incidents, prioritises them, allocates scarce response resources, and generates an explainable, approval-gated response plan.

The core design principle: **the deterministic engine decides; the LLM only explains.** IBM Granite summarises, explains and narrates decisions made by transparent, rule-based code — and the whole system degrades gracefully to a fully offline deterministic fallback when no API key is configured.

North-star loop:

```
Evidence → Situation State → Incidents → Priority → Resource Decision → Action → Outcome → Learning
```

## Features

- **Event ingestion & normalisation** — rainfall, waterlogging, drain-blocked, water-level, road-blocked and resource-status events normalised to a canonical `Evidence` schema.
- **Situation engine** — per-zone severity matrix (`normal / watch / warning / critical`) built from deterministic IMD-aligned thresholds.
- **Incident detection** — auto-creates, escalates and resolves incidents from zone severity; deterministic risk score per incident.
- **Transparent priority scoring** — six weighted factors (severity, critical facilities, road disruption, population impact, response deadline, infrastructure dependency) with a full audit trail of raw values, weights, contributions and reason codes.
- **Resource allocation** — greedy optimizer assigns available crews/pumps/vehicles to the highest-priority incidents, respecting capability and travel-time constraints; every assignment and every gap carries a reason code.
- **Response planning agent** — turns priorities + assignments into a structured, policy-grounded action plan with responsible units, response-time targets, human-approval states, and SOP citations from a built-in RAG knowledge base.
- **Citizen report intake** — free-text flood reports parsed by Granite into structured incidents, with a deterministic regex fallback (unit conversions included).
- **LLM reasoning with fallback** — five reasoning tasks (situation summary, priority explanation, assignment explanation, response plan, missing-information gaps). Every result is tagged `granite` or `fallback`.
- **watsonx Orchestrate boundary** — five typed, registerable tools (`ingest_incident`, `calculate_priority`, `optimize_resources`, `generate_response_plan`, `lookup_situation`) with strict Pydantic I/O contracts.
- **Command dashboard** — browser UI showing situation state, incidents, priorities, allocations, response actions, a WHY panel and an activity timeline, backed by a stdlib HTTP server.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Data contracts | Pydantic v2 (strict mode, `extra="forbid"`) |
| LLM | IBM Granite (`ibm/granite-3-8b-instruct`) |
| RAG | BM25-style keyword retrieval (stdlib only) |
| Tests | pytest (586 tests) |
| Lint | ruff |
| Dashboard | HTML/CSS/JS + stdlib `http.server` |

## Repository layout

```
src/
  models/         ← Pydantic domain models (stable contracts)
  engine/         ← Deterministic pipeline stages + priority + optimizer
  reasoning/      ← Granite LLM layer (client, prompts, fallback)
  workflow/       ← End-to-end workflow orchestrator + scenario data
  agents/         ← CitizenIncidentAgent + ResponsePlanningAgent
  knowledge/      ← RAG knowledge base (SOP / policy corpus)
  orchestrate/    ← watsonx Orchestrate tool boundary (5 tools + registry)
  dashboard/      ← Command dashboard frontend (HTML/CSS/JS)
scripts/
  run_workflow.py     ← Single-scenario end-to-end runner (no API key needed)
  serve_dashboard.py  ← Dashboard backend server (port 8000 by default)
tests/              ← 586 tests across all modules
```

## Getting started & Running on another system/laptop

### 1. Local Python Setup (Virtual Environment)
To run the project on a fresh machine:
```bash
# Clone the repository
git clone https://github.com/RahulSamariya/flowshield.git
cd flowshield

# Create and activate python virtual environment (Python 3.11+)
python -m venv .venv
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On macOS / Linux:
source .venv/bin/activate

# Install dependencies from lockfile
pip install -r requirements.txt

# Run all tests
pytest

# Run the end-to-end workflow (uses deterministic fallback)
python scripts/run_workflow.py
```

### 2. Run the Dashboard
Start the local dashboard server:
```bash
# Run server on port 8080 (or customize by passing port as argument)
python scripts/serve_dashboard.py 8080

# Open http://localhost:8080/ in your browser
```
The dashboard loads the Ward 12 heavy-rain scenario on start, lets you submit citizen reports live, and shows the full decision trace plus the WHY panel. Note: on Windows, set `$env:PYTHONIOENCODING="utf-8"` before running scripts that print Unicode.

### 3. Running with Docker
If the machine has Docker installed:
```bash
# Build the container image
docker build -t flowshield-dashboard .

# Run the container mapping VM port 8080
docker run -p 8080:8080 flowshield-dashboard
```
Open `http://localhost:8080` in your web browser.

### IBM Granite

Granite is used for citizen-report extraction and reasoning narratives. It is read from environment variables — the system runs fully offline (deterministic fallback) when the key is absent:

```bash
export GRANITE_API_URL="https://us-south.ml.cloud.ibm.com"   # default
export GRANITE_API_KEY="<your-key>"
export GRANITE_MODEL_ID="ibm/granite-3-8b-instruct"          # default
```

Every reasoning result is labelled `[GRANITE]` or `[FALLBACK]` so operators always know its provenance.

## Design principles

- **Structured state is the foundation** — situation, incidents, resources, actions and outcomes are typed objects; intelligence modules plug in on top.
- **Deterministic engine, explainer LLM** — scores, distances and allocations are never computed by the model; Granite only summarises and explains structured facts.
- **Explainability by construction** — every priority factor, optimizer assignment and resource gap carries machine-readable reason codes and human-readable rationale.
- **Graceful degradation** — every LLM entry point has a deterministic fallback; the demo never needs a live API key.
- **Future-proof boundaries** — provider interfaces allow ML risk models, live sensor feeds, and richer citizen channels (voice, image, multilingual) to be swapped in without rewriting the core.
- **No hardcoded cities** — city is free-text; Ahmedabad and Surat scenario data is configuration, not code.

## Scope boundaries (V1)

Not in scope for V1: production hydrodynamic/ML prediction, live IoT infrastructure, computer vision, GIS command centre, autonomous dispatch, mobile apps, voice/multichannel intake, and database persistence (state is in-memory by design).