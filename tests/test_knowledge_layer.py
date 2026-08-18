"""Tests for the FlowShield RAG knowledge layer.

Test class layout
-----------------
TestKnowledgeChunk              — KnowledgeChunk dataclass construction and fields
TestKnowledgeBase               — KnowledgeBase retrieval, filtering, edge cases
TestRetrievalResult             — RetrievalResult accessors (citations, chunks)
TestFlowshieldKB                — FLOWSHIELD_KB built-in corpus smoke tests
TestKBRetrievalRelevance        — Retrieval actually surfaces expected chunks
TestKBCategoryFilter            — Category-filtered retrieval
TestResponsePlanningAgentWithKB — ResponsePlanningAgent correctly wires the KB
TestCitationPropagation         — Citations propagate to PlanAction and ResponsePlan
TestKBNoSensorData              — Corpus must not contain live sensor values
TestPromptWithKBContext         — build_response_plan_with_kb_prompt builds valid prompt
"""

from __future__ import annotations

import pytest

from src.agents.response_planning_agent import PlanningResult, ResponsePlanningAgent
from src.engine.optimizer_result import (
    OA_BEST_FIT,
    UA_NO_RESOURCE,
    Assignment,
    OptimizationResult,
    UnassignedIncident,
)
from src.engine.priority_result import RC_SEVERITY_HIGH, FactorScore, PriorityLevel, PriorityResult
from src.knowledge.documents import FLOWSHIELD_KB
from src.knowledge.knowledge_base import KnowledgeBase, RetrievalResult, RetrievedChunk
from src.knowledge.knowledge_chunk import KnowledgeCategory, KnowledgeChunk
from src.models.incident import Incident, SeverityLevel
from src.models.resource import Resource, ResourceStatus, ResourceType
from src.models.situation import SituationState, ZoneSeverity, ZoneStatus
from src.reasoning.prompt_templates import build_response_plan_with_kb_prompt

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _chunk(
    chunk_id: str = "test-chunk",
    category: KnowledgeCategory = KnowledgeCategory.SOP,
    title: str = "Test SOP",
    text: str = "Deploy pump to flooded zone immediately.",
    tags: tuple[str, ...] = ("pump", "flood", "deploy"),
    source_ref: str = "Test SOP 2023, Sec 1.1",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=chunk_id,
        category=category,
        title=title,
        text=text,
        tags=tags,
        source_ref=source_ref,
    )


# ---------------------------------------------------------------------------
# TestKnowledgeChunk
# ---------------------------------------------------------------------------

class TestKnowledgeChunk:

    def test_construction(self) -> None:
        c = _chunk()
        assert c.id == "test-chunk"
        assert c.category == KnowledgeCategory.SOP

    def test_frozen(self) -> None:
        c = _chunk()
        with pytest.raises((AttributeError, TypeError)):
            c.text = "mutated"  # type: ignore[misc]

    def test_tags_default_empty_tuple(self) -> None:
        c = KnowledgeChunk(
            id="no-tags",
            category=KnowledgeCategory.ESCALATION,
            title="No Tags",
            text="Some policy text.",
        )
        assert c.tags == ()

    def test_source_ref_defaults_empty(self) -> None:
        c = KnowledgeChunk(
            id="no-ref",
            category=KnowledgeCategory.DRAINAGE,
            title="No Ref",
            text="Drainage guidance.",
        )
        assert c.source_ref == ""

    def test_category_values(self) -> None:
        for cat in KnowledgeCategory:
            assert isinstance(cat, str)


# ---------------------------------------------------------------------------
# TestKnowledgeBase
# ---------------------------------------------------------------------------

