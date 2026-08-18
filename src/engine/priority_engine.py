"""IncidentPriorityEngine — transparent, configurable incident prioritisation.

Entry point
-----------
    engine = IncidentPriorityEngine()
    result = engine.score(context)           # uses DEFAULT_CONFIG
    result = engine.score(context, config)   # custom weights

    ranked = engine.rank(contexts)           # score + sort a list

The engine is completely stateless.  The same instance can score thousands of
incidents concurrently.  All scoring logic is pure-function; no side effects.

Scoring pipeline
----------------
For each factor the engine:
  1. Reads the raw value from IncidentContext.
  2. Normalises it to [0.0, 1.0].
  3. Multiplies by the factor weight from PriorityConfig.
  4. Assigns one or more reason codes.

Final score  = sum of all factor contributions, clamped to [0.0, 1.0].
Priority level is assigned by banding the final score:
  CRITICAL  >= 0.75
  HIGH      >= 0.50
  MEDIUM    >= 0.25
  LOW       <  0.25

Factor details
--------------
1. SEVERITY
   Raw: SeverityLevel string
   Normalised: config.severity_score_{level}
   Reason codes: SEVERITY_{LEVEL}

2. CRITICAL_FACILITY
   Raw: int — number of critical facilities (hospitals, fire stations, shelters)
   Normalised: min(count / 2.0, 1.0)    [2+ facilities → 1.0]
   Reason codes: CRITICAL_FACILITY_HIGH (≥ 2), CRITICAL_FACILITY_LOW (== 1)

3. ROAD_DISRUPTION
   Raw: bool
   Normalised: 1.0 if True else 0.0
   Reason codes: ROAD_BLOCKED

4. POPULATION_IMPACT
   Raw: int | None (affected residents)
   Normalised: min(population / config.population_norm, 1.0)
   Reason codes: POPULATION_LARGE (≥ 50% of norm), POPULATION_MODERATE (10–50%)

5. RESPONSE_DEADLINE
   Raw: float | None (hours until deadline)
   Normalised: linear interpolation from 0.0 (≥ deadline_low_hrs)
               to 1.0 (≤ deadline_critical_hrs), clamped.
   Reason codes: DEADLINE_IMMINENT (≤ 2× critical_hrs),
                 DEADLINE_NEAR (≤ 50% of low_hrs)

6. INFRA_DEPENDENCY
   Raw: int — count of shared infrastructure assets at risk
   Normalised: min(count / config.infra_dependency_max, 1.0)
   Reason codes: INFRA_HIGH_DEPENDENCY (≥ max), INFRA_LOW_DEPENDENCY (1..max-1)
"""

from __future__ import annotations

from src.engine.priority_config import DEFAULT_CONFIG, PriorityConfig
from src.engine.priority_context import IncidentContext
from src.engine.priority_result import (
    FactorScore,
    PriorityLevel,
    PriorityResult,
    RC_CRITICAL_FACILITY_HIGH,
    RC_CRITICAL_FACILITY_LOW,
    RC_DEADLINE_IMMINENT,
    RC_DEADLINE_NEAR,
    RC_INFRA_HIGH_DEPENDENCY,
    RC_INFRA_LOW_DEPENDENCY,
    RC_POPULATION_LARGE,
    RC_POPULATION_MODERATE,
    RC_ROAD_BLOCKED,
    RC_SEVERITY_CRITICAL,
    RC_SEVERITY_HIGH,
    RC_SEVERITY_LOW,
    RC_SEVERITY_MEDIUM,
)
from src.models.incident import SeverityLevel


# ── level → band thresholds ───────────────────────────────────────────────────
_LEVEL_THRESHOLDS: list[tuple[float, PriorityLevel]] = [
    (0.75, PriorityLevel.CRITICAL),
    (0.50, PriorityLevel.HIGH),
    (0.25, PriorityLevel.MEDIUM),
    (0.0,  PriorityLevel.LOW),
]


def _priority_level(score: float) -> PriorityLevel:
    for threshold, level in _LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return PriorityLevel.LOW


# ── per-factor scorers ────────────────────────────────────────────────────────

def _score_severity(ctx: IncidentContext, cfg: PriorityConfig) -> FactorScore:
    level = ctx.incident.severity
    score_map = {
        SeverityLevel.LOW:      (cfg.severity_score_low,      RC_SEVERITY_LOW),
        SeverityLevel.MEDIUM:   (cfg.severity_score_medium,   RC_SEVERITY_MEDIUM),
        SeverityLevel.HIGH:     (cfg.severity_score_high,     RC_SEVERITY_HIGH),
        SeverityLevel.CRITICAL: (cfg.severity_score_critical, RC_SEVERITY_CRITICAL),
    }
    normalised, rc = score_map[level]
    return FactorScore(
        name="severity",
        raw_value=str(level),
        normalised=normalised,
        weight=cfg.weight_severity,
        contribution=round(normalised * cfg.weight_severity, 6),
        reason_codes=(rc,),
    )


def _score_critical_facility(ctx: IncidentContext, cfg: PriorityConfig) -> FactorScore:
    count = ctx.critical_facility_count
    normalised = round(min(count / 2.0, 1.0), 6)
    if count >= 2:
        codes: tuple[str, ...] = (RC_CRITICAL_FACILITY_HIGH,)
    elif count == 1:
        codes = (RC_CRITICAL_FACILITY_LOW,)
    else:
        codes = ()
    return FactorScore(
        name="critical_facility",
        raw_value=count,
        normalised=normalised,
        weight=cfg.weight_critical_facility,
        contribution=round(normalised * cfg.weight_critical_facility, 6),
        reason_codes=codes,
    )


