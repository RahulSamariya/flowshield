"""Prompt templates for the five Granite reasoning tasks.

Design constraints enforced in every prompt
--------------------------------------------
1. Granite receives ONLY structured JSON produced by the deterministic engine.
   It must never be asked to invent numbers, distances, scores, or availability.
2. Each prompt includes an explicit MUST NOT section listing forbidden actions.
3. Each prompt requests structured JSON output so callers can parse it reliably.
4. The system preamble is the same for all tasks — it establishes Granite's role
   as an *explainer*, not a *calculator*.

Prompt build functions
-----------------------
build_situation_summary_prompt(state_json, incidents_json)
build_priority_explanation_prompt(priority_results_json, incidents_json)
build_assignment_explanation_prompt(assignments_json, unassigned_json, resources_json)
build_response_plan_prompt(assignments_json, priority_results_json, incidents_json)
build_missing_information_prompt(state_json, incidents_json, resources_json)

All functions accept plain Python dicts / lists (already serialised from engine
dataclasses by the GraniteReasoningLayer) and return a ready-to-send prompt string.
"""

from __future__ import annotations

import json
from typing import Any

# ── shared system preamble ─────────────────────────────────────────────────────

_SYSTEM = """\
You are FLOWSHIELD Assistant, a flood emergency decision-support AI.
Your role is to EXPLAIN and SUMMARISE decisions made by a deterministic engine.

STRICT RULES — you MUST follow these without exception:
- Do NOT calculate or modify any numerical score, distance, or travel time.
- Do NOT invent, assume, or hallucinate resource availability or locations.
- Do NOT invent infrastructure facts not present in the JSON input.
- Do NOT recommend actions that contradict the engine's assignment decisions.
- Base every statement ONLY on facts present in the JSON provided to you.
- If a field is null or missing, state that the information is not available.
- Write for emergency operations centre operators — be concise and precise.
- Always output valid JSON in the exact schema specified for each task.
"""

_SEPARATOR = "\n" + "─" * 60 + "\n"