class TestKnowledgeBase:

    def _kb(self, *chunks: KnowledgeChunk) -> KnowledgeBase:
        return KnowledgeBase(chunks=list(chunks))

    def test_size_property(self) -> None:
        kb = self._kb(_chunk("a"), _chunk("b"))
        assert kb.size == 2

    def test_get_existing_chunk(self) -> None:
        c = _chunk("my-chunk")
        kb = self._kb(c)
        assert kb.get("my-chunk") is c

    def test_get_missing_chunk(self) -> None:
        kb = self._kb(_chunk())
        assert kb.get("nonexistent") is None

    def test_categories(self) -> None:
        kb = self._kb(
            _chunk("a", category=KnowledgeCategory.SOP),
            _chunk("b", category=KnowledgeCategory.ESCALATION),
        )
        assert KnowledgeCategory.SOP in kb.categories()
        assert KnowledgeCategory.ESCALATION in kb.categories()

    def test_empty_kb_returns_empty_hits(self) -> None:
        kb = KnowledgeBase(chunks=[])
        result = kb.retrieve("pump deployment")
        assert result.hits == []

    def test_empty_query_returns_empty_hits(self) -> None:
        kb = self._kb(_chunk())
        result = kb.retrieve("")
        assert result.hits == []

    def test_stopword_only_query_returns_empty(self) -> None:
        kb = self._kb(_chunk())
        result = kb.retrieve("the a and or")
        assert result.hits == []

    def test_basic_retrieval_returns_hit(self) -> None:
        kb = self._kb(_chunk(text="Deploy pump to flooded zone."))
        result = kb.retrieve("pump deployment flood")
        assert len(result.hits) >= 1

    def test_retrieval_returns_relevance_scores(self) -> None:
        kb = self._kb(_chunk(text="Deploy pump to flooded zone."))
        result = kb.retrieve("pump deployment")
        for h in result.hits:
            assert h.relevance_score > 0.0

    def test_top_k_limits_results(self) -> None:
        chunks = [_chunk(chunk_id=f"c{i}", text=f"flood pump zone {i}") for i in range(10)]
        kb = KnowledgeBase(chunks=chunks)
        result = kb.retrieve("pump flood", top_k=3)
        assert len(result.hits) <= 3

    def test_results_ordered_by_score_descending(self) -> None:
        kb = self._kb(
            _chunk("hi", text="pump flood pump pump flood"),
            _chunk("lo", text="unrelated content about roads"),
        )
        result = kb.retrieve("pump flood", top_k=5)
        scores = [h.relevance_score for h in result.hits]
        assert scores == sorted(scores, reverse=True)

    def test_category_filter_restricts_results(self) -> None:
        kb = self._kb(
            _chunk("sop1", category=KnowledgeCategory.SOP, text="pump flood deploy"),
            _chunk("esc1", category=KnowledgeCategory.ESCALATION, text="pump flood escalate"),
        )
        result = kb.retrieve("pump flood", category_filter=KnowledgeCategory.ESCALATION)
        for h in result.hits:
            assert h.chunk.category == KnowledgeCategory.ESCALATION

    def test_category_filter_none_retrieves_all(self) -> None:
        kb = self._kb(
            _chunk("sop1", category=KnowledgeCategory.SOP, text="pump flood deploy"),
            _chunk("esc1", category=KnowledgeCategory.ESCALATION, text="pump flood escalate"),
        )
        result = kb.retrieve("pump flood", category_filter=None, top_k=10)
        categories = {h.chunk.category for h in result.hits}
        assert len(categories) > 1

    def test_tags_boost_retrieval(self) -> None:
        """A chunk whose tags match the query should outrank one that doesn't."""
        kb = self._kb(
            _chunk("tagged", text="general guidance", tags=("pump", "dewatering", "flood")),
            _chunk("untagged", text="pump flood general guidance", tags=()),
        )
        result = kb.retrieve("pump dewatering", top_k=2)
        # "tagged" should be first due to tag weighting
        assert result.hits[0].chunk.id == "tagged"

    def test_zero_score_chunks_excluded(self) -> None:
        """A chunk with zero matching tokens must not appear in results."""
        # Use explicit title/tags with no overlap with the query
        c_match = KnowledgeChunk(
            id="match", category=KnowledgeCategory.SOP,
            title="Pump Deployment", text="pump flood deploy zone dewatering",
            tags=("pump", "flood"), source_ref="X",
        )
        c_nomatch = KnowledgeChunk(
            id="nomatch", category=KnowledgeCategory.COMMUNICATION,
            title="Administrative Filing Procedure", text="zxqabstract xylophone cornucopia",
            tags=("paperwork", "filing"), source_ref="Y",
        )
        kb = KnowledgeBase(chunks=[c_match, c_nomatch])
        result = kb.retrieve("pump flood dewatering")
        ids = [h.chunk.id for h in result.hits]
        assert "nomatch" not in ids

    def test_retrieval_result_query_preserved(self) -> None:
        kb = self._kb(_chunk())
        result = kb.retrieve("pump deployment")
        assert result.query == "pump deployment"

    def test_retrieval_result_category_filter_preserved(self) -> None:
        kb = self._kb(_chunk())
        result = kb.retrieve("pump", category_filter=KnowledgeCategory.SOP)
        assert result.category_filter == KnowledgeCategory.SOP