def _score_road_disruption(ctx: IncidentContext, cfg: PriorityConfig) -> FactorScore:
    normalised = 1.0 if ctx.road_blocked else 0.0
    return FactorScore(
        name="road_disruption",
        raw_value=ctx.road_blocked,
        normalised=normalised,
        weight=cfg.weight_road_disruption,
        contribution=round(normalised * cfg.weight_road_disruption, 6),
        reason_codes=(RC_ROAD_BLOCKED,) if ctx.road_blocked else (),
    )


def _score_population_impact(ctx: IncidentContext, cfg: PriorityConfig) -> FactorScore:
    pop = ctx.affected_population
    if pop is None or pop == 0:
        return FactorScore(
            name="population_impact",
            raw_value=pop,
            normalised=0.0,
            weight=cfg.weight_population_impact,
            contribution=0.0,
            reason_codes=(),
        )
    normalised = round(min(pop / cfg.population_norm, 1.0), 6)
    if normalised >= 0.5:
        codes: tuple[str, ...] = (RC_POPULATION_LARGE,)
    elif normalised >= 0.10:
        codes = (RC_POPULATION_MODERATE,)
    else:
        codes = ()
    return FactorScore(
        name="population_impact",
        raw_value=pop,
        normalised=normalised,
        weight=cfg.weight_population_impact,
        contribution=round(normalised * cfg.weight_population_impact, 6),
        reason_codes=codes,
    )


def _score_response_deadline(ctx: IncidentContext, cfg: PriorityConfig) -> FactorScore:
    hrs = ctx.hours_until_deadline
    if hrs is None:
        return FactorScore(
            name="response_deadline",
            raw_value=None,
            normalised=0.0,
            weight=cfg.weight_response_deadline,
            contribution=0.0,
            reason_codes=(),
        )
    # Linear interpolation: critical_hrs → 1.0, low_hrs → 0.0
    span = cfg.deadline_low_hrs - cfg.deadline_critical_hrs
    normalised = round(
        min(max((cfg.deadline_low_hrs - hrs) / span, 0.0), 1.0),
        6,
    )
    if hrs <= cfg.deadline_critical_hrs * 2:
        codes: tuple[str, ...] = (RC_DEADLINE_IMMINENT,)
    elif hrs <= cfg.deadline_low_hrs * 0.5:
        codes = (RC_DEADLINE_NEAR,)
    else:
        codes = ()
    return FactorScore(
        name="response_deadline",
        raw_value=hrs,
        normalised=normalised,
        weight=cfg.weight_response_deadline,
        contribution=round(normalised * cfg.weight_response_deadline, 6),
        reason_codes=codes,
    )


def _score_infra_dependency(ctx: IncidentContext, cfg: PriorityConfig) -> FactorScore:
    count = ctx.infra_dependency_count
    if count == 0:
        return FactorScore(
            name="infra_dependency",
            raw_value=0,
            normalised=0.0,
            weight=cfg.weight_infra_dependency,
            contribution=0.0,
            reason_codes=(),
        )
    normalised = round(min(count / cfg.infra_dependency_max, 1.0), 6)
    if count >= cfg.infra_dependency_max:
        codes: tuple[str, ...] = (RC_INFRA_HIGH_DEPENDENCY,)
    else:
        codes = (RC_INFRA_LOW_DEPENDENCY,)
    return FactorScore(
        name="infra_dependency",
        raw_value=count,
        normalised=normalised,
        weight=cfg.weight_infra_dependency,
        contribution=round(normalised * cfg.weight_infra_dependency, 6),
        reason_codes=codes,
    )


# ── ordered list of factor scorers ────────────────────────────────────────────
_FACTOR_SCORERS = [
    _score_severity,
    _score_critical_facility,
    _score_road_disruption,
    _score_population_impact,
    _score_response_deadline,
    _score_infra_dependency,
]


# ── engine ────────────────────────────────────────────────────────────────────

class IncidentPriorityEngine:
    """Stateless, transparent incident priority scorer.

    Usage::

        engine = IncidentPriorityEngine()

        # Score one incident
        result = engine.score(ctx)

        # Score and rank a list
        ranked = engine.rank([ctx_a, ctx_b, ctx_c])

        # Use custom weights for a specific scenario
        cfg = PriorityConfig(
            weight_severity=0.40,
            weight_critical_facility=0.15,
            weight_road_disruption=0.10,
            weight_population_impact=0.20,
            weight_response_deadline=0.10,
            weight_infra_dependency=0.05,
        )
        result = engine.score(ctx, config=cfg)
    """

    def score(
        self,
        context: IncidentContext,
        config: PriorityConfig = DEFAULT_CONFIG,
    ) -> PriorityResult:
        """Score a single incident and return a fully transparent PriorityResult."""
        factors = tuple(fn(context, config) for fn in _FACTOR_SCORERS)

        raw_score = sum(f.contribution for f in factors)
        final_score = round(min(max(raw_score, 0.0), 1.0), 4)

        all_codes: list[str] = []
        for f in factors:
            all_codes.extend(f.reason_codes)
        reason_codes = tuple(sorted(set(all_codes)))

        return PriorityResult(
            incident_id=context.incident.id,
            score=final_score,
            level=_priority_level(final_score),
            factors=factors,
            reason_codes=reason_codes,
        )

    def rank(
        self,
        contexts: list[IncidentContext],
        config: PriorityConfig = DEFAULT_CONFIG,
    ) -> list[PriorityResult]:
        """Score and rank a list of IncidentContexts by score descending."""
        results = [self.score(ctx, config) for ctx in contexts]
        return sorted(results, key=lambda r: r.score, reverse=True)
