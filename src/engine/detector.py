"""Detector — creates or updates Incidents from ZoneStatus changes.

The detector examines every zone in a SituationState and ensures that an open
Incident exists for every zone whose severity is above NORMAL.  It also
escalates or de-escalates existing incidents when the zone severity changes.

Incident creation rules
-----------------------
- NORMAL zone     → no incident (or resolves an existing open one)
- WATCH zone      → LOW incident (risk_score 0.1–0.3)
- WARNING zone    → MEDIUM or HIGH depending on population
- CRITICAL zone   → CRITICAL incident

Risk score formula (deterministic, no ML)
-----------------------------------------
score = clamp(
    (rainfall_weight * rainfall_norm)
    + (water_level_weight * wl_norm)
    + (population_weight * pop_norm)
    + (road_blocked_bonus),
    0.0, 1.0
)

Weights:  rainfall 0.4 | water_level 0.3 | population 0.2 | road_blocked 0.1
Norms:    rainfall  / 100.0  (100 mm/hr ≈ 1.0)
          water_lv  / 3.0    (3 m ≈ 1.0)
          population / 5000  (5000 people ≈ 1.0)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.models.incident import Incident, IncidentStatus, SeverityLevel
from src.models.situation import SituationState, ZoneSeverity, ZoneStatus

if TYPE_CHECKING:
    pass  # keep import clean

# ── weight constants ──────────────────────────────────────────────────────────
_W_RAIN = 0.40
_W_WL   = 0.30
_W_POP  = 0.20
_W_ROAD = 0.10

_NORM_RAIN = 100.0
_NORM_WL   = 3.0
_NORM_POP  = 5000.0

_SEVERITY_MAP: dict[ZoneSeverity, SeverityLevel] = {
    ZoneSeverity.WATCH:    SeverityLevel.LOW,
    ZoneSeverity.WARNING:  SeverityLevel.MEDIUM,
    ZoneSeverity.CRITICAL: SeverityLevel.CRITICAL,
}


def _risk_score(zone: ZoneStatus) -> float:
    rain_contrib = (
        min(zone.latest_rainfall_mm_hr / _NORM_RAIN, 1.0) * _W_RAIN
        if zone.latest_rainfall_mm_hr is not None else 0.0
    )
    wl_contrib = (
        min(zone.latest_water_level_m / _NORM_WL, 1.0) * _W_WL
        if zone.latest_water_level_m is not None else 0.0
    )
    pop_contrib = (
        min(zone.affected_population / _NORM_POP, 1.0) * _W_POP
        if zone.affected_population is not None else 0.0
    )
    road_contrib = _W_ROAD if zone.road_blocked else 0.0

    score = rain_contrib + wl_contrib + pop_contrib + road_contrib
    return round(min(max(score, 0.0), 1.0), 4)


def _incident_title(zone_id: str, severity: SeverityLevel) -> str:
    return f"[{severity.upper()}] Flood incident — zone {zone_id}"


class Detector:
    """Creates and maintains Incidents from the current SituationState.

    The incident registry is a ``dict[zone_id → Incident]`` passed in and
    mutated in place, keeping the detector stateless.

    Usage::

        incidents: dict[str, Incident] = {}
        detector = Detector()
        detector.sync(state, incidents)
    """

    def sync(
        self,
        state: SituationState,
        incidents: dict[str, Incident],
    ) -> list[Incident]:
        """Synchronise the incident registry with the current state.

        - Creates a new open incident for any zone newly above NORMAL.
        - Updates severity / risk_score for zones whose status changed.
        - Resolves the incident for any zone that returned to NORMAL.

        Returns the list of currently open incidents sorted by risk_score desc.
        """
        now = datetime.now(timezone.utc)

        for zone_id, zone in state.zones.items():
            existing = incidents.get(zone_id)

            if zone.severity == ZoneSeverity.NORMAL:
                # Zone is safe — resolve any open incident.
                if existing and existing.status == IncidentStatus.OPEN:
                    existing.status = IncidentStatus.RESOLVED
                    existing.resolved_at = now
                    existing.updated_at = now
                continue

            # Zone needs an incident.
            new_severity = _SEVERITY_MAP[zone.severity]
            new_score = _risk_score(zone)

            if existing is None or existing.status in (
                IncidentStatus.RESOLVED,
                IncidentStatus.CANCELLED,
            ):
                # Create fresh incident.
                incident = Incident(
                    city=state.city,
                    zone_id=zone_id,
                    severity=new_severity,
                    risk_score=new_score,
                    title=_incident_title(zone_id, new_severity),
                    description=(
                        f"Auto-detected from zone status. "
                        f"Rainfall: {zone.latest_rainfall_mm_hr} mm/hr, "
                        f"Water level: {zone.latest_water_level_m} m, "
                        f"Road blocked: {zone.road_blocked}."
                    ),
                    status=IncidentStatus.OPEN,
                )
                incidents[zone_id] = incident
            else:
                # Update existing open/assigned incident.
                existing.severity = new_severity
                existing.risk_score = new_score
                existing.title = _incident_title(zone_id, new_severity)
                existing.updated_at = now

        return sorted(
            [inc for inc in incidents.values() if inc.status == IncidentStatus.OPEN],
            key=lambda i: i.risk_score,
            reverse=True,
        )
