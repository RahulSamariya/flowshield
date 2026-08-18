"""CitizenIncidentAgent — converts a citizen flood report into a validated Incident.

Responsibilities
----------------
1. Call CitizenReportParser to extract structured data (via Granite or fallback).
2. Validate and clamp all extracted fields.
3. Compute a deterministic severity and risk_score from the extraction.
4. Construct a validated Evidence object (source=CITIZEN_REPORT).
5. Construct a validated Incident object.
6. Return an AgentResult containing both, plus the raw ExtractionResult.

What this agent MUST NOT do
----------------------------
- Assign resources.
- Dispatch actions.
- Modify any existing incident.
- Access zone registries, resource inventories, or routing data.
- Make decisions beyond producing a single Incident + Evidence pair.

Severity classification rules (deterministic, same thresholds as ingestor.py)
---------------------------------------------------------------------
water_depth_m >= 2.0   → CRITICAL
water_depth_m >= 1.0   → HIGH
water_depth_m >= 0.5   → MEDIUM
water_depth_m < 0.5    → LOW
No depth + text cues   → see _severity_from_extraction()

Risk score formula (mirrors detector.py weights)
------------------------------------------------
score = 0.40 * min(water_depth_m / 3.0, 1.0)    [if depth known]
      + 0.20 * 1.0 (if critical_facility)
      + 0.15 * 1.0 (if road_blocked)
      + 0.20 * min(population / 5000, 1.0)       [if population known]
      + 0.05 * severity_bonus                    [critical=1.0, high=0.7, medium=0.4, low=0.1]
clamped to [0.0, 1.0]

Zone-ID fallback
----------------
If no zone_id was extracted and no hint was provided, the agent uses
``UNKNOWN-{city}`` as the zone_id and records it in warnings.
Callers should resolve zone_id before feeding the incident downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.agents.citizen_report_parser import CitizenReportParser
from src.agents.extraction_result import ExtractionResult
from src.models.evidence import Evidence, EvidenceSource
from src.models.incident import Incident, IncidentStatus, SeverityLevel
from src.reasoning.granite_client import GraniteClient

# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Output of one CitizenIncidentAgent.process() call.

    Attributes
    ----------
    incident
        The validated Incident object.  Always present on success.
    evidence
        The validated Evidence object derived from the same report.
    extraction
        The raw ExtractionResult (intermediate representation).
    success
        True if a valid Incident was produced.
    warnings
        Non-fatal issues: low confidence, missing zone_id, clamped values, etc.
    errors
        Fatal issues that prevented Incident creation.  If non-empty,
        ``incident`` is None.
    """
    incident: Incident | None
    evidence: Evidence | None
    extraction: ExtractionResult
    success: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Severity / risk helpers
# ---------------------------------------------------------------------------

_SEVERITY_BONUS: dict[str, float] = {
    "critical": 1.0,
    "high":     0.7,
    "medium":   0.4,
    "low":      0.1,
}

_VALID_SEVERITY = {"low", "medium", "high", "critical"}
_VALID_INCIDENT_TYPES = {
    "waterlogging", "road_blocked", "drain_blocked",
    "flash_flood", "building_flood", "unknown",
}

_DEPTH_THRESHOLDS: list[tuple[float, str]] = [
    (2.0, "critical"),
    (1.0, "high"),
    (0.5, "medium"),
    (0.0, "low"),
]


def _severity_from_extraction(ext: ExtractionResult) -> SeverityLevel:
    """Deterministic severity. Depth thresholds override Granite's suggestion."""
    if ext.water_depth_m is not None:
        for threshold, level in _DEPTH_THRESHOLDS:
            if ext.water_depth_m >= threshold:
                return SeverityLevel(level)
    # No depth: accept Granite/fallback suggestion if valid
    sev = ext.severity.lower() if ext.severity else "low"
    if sev not in _VALID_SEVERITY:
        sev = "low"
    return SeverityLevel(sev)


def _risk_score(ext: ExtractionResult, severity: SeverityLevel) -> float:
    depth_contrib = (
        min(ext.water_depth_m / 3.0, 1.0) * 0.40
        if ext.water_depth_m is not None else 0.0
    )
    facility_contrib = 0.20 if ext.critical_facility else 0.0
    road_contrib = 0.15 if ext.road_blocked else 0.0
    pop_contrib = (
        min(ext.affected_population / 5000.0, 1.0) * 0.20
        if ext.affected_population is not None else 0.0
    )
    sev_bonus = _SEVERITY_BONUS.get(severity, 0.1) * 0.05

    return round(
        min(depth_contrib + facility_contrib + road_contrib + pop_contrib + sev_bonus, 1.0), 4
    )


def _build_title(ext: ExtractionResult, severity: SeverityLevel) -> str:
    parts: list[str] = [f"[{severity.upper()}]"]
    inc_type = ext.incident_type if ext.incident_type in _VALID_INCIDENT_TYPES else "waterlogging"
    parts.append(inc_type.replace("_", " ").title())
    if ext.location_raw:
        loc = ext.location_raw[:60].strip()
        parts.append(f"- {loc}")
    return " ".join(parts)[:200]


