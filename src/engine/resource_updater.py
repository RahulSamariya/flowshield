"""ResourceUpdater — applies resource-status changes from RawEvents.

Handles two RawEventTypes that don't produce Evidence:
  - RESOURCE_STATUS   payload: {"resource_id": str, "status": str, "zone_id": str|None}
  - INFRASTRUCTURE    payload: {"asset_id": str, "blocked": bool, "zone_id": str}

The updater mutates the resource registry in place and returns a change record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.models.event import RawEvent, RawEventType
from src.models.resource import Resource, ResourceStatus


@dataclass(frozen=True)
class ResourceChange:
    """A record of what changed on a resource."""
    resource_id: str
    previous_status: ResourceStatus
    new_status: ResourceStatus
    previous_zone: str | None
    new_zone: str | None
    occurred_at: datetime


class ResourceUpdater:
    """Applies resource-status changes from RawEvents.

    The resource registry is ``dict[resource_id → Resource]``.

    Usage::

        updater = ResourceUpdater()
        change = updater.apply(event, resources)
    """

    def apply(
        self,
        event: RawEvent,
        resources: dict[str, Resource],
    ) -> ResourceChange | None:
        """Apply the event to the resource registry.

        Returns a ResourceChange if a resource was modified, else None.
        """
        if event.event_type == RawEventType.RESOURCE_STATUS:
            return self._handle_resource_status(event, resources)
        if event.event_type == RawEventType.INFRASTRUCTURE:
            return self._handle_infrastructure(event, resources)
        return None

    def _handle_resource_status(
        self, event: RawEvent, resources: dict[str, Resource]
    ) -> ResourceChange | None:
        rid = event.payload.get("resource_id")
        if not rid:
            return None
        resource = resources.get(str(rid))
        if resource is None:
            return None

        new_status_raw = event.payload.get("status")
        new_zone = event.payload.get("zone_id")

        try:
            new_status = ResourceStatus(str(new_status_raw).lower())
        except ValueError:
            return None

        prev_status = resource.status
        prev_zone = resource.current_zone_id

        resource.status = new_status
        if new_zone is not None:
            resource.current_zone_id = str(new_zone) if new_zone else None
        elif new_status != ResourceStatus.DEPLOYED:
            # Non-deployed resources don't need a current zone.
            pass
        resource.updated_at = datetime.now(UTC)

        return ResourceChange(
            resource_id=rid,
            previous_status=prev_status,
            new_status=new_status,
            previous_zone=prev_zone,
            new_zone=resource.current_zone_id,
            occurred_at=event.occurred_at,
        )

    def _handle_infrastructure(
        self, event: RawEvent, resources: dict[str, Resource]
    ) -> ResourceChange | None:
        # Infrastructure events mark a drain/pump as unavailable.
        asset_id = event.payload.get("asset_id")
        blocked = event.payload.get("blocked", False)
        if not asset_id:
            return None
        resource = resources.get(str(asset_id))
        if resource is None:
            return None

        prev_status = resource.status
        new_status = ResourceStatus.UNAVAILABLE if blocked else ResourceStatus.AVAILABLE
        resource.status = new_status
        resource.updated_at = datetime.now(UTC)

        return ResourceChange(
            resource_id=str(asset_id),
            previous_status=prev_status,
            new_status=new_status,
            previous_zone=resource.current_zone_id,
            new_zone=resource.current_zone_id,
            occurred_at=event.occurred_at,
        )
