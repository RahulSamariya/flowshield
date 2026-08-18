"""Evidence model — a single raw signal ingested from any source.

Evidence is the entry point of the permanent flow:
  Evidence → SituationState → Incidents → Priority → Action → Outcome

Fields are intentionally nullable so that partial observations are valid.
The ``raw`` field preserves the full original payload without loss.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class EvidenceSource(StrEnum):
    """Known evidence producers.

    Open-ended by design: use ``EvidenceSource.OTHER`` for anything not yet
    classified, or extend the enum in future versions.
    """

    IMD_API = "imd_api"           # India Meteorological Department feed
    CITIZEN_REPORT = "citizen_report"  # Mobile / web submission
    SENSOR = "sensor"             # IoT water-level / rain gauge
    SATELLITE = "satellite"       # Remote-sensing derived
    MOCK = "mock"                 # Synthetic data for testing / demo
    OTHER = "other"


class Evidence(BaseModel):
    """A single, timestamped observation from one source about one zone.

    Observations are intentionally minimal: they record *what was seen*, not
    what it means.  Interpretation happens in the pipeline (ingestor.py).

    All numeric fields are optional because not every source provides every
    measurement.  Use ``model_validate`` with a dict or ``Evidence(**kwargs)``
    to create instances.

    Example::

        ev = Evidence(
            city="Ahmedabad",
            zone_id="AMC-W07",
            source=EvidenceSource.IMD_API,
            rainfall_mm_hr=45.2,
        )
    """

    # ── identity ──────────────────────────────────────────────────────────
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier (UUID4 by default).",
    )

    # ── provenance ────────────────────────────────────────────────────────
    city: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="City name as free text — not hardcoded to any city.",
    )
    zone_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Zone / ward identifier within the city.",
    )
    source: EvidenceSource = Field(
        ...,
        description="Which system or actor produced this observation.",
    )
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of the observation (not ingestion time).",
    )

    # ── measurements (all optional — partial observations are valid) ───────
    rainfall_mm_hr: float | None = Field(
        default=None,
        ge=0,
        description="Rainfall rate in millimetres per hour.",
    )
    water_level_m: float | None = Field(
        default=None,
        ge=0,
        description="Measured water level in metres above normal.",
    )
    road_blocked: bool | None = Field(
        default=None,
        description="True if the zone's primary road is reported blocked.",
    )
    affected_population: int | None = Field(
        default=None,
        ge=0,
        description="Estimated number of people directly affected.",
    )

    # ── raw payload ───────────────────────────────────────────────────────
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Original payload preserved verbatim for audit / replay.",
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("city", "zone_id", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def at_least_one_measurement(self) -> "Evidence":
        """Reject evidence that carries no measurement at all."""
        has_data = any(
            v is not None
            for v in (
                self.rainfall_mm_hr,
                self.water_level_m,
                self.road_blocked,
                self.affected_population,
            )
        )
        if not has_data:
            raise ValueError(
                "Evidence must contain at least one measurement "
                "(rainfall_mm_hr, water_level_m, road_blocked, or affected_population)."
            )
        return self

    model_config = {"frozen": False, "extra": "forbid"}
