"""RawEvent — the untyped dict that arrives at the engine boundary.

Every external signal (sensor ping, citizen report, drain sensor, etc.) is
first represented as a RawEvent before normalization.  This keeps the engine
boundary explicit: nothing typed enters the engine without passing through the
normalizer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RawEventType(StrEnum):
    """Vocabulary of known raw event kinds.

    The normalizer uses this to route each event to the correct Evidence fields.
    """

    RAINFALL = "rainfall"                   # Gauge / API rainfall reading
    WATERLOGGING = "waterlogging"           # Citizen / sensor waterlogging report
    DRAIN_BLOCKED = "drain_blocked"         # Drain blockage report
    WATER_LEVEL = "water_level"             # Standalone water-level reading
    ROAD_BLOCKED = "road_blocked"           # Road closure report
    RESOURCE_STATUS = "resource_status"     # Resource availability change
    INFRASTRUCTURE = "infrastructure"       # Asset / drain / pump status change


class RawEvent(BaseModel):
    """A single unvalidated event arriving at the system boundary.

    ``payload`` holds the raw fields exactly as received — no interpretation.
    ``event_type`` tells the normalizer how to map ``payload`` to Evidence.

    The model uses ``extra="allow"`` so callers can attach arbitrary debugging
    fields without breaking ingestion.
    """

    event_type: RawEventType
    city: str = Field(..., min_length=1, max_length=100)
    zone_id: str = Field(..., min_length=1, max_length=50)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="unknown", max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("city", "zone_id", "source", mode="before")
    @classmethod
    def strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    model_config = {"frozen": False, "extra": "allow"}
