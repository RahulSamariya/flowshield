"""ExtractionResult — the typed output of one citizen-report parse attempt.

This is the intermediate representation produced by CitizenReportParser.
It holds everything Granite (or the fallback) extracted from the raw text,
before deterministic validation turns it into an Incident + Evidence pair.

All fields are optional because a citizen may omit any detail.  The agent
uses what is present and records gaps in ``missing_fields``.

Field semantics
---------------
location_raw    Verbatim location string from the report ("near the school",
                "Main Bazaar road").  Never modified — used as-is for
                zone_id fallback when no canonical zone is available.

zone_id         Canonical zone identifier if the location could be mapped.
                None if the mapping is uncertain.

incident_type   Best-fit classification: "waterlogging", "road_blocked",
                "drain_blocked", "flash_flood", "building_flood", "unknown".

severity        Extracted severity hint: "low", "medium", "high", "critical".
                The agent re-validates this against water_depth_m rules.

water_depth_m   Numeric depth in metres, converted from feet/cm/inches if
                Granite detected a measurement in other units.

road_blocked    True if the report explicitly mentions a blocked road.

critical_facility  Name/type of any critical facility mentioned
                   ("school", "hospital", "shelter", None).

affected_population  Numeric estimate if mentioned ("about 200 people").

reported_at_raw  Verbatim time reference ("this morning", "2 hours ago").
                 Resolved to a datetime by the agent where possible.

raw_text        The original unmodified citizen report.

confidence      Granite's self-reported confidence 0.0–1.0.
                0.0 if the fallback extractor was used.

source          "granite" | "fallback"

missing_fields  Fields the extractor could not determine.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractionResult:
    """Typed output of one citizen-report parse attempt."""

    raw_text: str

    # location
    location_raw: str = ""
    zone_id: str | None = None
    city: str = ""

    # incident classification
    incident_type: str = "unknown"   # waterlogging | road_blocked | drain_blocked |
                                     # flash_flood  | building_flood | unknown
    severity: str = "low"            # low | medium | high | critical

    # measurements
    water_depth_m: float | None = None
    road_blocked: bool = False
    critical_facility: str | None = None  # "school" | "hospital" | "shelter" | None
    affected_population: int | None = None

    # temporal
    reported_at_raw: str = ""

    # meta
    confidence: float = 0.0
    source: str = "fallback"         # "granite" | "fallback"
    missing_fields: list[str] = field(default_factory=list)
    extraction_notes: str = ""