# ---------------------------------------------------------------------------
# TestRetrievalResult
# ---------------------------------------------------------------------------

class TestRetrievalResult:

    def _result_with_hits(self) -> RetrievalResult:
        chunks = [
            _chunk("c1", source_ref="SOP A, Sec 1"),
            _chunk("c2", source_ref="SOP B, Sec 2"),
            _chunk("c3", source_ref="SOP A, Sec 1"),  # duplicate source_ref
        ]
        hits = [RetrievedChunk(chunk=c, relevance_score=float(3 - i)) for i, c in enumerate(chunks)]
        return RetrievalResult(query="test", hits=hits)

    def test_chunks_property(self) -> None:
        result = self._result_with_hits()
        assert len(result.chunks) == 3

    def test_citations_unique(self) -> None:
        result = self._result_with_hits()
        cites = result.citations
        # "SOP A, Sec 1" appears twice in hits but only once in citations
        assert cites.count("SOP A, Sec 1") == 1

    def test_citations_ordered_by_hit_order(self) -> None:
        result = self._result_with_hits()
        assert result.citations[0] == "SOP A, Sec 1"
        assert result.citations[1] == "SOP B, Sec 2"

    def test_empty_source_ref_falls_back_to_title(self) -> None:
        c = _chunk(source_ref="")
        result = RetrievalResult(
            query="q",
            hits=[RetrievedChunk(chunk=c, relevance_score=1.0)],
        )
        assert result.citations == [c.title]


# ---------------------------------------------------------------------------
# TestFlowshieldKB
# ---------------------------------------------------------------------------

class TestFlowshieldKB:

    def test_corpus_size(self) -> None:
        assert FLOWSHIELD_KB.size >= 15  # at least 15 built-in chunks

    def test_all_expected_categories_present(self) -> None:
        cats = FLOWSHIELD_KB.categories()
        for expected in (
            KnowledgeCategory.SOP,
            KnowledgeCategory.DRAINAGE,
            KnowledgeCategory.ESCALATION,
            KnowledgeCategory.APPROVAL_POLICY,
            KnowledgeCategory.SAFETY,
            KnowledgeCategory.COMMUNICATION,
        ):
            assert expected in cats, f"Category {expected} missing from FLOWSHIELD_KB"

    def test_all_chunks_have_source_ref(self) -> None:
        for chunk_id, chunk in FLOWSHIELD_KB._chunks.items():
            assert chunk.source_ref, f"Chunk '{chunk_id}' has empty source_ref"

    def test_all_chunks_have_text(self) -> None:
        for chunk_id, chunk in FLOWSHIELD_KB._chunks.items():
            assert len(chunk.text) >= 50, f"Chunk '{chunk_id}' text too short"

    def test_all_chunk_ids_unique(self) -> None:
        ids = list(FLOWSHIELD_KB._chunks.keys())
        assert len(ids) == len(set(ids))

    def test_no_duplicate_titles(self) -> None:
        titles = [c.title for c in FLOWSHIELD_KB._chunks.values()]
        assert len(titles) == len(set(titles))


# ---------------------------------------------------------------------------
# TestKBRetrievalRelevance
# ---------------------------------------------------------------------------

