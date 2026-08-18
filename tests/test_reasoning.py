"""Tests for the GraniteReasoningLayer.

All tests run WITHOUT a real Granite endpoint.

Two test strategies:
  A. Fallback tests (no mock needed) — unset API key → GraniteUnavailable →
     deterministic fallback fires.  These verify the fallback contract.

  B. Mocked Granite tests — inject a GraniteClient stub that returns a canned
     JSON response.  These verify prompt construction, response parsing, and
     that the layer correctly surfaces structured output.

Tests are grouped by task:
  TestFallbackSituationSummary
  TestFallbackPriorityExplanation
  TestFallbackAssignmentExplanation
  TestFallbackResponsePlan
  TestFallbackMissingInformation
  TestGraniteMocked_* (one class per task, mocked client)
  TestGraniteClientGuards
  TestPromptTemplates
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.engine.optimizer_result import (
    OA_BEST_FIT,
    UA_ALL_TOO_FAR,
    UA_NO_RESOURCE,
    Assignment,
    OptimizationResult,
    UnassignedIncident,
)
from src.engine.priority_result import FactorScore, PriorityLevel, PriorityResult
from src.models.incident import Incident, SeverityLevel
from src.models.resource import Resource, ResourceStatus, ResourceType
from src.models.situation import SituationState, ZoneSeverity, ZoneStatus
from src.reasoning.granite_client import GraniteClient, GraniteConfig, GraniteUnavailable
from src.reasoning.prompt_templates import (
    build_assignment_explanation_prompt,
    build_missing_information_prompt,
    build_priority_explanation_prompt,
    build_response_plan_prompt,
    build_situation_summary_prompt,
)
from src.reasoning.reasoning_layer import GraniteReasoningLayer
from src.reasoning.reasoning_result import ReasoningSource, ReasoningTask

# ── shared fixtures ────────────────────────────────────────────────────────────

def make_state(
    city: str = "TestCity",
    zone_id: str = "W12",
    severity: ZoneSeverity = ZoneSeverity.WARNING,
    rainfall: float | None = 40.0,
    water_level: float | None = 1.2,
    population: int | None = 800,
    road_blocked: bool = False,
) -> SituationState:
    state = SituationState(city=city)
    state.zones[zone_id] = ZoneStatus(
        zone_id=zone_id,
        severity=severity,
        latest_rainfall_mm_hr=rainfall,
        latest_water_level_m=water_level,
        affected_population=population,
        road_blocked=road_blocked,
        evidence_count=3,
    )
    return state


def make_incident(
    iid: str = "inc-1",
    zone_id: str = "W12",
    severity: SeverityLevel = SeverityLevel.HIGH,
    title: str = "Flood incident W12",
) -> Incident:
    return Incident(
        id=iid,
        city="TestCity",
        zone_id=zone_id,
        severity=severity,
        risk_score=0.65,
        title=title,
    )


def make_priority_result(
    incident_id: str = "inc-1",
    score: float = 0.65,
    level: PriorityLevel = PriorityLevel.HIGH,
    reason_codes: tuple = ("SEVERITY_HIGH", "POPULATION_LARGE"),
) -> PriorityResult:
    factors = (
        FactorScore("severity", "high", 0.70, 0.30, 0.21, ("SEVERITY_HIGH",)),
        FactorScore("critical_facility", 0, 0.0, 0.20, 0.0, ()),
        FactorScore("road_disruption", False, 0.0, 0.15, 0.0, ()),
        FactorScore("population_impact", 800, 0.16, 0.20, 0.032, ("POPULATION_MODERATE",)),
        FactorScore("response_deadline", None, 0.0, 0.10, 0.0, ()),
        FactorScore("infra_dependency", 0, 0.0, 0.05, 0.0, ()),
    )
    return PriorityResult(
        incident_id=incident_id,
        score=score,
        level=level,
        factors=factors,
        reason_codes=reason_codes,
    )


def make_resource(
    rid: str = "pump-1",
    rtype: ResourceType = ResourceType.PUMP,
    zone: str = "W12",
) -> Resource:
    return Resource(
        id=rid,
        name=f"Resource {rid}",
        city="TestCity",
        type=rtype,
        home_zone_id=zone,
        current_zone_id=zone,
        status=ResourceStatus.AVAILABLE,
    )


def make_assignment(
    incident_id: str = "inc-1",
    resource_id: str = "pump-1",
    travel: float = 5.0,
) -> Assignment:
    return Assignment(
        incident_id=incident_id,
        resource_id=resource_id,
        incident_zone="W12",
        resource_zone="W12",
        estimated_travel_minutes=travel,
        fit_score=0.88,
        reason_codes=(OA_BEST_FIT,),
    )


def make_unassigned(
    incident_id: str = "inc-2",
    score: float = 0.35,
    reason: str = UA_NO_RESOURCE,
) -> UnassignedIncident:
    return UnassignedIncident(
        incident_id=incident_id,
        priority_score=score,
        reason_codes=(reason,),
    )


def _no_key_layer() -> GraniteReasoningLayer:
    """Layer guaranteed to always use fallback (no API key configured)."""
    cfg = GraniteConfig(api_url="http://unreachable", api_key="")
    return GraniteReasoningLayer(client=GraniteClient(cfg))


def _mocked_layer(response_json: dict) -> GraniteReasoningLayer:
    """Layer with a client stub that returns canned JSON."""
    mock_client = MagicMock(spec=GraniteClient)
    mock_client.generate.return_value = json.dumps(response_json)
    return GraniteReasoningLayer(client=mock_client)


# ═══════════════════════════════════════════════════════════════════════════════
# Task 1: Situation Summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallbackSituationSummary:
    @pytest.fixture
    def result(self):
        layer = _no_key_layer()
        state = make_state()
        incidents = [make_incident()]
        return layer.summarize_situation(state, incidents)

    def test_source_is_fallback(self, result):
        assert result.source == ReasoningSource.FALLBACK

    def test_task_is_situation_summary(self, result):
        assert result.task == ReasoningTask.SITUATION_SUMMARY

    def test_text_contains_city(self, result):
        assert "TestCity" in result.text

    def test_text_contains_severity(self, result):
        assert "warning" in result.text.lower() or "WARNING" in result.text

    def test_structured_has_required_keys(self, result):
        assert "summary" in result.structured
        assert "overall_severity" in result.structured
        assert "zones_at_risk" in result.structured
        assert "key_concerns" in result.structured

    def test_zones_at_risk_is_list(self, result):
        assert isinstance(result.structured["zones_at_risk"], list)

    def test_empty_city_no_incidents(self):
        layer = _no_key_layer()
        state = SituationState(city="EmptyCity")
        result = layer.summarize_situation(state, [])
        assert result.source == ReasoningSource.FALLBACK
        assert "EmptyCity" in result.text
        assert result.structured["zones_at_risk"] == []


class TestGraniteMocked_SituationSummary:
    @pytest.fixture
    def result(self):
        canned = {
            "summary": "Ward 12 is experiencing heavy flooding.",
            "overall_severity": "warning",
            "zones_at_risk": ["W12"],
            "key_concerns": ["road may flood"],
        }
        layer = _mocked_layer(canned)
        return layer.summarize_situation(make_state(), [make_incident()])

    def test_source_is_granite(self, result):
        assert result.source == ReasoningSource.GRANITE

    def test_text_from_summary_field(self, result):
        assert "Ward 12" in result.text

    def test_structured_matches_canned(self, result):
        assert result.structured["overall_severity"] == "warning"
        assert "W12" in result.structured["zones_at_risk"]


# ═══════════════════════════════════════════════════════════════════════════════
# Task 2: Priority Explanation
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallbackPriorityExplanation:
    @pytest.fixture
    def result(self):
        layer = _no_key_layer()
        incidents = [make_incident("inc-1"), make_incident("inc-2", severity=SeverityLevel.LOW)]
        prs = [
            make_priority_result("inc-1", score=0.65, level=PriorityLevel.HIGH),
            make_priority_result("inc-2", score=0.10, level=PriorityLevel.LOW,
                                 reason_codes=("SEVERITY_LOW",)),
        ]
        return layer.explain_priorities(prs, incidents)

    def test_source_is_fallback(self, result):
        assert result.source == ReasoningSource.FALLBACK

    def test_task_correct(self, result):
        assert result.task == ReasoningTask.PRIORITY_EXPLANATION

    def test_text_contains_rank_1(self, result):
        assert "#1" in result.text

    def test_text_mentions_severity_code(self, result):
        assert "SEVERITY_HIGH" in result.text

    def test_structured_has_explanations_list(self, result):
        assert "explanations" in result.structured
        assert len(result.structured["explanations"]) == 2

    def test_fallback_no_incidents(self):
        layer = _no_key_layer()
        result = layer.explain_priorities([], [])
        assert "No active incidents" in result.text


class TestGraniteMocked_PriorityExplanation:
    @pytest.fixture
    def result(self):
        canned = {
            "explanations": [
                {"incident_id": "inc-1", "rank": 1, "level": "high",
                 "explanation": "High severity with large population affected."}
            ]
        }
        layer = _mocked_layer(canned)
        return layer.explain_priorities(
            [make_priority_result("inc-1")],
            [make_incident("inc-1")],
        )

    def test_source_granite(self, result):
        assert result.source == ReasoningSource.GRANITE

    def test_explanation_in_text(self, result):
        assert "High severity" in result.text

    def test_structured_has_explanations(self, result):
        assert len(result.structured["explanations"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Task 3: Assignment Explanation
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallbackAssignmentExplanation:
    @pytest.fixture
    def result(self):
        layer = _no_key_layer()
        opt = OptimizationResult(
            assignments=[make_assignment("inc-1", "pump-1")],
            unassigned_incidents=[make_unassigned("inc-2", reason=UA_NO_RESOURCE)],
        )
        return layer.explain_assignments(opt, [make_resource("pump-1")])

    def test_source_fallback(self, result):
        assert result.source == ReasoningSource.FALLBACK

    def test_task_correct(self, result):
        assert result.task == ReasoningTask.ASSIGNMENT_EXPLANATION

    def test_text_mentions_assigned(self, result):
        assert "pump-1" in result.text or "Resource pump-1" in result.text

    def test_text_mentions_unassigned(self, result):
        assert "inc-2" in result.text

    def test_unassigned_message_no_resource(self, result):
        assert "No resources are currently available" in result.text

    def test_structured_has_both_keys(self, result):
        assert "assignments" in result.structured
        assert "unassigned" in result.structured

    def test_all_far_reason_message(self):
        layer = _no_key_layer()
        opt = OptimizationResult(
            assignments=[],
            unassigned_incidents=[make_unassigned("inc-x", reason=UA_ALL_TOO_FAR)],
        )
        result = layer.explain_assignments(opt, [])
        assert "exceed the maximum travel time" in result.text


class TestGraniteMocked_AssignmentExplanation:
    @pytest.fixture
    def result(self):
        canned = {
            "assignments": [
                {"incident_id": "inc-1", "resource_id": "pump-1",
                 "explanation": "Pump-1 was the best available resource for zone W12."}
            ],
            "unassigned": [
                {"incident_id": "inc-2",
                 "explanation": "No available resources remained."}
            ],
        }
        opt = OptimizationResult(
            assignments=[make_assignment()],
            unassigned_incidents=[make_unassigned()],
        )
        layer = _mocked_layer(canned)
        return layer.explain_assignments(opt, [make_resource()])

    def test_source_granite(self, result):
        assert result.source == ReasoningSource.GRANITE

    def test_assignment_explanation_in_text(self, result):
        assert "best available" in result.text


# ═══════════════════════════════════════════════════════════════════════════════
# Task 4: Response Plan
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallbackResponsePlan:
    @pytest.fixture
    def result(self):
        layer = _no_key_layer()
        opt = OptimizationResult(
            assignments=[make_assignment("inc-1", "pump-1", travel=8.0)],
            unassigned_incidents=[make_unassigned("inc-2")],
        )
        prs = [make_priority_result("inc-1")]
        incidents = [make_incident("inc-1")]
        return layer.generate_response_plan(opt, prs, incidents)

    def test_source_fallback(self, result):
        assert result.source == ReasoningSource.FALLBACK

    def test_task_correct(self, result):
        assert result.task == ReasoningTask.RESPONSE_PLAN

    def test_text_has_step_1(self, result):
        assert "1." in result.text

    def test_text_mentions_travel(self, result):
        assert "8.0" in result.text

    def test_coverage_note_mentions_unassigned(self, result):
        assert "1 incident" in result.structured["coverage_note"]

    def test_structured_has_steps_and_note(self, result):
        assert "steps" in result.structured
        assert "coverage_note" in result.structured

    def test_all_covered_note(self):
        layer = _no_key_layer()
        opt = OptimizationResult(
            assignments=[make_assignment()],
            unassigned_incidents=[],
        )
        result = layer.generate_response_plan(
            opt, [make_priority_result()], [make_incident()]
        )
        assert "All incidents covered" in result.structured["coverage_note"]


class TestGraniteMocked_ResponsePlan:
    @pytest.fixture
    def result(self):
        canned = {
            "plan_title": "W12 Flood Response Plan",
            "steps": [
                {"step": 1, "incident_id": "inc-1", "action": "Deploy Pump-1 to W12.",
                 "priority_level": "high", "estimated_travel_minutes": 5}
            ],
            "coverage_note": "All incidents covered.",
        }
        opt = OptimizationResult(assignments=[make_assignment()], unassigned_incidents=[])
        layer = _mocked_layer(canned)
        return layer.generate_response_plan(opt, [make_priority_result()], [make_incident()])

    def test_source_granite(self, result):
        assert result.source == ReasoningSource.GRANITE

    def test_plan_title_in_text(self, result):
        assert "W12 Flood Response Plan" in result.text

    def test_step_1_in_text(self, result):
        assert "Deploy Pump-1" in result.text


# ═══════════════════════════════════════════════════════════════════════════════
# Task 5: Missing Information
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallbackMissingInformation:
    @pytest.fixture
    def result(self):
        layer = _no_key_layer()
        # Zone missing water level; incident missing description; resource missing zone
        state = make_state(rainfall=30.0, water_level=None, population=None)
        incidents = [make_incident()]           # description defaults to ""
        resource = Resource(
            id="r1", name="Crew Alpha", city="TestCity",
            type=ResourceType.RESCUE_TEAM,
            home_zone_id="W12",
            current_zone_id=None,              # unknown location
            status=ResourceStatus.AVAILABLE,
        )
        return layer.identify_missing_information(state, incidents, [resource])

    def test_source_fallback(self, result):
        assert result.source == ReasoningSource.FALLBACK

    def test_task_correct(self, result):
        assert result.task == ReasoningTask.MISSING_INFORMATION

    def test_water_level_gap_detected(self, result):
        fields = [g["field"] for g in result.structured["gaps"]]
        assert "latest_water_level_m" in fields

    def test_population_gap_detected(self, result):
        fields = [g["field"] for g in result.structured["gaps"]]
        assert "affected_population" in fields

    def test_current_zone_gap_detected(self, result):
        fields = [g["field"] for g in result.structured["gaps"]]
        assert "current_zone_id" in fields

    def test_structured_has_summary(self, result):
        assert "summary" in result.structured

    def test_no_gaps_when_data_complete(self):
        layer = _no_key_layer()
        state = make_state(rainfall=20.0, water_level=0.5, population=200)
        inc = Incident(
            id="i1", city="TestCity", zone_id="W12",
            severity=SeverityLevel.LOW, risk_score=0.2,
            title="Minor flood", description="Some water on road.",
        )
        res = make_resource()
        result = layer.identify_missing_information(state, [inc], [res])
        assert len(result.structured["gaps"]) == 0
        assert "0 data gap" in result.text


class TestGraniteMocked_MissingInformation:
    @pytest.fixture
    def result(self):
        canned = {
            "gaps": [
                {"field": "water_level_m", "context": "zone W12",
                 "impact": "Cannot assess flood depth."}
            ],
            "summary": "One critical gap identified.",
        }
        layer = _mocked_layer(canned)
        return layer.identify_missing_information(
            make_state(water_level=None),
            [make_incident()],
            [make_resource()],
        )

    def test_source_granite(self, result):
        assert result.source == ReasoningSource.GRANITE

    def test_gap_in_text(self, result):
        assert "water_level_m" in result.text

    def test_summary_in_text(self, result):
        assert "One critical gap" in result.text


# ═══════════════════════════════════════════════════════════════════════════════
# GraniteClient guards
# ═══════════════════════════════════════════════════════════════════════════════

class TestGraniteClientGuards:
    def test_no_api_key_raises_unavailable(self):
        client = GraniteClient(GraniteConfig(api_url="http://unused", api_key=""))
        with pytest.raises(GraniteUnavailable, match="GRANITE_API_KEY"):
            client.generate("hello")

    def test_network_error_raises_unavailable(self):
        client = GraniteClient(
            GraniteConfig(api_url="http://127.0.0.1:19999", api_key="fake-key")
        )
        with pytest.raises(GraniteUnavailable):
            client.generate("hello")

    def test_granite_unavailable_is_runtime_error(self):
        assert issubclass(GraniteUnavailable, RuntimeError)


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt template structure checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptTemplates:
    def test_situation_summary_contains_must_not(self):
        p = build_situation_summary_prompt({"city": "X", "zones": {}}, [])
        assert "MUST NOT" in p

    def test_situation_summary_contains_json_schema(self):
        p = build_situation_summary_prompt({"city": "X", "zones": {}}, [])
        assert "zones_at_risk" in p
        assert "overall_severity" in p

    def test_priority_explanation_forbids_recalculation(self):
        p = build_priority_explanation_prompt([], [])
        assert "do not recalculate" in p.lower() or "MUST NOT" in p

    def test_assignment_explanation_forbids_inventing(self):
        p = build_assignment_explanation_prompt([], [], [])
        assert "MUST NOT" in p

    def test_response_plan_forbids_extra_steps(self):
        p = build_response_plan_prompt([], [], [])
        assert "MUST NOT" in p

    def test_missing_info_forbids_inventing_gaps(self):
        p = build_missing_information_prompt({"zones": {}}, [], [])
        assert "MUST NOT" in p

    def test_all_prompts_end_with_end_token(self):
        prompts = [
            build_situation_summary_prompt({}, []),
            build_priority_explanation_prompt([], []),
            build_assignment_explanation_prompt([], [], []),
            build_response_plan_prompt([], [], []),
            build_missing_information_prompt({}, [], []),
        ]
        for p in prompts:
            assert "<|end|>" in p

    def test_situation_prompt_embeds_state_json(self):
        state = {"city": "Surat", "zones": {"Z1": {"severity": "critical"}}}
        p = build_situation_summary_prompt(state, [])
        assert "Surat" in p
        assert "critical" in p

    def test_response_plan_contains_travel_minutes_instruction(self):
        p = build_response_plan_prompt([], [], [])
        assert "estimated_travel_minutes" in p


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback on malformed Granite JSON
# ═══════════════════════════════════════════════════════════════════════════════

class TestMalformedGraniteResponse:
    def test_malformed_json_falls_through_to_raw_text(self):
        """If Granite returns non-JSON, the layer uses raw text as the text field."""
        mock_client = MagicMock(spec=GraniteClient)
        mock_client.generate.return_value = "I cannot process this."
        layer = GraniteReasoningLayer(client=mock_client)
        result = layer.summarize_situation(make_state(), [make_incident()])
        # Source should still be granite (it responded, just not valid JSON)
        assert result.source == ReasoningSource.GRANITE
        # structured should be empty (parse failed gracefully)
        assert result.structured == {}

    def test_markdown_wrapped_json_parsed_correctly(self):
        """Granite sometimes wraps JSON in ```json fences — layer strips them."""
        canned = {"summary": "Heavy rain.", "overall_severity": "warning",
                  "zones_at_risk": [], "key_concerns": []}
        mock_client = MagicMock(spec=GraniteClient)
        mock_client.generate.return_value = (
            "```json\n" + json.dumps(canned) + "\n```"
        )
        layer = GraniteReasoningLayer(client=mock_client)
        result = layer.summarize_situation(make_state(), [])
        assert result.structured.get("overall_severity") == "warning"
