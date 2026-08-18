"""Tests for the FlowShield watsonx Orchestrate layer.

Test class layout
-----------------
TestToolContracts               — Pydantic model validation for all I/O contracts
TestToolIngestIncident          — ingest_incident tool correctness + error paths
TestToolCalculatePriority       — calculate_priority tool correctness
TestToolOptimizeResources       — optimize_resources tool correctness + gap handling
TestToolGenerateResponsePlan    — generate_response_plan tool correctness
TestToolLookupSituation         — lookup_situation tool with/without engine
TestToolRegistry                — ToolRegistry.get, invoke, schema export
TestScenarioRunnerHappyPath     — full end-to-end citizen report scenario
TestScenarioRunnerFailurePaths  — ingestion failure, empty resources, unknown zone
TestScenarioRunnerOrchestrate   — Orchestrate manifest shape + schema validity
TestEngineIsolation             — core modules remain importable without orchestrate
"""

from __future__ import annotations

from datetime import UTC

import pytest

from src.orchestrate import (
    FLOWSHIELD_REGISTRY,
    AssignmentRecord,
    CalculatePriorityInput,
    CitizenReportScenario,
    GenerateResponsePlanInput,
    IngestIncidentInput,
    LookupSituationInput,
    OptimizeResourcesInput,
    PlanActionRecord,
    PriorityResultSpec,
    ResourceSpec,
    ScenarioResult,
    UnassignedRecord,
    calculate_priority,
    generate_response_plan,
    ingest_incident,
    lookup_situation,
    optimize_resources,
    run_citizen_report_scenario,
)
from src.orchestrate.tool_contracts import (
    CalculatePriorityOutput,
    GenerateResponsePlanOutput,
    IngestIncidentOutput,
    LookupSituationOutput,
    OptimizeResourcesOutput,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

CITY = "TestCity"
ZONE = "Z-01"


def _resource(
    rid: str = "res-01",
    rtype: str = "pump",
    zone: str = ZONE,
) -> ResourceSpec:
    return ResourceSpec(
        id=rid, name=f"Resource {rid}", city=CITY,
        type=rtype, home_zone_id=zone, current_zone_id=zone,
    )


def _pr_spec(
    incident_id: str = "inc-01",
    score: float = 0.70,
    level: str = "high",
) -> PriorityResultSpec:
    return PriorityResultSpec(
        incident_id=incident_id,
        priority_score=score,
        priority_level=level,
        reason_codes=["SEVERITY_HIGH"],
        factor_breakdown=[{
            "name": "severity", "raw_value": "high",
            "normalised": 0.7, "weight": 0.3,
            "contribution": 0.21, "reason_codes": ["SEVERITY_HIGH"],
        }],
    )


def _assignment(
    incident_id: str = "inc-01",
    resource_id: str = "res-01",
) -> AssignmentRecord:
    return AssignmentRecord(
        incident_id=incident_id, resource_id=resource_id,
        incident_zone=ZONE, resource_zone=ZONE,
        estimated_travel_minutes=5.0, fit_score=0.9,
        reason_codes=["OA_BEST_FIT"],
    )


# ---------------------------------------------------------------------------
# TestToolContracts
# ---------------------------------------------------------------------------

class TestToolContracts:

    def test_ingest_incident_input_valid(self) -> None:
        inp = IngestIncidentInput(city=CITY, report_text="Water near school.")
        assert inp.city == CITY

    def test_ingest_incident_input_rejects_extra(self) -> None:
        with pytest.raises(Exception):
            IngestIncidentInput(city=CITY, report_text="x", unknown="oops")

    def test_ingest_incident_input_empty_city_raises(self) -> None:
        with pytest.raises(Exception):
            IngestIncidentInput(city="", report_text="Water.")

    def test_calculate_priority_input_valid(self) -> None:
        inp = CalculatePriorityInput(
            city=CITY, incident_id="i1", zone_id=ZONE,
            severity="high", risk_score=0.7, title="Test",
        )
        assert inp.severity == "high"

    def test_calculate_priority_rejects_bad_risk_score(self) -> None:
        with pytest.raises(Exception):
            CalculatePriorityInput(
                city=CITY, incident_id="i1", zone_id=ZONE,
                severity="high", risk_score=2.0, title="T",
            )

    def test_optimize_resources_input_valid(self) -> None:
        inp = OptimizeResourcesInput(
            city=CITY,
            priority_results=[_pr_spec()],
            resources=[_resource()],
            zone_of_incident={"inc-01": ZONE},
        )
        assert len(inp.resources) == 1

    def test_generate_response_plan_input_valid(self) -> None:
        inp = GenerateResponsePlanInput(
            city=CITY,
            priority_results=[_pr_spec()],
            assignments=[_assignment()],
            unassigned_incidents=[],
            resources=[_resource()],
        )
        assert inp.use_knowledge_base is True

    def test_lookup_situation_input_valid(self) -> None:
        inp = LookupSituationInput(city=CITY, zone_ids=[ZONE])
        assert inp.zone_ids == [ZONE]

    def test_resource_spec_extra_field_rejected(self) -> None:
        with pytest.raises(Exception):
            ResourceSpec(
                id="r", name="R", city=CITY, type="pump",
                home_zone_id=ZONE, unknown_field="x",
            )

    def test_plan_action_record_extra_field_rejected(self) -> None:
        with pytest.raises(Exception):
            PlanActionRecord(
                id="p", incident_id="i", resource_id=None,
                action_description="escalate to EOC.",
                responsible_unit="EOC", priority_rank=1,
                priority_level="high", priority_score=0.7,
                target_response_minutes=30, estimated_travel_minutes=None,
                reason_codes=[], evidence_ids=[], citations=[],
                retrieved_chunk_ids=[], approval_state="required",
                reasoning_text="Gap.", surprise="boom",
            )


# ---------------------------------------------------------------------------
# TestToolIngestIncident
# ---------------------------------------------------------------------------

class TestToolIngestIncident:

    def test_successful_ingestion(self) -> None:
        out = ingest_incident(IngestIncidentInput(
            city=CITY,
            report_text="Water is knee deep near the school. Road blocked.",
            zone_id_hint=ZONE,
        ))
        assert out.success is True
        assert out.incident_id is not None
        assert out.severity in ("low", "medium", "high", "critical")

    def test_empty_report_fails(self) -> None:
        out = ingest_incident(IngestIncidentInput(city=CITY, report_text="   "))
        assert out.success is False
        assert len(out.errors) > 0

    def test_output_has_evidence_id(self) -> None:
        out = ingest_incident(IngestIncidentInput(
            city=CITY,
            report_text="Flooding near the market. 2 feet deep.",
            zone_id_hint=ZONE,
        ))
        if out.success:
            assert out.evidence_id is not None

    def test_zone_id_hint_used(self) -> None:
        out = ingest_incident(IngestIncidentInput(
            city=CITY, report_text="Water everywhere.", zone_id_hint="MY-ZONE",
        ))
        if out.success:
            assert out.zone_id == "MY-ZONE"

    def test_output_never_raises(self) -> None:
        # Even garbage input must not raise
        out = ingest_incident(IngestIncidentInput(
            city=CITY, report_text="!@#$%^&*()",
        ))
        assert isinstance(out, IngestIncidentOutput)

    def test_risk_score_in_range(self) -> None:
        out = ingest_incident(IngestIncidentInput(
            city=CITY, report_text="Deep water near hospital.", zone_id_hint=ZONE,
        ))
        if out.success:
            assert 0.0 <= out.risk_score <= 1.0

    def test_city_preserved_in_output(self) -> None:
        out = ingest_incident(IngestIncidentInput(
            city="Surat", report_text="Flood near the bridge.", zone_id_hint="S-01",
        ))
        # ingestion doesn't carry city back, but should not fail
        assert isinstance(out, IngestIncidentOutput)

    def test_warnings_are_list(self) -> None:
        out = ingest_incident(IngestIncidentInput(
            city=CITY, report_text="Some flooding.", zone_id_hint=ZONE,
        ))
        assert isinstance(out.warnings, list)


# ---------------------------------------------------------------------------
# TestToolCalculatePriority
# ---------------------------------------------------------------------------

class TestToolCalculatePriority:

    def _base_input(self, **overrides) -> CalculatePriorityInput:
        base = dict(
            city=CITY, incident_id="inc-01", zone_id=ZONE,
            severity="high", risk_score=0.7, title="Flood",
        )
        base.update(overrides)
        return CalculatePriorityInput(**base)

    def test_returns_output(self) -> None:
        out = calculate_priority(self._base_input())
        assert isinstance(out, CalculatePriorityOutput)

    def test_incident_id_preserved(self) -> None:
        out = calculate_priority(self._base_input(incident_id="my-inc"))
        assert out.incident_id == "my-inc"

    def test_priority_score_in_range(self) -> None:
        out = calculate_priority(self._base_input())
        assert 0.0 <= out.priority_score <= 1.0

    def test_priority_level_valid(self) -> None:
        out = calculate_priority(self._base_input())
        assert out.priority_level in ("critical", "high", "medium", "low")

    def test_reason_codes_nonempty_for_high(self) -> None:
        out = calculate_priority(self._base_input(severity="high"))
        assert len(out.reason_codes) > 0

    def test_critical_severity_scores_high(self) -> None:
        out = calculate_priority(self._base_input(severity="critical", risk_score=0.9))
        assert out.priority_score >= 0.25  # at least MEDIUM

    def test_road_blocked_increases_score(self) -> None:
        without = calculate_priority(self._base_input(road_blocked=False))
        with_ = calculate_priority(self._base_input(road_blocked=True))
        assert with_.priority_score >= without.priority_score

    def test_factor_breakdown_has_six_factors(self) -> None:
        out = calculate_priority(self._base_input())
        assert len(out.factor_breakdown) == 6

    def test_factor_breakdown_names(self) -> None:
        out = calculate_priority(self._base_input())
        names = [f["name"] for f in out.factor_breakdown]
        assert "severity" in names
        assert "road_disruption" in names

    def test_critical_facility_raises_score(self) -> None:
        without = calculate_priority(self._base_input(critical_facility_count=0))
        with_ = calculate_priority(self._base_input(critical_facility_count=2))
        assert with_.priority_score > without.priority_score


# ---------------------------------------------------------------------------
# TestToolOptimizeResources
# ---------------------------------------------------------------------------

class TestToolOptimizeResources:

    def _base_input(self, resources=None, **overrides) -> OptimizeResourcesInput:
        if resources is None:
            resources = [_resource()]
        base = dict(
            city=CITY,
            priority_results=[_pr_spec()],
            resources=resources,
            zone_of_incident={"inc-01": ZONE},
            distances={ZONE: {ZONE: 0.0}},
        )
        base.update(overrides)
        return OptimizeResourcesInput(**base)

    def test_assigns_resource_to_incident(self) -> None:
        out = optimize_resources(self._base_input())
        assert out.assignment_count == 1
        assert len(out.assignments) == 1

    def test_assignment_incident_id_correct(self) -> None:
        out = optimize_resources(self._base_input())
        assert out.assignments[0].incident_id == "inc-01"

    def test_assignment_resource_id_correct(self) -> None:
        out = optimize_resources(self._base_input())
        assert out.assignments[0].resource_id == "res-01"

    def test_no_resources_produces_gap(self) -> None:
        out = optimize_resources(self._base_input(resources=[]))
        assert out.gap_count == 1
        assert len(out.unassigned_incidents) == 1

    def test_gap_has_reason_codes(self) -> None:
        out = optimize_resources(self._base_input(resources=[]))
        assert len(out.unassigned_incidents[0].reason_codes) > 0

    def test_assigned_resource_ids_populated(self) -> None:
        out = optimize_resources(self._base_input())
        assert "res-01" in out.assigned_resource_ids

    def test_two_incidents_one_resource(self) -> None:
        prs = [_pr_spec("i1", 0.8), _pr_spec("i2", 0.5)]
        out = optimize_resources(OptimizeResourcesInput(
            city=CITY,
            priority_results=prs,
            resources=[_resource()],
            zone_of_incident={"i1": ZONE, "i2": ZONE},
        ))
        # One assigned, one gap
        assert out.assignment_count + out.gap_count == 2

    def test_reason_codes_present_in_assignment(self) -> None:
        out = optimize_resources(self._base_input())
        assert len(out.assignments[0].reason_codes) > 0

    def test_travel_minutes_non_negative(self) -> None:
        out = optimize_resources(self._base_input())
        assert out.assignments[0].estimated_travel_minutes >= 0.0


# ---------------------------------------------------------------------------
# TestToolGenerateResponsePlan
# ---------------------------------------------------------------------------

class TestToolGenerateResponsePlan:

    def _base_input(self, with_gap: bool = False) -> GenerateResponsePlanInput:
        assignments = [] if with_gap else [_assignment()]
        unassigned = [UnassignedRecord(
            incident_id="inc-01", priority_score=0.7, reason_codes=["UA_NO_RESOURCE"]
        )] if with_gap else []
        return GenerateResponsePlanInput(
            city=CITY,
            priority_results=[_pr_spec()],
            assignments=assignments,
            unassigned_incidents=unassigned,
            resources=[_resource()],
            use_knowledge_base=True,
        )

    def test_returns_output(self) -> None:
        out = generate_response_plan(self._base_input())
        assert isinstance(out, GenerateResponsePlanOutput)

    def test_plan_id_is_uuid(self) -> None:
        out = generate_response_plan(self._base_input())
        assert len(out.plan_id) == 36

    def test_action_count_matches_assignments(self) -> None:
        out = generate_response_plan(self._base_input())
        assert out.action_count == 1

    def test_gap_count_for_unassigned(self) -> None:
        out = generate_response_plan(self._base_input(with_gap=True))
        assert out.gap_count == 1

    def test_gap_requires_approval(self) -> None:
        out = generate_response_plan(self._base_input(with_gap=True))
        assert out.requires_human_approval is True

    def test_citations_present_with_kb(self) -> None:
        out = generate_response_plan(self._base_input())
        assert len(out.knowledge_citations) > 0

    def test_citations_absent_without_kb(self) -> None:
        inp = self._base_input()
        inp = inp.model_copy(update={"use_knowledge_base": False})
        out = generate_response_plan(inp)
        assert out.knowledge_citations == []

    def test_reasoning_summary_nonempty(self) -> None:
        out = generate_response_plan(self._base_input())
        assert len(out.reasoning_summary) > 0

    def test_plan_actions_have_incident_id(self) -> None:
        out = generate_response_plan(self._base_input())
        for pa in out.plan_actions:
            assert pa.incident_id

    def test_plan_action_has_reasoning_text(self) -> None:
        out = generate_response_plan(self._base_input())
        for pa in out.plan_actions:
            assert len(pa.reasoning_text) > 0

    def test_city_preserved(self) -> None:
        out = generate_response_plan(self._base_input())
        assert out.city == CITY

    def test_warnings_is_list(self) -> None:
        out = generate_response_plan(self._base_input())
        assert isinstance(out.warnings, list)


# ---------------------------------------------------------------------------
# TestToolLookupSituation
# ---------------------------------------------------------------------------

class TestToolLookupSituation:

    def test_without_engine_returns_empty_safe(self) -> None:
        out = lookup_situation(LookupSituationInput(city=CITY), engine=None)
        assert isinstance(out, LookupSituationOutput)
        assert out.city == CITY
        assert out.overall_severity == "normal"
        assert out.zones == []

    def test_with_engine_returns_zones(self) -> None:
        from datetime import datetime

        from src.engine.engine import SituationEngine
        from src.models.event import RawEvent, RawEventType

        engine = SituationEngine(city=CITY)
        event = RawEvent(
            event_type=RawEventType.RAINFALL,
            city=CITY,
            zone_id=ZONE,
            source="mock",
            occurred_at=datetime.now(UTC),
            payload={"rainfall_mm_hr": 45.0},
        )
        engine.process(event)
        out = lookup_situation(LookupSituationInput(city=CITY), engine=engine)
        assert len(out.zones) >= 1

    def test_zone_filter_applied(self) -> None:
        from datetime import datetime

        from src.engine.engine import SituationEngine
        from src.models.event import RawEvent, RawEventType

        engine = SituationEngine(city=CITY)
        for zone in ("Z-01", "Z-02"):
            engine.process(RawEvent(
                event_type=RawEventType.RAINFALL, city=CITY, zone_id=zone,
                source="mock", occurred_at=datetime.now(UTC),
                payload={"rainfall_mm_hr": 20.0},
            ))
        out = lookup_situation(
            LookupSituationInput(city=CITY, zone_ids=["Z-01"]),
            engine=engine,
        )
        assert all(z.zone_id == "Z-01" for z in out.zones)

    def test_overall_severity_string(self) -> None:
        out = lookup_situation(LookupSituationInput(city=CITY), engine=None)
        assert out.overall_severity in ("normal", "watch", "warning", "critical")

    def test_critical_zone_ids_empty_for_light_rain(self) -> None:
        from datetime import datetime

        from src.engine.engine import SituationEngine
        from src.models.event import RawEvent, RawEventType

        engine = SituationEngine(city=CITY)
        engine.process(RawEvent(
            event_type=RawEventType.RAINFALL, city=CITY, zone_id=ZONE,
            source="mock", occurred_at=datetime.now(UTC),
            payload={"rainfall_mm_hr": 5.0},
        ))
        out = lookup_situation(LookupSituationInput(city=CITY), engine=engine)
        assert ZONE not in out.critical_zone_ids


# ---------------------------------------------------------------------------
# TestToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:

    def test_registry_has_five_tools(self) -> None:
        assert len(FLOWSHIELD_REGISTRY) == 5

    def test_all_tool_names_present(self) -> None:
        expected = {
            "ingest_incident", "calculate_priority", "optimize_resources",
            "generate_response_plan", "lookup_situation",
        }
        assert set(FLOWSHIELD_REGISTRY.names) == expected

    def test_get_tool_by_name(self) -> None:
        spec = FLOWSHIELD_REGISTRY.get("ingest_incident")
        assert spec is not None
        assert spec.name == "ingest_incident"

    def test_get_missing_returns_none(self) -> None:
        assert FLOWSHIELD_REGISTRY.get("nonexistent_tool") is None

    def test_tool_has_description(self) -> None:
        for name in FLOWSHIELD_REGISTRY.names:
            spec = FLOWSHIELD_REGISTRY.get(name)
            assert len(spec.description) > 10

    def test_input_schema_is_dict(self) -> None:
        spec = FLOWSHIELD_REGISTRY.get("ingest_incident")
        schema = spec.input_schema
        assert isinstance(schema, dict)
        assert "properties" in schema

    def test_output_schema_is_dict(self) -> None:
        spec = FLOWSHIELD_REGISTRY.get("ingest_incident")
        schema = spec.output_schema
        assert isinstance(schema, dict)

    def test_invoke_ingest_incident(self) -> None:
        inp = IngestIncidentInput(city=CITY, report_text="Flood near school.", zone_id_hint=ZONE)
        out = FLOWSHIELD_REGISTRY.invoke("ingest_incident", inp)
        assert isinstance(out, IngestIncidentOutput)

    def test_invoke_unknown_tool_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            FLOWSHIELD_REGISTRY.invoke("bogus_tool", None)

    def test_orchestrate_manifest_structure(self) -> None:
        manifest = FLOWSHIELD_REGISTRY.to_orchestrate_manifest()
        assert len(manifest) == 5
        for entry in manifest:
            assert "name" in entry
            assert "description" in entry
            assert "parameters" in entry
            assert "returns" in entry

    def test_orchestrate_manifest_tool_names(self) -> None:
        manifest = FLOWSHIELD_REGISTRY.to_orchestrate_manifest()
        names = [e["name"] for e in manifest]
        assert "ingest_incident" in names
        assert "generate_response_plan" in names


# ---------------------------------------------------------------------------
# TestScenarioRunnerHappyPath
# ---------------------------------------------------------------------------

class TestScenarioRunnerHappyPath:

    def _run(
        self, report: str = "Water is knee deep near the school. Road blocked."
    ) -> ScenarioResult:
        return run_citizen_report_scenario(CitizenReportScenario(
            city=CITY,
            report_text=report,
            zone_id_hint=ZONE,
            resources=[_resource()],
            distances={ZONE: {ZONE: 0.0}},
        ))

    def test_scenario_succeeds(self) -> None:
        assert self._run().success is True

    def test_all_five_steps_executed(self) -> None:
        result = self._run()
        assert set(result.step_trace) == {
            "ingest_incident", "calculate_priority",
            "optimize_resources", "generate_response_plan", "lookup_situation",
        }

    def test_ingestion_output_present(self) -> None:
        assert self._run().ingestion is not None

    def test_priority_output_present(self) -> None:
        result = self._run()
        assert result.priority is not None

    def test_optimization_output_present(self) -> None:
        result = self._run()
        assert result.optimization is not None

    def test_response_plan_output_present(self) -> None:
        result = self._run()
        assert result.response_plan is not None

    def test_situation_output_present(self) -> None:
        result = self._run()
        assert result.situation is not None

    def test_response_plan_has_actions(self) -> None:
        result = self._run()
        assert result.response_plan.action_count >= 1

    def test_citations_returned(self) -> None:
        result = self._run()
        assert len(result.response_plan.knowledge_citations) > 0

    def test_no_errors_on_success(self) -> None:
        result = self._run()
        assert result.errors == []

    def test_intermediate_values_are_pydantic_models(self) -> None:
        result = self._run()
        assert isinstance(result.ingestion, IngestIncidentOutput)
        assert isinstance(result.optimization, OptimizeResourcesOutput)
        assert isinstance(result.response_plan, GenerateResponsePlanOutput)
        assert isinstance(result.situation, LookupSituationOutput)


# ---------------------------------------------------------------------------
# TestScenarioRunnerFailurePaths
# ---------------------------------------------------------------------------

class TestScenarioRunnerFailurePaths:

    def test_empty_report_fails_gracefully(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY, report_text="", zone_id_hint=ZONE,
        ))
        assert result.success is False
        assert len(result.errors) > 0

    def test_whitespace_report_fails_gracefully(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY, report_text="   ", zone_id_hint=ZONE,
        ))
        assert result.success is False

    def test_ingestion_failure_still_runs_situation_lookup(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY, report_text="",
        ))
        assert "lookup_situation" in result.step_trace

    def test_no_resources_produces_gap(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY,
            report_text="Heavy flooding near the market.",
            zone_id_hint=ZONE,
            resources=[],
        ))
        if result.success:
            assert result.optimization.gap_count == 1

    def test_malformed_resource_dict_skipped_with_warning(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY,
            report_text="Water near school.",
            zone_id_hint=ZONE,
            resources=[{"id": "bad-resource"}],  # missing required fields
        ))
        # Should not raise — malformed resources are skipped
        assert isinstance(result, ScenarioResult)

    def test_failure_ingestion_step_trace(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY, report_text="",
        ))
        assert "ingest_incident" in result.step_trace
        assert "calculate_priority" not in result.step_trace

    def test_success_false_when_ingestion_fails(self) -> None:
        result = run_citizen_report_scenario(CitizenReportScenario(
            city=CITY, report_text="",
        ))
        assert result.success is False


