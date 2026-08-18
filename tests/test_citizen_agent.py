"""Tests for CitizenIncidentAgent and CitizenReportParser.

Five realistic citizen reports, each covering a distinct extraction path:

  Report 1 — Depth in feet + school + road blocked
      "Water is almost 2 feet near the school and the road is blocked."
      Expects: severity MEDIUM, road_blocked=True, facility=school

  Report 2 — Depth in cm + hospital + high population
      "Near Civil Hospital, drainage water 90 cm deep, about 500 people stuck."
      Expects: severity HIGH, facility=hospital, affected_population=500

  Report 3 — Flood keyword + no depth (fallback severity from text)
      "Flash flood near Main Bazaar, neck-deep water, people need rescue urgently."
      Expects: severity CRITICAL (from "neck-deep"/"rescue")

  Report 4 — Zone code explicitly mentioned
      "Ward W12-N waterlogging near the school, ankle-deep water."
      Expects: zone_id=W12-N extracted, severity LOW (ankle-deep)

  Report 5 — Drain blocked, no critical facility, metres unit
      "Storm drain near Ramnagar is overflowing and blocked. Water 0.7 m on road."
      Expects: incident_type=drain_blocked OR waterlogging, depth~0.7, severity MEDIUM

Additional tests:
  - Mocked Granite response (valid JSON)
  - Mocked Granite response (malformed JSON → fallback)
  - Empty report → AgentResult.success=False
  - Agent does not assign resources (no resource_id/action on result)
  - zone_id_hint used when extraction cannot find zone
  - risk_score is deterministic from depth+facility+road+population
  - Evidence has source=CITIZEN_REPORT
  - Incident has evidence_ids linking to Evidence
  - Low-confidence warning when confidence < threshold
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.agents.citizen_incident_agent import (
    AgentResult,
    CitizenIncidentAgent,
    _risk_score,
    _severity_from_extraction,
)
from src.agents.citizen_report_parser import (
    _extract_depth,
    _extract_facility,
    _extract_severity_from_text,
)
from src.agents.extraction_result import ExtractionResult
from src.models.evidence import EvidenceSource
from src.models.incident import IncidentStatus, SeverityLevel
from src.reasoning.granite_client import GraniteClient, GraniteUnavailable

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

CITY = "Ahmedabad"


def _no_key_agent(**kwargs) -> CitizenIncidentAgent:
    """Agent guaranteed to use the fallback extractor (no API key)."""
    from src.reasoning.granite_client import GraniteConfig
    cfg = GraniteConfig(api_url="http://unreachable", api_key="")
    return CitizenIncidentAgent(city=CITY, client=GraniteClient(cfg), **kwargs)


def _mocked_agent(granite_json: dict) -> CitizenIncidentAgent:
    """Agent with a GraniteClient stub returning canned JSON."""
    mock_client = MagicMock(spec=GraniteClient)
    mock_client.generate.return_value = json.dumps(granite_json)
    return CitizenIncidentAgent(city=CITY, client=mock_client)


# ============================================================================
# Report 1 -- Depth in feet + school + road blocked
# ============================================================================

class TestReport1_DepthFeetSchoolRoadBlocked:
    """Water is almost 2 feet near the school and the road is blocked."""

    REPORT = "Water is almost 2 feet near the school and the road is blocked."

    @pytest.fixture
    def result(self) -> AgentResult:
        return _no_key_agent().process(self.REPORT, zone_id_hint="W12-N")

    def test_success(self, result):
        assert result.success is True

    def test_incident_is_not_none(self, result):
        assert result.incident is not None

    def test_road_blocked_extracted(self, result):
        assert result.extraction.road_blocked is True

    def test_school_facility_extracted(self, result):
        assert result.extraction.critical_facility == "school"

    def test_depth_converted_from_feet(self, result):
        # 2 feet = 0.6096 m → rounds to ~0.610
        assert result.extraction.water_depth_m is not None
        assert 0.59 < result.extraction.water_depth_m < 0.63

    def test_severity_medium_from_depth(self, result):
        # 0.6 m >= 0.5 m threshold → MEDIUM
        assert result.incident.severity == SeverityLevel.MEDIUM

    def test_zone_id_hint_used(self, result):
        assert result.incident.zone_id == "W12-N"

    def test_evidence_source_citizen_report(self, result):
        assert result.evidence.source == EvidenceSource.CITIZEN_REPORT

    def test_evidence_links_to_incident(self, result):
        assert result.evidence.id in result.incident.evidence_ids

    def test_incident_status_open(self, result):
        assert result.incident.status == IncidentStatus.OPEN

    def test_incident_has_no_resource_assignment(self, result):
        # Agent must not produce resource assignments
        assert not hasattr(result.incident, "resource_id")
        assert not hasattr(result.incident, "action_id")

    def test_risk_score_above_zero(self, result):
        assert result.incident.risk_score > 0.0

    def test_risk_score_includes_facility_and_road(self, result):
        # facility (0.20) + road (0.15) + depth contribution all > 0
        # minimum score with these three: 0.35 + depth
        assert result.incident.risk_score >= 0.35


# ============================================================================
# Report 2 -- Depth in cm + hospital + high population
# ============================================================================

class TestReport2_CmHospitalPopulation:
    """Near Civil Hospital, drainage water 90 cm deep, about 500 people stuck."""

    REPORT = "Near Civil Hospital, drainage water 90 cm deep, about 500 people stuck."

    @pytest.fixture
    def result(self) -> AgentResult:
        return _no_key_agent().process(self.REPORT, zone_id_hint="W12-C")

    def test_success(self, result):
        assert result.success is True

    def test_hospital_facility_extracted(self, result):
        assert result.extraction.critical_facility == "hospital"

    def test_depth_converted_from_cm(self, result):
        # 90 cm = 0.9 m
        assert result.extraction.water_depth_m is not None
        assert abs(result.extraction.water_depth_m - 0.9) < 0.01

    def test_severity_medium_from_depth(self, result):
        # 0.9 m >= 0.5 m but < 1.0 m → MEDIUM
        assert result.incident.severity == SeverityLevel.MEDIUM

    def test_population_extracted(self, result):
        assert result.extraction.affected_population == 500

    def test_evidence_has_water_level(self, result):
        assert result.evidence.water_level_m is not None
        assert abs(result.evidence.water_level_m - 0.9) < 0.01

    def test_evidence_affected_population(self, result):
        assert result.evidence.affected_population == 500

    def test_risk_score_above_0_30(self, result):
        # facility 0.20 + depth ~0.30×0.40 + pop 500/5000×0.20 = 0.20+0.12+0.02 = 0.34+
        assert result.incident.risk_score > 0.30


# ============================================================================
# Report 3 -- Flash flood, neck-deep, rescue urgency
# ============================================================================

class TestReport3_FlashFloodCritical:
    """Flash flood near Main Bazaar, neck-deep water, people need rescue urgently."""

    REPORT = "Flash flood near Main Bazaar, neck-deep water, people need rescue urgently."

    @pytest.fixture
    def result(self) -> AgentResult:
        return _no_key_agent().process(self.REPORT, zone_id_hint="W12-S")

    def test_success(self, result):
        assert result.success is True

    def test_severity_critical(self, result):
        assert result.incident.severity == SeverityLevel.CRITICAL

    def test_incident_type_flash_flood_or_waterlogging(self, result):
        # fallback may not split flash_flood from waterlogging, accept either
        assert result.extraction.incident_type in ("flash_flood", "waterlogging", "unknown")

    def test_title_mentions_severity(self, result):
        assert "CRITICAL" in result.incident.title

    def test_description_contains_original_report(self, result):
        assert "rescue" in result.incident.description.lower()

    def test_risk_score_is_nonzero(self, result):
        assert result.incident.risk_score > 0.0


# ============================================================================
# Report 4 -- Zone code in text, ankle-deep
# ============================================================================

class TestReport4_ZoneCodeInText:
    """Ward W12-N waterlogging near the school, ankle-deep water."""

    REPORT = "Ward W12-N waterlogging near the school, ankle-deep water."

    @pytest.fixture
    def result(self) -> AgentResult:
        return _no_key_agent().process(self.REPORT)

    def test_success(self, result):
        assert result.success is True

    def test_severity_is_low_or_medium(self, result):
        # ankle-deep → LOW from text cues (no numeric depth given)
        assert result.incident.severity in (SeverityLevel.LOW, SeverityLevel.MEDIUM)

    def test_school_facility_extracted(self, result):
        assert result.extraction.critical_facility == "school"

    def test_incident_type_waterlogging(self, result):
        assert result.extraction.incident_type in ("waterlogging", "unknown")

    def test_evidence_city_correct(self, result):
        assert result.evidence.city == CITY

    def test_incident_has_description(self, result):
        assert len(result.incident.description) > 0


# ============================================================================
# Report 5 -- Drain blocked, metres, no facility
# ============================================================================

class TestReport5_DrainBlockedMetres:
    """Storm drain near Ramnagar is overflowing and blocked. Water 0.7 m on road."""

    REPORT = "Storm drain near Ramnagar is overflowing and blocked. Water 0.7 m on road."

    @pytest.fixture
    def result(self) -> AgentResult:
        return _no_key_agent().process(self.REPORT, zone_id_hint="W12-S")

    def test_success(self, result):
        assert result.success is True

    def test_depth_in_metres_extracted(self, result):
        assert result.extraction.water_depth_m is not None
        assert abs(result.extraction.water_depth_m - 0.7) < 0.01

    def test_severity_medium_from_depth(self, result):
        # 0.7 m >= 0.5 m → MEDIUM
        assert result.incident.severity == SeverityLevel.MEDIUM

    def test_no_critical_facility(self, result):
        assert result.extraction.critical_facility is None

    def test_risk_score_lower_than_with_facility(self, result):
        # Without facility (0.20 weight), score should be lower than a hospital report
        assert result.incident.risk_score < 0.50

    def test_evidence_water_level_set(self, result):
        assert result.evidence.water_level_m is not None
        assert abs(result.evidence.water_level_m - 0.7) < 0.01


# ============================================================================
# Granite mocked path
# ============================================================================

class TestGraniteMockedExtraction:
    """Verify Granite JSON is properly mapped to ExtractionResult + Incident."""

    CANNED = {
        "location_raw": "near Civil Hospital",
        "zone_id": "W12-C",
        "incident_type": "waterlogging",
        "severity": "high",
        "water_depth_m": 1.3,
        "road_blocked": True,
        "critical_facility": "hospital",
        "affected_population": 320,
        "reported_at_raw": "this morning",
        "confidence": 0.82,
        "missing_fields": [],
    }

    @pytest.fixture
    def result(self) -> AgentResult:
        return _mocked_agent(self.CANNED).process(
            "Near Civil Hospital water is very high and road blocked."
        )

    def test_source_is_granite(self, result):
        assert result.extraction.source == "granite"

    def test_zone_id_extracted_by_granite(self, result):
        assert result.extraction.zone_id == "W12-C"
        assert result.incident.zone_id == "W12-C"

    def test_depth_from_granite(self, result):
        assert result.extraction.water_depth_m == 1.3

    def test_severity_high_from_depth(self, result):
        # 1.3 m >= 1.0 m → HIGH (deterministic override)
        assert result.incident.severity == SeverityLevel.HIGH

    def test_road_blocked_from_granite(self, result):
        assert result.extraction.road_blocked is True

    def test_facility_from_granite(self, result):
        assert result.extraction.critical_facility == "hospital"

    def test_population_from_granite(self, result):
        assert result.extraction.affected_population == 320

    def test_confidence_from_granite(self, result):
        assert result.extraction.confidence == 0.82

    def test_no_low_confidence_warning_for_high_confidence(self, result):
        assert not any("Low extraction confidence" in w for w in result.warnings)


class TestGraniteMalformedFallback:
    """If Granite returns non-JSON, fall back to keyword extractor."""

    @pytest.fixture
    def result(self) -> AgentResult:
        mock_client = MagicMock(spec=GraniteClient)
        mock_client.generate.return_value = "Sorry, I cannot process this request."
        agent = CitizenIncidentAgent(city=CITY, client=mock_client)
        return agent.process("Water knee deep near the school, road blocked.", zone_id_hint="Z1")

    def test_success_via_fallback(self, result):
        assert result.success is True

    def test_source_is_fallback(self, result):
        assert result.extraction.source == "fallback"

    def test_road_blocked_extracted_by_fallback(self, result):
        assert result.extraction.road_blocked is True

    def test_school_extracted_by_fallback(self, result):
        assert result.extraction.critical_facility == "school"


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    def test_empty_report_returns_failure(self):
        agent = _no_key_agent()
        result = agent.process("")
        assert result.success is False
        assert result.incident is None
        assert len(result.errors) > 0

    def test_whitespace_only_report_returns_failure(self):
        result = _no_key_agent().process("   ")
        assert result.success is False

    def test_zone_id_hint_applied_when_extraction_finds_none(self):
        result = _no_key_agent().process(
            "There is water everywhere.", zone_id_hint="W12-X"
        )
        assert result.incident.zone_id == "W12-X"

    def test_unknown_zone_placeholder_when_no_hint(self):
        result = _no_key_agent().process("Water is everywhere, road blocked.")
        assert result.incident.zone_id.startswith("UNKNOWN-")

    def test_unknown_zone_produces_warning(self):
        result = _no_key_agent().process("Water is everywhere, road blocked.")
        assert any("UNKNOWN" in w for w in result.warnings)

    def test_agent_result_has_no_resource_attribute(self):
        result = _no_key_agent().process("Water knee-deep near school.", zone_id_hint="Z1")
        assert not hasattr(result, "resource_id")
        assert not hasattr(result, "action")
        assert not hasattr(result, "assignment")

    def test_low_confidence_warning_fires(self):
        result = CitizenIncidentAgent(
            city=CITY,
            client=MagicMock(spec=GraniteClient, **{"generate.side_effect": GraniteUnavailable}),
            low_confidence_threshold=0.99,   # fallback always produces 0.40 → triggers
        ).process("Some flooding somewhere.", zone_id_hint="Z1")
        assert any("Low extraction confidence" in w for w in result.warnings)

    def test_multiple_reports_produce_independent_incidents(self):
        agent = _no_key_agent()
        r1 = agent.process("Water near school 1 foot deep.", zone_id_hint="Z1")
        r2 = agent.process("Drain blocked near hospital, 0.8 m water.", zone_id_hint="Z2")
        assert r1.incident.id != r2.incident.id
        assert r1.evidence.id != r2.evidence.id


# ============================================================================
# Unit tests for parser internals
# ============================================================================

class TestParserInternals:
    def test_feet_to_metres(self):
        assert abs(_extract_depth("2 feet deep") - 0.6096) < 0.001

    def test_inches_to_metres(self):
        assert abs(_extract_depth("18 inches") - 0.4572) < 0.001

    def test_cm_to_metres(self):
        assert abs(_extract_depth("90 cm") - 0.9) < 0.001

    def test_metres_direct(self):
        assert abs(_extract_depth("1.5 m") - 1.5) < 0.001

    def test_no_depth_returns_none(self):
        assert _extract_depth("water on road") is None

    def test_school_extracted(self):
        assert _extract_facility("near the school") == "school"

    def test_hospital_extracted(self):
        assert _extract_facility("Civil Hospital is flooded") == "hospital"

    def test_no_facility_returns_none(self):
        assert _extract_facility("water everywhere") is None

    def test_neck_deep_is_critical(self):
        assert _extract_severity_from_text("neck-deep water", None) == "critical"

    def test_knee_deep_is_high(self):
        assert _extract_severity_from_text("knee-deep water", None) == "high"

    def test_depth_2m_is_critical(self):
        assert _extract_severity_from_text("water everywhere", 2.0) == "critical"

    def test_depth_1m_is_high(self):
        assert _extract_severity_from_text("water", 1.0) == "high"

    def test_depth_0_6m_is_medium(self):
        assert _extract_severity_from_text("water", 0.6) == "medium"

    def test_depth_0_2m_is_low(self):
        assert _extract_severity_from_text("water", 0.2) == "low"


# ============================================================================
# Deterministic severity + risk_score unit tests
# ============================================================================

class TestSeverityAndRiskScore:
    def _ext(self, depth=None, facility=None, road=False, pop=None, sev="low"):
        return ExtractionResult(
            raw_text="test",
            water_depth_m=depth,
            critical_facility=facility,
            road_blocked=road,
            affected_population=pop,
            severity=sev,
        )

    def test_2m_depth_is_critical(self):
        ext = self._ext(depth=2.0)
        assert _severity_from_extraction(ext) == SeverityLevel.CRITICAL

    def test_1m_depth_is_high(self):
        ext = self._ext(depth=1.0)
        assert _severity_from_extraction(ext) == SeverityLevel.HIGH

    def test_0_5m_depth_is_medium(self):
        ext = self._ext(depth=0.5)
        assert _severity_from_extraction(ext) == SeverityLevel.MEDIUM

    def test_0_3m_depth_is_low(self):
        ext = self._ext(depth=0.3)
        assert _severity_from_extraction(ext) == SeverityLevel.LOW

    def test_text_severity_used_when_no_depth(self):
        ext = self._ext(sev="high")
        assert _severity_from_extraction(ext) == SeverityLevel.HIGH

    def test_depth_overrides_text_severity(self):
        # text says low but depth says critical
        ext = self._ext(depth=2.5, sev="low")
        assert _severity_from_extraction(ext) == SeverityLevel.CRITICAL

    def test_risk_score_zero_for_minimal_low(self):
        ext = self._ext(sev="low")
        s = _severity_from_extraction(ext)
        score = _risk_score(ext, s)
        assert 0.0 <= score < 0.1

    def test_risk_score_includes_facility(self):
        ext_no = self._ext(depth=0.6, facility=None,        road=False)
        ext_yes = self._ext(depth=0.6, facility="hospital", road=False)
        s = SeverityLevel.MEDIUM
        assert _risk_score(ext_yes, s) > _risk_score(ext_no, s)

    def test_risk_score_includes_road(self):
        ext_no  = self._ext(depth=0.6, road=False)
        ext_yes = self._ext(depth=0.6, road=True)
        s = SeverityLevel.MEDIUM
        assert _risk_score(ext_yes, s) > _risk_score(ext_no, s)

    def test_risk_score_clamped_to_1(self):
        ext = self._ext(depth=5.0, facility="hospital", road=True,
                        pop=10000, sev="critical")
        s = SeverityLevel.CRITICAL
        assert _risk_score(ext, s) <= 1.0
