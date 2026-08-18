"""Unit tests for the Resource domain model."""

import pytest
from pydantic import ValidationError

from src.models.resource import Resource, ResourceStatus, ResourceType


# ── helpers ────────────────────────────────────────────────────────────────────

def minimal_resource(**overrides) -> dict:
    base = {
        "name": "Pump Unit 1",
        "city": "TestCity",
        "type": ResourceType.PUMP,
        "home_zone_id": "TC-01",
    }
    base.update(overrides)
    return base


# ── valid construction ─────────────────────────────────────────────────────────

class TestResourceValid:
    def test_minimal(self):
        r = Resource(**minimal_resource())
        assert r.status == ResourceStatus.AVAILABLE
        assert r.current_zone_id is None

    def test_all_resource_types(self):
        for rt in ResourceType:
            Resource(**minimal_resource(type=rt))

    def test_deployed_with_zone(self):
        r = Resource(**minimal_resource(
            status=ResourceStatus.DEPLOYED,
            current_zone_id="TC-02",
        ))
        assert r.current_zone_id == "TC-02"

    def test_capacity_set(self):
        r = Resource(**minimal_resource(capacity=5000))
        assert r.capacity == 5000

    def test_auto_id_uuid(self):
        import uuid
        r = Resource(**minimal_resource())
        uuid.UUID(r.id)

    def test_whitespace_stripped_city_and_home_zone(self):
        r = Resource(**minimal_resource(city=" C ", home_zone_id=" Z "))
        assert r.city == "C"
        assert r.home_zone_id == "Z"


# ── invalid construction ───────────────────────────────────────────────────────

class TestResourceInvalid:
    def test_deployed_without_current_zone_raises(self):
        with pytest.raises(ValidationError, match="must have a current_zone_id"):
            Resource(**minimal_resource(
                status=ResourceStatus.DEPLOYED,
                current_zone_id=None,
            ))

    def test_zero_capacity_raises(self):
        with pytest.raises(ValidationError):
            Resource(**minimal_resource(capacity=0))

    def test_negative_capacity_raises(self):
        with pytest.raises(ValidationError):
            Resource(**minimal_resource(capacity=-10))

    def test_empty_name_raises(self):
        with pytest.raises(ValidationError):
            Resource(**minimal_resource(name=""))

    def test_empty_city_raises(self):
        with pytest.raises(ValidationError):
            Resource(**minimal_resource(city=""))

    def test_extra_field_raises(self):
        with pytest.raises(ValidationError):
            Resource(**minimal_resource(surprise="oops"))
