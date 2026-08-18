"""CitizenReportParser — extract structured data from a citizen flood report.

Two code paths
--------------
Granite path (online)
    Build a strict extraction prompt, call Granite, parse the JSON response.
    On any parse failure, fall back to the keyword extractor.

Fallback path (offline / Granite unavailable)
    A deterministic keyword extractor built on regex patterns.
    It covers the most common report patterns and is transparent about its
    limits (low confidence score, source="fallback").

Extraction prompt contract
--------------------------
Granite is given the report text and asked to return a single JSON object
matching the ExtractionResult schema.  It is explicitly told:

  MUST NOT invent measurements not present in the report.
  MUST NOT guess a zone_id unless the text contains a recognisable zone code.
  MUST convert non-SI units (feet, inches, cm) to metres.
  Confidence must reflect genuine certainty, not optimism.

Unit conversions applied by the fallback
-----------------------------------------
  1 foot  = 0.3048 m
  1 inch  = 0.0254 m
  1 cm    = 0.01   m
"""

from __future__ import annotations

import json
import logging
import re

from src.agents.extraction_result import ExtractionResult
from src.reasoning.granite_client import GraniteClient, GraniteUnavailable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit-conversion helpers
# ---------------------------------------------------------------------------

_FOOT_TO_M  = 0.3048
_INCH_TO_M  = 0.0254
_CM_TO_M    = 0.01

_DEPTH_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:feet|foot|ft)\b", re.I), _FOOT_TO_M),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:inches?|in)\b", re.I), _INCH_TO_M),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:cm|centimetres?|centimeters?)\b", re.I), _CM_TO_M),
    (re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)\b", re.I), 1.0),
]

# Severity cues
_CRITICAL_WORDS = re.compile(
    r"\b(neck[- ]deep|chest[- ]deep|swept|drowning|danger|emergency|rescue|waist[- ]deep)\b",
    re.I,
)
_HIGH_WORDS = re.compile(
    r"\b(knee[- ]deep|thigh[- ]deep|flood|severe|overflowing|burst)\b", re.I
)
_MEDIUM_WORDS = re.compile(
    r"\b(waterlogging|calf[- ]deep|ankle[- ]deep|stagnant|blocked|accumulated)\b", re.I
)

# Facility cues
_FACILITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bhospital\b", re.I), "hospital"),
    (re.compile(r"\bschool\b", re.I), "school"),
    (re.compile(r"\bshelter\b", re.I), "shelter"),
    (re.compile(r"\bfire station\b", re.I), "fire_station"),
    (re.compile(r"\bcollege\b", re.I), "school"),
]

# Road-blocked cues
_ROAD_BLOCKED = re.compile(
    r"\b(road blocked|road is blocked|road closed|traffic stopped|"
    r"unable to pass|impassable|blocked road)\b",
    re.I,
)


def _extract_depth(text: str) -> float | None:
    """Return depth in metres from first matching unit pattern, or None."""
    for pattern, factor in _DEPTH_PATTERNS:
        m = pattern.search(text)
        if m:
            return round(float(m.group(1)) * factor, 3)
    return None


def _extract_facility(text: str) -> str | None:
    for pattern, name in _FACILITY_PATTERNS:
        if pattern.search(text):
            return name
    return None


def _extract_severity_from_text(text: str, depth_m: float | None) -> str:
    """Rule-based severity from keywords + depth thresholds."""
    if _CRITICAL_WORDS.search(text):
        return "critical"
    # depth-based (same thresholds as ingestor.py)
    if depth_m is not None:
        if depth_m >= 2.0:
            return "critical"
        if depth_m >= 1.0:
            return "high"
        if depth_m >= 0.5:
            return "medium"
    if _HIGH_WORDS.search(text):
        return "high"
    if _MEDIUM_WORDS.search(text):
        return "medium"
    return "low"


def _extract_incident_type(text: str) -> str:
    lower = text.lower()
    if re.search(r"\bdrain\b.*\bblock", lower) or re.search(r"\bblock.*\bdrain", lower):
        return "drain_blocked"
    if _ROAD_BLOCKED.search(text):
        return "road_blocked"
    if re.search(r"\bflash\s*flood\b", lower):
        return "flash_flood"
    if re.search(r"\bbuilding|house|flat|apartment\b", lower):
        return "building_flood"
    if re.search(r"\bwater\b", lower):
        return "waterlogging"
    return "unknown"


def _extract_population(text: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:people|persons?|families|residents|households?)", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _keyword_fallback(text: str, city: str, zone_id: str | None) -> ExtractionResult:
    """Pure-regex extractor. Always succeeds; confidence is low."""
    depth = _extract_depth(text)
    road = bool(_ROAD_BLOCKED.search(text))
    facility = _extract_facility(text)
    severity = _extract_severity_from_text(text, depth)
    inc_type = _extract_incident_type(text)
    population = _extract_population(text)

    missing: list[str] = []
    if depth is None:
        missing.append("water_depth_m")
    if not zone_id:
        missing.append("zone_id")
    if not facility:
        missing.append("critical_facility")
    if population is None:
        missing.append("affected_population")

    return ExtractionResult(
        raw_text=text,
        location_raw=text[:80],
        zone_id=zone_id,
        city=city,
        incident_type=inc_type,
        severity=severity,
        water_depth_m=depth,
        road_blocked=road,
        critical_facility=facility,
        affected_population=population,
        reported_at_raw="",
        confidence=0.40,
        source="fallback",
        missing_fields=missing,
        extraction_notes="Keyword extractor used (Granite unavailable).",
    )