def _json(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


# ── Task 1: Situation Summary ──────────────────────────────────────────────────

def build_situation_summary_prompt(
    state: dict[str, Any],
    incidents: list[dict[str, Any]],
) -> str:
    """Prompt asking Granite to summarise the current flood situation.

    Input JSON contains:
      state     — SituationState with per-zone severity, rainfall, water level
      incidents — list of open Incident records

    Expected output schema::

        {
          "summary": "<2–4 sentence plain-English situation overview>",
          "overall_severity": "<normal|watch|warning|critical>",
          "zones_at_risk": ["<zone_id>", ...],
          "key_concerns": ["<concern 1>", "<concern 2>", ...]
        }
    """
    return f"""{_SYSTEM}{_SEPARATOR}
TASK: SITUATION SUMMARY

You are given the current flood situation state and list of active incidents.
Write a concise situation summary for emergency operators.

MUST NOT: invent any zone names, severity levels, rainfall values, or counts
          that are not explicitly present in the JSON below.

SITUATION STATE:
{_json(state)}

ACTIVE INCIDENTS:
{_json(incidents)}

Respond with ONLY the following JSON (no markdown, no extra text):
{{
  "summary": "<2–4 sentence plain-English overview of the current flood situation>",
  "overall_severity": "<the overall_severity value from the state>",
  "zones_at_risk": ["<zone_ids where severity is watch/warning/critical>"],
  "key_concerns": ["<up to 4 most important operational concerns from the data>"]
}}
<|end|>"""


# ── Task 2: Priority Explanation ───────────────────────────────────────────────

def build_priority_explanation_prompt(
    priority_results: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
) -> str:
    """Prompt asking Granite to explain why incidents are ranked as they are.

    Input JSON contains:
      priority_results — PriorityResult records (score, level, factors, reason_codes)
      incidents        — Incident records for context (title, zone, severity)

    Expected output schema::

        {
          "explanations": [
            {
              "incident_id": "<id>",
              "rank": 1,
              "level": "<critical|high|medium|low>",
              "explanation": "<1–2 sentences why this incident is at this rank>"
            },
            ...
          ]
        }
    """
    return f"""{_SYSTEM}{_SEPARATOR}
TASK: PRIORITY EXPLANATION

You are given the priority scores computed by the deterministic engine for each
active incident, plus the incident details.
Explain to operators WHY each incident is ranked where it is, using only the
factor scores and reason codes already computed — do not recalculate anything.

MUST NOT: change, challenge, or recalculate any score or rank.
MUST NOT: add factors not present in the reason_codes list.

PRIORITY RESULTS (engine output — do not modify):
{_json(priority_results)}

INCIDENT DETAILS:
{_json(incidents)}

Respond with ONLY the following JSON (no markdown, no extra text):
{{
  "explanations": [
    {{
      "incident_id": "<id>",
      "rank": <integer rank, 1 = highest priority>,
      "level": "<level from priority result>",
      "explanation": "<1–2 sentences using the factor names and reason codes to explain the rank>"
    }}
  ]
}}
<|end|>"""


# ── Task 3: Assignment Explanation ────────────────────────────────────────────

def build_assignment_explanation_prompt(
    assignments: list[dict[str, Any]],
    unassigned: list[dict[str, Any]],
    resources: list[dict[str, Any]],
) -> str:
    """Prompt asking Granite to explain resource-allocation decisions.

    Input JSON contains:
      assignments — Assignment records (incident_id, resource_id, travel_min,
                    fit_score, reason_codes)
      unassigned  — UnassignedIncident records with reason_codes
      resources   — Resource details for name/type lookups

    Expected output schema::

        {
          "assignments": [
            {
              "incident_id": "<id>",
              "resource_id": "<id>",
              "explanation": "<1–2 sentences why this resource was chosen>"
            }
          ],
          "unassigned": [
            {
              "incident_id": "<id>",
              "explanation": "<1 sentence why no resource was available>"
            }
          ]
        }
    """
    return f"""{_SYSTEM}{_SEPARATOR}
TASK: ASSIGNMENT EXPLANATION

You are given the resource assignments produced by the deterministic optimizer,
plus details on unassigned incidents and available resources.
Explain each assignment and each gap to operators in plain language.

MUST NOT: suggest alternative assignments or second-guess the optimizer.
MUST NOT: invent resource names, types, or capabilities not in the JSON below.
MUST NOT: change any travel time, fit score, or reason code.

ASSIGNMENTS (engine output — do not modify):
{_json(assignments)}

UNASSIGNED INCIDENTS:
{_json(unassigned)}

RESOURCE DETAILS:
{_json(resources)}

Respond with ONLY the following JSON (no markdown, no extra text):
{{
  "assignments": [
    {{
      "incident_id": "<id>",
      "resource_id": "<id>",
      "explanation": "<1–2 sentences explaining the assignment decision using reason_codes>"
    }}
  ],
  "unassigned": [
    {{
      "incident_id": "<id>",
      "explanation": "<1 sentence explaining the gap using the reason_code>"
    }}
  ]
}}
<|end|>"""


# ── Task 4a: Response Plan (with KB context) ──────────────────────────────────

def build_response_plan_with_kb_prompt(
    assignments: list[dict[str, Any]],
    priority_results: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    kb_context: list[str],
) -> str:
    """Prompt for response plan generation with retrieved policy context injected.

    ``kb_context`` is a list of strings, each formatted as::

        [<source_ref>]
        <policy text>

    Granite is instructed to cite the source refs where relevant.

    Expected output schema — same as build_response_plan_prompt, plus::

        {
          ...,
          "policy_citations": ["<source_ref>", ...],
          "coverage_note": "..."
        }
    """
    kb_section = (
        "\n\n".join(kb_context)
        if kb_context
        else "No policy context retrieved."
    )
    return f"""{_SYSTEM}{_SEPARATOR}
TASK: RESPONSE PLAN (WITH POLICY GROUNDING)

You are given the engine's resource assignments and incident priority results,
plus POLICY CONTEXT retrieved from the municipal SOP library.
Produce a numbered operator action plan ordered by priority (highest first).
Each step must be a clear, actionable instruction based only on the assignments.
Where a retrieved policy clause is relevant to an action, cite its source reference
in the ``policy_citations`` list.

MUST NOT: add steps not backed by an assignment in the JSON.
MUST NOT: invent estimated times — use only the estimated_travel_minutes values
          already present in the assignment records.
MUST NOT: recommend resources not listed in the assignments.
MUST NOT: fabricate policy clauses not present in the POLICY CONTEXT section.

ASSIGNMENTS (engine output):
{_json(assignments)}

PRIORITY RESULTS (engine output):
{_json(priority_results)}

INCIDENT DETAILS:
{_json(incidents)}

POLICY CONTEXT (retrieved from SOP library — cite source refs where applicable):
{kb_section}

Respond with ONLY the following JSON (no markdown, no extra text):
{{
  "plan_title": "<city or zone name> Flood Response Plan",
  "steps": [
    {{
      "step": <integer starting at 1>,
      "incident_id": "<id>",
      "action": "<clear operator instruction, e.g.: Deploy Pump Unit A to zone W12 — ETA X min>",
      "priority_level": "<level>",
      "estimated_travel_minutes": <number from assignment>,
      "policy_note": "<optional 1-sentence reference to a relevant policy clause, or null>"
    }}
  ],
  "policy_citations": ["<source_ref from POLICY CONTEXT>", ...],
  "coverage_note": "<1 sentence summarising any unaddressed incidents, or 'All incidents covered.'>"
}}
<|end|>"""


# ── Task 4: Response Plan (original, no KB) ───────────────────────────────────

def build_response_plan_prompt(
    assignments: list[dict[str, Any]],
    priority_results: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
) -> str:
    """Prompt asking Granite to produce a human-readable operator response plan.

    The plan presents the assignments as ordered action steps, highest
    priority first.

    Expected output schema::

        {
          "plan_title": "<city> Flood Response Plan — <timestamp>",
          "steps": [
            {
              "step": 1,
              "incident_id": "<id>",
              "action": "<plain-English action sentence for operators>",
              "priority_level": "<critical|high|medium|low>",
              "estimated_travel_minutes": <number>
            }
          ],
          "coverage_note": "<1 sentence on unassigned incidents if any>"
        }
    """
    return f"""{_SYSTEM}{_SEPARATOR}
TASK: RESPONSE PLAN

You are given the engine's resource assignments and incident priority results.
Produce a numbered operator action plan ordered by priority (highest first).
Each step must be a clear, actionable instruction based only on the assignments.

MUST NOT: add steps not backed by an assignment in the JSON.
MUST NOT: invent estimated times — use only the estimated_travel_minutes values
          already present in the assignment records.
MUST NOT: recommend resources not listed in the assignments.

ASSIGNMENTS (engine output):
{_json(assignments)}

PRIORITY RESULTS (engine output):
{_json(priority_results)}

INCIDENT DETAILS:
{_json(incidents)}

Respond with ONLY the following JSON (no markdown, no extra text):
{{
  "plan_title": "<city or zone name> Flood Response Plan",
  "steps": [
    {{
      "step": <integer starting at 1>,
      "incident_id": "<id>",
      "action": "<clear operator instruction, e.g.: Deploy Pump Unit A to zone W12 — ETA X min>",
      "priority_level": "<level>",
      "estimated_travel_minutes": <number from assignment>
    }}
  ],
  "coverage_note": "<1 sentence summarising any unaddressed incidents, or 'All incidents covered.'>"
}}
<|end|>"""


# ── Task 5: Missing Information ───────────────────────────────────────────────

def build_missing_information_prompt(
    state: dict[str, Any],
    incidents: list[dict[str, Any]],
    resources: list[dict[str, Any]],
) -> str:
    """Prompt asking Granite to identify data gaps in the current picture.

    Gaps are fields that are null/missing and would materially improve
    situational awareness.

    Expected output schema::

        {
          "gaps": [
            {
              "field": "<field name or data type>",
              "context": "<which incident/zone/resource is affected>",
              "impact": "<why this gap matters for response decisions>"
            }
          ],
          "summary": "<1–2 sentences on overall data quality>"
        }
    """
    return f"""{_SYSTEM}{_SEPARATOR}
TASK: MISSING INFORMATION IDENTIFICATION

You are given the current situation state, active incidents, and resource details.
Identify fields that are null, missing, or unknown that would meaningfully improve
the ability to make response decisions.
Report only genuine gaps — do not fabricate missing fields.

MUST NOT: suggest specific values to fill the gaps.
MUST NOT: invent gaps not evidenced by null/missing values in the JSON.

SITUATION STATE:
{_json(state)}

ACTIVE INCIDENTS:
{_json(incidents)}

RESOURCE DETAILS:
{_json(resources)}

Respond with ONLY the following JSON (no markdown, no extra text):
{{
  "gaps": [
    {{
      "field": "<the name of the missing/null field>",
      "context": "<which record — e.g. incident <id>, zone <id>, resource <id>>",
      "impact": "<1 sentence on why this gap hinders decision-making>"
    }}
  ],
  "summary": "<1–2 sentences on overall data completeness>"
}}
<|end|>"""
