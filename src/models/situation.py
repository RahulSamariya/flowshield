"""SituationState model — aggregated ground truth for one city at one moment.

A SituationState is the output of the ingestor stage.  It summarises all
current Evidence into a per-zone severity matrix.  It is the single source of
truth consumed by every downstream pipeline stage.

Flow position:
  Evidence → **SituationState** → Incidents → Priority → Action → Outcome
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class ZoneSeverity(StrEnum):
    """Ordered severity levels for a zone.

    Levels are ordered: NORMAL < WATCH < WARNING < CRITICAL.
    Use ``ZoneSeverity`` comparisons via string ordering or convert to int with
    ``SEVERITY_RANK[level]``.
    """

    NORMAL = "normal"
    WATCH = "watch"
    WARNING = "warning"
    CRITICAL = "critical"


#: Numeric rank for severity comparison (higher = more severe).
SEVERITY_RANK: dict[ZoneSeverity, int] = {
    ZoneSeverity.NORMAL: 0,
    ZoneSeverity.WATCH: 1,
    ZoneSeverity.WARNING: 2,
    ZoneSeverity.CRITICAL: 3,
}


class ZoneStatus(BaseModel):
    """Current flood status for a single zone within a city.

    Computed by the ingestor from one or more Evidence records.  All numeric
    fields are optional because a zone may be in a city that has no rainfall
    sensors — its severity may still be elevated via citizen reports.
    """

    zone_id: str = Field(..., min_length=1, max_length=50)
    severity: ZoneSeverity = Field(
        default=ZoneSeverity.NORMAL,
        description="Current severity classification for this zone.",
    )
    latest_rainfall_mm_hr: float | None = Field(
        default=None,
        ge=0,
        description="Most recent rainfall reading for this zone.",
    )
    latest_water_level_m: float | None = Field(
        default=None,
        ge=0,
        description="Most recent water-level reading for this zone.",
    )
    road_blocked: bool = Field(
        default=False,
        description="True if any current evidence indicates a blocked road.",
    )
    affected_population: int | None = Field(
        default=None,
        ge=0,
        description="Latest estimated affected population count.",
    )
    evidence_count: int = Field(
        default=0,
        ge=0,
        description="Number of Evidence records that contributed to this status.",
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the last update to this zone status.",
    )

    model_config = {"frozen": False, "extra": "forbid"}


class SituationState(BaseModel):
    """Aggregated flood situation for one city at one point in time.

    ``zones`` is a mapping of ``zone_id → ZoneStatus``.  An empty dict is
    valid (no data yet for this city).

    The ``overall_severity`` is a read-only derived property — the highest
    severity level across all zones.

    Example::

        state = SituationState(city="Surat")
        state.zones["SUR-Z01"] = ZoneStatus(
            zone_id="SUR-Z01",
            severity=ZoneSeverity.WARNING,
            latest_rainfall_mm_hr=38.0,
        )
        assert state.overall_severity == ZoneSeverity.WARNING
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    city: str = Field(..., min_length=1, max_length=100)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    zones: dict[str, ZoneStatus] = Field(
        default_factory=dict,
        description="Mapping of zone_id to its current status.",
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("city", mode="before")
    @classmethod
    def strip_city(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def zone_keys_match_ids(self) -> "SituationState":
        """Dict keys must match the embedded zone_id."""
        for key, zone in self.zones.items():
            if key != zone.zone_id:
                raise ValueError(
                    f"Zone dict key '{key}' does not match zone.zone_id '{zone.zone_id}'."
                )
        return self

    # ── derived property ──────────────────────────────────────────────────

    @property
    def overall_severity(self) -> ZoneSeverity:
        """Highest severity level across all zones; NORMAL if no zones."""
        if not self.zones:
            return ZoneSeverity.NORMAL
        return max(
            (z.severity for z in self.zones.values()),
            key=lambda s: SEVERITY_RANK[s],
        )

    model_config = {"frozen": False, "extra": "forbid"}