# ---------------------------------------------------------------------------
# Granite extraction prompt
# ---------------------------------------------------------------------------

_SYSTEM_PREAMBLE = """\
You are a flood emergency data extraction assistant.
Your ONLY job is to extract structured information from a citizen flood report.

STRICT RULES:
- Extract ONLY what is explicitly stated. Do NOT invent or assume measurements.
- Convert depth/level units to metres: 1 foot=0.3048 m, 1 inch=0.0254 m, 1 cm=0.01 m.
- severity must be one of: low | medium | high | critical
- incident_type must be one of: waterlogging | road_blocked | drain_blocked |
  flash_flood | building_flood | unknown
- critical_facility must be one of: hospital | school | shelter | fire_station | null
- zone_id: extract ONLY if a ward/zone code is explicitly stated; otherwise null.
- confidence: your genuine certainty in the extraction (0.0 to 1.0).
- missing_fields: list field names you could not determine from the text.
- Do NOT recommend actions, resources, or priorities.
"""

_OUTPUT_SCHEMA = """\
Respond with ONLY this JSON (no markdown, no extra text):
{
  "location_raw": "<verbatim location string from report, or empty string>",
  "zone_id": "<ward/zone code if explicitly in text, else null>",
  "incident_type": "<waterlogging|road_blocked|drain_blocked|flash_flood|building_flood|unknown>",
  "severity": "<low|medium|high|critical>",
  "water_depth_m": <depth in metres as a number, or null>,
  "road_blocked": <true|false>,
  "critical_facility": "<hospital|school|shelter|fire_station|null>",
  "affected_population": <integer or null>,
  "reported_at_raw": "<verbatim time reference or empty string>",
  "confidence": <0.0 to 1.0>,
  "missing_fields": ["<field1>", ...]
}
<|end|>"""


def _build_extraction_prompt(report_text: str, city: str) -> str:
    return (
        f"{_SYSTEM_PREAMBLE}\n"
        f"{'─' * 60}\n"
        f"City context: {city}\n\n"
        f"CITIZEN REPORT:\n\"{report_text}\"\n\n"
        f"{_OUTPUT_SCHEMA}"
    )


def _parse_granite_response(raw: str, report_text: str, city: str) -> ExtractionResult | None:
    """Parse Granite JSON into ExtractionResult.  Returns None on any failure."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return ExtractionResult(
            raw_text=report_text,
            location_raw=str(data.get("location_raw", "")),
            zone_id=data.get("zone_id") or None,
            city=city,
            incident_type=str(data.get("incident_type", "unknown")),
            severity=str(data.get("severity", "low")),
            water_depth_m=(
                float(data["water_depth_m"]) if data.get("water_depth_m") is not None else None
            ),
            road_blocked=bool(data.get("road_blocked", False)),
            critical_facility=data.get("critical_facility") or None,
            affected_population=(
                int(data["affected_population"])
                if data.get("affected_population") is not None else None
            ),
            reported_at_raw=str(data.get("reported_at_raw", "")),
            confidence=float(data.get("confidence", 0.5)),
            source="granite",
            missing_fields=list(data.get("missing_fields", [])),
            extraction_notes="Extracted by Granite.",
        )
    except (TypeError, ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Public parser class
# ---------------------------------------------------------------------------

class CitizenReportParser:
    """Extracts structured data from a citizen flood report.

    Tries Granite first; falls back to the keyword extractor if unavailable
    or if the response cannot be parsed.

    Usage::

        parser = CitizenReportParser(city="Ahmedabad")
        result = parser.parse("Water near school, 2 feet deep, road blocked.")
    """

    def __init__(self, city: str, client: GraniteClient | None = None) -> None:
        self.city = city.strip()
        self._client = client or GraniteClient()

    def parse(self, report_text: str, zone_id_hint: str | None = None) -> ExtractionResult:
        """Parse a raw citizen report.  Never raises."""
        text = report_text.strip()
        prompt = _build_extraction_prompt(text, self.city)
        try:
            raw = self._client.generate(prompt)
            result = _parse_granite_response(raw, text, self.city)
            if result is not None:
                if zone_id_hint and not result.zone_id:
                    result.zone_id = zone_id_hint
                return result
            logger.warning("Granite response unparseable for citizen report; using fallback.")
        except GraniteUnavailable as exc:
            logger.warning("Granite unavailable for citizen report: %s", exc)
        return _keyword_fallback(text, self.city, zone_id_hint)
