"""EventNormalizer — maps a RawEvent to a typed Evidence object.

This is the only place where raw field names from external systems are
translated to the canonical Evidence schema.  All other engine stages
work exclusively with Evidence.

Rules per event type
--------------------
RAINFALL        payload.rainfall_mm_hr  → Evidence.rainfall_mm_hr
WATERLOGGING    payload.water_level_m   → Evidence.water_level_m
                payload.affected_people → Evidence.affected_population
DRAIN_BLOCKED   sets road_blocked=True
                payload.water_level_m   → Evidence.water_level_m (optional)
WATER_LEVEL     payload.water_level_m   → Evidence.water_level_m
ROAD_BLOCKED    sets road_blocked=True
RESOURCE_STATUS does not produce Evidence (handled directly by ResourceUpdater)
INFRASTRUCTURE  does not produce Evidence (handled directly by ResourceUpdater)
"""

from __future__ import annotations

from src.models.event import RawEvent, RawEventType
from src.models.evidence import Evidence, EvidenceSource

# Map the free-text ``source`` field on RawEvent to a typed EvidenceSource.
_SOURCE_MAP: dict[str, EvidenceSource] = {
    "imd_api": EvidenceSource.IMD_API,
    "imd": EvidenceSource.IMD_API,
    "citizen": EvidenceSource.CITIZEN_REPORT,
    "citizen_report": EvidenceSource.CITIZEN_REPORT,
    "sensor": EvidenceSource.SENSOR,
    "satellite": EvidenceSource.SATELLITE,
    "mock": EvidenceSource.MOCK,
}


def _map_source(raw_source: str) -> EvidenceSource:
    return _SOURCE_MAP.get(raw_source.lower(), EvidenceSource.OTHER)


class NormalizationError(ValueError):
    """Raised when a RawEvent cannot be mapped to a valid Evidence."""


class EventNormalizer:
    """Converts a RawEvent into a canonical Evidence instance.

    ``normalize`` returns ``None`` for event types that do not produce
    Evidence (RESOURCE_STATUS, INFRASTRUCTURE).  The engine handles those
    directly via ResourceUpdater.

    Raises ``NormalizationError`` if the payload is structurally invalid for
    the declared event type.
    """

    def normalize(self, event: RawEvent) -> Evidence | None:
        """Return a typed Evidence, or None if the event type produces no Evidence."""
        handler = self._handlers.get(event.event_type)
        if handler is None:
            return None
        return handler(self, event)

    # ── per-type handlers ─────────────────────────────────────────────────

    def _rainfall(self, event: RawEvent) -> Evidence:
        mm = event.payload.get("rainfall_mm_hr")
        if mm is None:
            raise NormalizationError(
                f"RAINFALL event missing 'rainfall_mm_hr' in payload: {event.payload}"
            )
        try:
            mm = float(mm)
        except (TypeError, ValueError) as exc:
            raise NormalizationError(f"'rainfall_mm_hr' must be numeric: {mm}") from exc
        if mm < 0:
            raise NormalizationError(f"'rainfall_mm_hr' must be >= 0, got {mm}")
        return Evidence(
            city=event.city,
            zone_id=event.zone_id,
            source=_map_source(event.source),
            observed_at=event.occurred_at,
            rainfall_mm_hr=mm,
            raw=dict(event.payload),
        )

    def _waterlogging(self, event: RawEvent) -> Evidence:
        wl = event.payload.get("water_level_m")
        pop = event.payload.get("affected_people")
        # At least one of water_level_m or affected_people must be present.
        if wl is None and pop is None:
            raise NormalizationError(
                "WATERLOGGING event requires 'water_level_m' or 'affected_people' "
                f"in payload: {event.payload}"
            )
        kwargs: dict = dict(
            city=event.city,
            zone_id=event.zone_id,
            source=_map_source(event.source),
            observed_at=event.occurred_at,
            raw=dict(event.payload),
        )
        if wl is not None:
            kwargs["water_level_m"] = float(wl)
        if pop is not None:
            kwargs["affected_population"] = int(pop)
        return Evidence(**kwargs)

    def _drain_blocked(self, event: RawEvent) -> Evidence:
        kwargs: dict = dict(
            city=event.city,
            zone_id=event.zone_id,
            source=_map_source(event.source),
            observed_at=event.occurred_at,
            road_blocked=True,
            raw=dict(event.payload),
        )
        wl = event.payload.get("water_level_m")
        if wl is not None:
            kwargs["water_level_m"] = float(wl)
        return Evidence(**kwargs)

    def _water_level(self, event: RawEvent) -> Evidence:
        wl = event.payload.get("water_level_m")
        if wl is None:
            raise NormalizationError(
                f"WATER_LEVEL event missing 'water_level_m' in payload: {event.payload}"
            )
        return Evidence(
            city=event.city,
            zone_id=event.zone_id,
            source=_map_source(event.source),
            observed_at=event.occurred_at,
            water_level_m=float(wl),
            raw=dict(event.payload),
        )

    def _road_blocked(self, event: RawEvent) -> Evidence:
        return Evidence(
            city=event.city,
            zone_id=event.zone_id,
            source=_map_source(event.source),
            observed_at=event.occurred_at,
            road_blocked=True,
            raw=dict(event.payload),
        )

    # ── dispatch table ────────────────────────────────────────────────────

    _handlers: dict = {
        RawEventType.RAINFALL: _rainfall,
        RawEventType.WATERLOGGING: _waterlogging,
        RawEventType.DRAIN_BLOCKED: _drain_blocked,
        RawEventType.WATER_LEVEL: _water_level,
        RawEventType.ROAD_BLOCKED: _road_blocked,
        # RESOURCE_STATUS and INFRASTRUCTURE → None (handled elsewhere)
        RawEventType.RESOURCE_STATUS: None,
        RawEventType.INFRASTRUCTURE: None,
    }