class TestKBRetrievalRelevance:
    """Verify that semantically relevant chunks surface for realistic queries."""

    def test_pump_query_retrieves_dewatering_chunk(self) -> None:
        result = FLOWSHIELD_KB.retrieve("pump dewatering waterlogging")
        ids = [h.chunk.id for h in result.hits]
        assert any("dewatering" in cid or "waterlogging" in cid for cid in ids)

    def test_escalation_query_finds_escalation_chunks(self) -> None:
        result = FLOWSHIELD_KB.retrieve("escalate critical EOC authority")
        cats = {h.chunk.category for h in result.hits}
        assert KnowledgeCategory.ESCALATION in cats

    def test_approval_query_finds_approval_chunks(self) -> None:
        result = FLOWSHIELD_KB.retrieve("approval sign-off human authorisation critical")
        cats = {h.chunk.category for h in result.hits}
        assert KnowledgeCategory.APPROVAL_POLICY in cats

    def test_rescue_query_finds_sop_or_safety(self) -> None:
        result = FLOWSHIELD_KB.retrieve("rescue team deployment swift water")
        cats = {h.chunk.category for h in result.hits}
        assert KnowledgeCategory.SOP in cats or KnowledgeCategory.SAFETY in cats

    def test_drain_query_finds_drainage_chunk(self) -> None:
        result = FLOWSHIELD_KB.retrieve("drain blockage clearance maintenance")
        cats = {h.chunk.category for h in result.hits}
        assert KnowledgeCategory.DRAINAGE in cats or KnowledgeCategory.SOP in cats

    def test_ai_query_finds_approval_policy(self) -> None:
        result = FLOWSHIELD_KB.retrieve("AI generated recommendation human oversight")
        ids = [h.chunk.id for h in result.hits]
        assert any("ai" in cid for cid in ids)

    def test_road_closure_query_relevant(self) -> None:
        result = FLOWSHIELD_KB.retrieve("road closure flood barricade")
        assert len(result.hits) > 0


# ---------------------------------------------------------------------------
# TestKBCategoryFilter
# ---------------------------------------------------------------------------

class TestKBCategoryFilter:

    def test_sop_filter(self) -> None:
        result = FLOWSHIELD_KB.retrieve(
            "flood response deploy", category_filter=KnowledgeCategory.SOP
        )
        for h in result.hits:
            assert h.chunk.category == KnowledgeCategory.SOP

    def test_escalation_filter(self) -> None:
        result = FLOWSHIELD_KB.retrieve(
            "escalate authority resource gap", category_filter=KnowledgeCategory.ESCALATION
        )
        for h in result.hits:
            assert h.chunk.category == KnowledgeCategory.ESCALATION

    def test_approval_filter(self) -> None:
        result = FLOWSHIELD_KB.retrieve(
            "approval sign-off", category_filter=KnowledgeCategory.APPROVAL_POLICY
        )
        for h in result.hits:
            assert h.chunk.category == KnowledgeCategory.APPROVAL_POLICY

    def test_drainage_filter(self) -> None:
        result = FLOWSHIELD_KB.retrieve(
            "pump dewatering drain", category_filter=KnowledgeCategory.DRAINAGE
        )
        for h in result.hits:
            assert h.chunk.category == KnowledgeCategory.DRAINAGE

    def test_nonexistent_category_returns_empty(self) -> None:
        """If no chunks match the category, hits should be empty."""
        kb = KnowledgeBase(chunks=[
            _chunk("a", category=KnowledgeCategory.SOP, text="pump flood deploy"),
        ])
        result = kb.retrieve("pump", category_filter=KnowledgeCategory.ESCALATION)
        assert result.hits == []


# ---------------------------------------------------------------------------
# TestResponsePlanningAgentWithKB
# ---------------------------------------------------------------------------

CITY = "TestCity"


def _make_incident(zone_id: str = "Z-01", evidence_ids: list[str] | None = None) -> Incident:
    return Incident(
        id=f"inc-{zone_id}",
        city=CITY,
        zone_id=zone_id,
        severity=SeverityLevel.HIGH,
        risk_score=0.70,
        title=f"Waterlogging flood zone {zone_id}",
        evidence_ids=evidence_ids or [f"ev-{zone_id}"],
    )


def _make_resource(rid: str = "res-01", rtype: ResourceType = ResourceType.PUMP) -> Resource:
    return Resource(
        id=rid, name=f"Resource {rid}", city=CITY,
        type=rtype, home_zone_id="Z-01",
        current_zone_id="Z-01", status=ResourceStatus.AVAILABLE,
    )


def _make_pr(incident_id: str, score: float = 0.70) -> PriorityResult:
    return PriorityResult(
        incident_id=incident_id,
        score=score,
        level=PriorityLevel.HIGH,
        factors=(FactorScore("severity", "high", 0.7, 0.3, 0.21, (RC_SEVERITY_HIGH,)),),
        reason_codes=(RC_SEVERITY_HIGH,),
    )


