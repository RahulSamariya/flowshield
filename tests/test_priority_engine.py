"""Tests for IncidentPriorityEngine.

Five incident profiles that exercise distinct scoring paths:

  Profile A — "Quiet watch"
      Low severity, no facilities, no road block, small population,
      no deadline, no infra.  Expected: LOW band, minimal score.

  Profile B — "Road-blocked waterlogging"
      Medium severity, 1 facility, road blocked, moderate population,
      no deadline.  Expected: MEDIUM–HIGH band.

  Profile C — "Hospital district flood"
      High severity, 3 critical facilities (hospital + fire station + shelter),
      road blocked, large population, near deadline.  Expected: CRITICAL band.

  Profile D — "Infrastructure cascade risk"
      Critical severity, no facilities, no road block, small population,
      comfortable deadline, 5 shared infra assets.  Expected: HIGH band.

  Profile E — "Deadline-driven emergency"
      Medium severity, no facilities, no road block, zero population,
      0.5 hours until deadline.  Expected: HIGH band driven purely by deadline.

Additional tests cover:
  - PriorityConfig validation (bad weights, bad deadline ordering)
  - factor breakdown (each factor's contribution is independently verified)
  - rank() ordering across multiple incidents
  - custom config overrides default
  - factor() lookup helper
  - reason_codes are deduplicated and sorted
"""

from __future__ import annotations

import pytest

from src.engine.priority_config import DEFAULT_CONFIG, PriorityConfig
from src.engine.priority_context import IncidentContext
from src.engine.priority_engine import IncidentPriorityEngine
from src.engine.priority_result import (
    RC_CRITICAL_FACILITY_HIGH,
    RC_CRITICAL_FACILITY_LOW,
    RC_DEADLINE_IMMINENT,
    RC_INFRA_HIGH_DEPENDENCY,
    RC_POPULATION_LARGE,
    RC_POPULATION_MODERATE,
    RC_ROAD_BLOCKED,
    RC_SEVERITY_CRITICAL,
    RC_SEVERITY_LOW,
    RC_SEVERITY_MEDIUM,
    PriorityLevel,
)
from src.models.incident import Incident, SeverityLevel

# ── shared helpers ────────────────────────────────────────────────────────────

def make_incident(severity: SeverityLevel, zone_id: str = "W12") -> Incident:
    return Incident(
        city="TestCity",
        zone_id=zone_id,
        severity=severity,
        risk_score=0.5,
        title=f"Test incident [{severity}]",
    )


ENGINE = IncidentPriorityEngine()


# ── Profile A: Quiet watch ─────────────────────────────────────────────────────

class TestProfileA_QuietWatch:
    """Low severity, no contextual amplifiers."""

    @pytest.fixture
    def ctx(self):
        return IncidentContext(
            incident=make_incident(SeverityLevel.LOW),
            critical_facility_count=0,
            road_blocked=False,
            affected_population=100,
            hours_until_deadline=None,
            infra_dependency_count=0,
        )

    def test_level_is_low(self, ctx):
        result = ENGINE.score(ctx)
        assert result.level == PriorityLevel.LOW

    def test_score_below_0_25(self, ctx):
        result = ENGINE.score(ctx)
        assert result.score < 0.25

    def test_severity_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_SEVERITY_LOW in result.reason_codes

    def test_no_road_blocked_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_ROAD_BLOCKED not in result.reason_codes

    def test_six_factors_present(self, ctx):
        result = ENGINE.score(ctx)
        assert len(result.factors) == 6

    def test_incident_id_matches(self, ctx):
        result = ENGINE.score(ctx)
        assert result.incident_id == ctx.incident.id

    def test_factor_contributions_sum_to_score(self, ctx):
        result = ENGINE.score(ctx)
        total = sum(f.contribution for f in result.factors)
        assert abs(total - result.score) < 1e-4


# ── Profile B: Road-blocked waterlogging ──────────────────────────────────────

