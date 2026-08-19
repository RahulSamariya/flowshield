# FLOWSHIELD DEVELOPMENT CONTRACT

## Project

FLOWSHIELD is an Agentic AI urban flood incident and decision-support
system for the Ahmedabad/Surat urban infrastructure challenge.

V1 is COMPLETE.

The V1 architecture is FROZEN.

Do not redesign or rewrite the V1 core unless explicitly instructed.

## Permanent pipeline

Evidence
→ SituationState
→ Incidents
→ Priority/Risk
→ Resource Optimization
→ Action Plan
→ Action Execution
→ Outcome
→ State Update

## Permanent domain contracts

- SituationState
- Incident
- Resource
- Action
- Outcome
- Event

## Existing engines

- IncidentPriorityEngine
- GreedyResourceOptimizer
- Response Planning Agent
- Granite reasoning layer
- RAG knowledge layer
- watsonx Orchestrate tool boundary

## V1 architectural principles

1. Deterministic code performs calculations and state mutations.
2. Granite explains, summarizes, reasons over structured information,
   and uses RAG for policy grounding.
3. LLMs must not invent resources, calculate distances, or directly
   mutate core state.
4. Orchestration must remain separate from core business logic.
5. Domain models must remain stable and typed.
6. New capabilities must be added through clear interfaces.
7. Do not create unnecessary agents.
8. Do not add unnecessary infrastructure.
9. Preserve backward compatibility.
10. All existing tests must continue to pass.

## V2 goal

V2 upgrades FLOWSHIELD from a mostly static response planner into
an adaptive flood incident command system.

V2 capabilities:

1. Real action lifecycle
2. Real outcome lifecycle
3. Situation reassessment
4. Dynamic re-optimization
5. Scenario / What-if engine
6. Incident dependency intelligence
7. Intervention impact analysis
8. Decision explainability
9. Scenario comparison
10. Improved RAG provenance

## V2 architectural rule

Extend existing contracts where possible.

Do not replace the V1 architecture.

Future implementations must remain replaceable:

RiskProvider
ResourceOptimizer
StateRepository
EvidenceProvider
etc.

## Future ML rule

Do NOT train or add an ML flood prediction model without a legitimate
validated dataset.

The current deterministic priority/risk implementation remains the
baseline RiskProvider.

Future ML models must implement the same RiskProvider interface.

## Development process

Before modifying code:

1. Inspect the existing implementation.
2. Explain the affected files.
3. Propose the smallest implementation.
4. Wait for approval if the change affects architecture.
5. Implement incrementally.
6. Run all tests.
7. Report changed files and test results.
8. Never silently rewrite unrelated code.