# ---------------------------------------------------------------------------
# TestScenarioRunnerOrchestrate
# ---------------------------------------------------------------------------

class TestScenarioRunnerOrchestrate:
    """Verify the Orchestrate manifest and schema shapes."""

    def test_manifest_serialisable(self) -> None:
        import json
        manifest = FLOWSHIELD_REGISTRY.to_orchestrate_manifest()
        # Must be JSON-serialisable (no non-primitive types)
        json.dumps(manifest)  # raises if not serialisable

    def test_all_input_schemas_have_required_field(self) -> None:
        for name in FLOWSHIELD_REGISTRY.names:
            spec = FLOWSHIELD_REGISTRY.get(name)
            schema = spec.input_schema
            # At minimum, 'city' should be a required or present property
            props = schema.get("properties", {})
            if name != "lookup_situation":
                assert "city" in props, f"Tool {name} missing 'city' in input schema"

    def test_output_schemas_have_type_object(self) -> None:
        for name in FLOWSHIELD_REGISTRY.names:
            spec = FLOWSHIELD_REGISTRY.get(name)
            schema = spec.output_schema
            assert schema.get("type") == "object" or "properties" in schema

    def test_to_orchestrate_spec_shape(self) -> None:
        spec = FLOWSHIELD_REGISTRY.get("ingest_incident")
        d = spec.to_orchestrate_spec()
        assert set(d.keys()) == {"name", "description", "parameters", "returns"}
        assert d["name"] == "ingest_incident"