def _build_description(ext: ExtractionResult) -> str:
    lines: list[str] = [f"Citizen report: {ext.raw_text[:500]}"]
    if ext.water_depth_m is not None:
        lines.append(f"Water depth: {ext.water_depth_m:.2f} m")
    if ext.road_blocked:
        lines.append("Road blocked: yes")
    if ext.critical_facility:
        lines.append(f"Critical facility nearby: {ext.critical_facility}")
    if ext.affected_population:
        lines.append(f"Estimated affected people: {ext.affected_population}")
    if ext.reported_at_raw:
        lines.append(f"Reported at: {ext.reported_at_raw}")
    lines.append(f"Extraction source: {ext.source} (confidence {ext.confidence:.2f})")
    return "\n".join(lines)[:2000]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class CitizenIncidentAgent:
    """Converts a citizen text report into a validated Incident + Evidence pair.

    This agent has NO authority over resources, actions, or routing.
    It only produces an Incident for downstream pipeline stages.

    Usage::

        agent = CitizenIncidentAgent(city="Ahmedabad")
        result = agent.process(
            report="Water is 2 feet near the school, road blocked.",
            zone_id_hint="W12-N",
        )
        if result.success:
            print(result.incident)
    """

    def __init__(
        self,
        city: str,
        client: GraniteClient | None = None,
        low_confidence_threshold: float = 0.35,
    ) -> None:
        self.city = city.strip()
        self.low_confidence_threshold = low_confidence_threshold
        self._parser = CitizenReportParser(city=self.city, client=client)

    def process(
        self,
        report: str,
        zone_id_hint: str | None = None,
    ) -> AgentResult:
        """Parse ``report`` and return an AgentResult with Incident + Evidence.

        Parameters
        ----------
        report:
            Raw citizen text.  No length restriction, but practical reports
            should be under 1000 characters.
        zone_id_hint:
            Optional known zone_id for this report (e.g. from the submission
            form's location picker).  Used when Granite cannot extract one.

        Returns
        -------
        AgentResult
            Always returned — never raises.  Check ``result.success``.
        """
        if not report or not report.strip():
            return AgentResult(
                incident=None,
                evidence=None,
                extraction=ExtractionResult(raw_text=report or ""),
                success=False,
                errors=["Empty report — nothing to process."],
            )

        ext = self._parser.parse(report.strip(), zone_id_hint=zone_id_hint)
        warnings: list[str] = []
        errors: list[str] = []

        # ── zone_id ───────────────────────────────────────────────────────
        zone_id = ext.zone_id or zone_id_hint
        if not zone_id:
            zone_id = f"UNKNOWN-{self.city}"
            warnings.append(
                f"zone_id could not be extracted. Using placeholder '{zone_id}'. "
                "Resolve before routing to the engine."
            )

        # ── confidence ────────────────────────────────────────────────────
        if ext.confidence < self.low_confidence_threshold:
            warnings.append(
                f"Low extraction confidence ({ext.confidence:.2f}). "
                "Manual review recommended."
            )

        # ── severity + risk_score ─────────────────────────────────────────
        severity = _severity_from_extraction(ext)
        risk_score = _risk_score(ext, severity)

        # ── build Evidence ────────────────────────────────────────────────
        try:
            evidence = Evidence(
                city=self.city,
                zone_id=zone_id,
                source=EvidenceSource.CITIZEN_REPORT,
                observed_at=datetime.now(UTC),
                rainfall_mm_hr=None,
                water_level_m=ext.water_depth_m,
                road_blocked=ext.road_blocked,
                affected_population=ext.affected_population,
                raw={
                    "original_report": ext.raw_text,
                    "extraction_source": ext.source,
                    "confidence": ext.confidence,
                    "incident_type": ext.incident_type,
                    "critical_facility": ext.critical_facility,
                },
            )
        except Exception as exc:
            errors.append(f"Evidence validation failed: {exc}")
            return AgentResult(
                incident=None,
                evidence=None,
                extraction=ext,
                success=False,
                warnings=warnings,
                errors=errors,
            )

        # ── build Incident ────────────────────────────────────────────────
        try:
            incident = Incident(
                city=self.city,
                zone_id=zone_id,
                severity=severity,
                risk_score=risk_score,
                title=_build_title(ext, severity),
                description=_build_description(ext),
                status=IncidentStatus.OPEN,
                evidence_ids=[evidence.id],
            )
        except Exception as exc:
            errors.append(f"Incident validation failed: {exc}")
            return AgentResult(
                incident=None,
                evidence=evidence,
                extraction=ext,
                success=False,
                warnings=warnings,
                errors=errors,
            )

        return AgentResult(
            incident=incident,
            evidence=evidence,
            extraction=ext,
            success=True,
            warnings=warnings,
            errors=errors,
        )