def _make_state(incidents: list[Incident] | None = None) -> SituationState:
    state = SituationState(
        city=CITY,
        zones={"Z-01": ZoneStatus(zone_id="Z-01", severity=ZoneSeverity.WARNING)},
    )
    if incidents:
        object.__setattr__(state, "_incidents", {inc.id: inc for inc in incidents})
    return state


class TestResponsePlanningAgentWithKB:

    def test_agent_accepts_kb_parameter(self) -> None:
        agent = ResponsePlanningAgent(city=CITY, knowledge_base=FLOWSHIELD_KB)
        assert agent._kb is FLOWSHIELD_KB

    def test_agent_works_without_kb(self) -> None:
        agent = ResponsePlanningAgent(city=CITY)
        assert agent._kb is None

    def test_plan_with_kb_returns_success(self) -> None:
        inc = _make_incident()
        res = _make_resource()
        pr = _make_pr(inc.id)
        opt = OptimizationResult(
            assignments=[Assignment(
                incident_id=inc.id, resource_id=res.id,
                incident_zone="Z-01", resource_zone="Z-01",
                estimated_travel_minutes=10.0, fit_score=0.8,
                reason_codes=(OA_BEST_FIT,),
            )]
        )
        agent = ResponsePlanningAgent(city=CITY, knowledge_base=FLOWSHIELD_KB)
        result = agent.plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[res],
        )
        assert result.success is True

    def test_plan_without_kb_has_empty_citations(self) -> None:
        inc = _make_incident()
        res = _make_resource()
        pr = _make_pr(inc.id)
        opt = OptimizationResult(
            assignments=[Assignment(
                incident_id=inc.id, resource_id=res.id,
                incident_zone="Z-01", resource_zone="Z-01",
                estimated_travel_minutes=10.0, fit_score=0.8,
                reason_codes=(OA_BEST_FIT,),
            )]
        )
        result = ResponsePlanningAgent(city=CITY).plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[res],
        )
        for pa in result.plan.plan_actions:
            assert pa.citations == ()
            assert pa.retrieved_chunk_ids == ()


# ---------------------------------------------------------------------------
# TestCitationPropagation
# ---------------------------------------------------------------------------

class TestCitationPropagation:

    def _plan_with_kb(self, incident_title: str = "Waterlogging flood zone Z-01") -> PlanningResult:
        inc = Incident(
            id="inc-Z-01", city=CITY, zone_id="Z-01",
            severity=SeverityLevel.HIGH, risk_score=0.70,
            title=incident_title, evidence_ids=["ev-01"],
        )
        res = _make_resource()
        pr = _make_pr(inc.id)
        opt = OptimizationResult(
            assignments=[Assignment(
                incident_id=inc.id, resource_id=res.id,
                incident_zone="Z-01", resource_zone="Z-01",
                estimated_travel_minutes=10.0, fit_score=0.8,
                reason_codes=(OA_BEST_FIT,),
            )]
        )
        agent = ResponsePlanningAgent(city=CITY, knowledge_base=FLOWSHIELD_KB)
        return agent.plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[res],
        )

    def test_plan_action_has_citations_with_kb(self) -> None:
        result = self._plan_with_kb()
        pa = result.plan.plan_actions[0]
        assert len(pa.citations) > 0

    def test_citations_are_strings(self) -> None:
        result = self._plan_with_kb()
        for pa in result.plan.plan_actions:
            for cite in pa.citations:
                assert isinstance(cite, str)
                assert len(cite) > 0

    def test_plan_level_knowledge_citations_non_empty(self) -> None:
        result = self._plan_with_kb()
        assert len(result.plan.knowledge_citations) > 0

    def test_knowledge_citations_are_unique(self) -> None:
        result = self._plan_with_kb()
        cites = list(result.plan.knowledge_citations)
        assert len(cites) == len(set(cites))

    def test_retrieved_chunk_ids_reference_real_chunks(self) -> None:
        result = self._plan_with_kb()
        for pa in result.plan.plan_actions:
            for cid in pa.retrieved_chunk_ids:
                assert FLOWSHIELD_KB.get(cid) is not None, f"Unknown chunk id '{cid}'"

    def test_gap_action_cites_escalation_policy(self) -> None:
        inc = _make_incident()
        res = _make_resource()
        pr = _make_pr(inc.id)
        unassigned = UnassignedIncident(
            incident_id=inc.id,
            priority_score=0.70,
            reason_codes=(UA_NO_RESOURCE,),
        )
        opt = OptimizationResult(unassigned_incidents=[unassigned])
        agent = ResponsePlanningAgent(city=CITY, knowledge_base=FLOWSHIELD_KB)
        result = agent.plan(
            state=_make_state([inc]),
            priority_results=[pr],
            opt_result=opt,
            resources=[res],
        )
        pa = result.plan.plan_actions[0]
        # Gap actions use category_hint="escalation"
        for cid in pa.retrieved_chunk_ids:
            chunk = FLOWSHIELD_KB.get(cid)
            assert chunk is not None
            assert chunk.category == KnowledgeCategory.ESCALATION


