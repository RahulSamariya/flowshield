"""SituationEngine — the main orchestrator.

Wires together all pipeline stages into a single ``process(event)`` call:

  RawEvent
      │
      ▼  normalizer
  Evidence (or None for resource/infra events)
      │
      ├──▶ ingestor   → updates ZoneStatus in SituationState
      ├──▶ detector   → creates / updates / resolves Incidents
      └──▶ history    → appends EngineRecord

  (RESOURCE_STATUS / INFRASTRUCTURE events)
      │
      ├──▶ resource_updater → updates Resource registry
      └──▶ history          → appends EngineRecord

The engine owns:
  - one SituationState per city
  - one flat incident registry  (zone_id → Incident)
  - one flat resource registry  (resource_id → Resource)
  - one HistoryStore

All registries are plain dicts — no ORM, no DB in V1.
"""

from __future__ import annotations

from src.engine.detector import Detector
from src.engine.history import EngineRecord, HistoryStore
from src.engine.ingestor import Ingestor
from src.engine.normalizer import EventNormalizer
from src.engine.resource_updater import ResourceUpdater
from src.models.event import RawEvent
from src.models.incident import Incident
from src.models.resource import Resource
from src.models.situation import SituationState


class SituationEngine:
    """Processes RawEvents and maintains live situation awareness.

    Parameters
    ----------
    city:
        City name for this engine instance.  All events must share this city.

    Example::

        engine = SituationEngine(city="Ahmedabad")
        # Pre-load resources
        for r in scenario_resources:
            engine.resources[r.id] = r
        # Feed events
        record = engine.process(raw_event)
    """

    def __init__(self, city: str) -> None:
        self.city = city.strip()
        self.state = SituationState(city=self.city)

        # zone_id → Incident  (one active incident per zone at a time)
        self.incidents: dict[str, Incident] = {}

        # resource_id → Resource
        self.resources: dict[str, Resource] = {}

        # append-only audit log
        self.history = HistoryStore()

        self._normalizer = EventNormalizer()
        self._ingestor = Ingestor()
        self._detector = Detector()
        self._resource_updater = ResourceUpdater()

    # ── public API ────────────────────────────────────────────────────────

    def process(self, event: RawEvent) -> EngineRecord:
        """Process one RawEvent and return the history record for this cycle."""
        if event.city != self.city:
            raise ValueError(
                f"Engine city is '{self.city}' but event city is '{event.city}'."
            )

        record = EngineRecord(
            raw_event_type=event.event_type,
            raw_event_payload=dict(event.payload),
            city=event.city,
            zone_id=event.zone_id,
            occurred_at=event.occurred_at,
        )

        # ── resource/infra events ─────────────────────────────────────────
        change = self._resource_updater.apply(event, self.resources)
        if change is not None:
            record.resource_id = change.resource_id
            record.resource_status_before = change.previous_status
            record.resource_status_after = change.new_status
            self.history.append(record)
            return record

        # ── evidence-producing events ─────────────────────────────────────
        evidence = self._normalizer.normalize(event)
        if evidence is None:
            # Unknown event type — record and skip.
            self.history.append(record)
            return record

        record.evidence_id = evidence.id

        # Capture severity before ingestion.
        existing_zone = self.state.zones.get(event.zone_id)
        record.zone_severity_before = (
            existing_zone.severity if existing_zone else None
        )

        # Stage 1 — ingest.
        zone = self._ingestor.apply(evidence, self.state)
        record.zone_severity_after = zone.severity

        # Stage 2 — detect incidents (track created/updated/resolved).
        previous_ids = {
            zid: inc.status
            for zid, inc in self.incidents.items()
        }
        self._detector.sync(self.state, self.incidents)

        for zid, inc in self.incidents.items():
            was = previous_ids.get(zid)
            if was is None:
                record.incidents_created.append(inc.id)
            elif was != inc.status:
                if inc.status == "resolved":
                    record.incidents_resolved.append(inc.id)
                else:
                    record.incidents_updated.append(inc.id)

        self.history.append(record)
        return record

    # ── convenience queries ───────────────────────────────────────────────

    def open_incidents(self) -> list[Incident]:
        """Return all open incidents sorted by risk_score descending."""
        from src.models.incident import IncidentStatus
        return sorted(
            [i for i in self.incidents.values() if i.status == IncidentStatus.OPEN],
            key=lambda i: i.risk_score,
            reverse=True,
        )

    def available_resources(self, resource_type: str | None = None) -> list[Resource]:
        """Return available resources, optionally filtered by type."""
        from src.models.resource import ResourceStatus
        result = [
            r for r in self.resources.values()
            if r.status == ResourceStatus.AVAILABLE
        ]
        if resource_type:
            result = [r for r in result if r.type == resource_type]
        return result
