"""run_workflow.py -- execute one complete FLOWSHIELD flood-response workflow.

Scenario: Heavy rainfall in Ward 12, Ahmedabad.
Runs all 9 stages and prints structured output for each.

Usage
-----
    python scripts/run_workflow.py

No arguments required.  Granite API key is optional -- if absent the reasoning
layer uses the deterministic fallback and labels output as [FALLBACK].
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from typing import Any

# ensure src/ is importable from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.reasoning.reasoning_result import ReasoningSource
from src.workflow.scenario_ward12 import (
    CITY,
    DISTANCES,
    INCIDENT_CONTEXT,
    make_events,
    make_resources,
)
from src.workflow.workflow import FloodResponseWorkflow

# ---------------------------------------------------------------------------
# print helpers
# ---------------------------------------------------------------------------

WIDTH = 72


def _banner(title: str) -> None:
    print()
    print("+" + "=" * (WIDTH - 2) + "+")
    label = "  " + title + "  "
    padding = WIDTH - 2 - len(label)
    left = padding // 2
    right = padding - left
    print("|" + " " * left + label + " " * right + "|")
    print("+" + "=" * (WIDTH - 2) + "+")


def _row(label: str, value: Any, indent: int = 4) -> None:
    prefix = " " * indent
    val_str = str(value)
    if len(val_str) > 55:
        val_str = val_str[:52] + "..."
    print(f"{prefix}{label:<30} {val_str}")


def _text_block(text: str, indent: int = 4) -> None:
    prefix = " " * indent
    for line in text.splitlines():
        wrapped = textwrap.fill(
            line, width=WIDTH - indent,
            initial_indent=prefix,
            subsequent_indent=prefix + "  ",
        )
        print(wrapped)


def _source_tag(source: ReasoningSource) -> str:
    return "[GRANITE]" if source == ReasoningSource.GRANITE else "[FALLBACK]"


# ---------------------------------------------------------------------------
# stage printers
# ---------------------------------------------------------------------------

def print_stage_1(result) -> None:
    _banner("STAGE 1 -- EVENT INGESTION")
    print(f"  Events fed:              {len(result.engine_records)}")
    print(f"  Evidence IDs produced:   {len(result.evidence_ids)}")
    for i, rec in enumerate(result.engine_records, 1):
        print(f"\n  Event {i}:")
        _row("type", rec.raw_event_type)
        _row("zone", rec.zone_id)
        _row("severity before", rec.zone_severity_before or "-- (new zone)")
        _row("severity after", rec.zone_severity_after or "--")
        _row("evidence_id", (rec.evidence_id or "-- (resource event)")[:36])
        if rec.incidents_created:
            _row("incident created", rec.incidents_created[0][:8] + "...")
        if rec.incidents_updated:
            _row("incident updated", rec.incidents_updated[0][:8] + "...")


def print_stage_2(result) -> None:
    _banner("STAGE 2 -- SITUATION STATE")
    state = result.situation_state
    print(f"  City:              {state.city}")
    print(f"  Overall severity:  {state.overall_severity.upper()}")
    print(f"  Zones monitored:   {len(state.zones)}")
    for zid, zone in state.zones.items():
        print(f"\n  Zone: {zid}")
        _row("severity", zone.severity.upper())
        _row("rainfall mm/hr", zone.latest_rainfall_mm_hr or "--")
        _row("water level m", zone.latest_water_level_m or "--")
        _row("road blocked", zone.road_blocked)
        _row("affected population", zone.affected_population or "--")
        _row("evidence count", zone.evidence_count)


def print_stage_3(result) -> None:
    _banner("STAGE 3 -- INCIDENTS DETECTED")
    print(f"  Open incidents: {len(result.incidents)}")
    for inc in result.incidents:
        print(f"\n  [{inc.severity.upper()}] {inc.title}")
        _row("id", inc.id[:8] + "...")
        _row("zone", inc.zone_id)
        _row("risk_score", f"{inc.risk_score:.4f}")
        _row("status", inc.status)


def print_stage_4(result) -> None:
    _banner("STAGE 4 -- PRIORITY SCORES")
    for rank, pr in enumerate(result.priority_results, 1):
        print(f"\n  Rank #{rank}  [{pr.level.upper()}]  score={pr.score:.4f}  "
              f"incident={pr.incident_id[:8]}...")
        _row("reason codes", ", ".join(pr.reason_codes))
        print("  Factors:")
        for f in pr.factors:
            bar = "#" * int(f.normalised * 12)
            print(f"    {f.name:<22} {bar:<12}  "
                  f"contrib={f.contribution:.4f}  raw={f.raw_value}")


def print_stage_5(result) -> None:
    _banner("STAGE 5 -- RESOURCE ALLOCATION")
    opt = result.optimization_result
    print(f"  Resources available: {len(result.resources_used)}")
    print(f"  Assignments made:    {len(opt.assignments)}")
    print(f"  Unassigned:          {len(opt.unassigned_incidents)}")

    if opt.assignments:
        print("\n  Assignments:")
        for a in opt.assignments:
            res_name = next(
                (r.name for r in result.resources_used if r.id == a.resource_id),
                a.resource_id,
            )
            print(f"\n  [OK] {res_name}")
            _row("  -> incident", a.incident_id[:8] + "...")
            _row("     incident zone", a.incident_zone)
            _row("     resource zone", a.resource_zone)
            _row("     ETA (min)", a.estimated_travel_minutes)
            _row("     fit score", f"{a.fit_score:.4f}")
            _row("     reason", ", ".join(a.reason_codes))

    if opt.unassigned_incidents:
        print("\n  Unassigned incidents:")
        for u in opt.unassigned_incidents:
            print(f"\n  [--] incident {u.incident_id[:8]}...  "
                  f"priority={u.priority_score:.4f}")
            _row("     reason", ", ".join(u.reason_codes))


def print_stage_6(result) -> None:
    _banner("STAGE 6 -- ACTION OBJECTS GENERATED")
    print(f"  Actions created: {len(result.actions)}")
    for action in result.actions:
        print(f"\n  Action {action.id[:8]}...")
        _row("incident_id", action.incident_id[:8] + "...")
        _row("resource_id", action.resource_id)
        _row("decided_by", action.decided_by)
        _row("status", action.status)
        _row("rationale", action.decision_rationale[:60] + "...")


def print_stage_7(result) -> None:
    _banner("STAGE 7 -- GRANITE REASONING")

    def _print_result(label: str, r) -> None:
        if r is None:
            print(f"\n  {label}: (skipped)")
            return
        tag = _source_tag(r.source)
        print(f"\n  {label}  {tag}")
        _text_block(r.text)

    _print_result("Situation Summary", result.reasoning_situation)
    _print_result("Priority Explanation", result.reasoning_priorities)
    _print_result("Assignment Explanation", result.reasoning_assignments)


def print_stage_8(result) -> None:
    _banner("STAGE 8 -- OPERATOR RESPONSE PLAN")
    r = result.operator_response
    if r is None:
        print("  (no response plan generated)")
        return
    tag = _source_tag(r.source)
    print(f"  Source: {tag}\n")
    _text_block(r.text)

    if r.structured:
        print("\n  Structured JSON:")
        json_str = json.dumps(r.structured, indent=4, default=str)
        for line in json_str.splitlines():
            print(f"    {line}")


def print_stage_9(result) -> None:
    _banner("STAGE 9 -- OUTCOMES PERSISTED")
    print(f"  Outcomes recorded: {len(result.outcomes)}")
    for outcome in result.outcomes:
        print(f"\n  Outcome {outcome.id[:8]}...")
        _row("action_id", outcome.action_id[:8] + "...")
        _row("incident_id", outcome.incident_id[:8] + "...")
        _row("success", outcome.success)
        _row("severity_after", outcome.severity_after)
        _row("notes", outcome.notes[:60] + "...")


def print_summary(result) -> None:
    _banner("WORKFLOW COMPLETE -- SUMMARY")
    elapsed = None
    if result.completed_at and result.started_at:
        elapsed = (result.completed_at - result.started_at).total_seconds()

    print(f"  Scenario:          {result.scenario_name}")
    print(f"  City:              {result.city}")
    print(f"  Started:           {result.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if elapsed is not None:
        print(f"  Elapsed:           {elapsed:.2f}s")
    print()
    print(f"  Events ingested:   {len(result.engine_records)}")
    print(f"  Evidence produced: {len(result.evidence_ids)}")
    state = result.situation_state
    print(f"  Zones monitored:   {len(state.zones) if state else 0}")
    print(f"  Overall severity:  {state.overall_severity.upper() if state else '--'}")
    print(f"  Incidents open:    {len(result.incidents)}")
    print(f"  Priorities ranked: {len(result.priority_results)}")
    opt = result.optimization_result
    if opt:
        print(f"  Assignments made:  {len(opt.assignments)}")
        print(f"  Unassigned:        {len(opt.unassigned_incidents)}")
    print(f"  Actions generated: {len(result.actions)}")
    print(f"  Outcomes stored:   {len(result.outcomes)}")
    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    [!] {w}")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    print()
    print("+" + "=" * 70 + "+")
    print("|" + "  FLOWSHIELD -- End-to-End Flood Response Workflow".center(70) + "|")
    print("|" + "  Scenario: Heavy Rainfall -- Ward 12, Ahmedabad".center(70) + "|")
    print("+" + "=" * 70 + "+")

    wf = FloodResponseWorkflow(
        scenario_name="Ward 12 Heavy Rain -- July 2025",
        city=CITY,
        events=make_events(),
        resources=make_resources(),
        incident_context=INCIDENT_CONTEXT,
        distances=DISTANCES,
        max_travel_minutes=60.0,
    )

    result = wf.run()

    print_stage_1(result)
    print_stage_2(result)
    print_stage_3(result)
    print_stage_4(result)
    print_stage_5(result)
    print_stage_6(result)
    print_stage_7(result)
    print_stage_8(result)
    print_stage_9(result)
    print_summary(result)


if __name__ == "__main__":
    main()