# ---------------------------------------------------------------------------
# TestKBNoSensorData
# ---------------------------------------------------------------------------

class TestKBNoSensorData:
    """Verify that the knowledge corpus does not contain live sensor values."""

    _SENSOR_PATTERNS = [
        # These patterns indicate live sensor readings, not SOP procedural text
        "current rainfall",
        "current water level",
        "sensor reading",
        "real-time sensor",
        "real-time reading",
        "live data",
        "live sensor",
    ]

    def test_no_sensor_data_in_corpus_text(self) -> None:
        for chunk in FLOWSHIELD_KB._chunks.values():
            lower = chunk.text.lower()
            for pattern in self._SENSOR_PATTERNS:
                assert pattern not in lower, (
                    f"Chunk '{chunk.id}' contains sensor data pattern: '{pattern}'"
                )

    def test_no_resource_availability_in_corpus(self) -> None:
        forbidden = ["currently available", "resource available", "pump available"]
        for chunk in FLOWSHIELD_KB._chunks.values():
            lower = chunk.text.lower()
            for phrase in forbidden:
                assert phrase not in lower, (
                    f"Chunk '{chunk.id}' may contain live resource data: '{phrase}'"
                )


# ---------------------------------------------------------------------------
# TestPromptWithKBContext
# ---------------------------------------------------------------------------

class TestPromptWithKBContext:

    def test_prompt_contains_kb_section(self) -> None:
        prompt = build_response_plan_with_kb_prompt(
            assignments=[{"incident_id": "i1", "resource_id": "r1"}],
            priority_results=[],
            incidents=[],
            kb_context=["[AMC SOP 2023, Sec 3.1]\nDeploy pump immediately."],
        )
        assert "POLICY CONTEXT" in prompt
        assert "AMC SOP 2023, Sec 3.1" in prompt

    def test_prompt_with_empty_kb_context(self) -> None:
        prompt = build_response_plan_with_kb_prompt(
            assignments=[],
            priority_results=[],
            incidents=[],
            kb_context=[],
        )
        assert "No policy context retrieved." in prompt

    def test_prompt_contains_must_not_rules(self) -> None:
        prompt = build_response_plan_with_kb_prompt([], [], [], [])
        assert "MUST NOT" in prompt

    def test_prompt_requests_policy_citations_in_schema(self) -> None:
        prompt = build_response_plan_with_kb_prompt([], [], [], [])
        assert "policy_citations" in prompt

    def test_prompt_requests_policy_note_per_step(self) -> None:
        prompt = build_response_plan_with_kb_prompt([], [], [], [])
        assert "policy_note" in prompt

    def test_prompt_ends_with_end_token(self) -> None:
        prompt = build_response_plan_with_kb_prompt([], [], [], [])
        assert prompt.strip().endswith("<|end|>")

    def test_must_not_fabricate_policy_in_prompt(self) -> None:
        prompt = build_response_plan_with_kb_prompt([], [], [], [])
        assert "fabricate" in prompt.lower()

    def test_multiple_kb_blocks_in_prompt(self) -> None:
        prompt = build_response_plan_with_kb_prompt(
            assignments=[], priority_results=[], incidents=[],
            kb_context=[
                "[SOP A]\nFirst policy.",
                "[SOP B]\nSecond policy.",
            ],
        )
        assert "SOP A" in prompt
        assert "SOP B" in prompt