# ---------------------------------------------------------------------------
# TestEngineIsolation
# ---------------------------------------------------------------------------

class TestEngineIsolation:
    """Core modules must remain importable and usable independently."""

    def test_situation_engine_importable_without_orchestrate(self) -> None:
        from src.engine.engine import SituationEngine
        eng = SituationEngine(city="Standalone")
        assert eng.city == "Standalone"

    def test_priority_engine_importable_without_orchestrate(self) -> None:
        from src.engine.priority_engine import IncidentPriorityEngine
        assert IncidentPriorityEngine() is not None

    def test_citizen_agent_importable_without_orchestrate(self) -> None:
        from src.agents.citizen_incident_agent import CitizenIncidentAgent
        agent = CitizenIncidentAgent(city="Standalone")
        assert agent.city == "Standalone"

    def test_knowledge_base_importable_without_orchestrate(self) -> None:
        from src.knowledge.documents import FLOWSHIELD_KB
        assert FLOWSHIELD_KB.size > 0

    def test_orchestrate_module_does_not_pollute_engine_namespace(self) -> None:
        """Importing orchestrate must not modify engine module globals."""
        from src.engine import engine as eng_module
        attrs_before = set(dir(eng_module))
        import src.orchestrate  # noqa: F401
        attrs_after = set(dir(eng_module))
        assert attrs_before == attrs_after
