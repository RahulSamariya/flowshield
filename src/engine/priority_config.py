"""Priority configuration — all weights and normalisation constants in one place.

To change scoring behaviour, create a ``PriorityConfig`` instance with custom
values and pass it to ``IncidentPriorityEngine.score()``.
The ``DEFAULT_CONFIG`` is used when no config is supplied.

Factor weights (must sum to 1.0 for the final score to stay in [0, 1])
-----------------------------------------------------------------------
SEVERITY            0.30   — base severity of the flood event
CRITICAL_FACILITY   0.20   — exposure of hospitals, fire stations, shelters
ROAD_DISRUPTION     0.15   — primary road blocked; impedes emergency access
POPULATION_IMPACT   0.20   — number of directly affected residents
RESPONSE_DEADLINE   0.10   — urgency derived from hours remaining to act
INFRA_DEPENDENCY    0.05   — dependency on shared infrastructure at risk

Normalisation references
------------------------
population_norm          5000   people  → contribution = 1.0
deadline_critical_hrs    1.0    hours   → 1.0  (< 1 h = maximum urgency)
deadline_low_hrs         24.0   hours   → 0.0  (> 24 h = no time pressure)
infra_dependency_max     5      assets  → 1.0  (5+ shared assets)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PriorityConfig:
    """Immutable weight + normalisation configuration.

    Weights must sum to 1.0.  A ``ValueError`` is raised on construction if
    they do not (within a 1e-6 tolerance).

    All normalisation references control what raw value maps to a contribution
    of 1.0 for that factor.
    """

    # ── factor weights ────────────────────────────────────────────────────
    weight_severity: float            = 0.30
    weight_critical_facility: float   = 0.20
    weight_road_disruption: float     = 0.15
    weight_population_impact: float   = 0.20
    weight_response_deadline: float   = 0.10
    weight_infra_dependency: float    = 0.05

    # ── severity base scores (0–1 per level) ──────────────────────────────
    severity_score_low: float      = 0.20
    severity_score_medium: float   = 0.45
    severity_score_high: float     = 0.70
    severity_score_critical: float = 1.00

    # ── normalisation references ───────────────────────────────────────────
    population_norm: float         = 5000.0   # people → contribution = 1.0
    deadline_critical_hrs: float   = 1.0      # hours remaining → max urgency
    deadline_low_hrs: float        = 24.0     # hours remaining → zero urgency
    infra_dependency_max: int      = 5        # shared assets → contribution = 1.0

    def __post_init__(self) -> None:
        total = (
            self.weight_severity
            + self.weight_critical_facility
            + self.weight_road_disruption
            + self.weight_population_impact
            + self.weight_response_deadline
            + self.weight_infra_dependency
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"PriorityConfig weights must sum to 1.0, got {total:.6f}. "
                "Adjust individual weights so they sum to exactly 1.0."
            )
        if self.deadline_critical_hrs >= self.deadline_low_hrs:
            raise ValueError(
                "deadline_critical_hrs must be strictly less than deadline_low_hrs."
            )


#: Default configuration — used when no config is passed to the engine.
DEFAULT_CONFIG = PriorityConfig()