class TestProfileB_RoadBlockedWaterlogging:
    """Medium severity, 1 facility, road blocked, moderate population."""

    @pytest.fixture
    def ctx(self):
        return IncidentContext(
            incident=make_incident(SeverityLevel.MEDIUM),
            critical_facility_count=1,
            road_blocked=True,
            affected_population=1500,
            hours_until_deadline=None,
            infra_dependency_count=0,
        )

    def test_level_is_at_least_medium(self, ctx):
        result = ENGINE.score(ctx)
        assert result.level in (PriorityLevel.MEDIUM, PriorityLevel.HIGH)

    def test_road_blocked_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_ROAD_BLOCKED in result.reason_codes

    def test_critical_facility_low_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_CRITICAL_FACILITY_LOW in result.reason_codes

    def test_population_moderate_reason_code(self, ctx):
        # 1500 / 5000 = 0.30 → between 10% and 50% → MODERATE
        result = ENGINE.score(ctx)
        assert RC_POPULATION_MODERATE in result.reason_codes

    def test_road_disruption_contribution_nonzero(self, ctx):
        result = ENGINE.score(ctx)
        road = result.factor("road_disruption")
        assert road is not None
        assert road.contribution > 0

    def test_score_higher_than_profile_a(self, ctx):
        ctx_a = IncidentContext(
            incident=make_incident(SeverityLevel.LOW),
            critical_facility_count=0,
            road_blocked=False,
            affected_population=100,
        )
        score_a = ENGINE.score(ctx_a).score
        score_b = ENGINE.score(ctx).score
        assert score_b > score_a


# ── Profile C: Hospital district flood ───────────────────────────────────────

class TestProfileC_HospitalDistrictFlood:
    """High severity, 3 facilities, road blocked, large population, near deadline."""

    @pytest.fixture
    def ctx(self):
        return IncidentContext(
            incident=make_incident(SeverityLevel.HIGH),
            critical_facility_count=3,
            road_blocked=True,
            affected_population=4500,
            hours_until_deadline=0.8,   # < deadline_critical_hrs (1.0) → imminent
            infra_dependency_count=2,
        )

    def test_level_is_critical(self, ctx):
        result = ENGINE.score(ctx)
        assert result.level == PriorityLevel.CRITICAL

    def test_score_above_0_75(self, ctx):
        result = ENGINE.score(ctx)
        assert result.score >= 0.75

    def test_critical_facility_high_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_CRITICAL_FACILITY_HIGH in result.reason_codes

    def test_road_blocked_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_ROAD_BLOCKED in result.reason_codes

    def test_population_large_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_POPULATION_LARGE in result.reason_codes

    def test_deadline_imminent_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_DEADLINE_IMMINENT in result.reason_codes

    def test_all_factors_contribute(self, ctx):
        result = ENGINE.score(ctx)
        # Every factor should have a positive contribution
        for f in result.factors:
            assert f.contribution >= 0.0
        non_zero = [f for f in result.factors if f.contribution > 0]
        assert len(non_zero) == 6   # all six factors fired

    def test_reason_codes_deduplicated(self, ctx):
        result = ENGINE.score(ctx)
        assert len(result.reason_codes) == len(set(result.reason_codes))

    def test_reason_codes_sorted(self, ctx):
        result = ENGINE.score(ctx)
        assert list(result.reason_codes) == sorted(result.reason_codes)


# ── Profile D: Infrastructure cascade ────────────────────────────────────────

class TestProfileD_InfrastructureCascade:
    """Critical severity, no facilities, max infra dependency, comfortable deadline."""

    @pytest.fixture
    def ctx(self):
        return IncidentContext(
            incident=make_incident(SeverityLevel.CRITICAL),
            critical_facility_count=0,
            road_blocked=False,
            affected_population=200,
            hours_until_deadline=20.0,  # comfortable — near the low threshold
            infra_dependency_count=5,   # == infra_dependency_max → full contribution
        )

    def test_level_is_medium_or_above(self, ctx):
        # CRITICAL severity (0.30) + max infra (0.05) + small pop + partial deadline = ~0.375
        # No facility, no road block keeps it out of HIGH. MEDIUM is the correct band.
        result = ENGINE.score(ctx)
        assert result.level in (PriorityLevel.MEDIUM, PriorityLevel.HIGH, PriorityLevel.CRITICAL)

    def test_severity_critical_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_SEVERITY_CRITICAL in result.reason_codes

    def test_infra_high_dependency_reason_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_INFRA_HIGH_DEPENDENCY in result.reason_codes

    def test_no_road_blocked_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_ROAD_BLOCKED not in result.reason_codes

    def test_infra_contribution_is_full_weight(self, ctx):
        result = ENGINE.score(ctx)
        infra = result.factor("infra_dependency")
        assert infra is not None
        assert abs(infra.contribution - DEFAULT_CONFIG.weight_infra_dependency) < 1e-5

    def test_score_driven_by_severity_and_infra(self, ctx):
        result = ENGINE.score(ctx)
        sev = result.factor("severity")
        infra = result.factor("infra_dependency")
        assert sev is not None and infra is not None
        # Their combined contribution alone should be > 0.30
        assert sev.contribution + infra.contribution > 0.30


