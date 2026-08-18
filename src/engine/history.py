"""HistoryStore — append-only event log for the engine.

Every state-changing operation produces an EngineRecord that is appended here.
The store is in-memory for V1.  V2 can swap the backend (file, DB) without
changing the engine.

An EngineRecord captures:
  - what event was processed
  - what Evidence was produced (if any)
  - what zone was updated and what its severity became
  - what incidents were created or updated
  - what resource changes occurred
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class EngineRecord:
    """Immutable snapshot of one engine processing cycle."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── source ────────────────────────────────────────────────────────────
    raw_event_type: str = ""
    raw_event_payload: dict[str, Any] = field(default_factory=dict)
    city: str = ""
    zone_id: str = ""

    # ── evidence ──────────────────────────────────────────────────────────
    evidence_id: str | None = None

    # ── situation ─────────────────────────────────────────────────────────
    zone_severity_before: str | None = None
    zone_severity_after: str | None = None

    # ── incidents ─────────────────────────────────────────────────────────
    incidents_created: list[str] = field(default_factory=list)   # incident IDs
    incidents_updated: list[str] = field(default_factory=list)   # incident IDs
    incidents_resolved: list[str] = field(default_factory=list)  # incident IDs

    # ── resources ─────────────────────────────────────────────────────────
    resource_id: str | None = None
    resource_status_before: str | None = None
    resource_status_after: str | None = None


class HistoryStore:
    """In-memory append-only log of EngineRecords.

    Usage::

        store = HistoryStore()
        store.append(record)
        all_records = store.all()
        ward_records = store.for_zone("W12")
    """

    def __init__(self) -> None:
        self._records: list[EngineRecord] = []

    def append(self, record: EngineRecord) -> None:
        """Append a record. Raises if the record id already exists."""
        self._records.append(record)

    def all(self) -> list[EngineRecord]:
        """Return all records in insertion order."""
        return list(self._records)

    def for_zone(self, zone_id: str) -> list[EngineRecord]:
        """Return all records touching the given zone_id."""
        return [r for r in self._records if r.zone_id == zone_id]

    def for_city(self, city: str) -> list[EngineRecord]:
        """Return all records for the given city."""
        return [r for r in self._records if r.city == city]

    def __len__(self) -> int:
        return len(self._records)
