"""Priority result — the output of IncidentPriorityEngine.score().

PriorityResult is intentionally verbose: every field that contributed to the
final score is recorded with its raw value, normalised contribution, weight,
and reason code.  This makes the scoring fully auditable without replaying
the calculation.

PriorityLevel bands
-------------------
CRITICAL   score >= 0.75
HIGH       score >= 0.50
MEDIUM     score >= 0.25
LOW        score <  0.25
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PriorityLevel(StrEnum):
    """Discrete priority band derived from the continuous score."""

    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"


# Reason code vocabulary — short machine-readable strings used in reports.
# Each factor can emit zero, one, or several reason codes.
RC_SEVERITY_CRITICAL        = "SEVERITY_CRITICAL"
RC_SEVERITY_HIGH            = "SEVERITY_HIGH"
RC_SEVERITY_MEDIUM          = "SEVERITY_MEDIUM"
RC_SEVERITY_LOW             = "SEVERITY_LOW"
RC_CRITICAL_FACILITY_HIGH   = "CRITICAL_FACILITY_HIGH"   # ≥ 2 facilities
RC_CRITICAL_FACILITY_LOW    = "CRITICAL_FACILITY_LOW"    # 1 facility
RC_ROAD_BLOCKED             = "ROAD_BLOCKED"
RC_POPULATION_LARGE         = "POPULATION_LARGE"         # ≥ 50 % of norm
RC_POPULATION_MODERATE      = "POPULATION_MODERATE"      # 10–50 % of norm
RC_DEADLINE_IMMINENT        = "DEADLINE_IMMINENT"        # ≤ 2× critical threshold
RC_DEADLINE_NEAR            = "DEADLINE_NEAR"            # ≤ 50 % of low threshold
RC_INFRA_HIGH_DEPENDENCY    = "INFRA_HIGH_DEPENDENCY"    # ≥ max threshold
RC_INFRA_LOW_DEPENDENCY     = "INFRA_LOW_DEPENDENCY"     # < max threshold but > 0


@dataclass(frozen=True)
class FactorScore:
    """The contribution of a single factor to the final priority score.

    Attributes
    ----------
    name
        Human-readable factor name (e.g. "severity").
    raw_value
        The input value before normalisation (e.g. 1800 people, True, "critical").
    normalised
        Value after normalisation, in [0.0, 1.0].
    weight
        Weight applied to the normalised value (from PriorityConfig).
    contribution
        ``normalised * weight`` — the actual addend to the final score.
    reason_codes
        Machine-readable codes describing why this factor scored as it did.
    """

    name: str
    raw_value: object
    normalised: float
    weight: float
    contribution: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class PriorityResult:
    """The complete, transparent output of one scoring run.

    Attributes
    ----------
    incident_id
        ID of the scored Incident.
    score
        Final priority score in [0.0, 1.0].
    level
        Discrete band: CRITICAL / HIGH / MEDIUM / LOW.
    factors
        One FactorScore per scoring factor, in calculation order.
    reason_codes
        Deduplicated, sorted list of all reason codes across all factors.
        Suitable for display or downstream filtering.
    """

    incident_id: str
    score: float
    level: PriorityLevel
    factors: tuple[FactorScore, ...]
    reason_codes: tuple[str, ...]

    def factor(self, name: str) -> FactorScore | None:
        """Return the FactorScore for the given factor name, or None."""
        for f in self.factors:
            if f.name == name:
                return f
        return None