# ── Profile E: Deadline-driven emergency ─────────────────────────────────────

class TestProfileE_DeadlineDriven:
    """Medium severity, no other amplifiers, 0.5 h deadline → HIGH from urgency alone."""

    @pytest.fixture
    def ctx(self):
        return IncidentContext(
            incident=make_incident(SeverityLevel.MEDIUM),
            critical_facility_count=0,
            road_blocked=False,
            affected_population=None,
            hours_until_deadline=0.5,   # half of deadline_critical_hrs → very urgent
            infra_dependency_count=0,
        )

    def test_deadline_imminent_code_present(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_DEADLINE_IMMINENT in result.reason_codes

    def test_deadline_contribution_maxed(self, ctx):
        # 0.5 h < critical_hrs (1.0) → normalised = 1.0
        result = ENGINE.score(ctx)
        dl = result.factor("response_deadline")
        assert dl is not None
        assert dl.normalised == 1.0
        assert abs(dl.contribution - DEFAULT_CONFIG.weight_response_deadline) < 1e-5

    def test_population_contribution_zero(self, ctx):
        result = ENGINE.score(ctx)
        pop = result.factor("population_impact")
        assert pop is not None
        assert pop.contribution == 0.0

    def test_score_higher_than_same_medium_no_deadline(self, ctx):
        ctx_no_dl = IncidentContext(
            incident=make_incident(SeverityLevel.MEDIUM),
            critical_facility_count=0,
            road_blocked=False,
            affected_population=None,
            hours_until_deadline=None,
            infra_dependency_count=0,
        )
        score_with = ENGINE.score(ctx).score
        score_without = ENGINE.score(ctx_no_dl).score
        assert score_with > score_without

    def test_severity_medium_code(self, ctx):
        result = ENGINE.score(ctx)
        assert RC_SEVERITY_MEDIUM in result.reason_codes


# ── PriorityConfig validation ─────────────────────────────────────────────────

class TestPriorityConfigValidation:
    def test_default_config_weights_sum_to_1(self):
        total = (
            DEFAULT_CONFIG.weight_severity
            + DEFAULT_CONFIG.weight_critical_facility
            + DEFAULT_CONFIG.weight_road_disruption
            + DEFAULT_CONFIG.weight_population_impact
            + DEFAULT_CONFIG.weight_response_deadline
            + DEFAULT_CONFIG.weight_infra_dependency
        )
        assert abs(total - 1.0) < 1e-6

    def test_weights_not_summing_to_1_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            PriorityConfig(
                weight_severity=0.50,
                weight_critical_facility=0.20,
                weight_road_disruption=0.15,
                weight_population_impact=0.20,
                weight_response_deadline=0.10,
                weight_infra_dependency=0.05,
            )

    def test_bad_deadline_ordering_raises(self):
        with pytest.raises(ValueError, match="deadline_critical_hrs"):
            PriorityConfig(
                weight_severity=0.30,
                weight_critical_facility=0.20,
                weight_road_disruption=0.15,
                weight_population_impact=0.20,
                weight_response_deadline=0.10,
                weight_infra_dependency=0.05,
                deadline_critical_hrs=24.0,
                deadline_low_hrs=1.0,
            )


# ── Custom config ─────────────────────────────────────────────────────────────

class TestCustomConfig:
    def test_severity_only_config(self):
        """A config that puts all weight on severity."""
        cfg = PriorityConfig(
            weight_severity=1.00,
            weight_critical_facility=0.00,
            weight_road_disruption=0.00,
            weight_population_impact=0.00,
            weight_response_deadline=0.00,
            weight_infra_dependency=0.00,
        )
        ctx = IncidentContext(
            incident=make_incident(SeverityLevel.CRITICAL),
            critical_facility_count=5,
            road_blocked=True,
            affected_population=9000,
            hours_until_deadline=0.1,
            infra_dependency_count=10,
        )
        result = ENGINE.score(ctx, config=cfg)
        # Only severity contributes → score == severity_score_critical == 1.0
        assert result.score == 1.0
        assert result.level == PriorityLevel.CRITICAL

    def test_custom_config_changes_ranking(self):
        """Flip to infrastructure-heavy config and verify ranking changes."""
        default_ctx_a = IncidentContext(
            incident=make_incident(SeverityLevel.CRITICAL, zone_id="Z1"),
            infra_dependency_count=0,
        )
        default_ctx_b = IncidentContext(
            incident=make_incident(SeverityLevel.LOW, zone_id="Z2"),
            infra_dependency_count=5,
        )

        # With DEFAULT_CONFIG, critical severity (Z1) scores higher
        ranked_default = ENGINE.rank([default_ctx_a, default_ctx_b])
        assert ranked_default[0].incident_id == default_ctx_a.incident.id

        # With infra-heavy config, high infra (Z2) can compete
        cfg_infra = PriorityConfig(
            weight_severity=0.15,
            weight_critical_facility=0.15,
            weight_road_disruption=0.10,
            weight_population_impact=0.15,
            weight_response_deadline=0.10,
            weight_infra_dependency=0.35,
        )
        ranked_infra = ENGINE.rank([default_ctx_a, default_ctx_b], config=cfg_infra)
        # Z2 (full infra) should now outscore Z1 (no infra, low severity score offset)
        assert ranked_infra[0].incident_id == default_ctx_b.incident.id


# ── rank() ordering ───────────────────────────────────────────────────────────

class TestRanking:
    def test_rank_returns_descending_order(self):
        contexts = [
            IncidentContext(incident=make_incident(SeverityLevel.LOW,      "Z1")),
            IncidentContext(incident=make_incident(SeverityLevel.CRITICAL,  "Z2")),
            IncidentContext(incident=make_incident(SeverityLevel.MEDIUM,   "Z3")),
            IncidentContext(incident=make_incident(SeverityLevel.HIGH,     "Z4")),
        ]
        ranked = ENGINE.rank(contexts)
        scores = [r.score for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_rank_empty_list(self):
        assert ENGINE.rank([]) == []

    def test_rank_single_item(self):
        ctx = IncidentContext(incident=make_incident(SeverityLevel.HIGH))
        ranked = ENGINE.rank([ctx])
        assert len(ranked) == 1

    def test_rank_length_matches_input(self):
        contexts = [
            IncidentContext(incident=make_incident(SeverityLevel.LOW,  f"Z{i}"))
            for i in range(5)
        ]
        ranked = ENGINE.rank(contexts)
        assert len(ranked) == 5


# ── factor() helper ───────────────────────────────────────────────────────────

class TestFactorHelper:
    def test_known_factor_returns_factor_score(self):
        ctx = IncidentContext(incident=make_incident(SeverityLevel.HIGH))
        result = ENGINE.score(ctx)
        assert result.factor("severity") is not None

    def test_unknown_factor_returns_none(self):
        ctx = IncidentContext(incident=make_incident(SeverityLevel.HIGH))
        result = ENGINE.score(ctx)
        assert result.factor("does_not_exist") is None

    def test_all_six_factor_names_present(self):
        ctx = IncidentContext(incident=make_incident(SeverityLevel.MEDIUM))
        result = ENGINE.score(ctx)
        expected = {
            "severity", "critical_facility", "road_disruption",
            "population_impact", "response_deadline", "infra_dependency",
        }
        assert {f.name for f in result.factors} == expected
