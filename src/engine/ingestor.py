"""Ingestor — updates SituationState from a single Evidence record.

The ingestor is the first pipeline stage after normalization.  It has one
job: merge new evidence into the live ZoneStatus map, applying the severity
classification rules.

Severity classification thresholds (deterministic, rule-based)
---------------------------------------------------------------
Rainfall (mm/hr):
  >= 64.5  → CRITICAL  (IMD very heavy rain)
  >= 35.5  → WARNING   (IMD heavy rain)
  >= 15.5  → WATCH     (IMD moderate rain)
  <  15.5  → NORMAL

Water level (m above normal):
  >= 2.0   → CRITICAL
  >= 1.0   → WARNING
  >= 0.5   → WATCH
  <  0.5   → NORMAL

Road blocked alone → minimum WATCH (unless higher severity already applies).

The worst severity across all signals wins for the zone.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.models.evidence import Evidence
from src.models.situation import SEVERITY_RANK, SituationState, ZoneSeverity, ZoneStatus

# ── thresholds ─────────────────────────────────────────────────────────────────

_RAINFALL_THRESHOLDS: list[tuple[float, ZoneSeverity]] = [
    (64.5, ZoneSeverity.CRITICAL),
    (35.5, ZoneSeverity.WARNING),
    (15.5, ZoneSeverity.WATCH),
    (0.0,  ZoneSeverity.NORMAL),
]

_WATER_LEVEL_THRESHOLDS: list[tuple[float, ZoneSeverity]] = [
    (2.0, ZoneSeverity.CRITICAL),
    (1.0, ZoneSeverity.WARNING),
    (0.5, ZoneSeverity.WATCH),
    (0.0, ZoneSeverity.NORMAL),
]


def _classify_rainfall(mm_hr: float) -> ZoneSeverity:
    for threshold, level in _RAINFALL_THRESHOLDS:
        if mm_hr >= threshold:
            return level
    return ZoneSeverity.NORMAL


def _classify_water_level(metres: float) -> ZoneSeverity:
    for threshold, level in _WATER_LEVEL_THRESHOLDS:
        if metres >= threshold:
            return level
    return ZoneSeverity.NORMAL


def _max_severity(*levels: ZoneSeverity) -> ZoneSeverity:
    return max(levels, key=lambda s: SEVERITY_RANK[s])


class Ingestor:
    """Merges one Evidence record into a SituationState.

    The ingestor is stateless — it operates on the SituationState passed in
    and mutates it in place.  This keeps it trivially testable.

    Usage::

        ingestor = Ingestor()
        ingestor.apply(evidence, state)
    """

    def apply(self, evidence: Evidence, state: SituationState) -> ZoneStatus:
        """Merge ``evidence`` into ``state``.

        Creates the ZoneStatus entry for the zone if it does not exist yet.
        Returns the (updated) ZoneStatus for the zone.
        """
        if state.city != evidence.city:
            raise ValueError(
                f"Evidence city '{evidence.city}' does not match "
                f"SituationState city '{state.city}'."
            )

        zone = state.zones.get(evidence.zone_id)
        if zone is None:
            zone = ZoneStatus(zone_id=evidence.zone_id)
            state.zones[evidence.zone_id] = zone

        # ── update measurements (keep latest non-None value) ──────────────
        if evidence.rainfall_mm_hr is not None:
            zone.latest_rainfall_mm_hr = evidence.rainfall_mm_hr
        if evidence.water_level_m is not None:
            zone.latest_water_level_m = evidence.water_level_m
        if evidence.road_blocked is not None:
            zone.road_blocked = evidence.road_blocked
        if evidence.affected_population is not None:
            zone.affected_population = evidence.affected_population

        zone.evidence_count += 1

        # ── recompute severity ────────────────────────────────────────────
        candidates: list[ZoneSeverity] = [ZoneSeverity.NORMAL]

        if zone.latest_rainfall_mm_hr is not None:
            candidates.append(_classify_rainfall(zone.latest_rainfall_mm_hr))
        if zone.latest_water_level_m is not None:
            candidates.append(_classify_water_level(zone.latest_water_level_m))
        if zone.road_blocked:
            candidates.append(ZoneSeverity.WATCH)

        zone.severity = _max_severity(*candidates)
        zone.last_updated = datetime.now(UTC)

        state.updated_at = datetime.now(UTC)
        return zone
