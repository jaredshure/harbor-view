"""Tests for harbor_view.providers.models."""
from __future__ import annotations

import datetime as dt

from harbor_view.providers.models import Vessel, VesselStatus, VesselType


def test_vessel_requires_no_optional_fields():
    """A Vessel can be constructed with only the fields every provider
    can always supply -- optional fields default to None.
    """
    v = Vessel(
        name="TEST SHIP",
        vessel_type=VesselType.CARGO,
        latitude=26.1,
        longitude=-80.1,
        heading_deg=180,
        origin="A",
        destination="B",
    )
    assert v.mmsi is None
    assert v.speed_kn is None
    assert v.status is None
    assert v.timestamp is None


def test_vessel_accepts_all_fields():
    now = dt.datetime(2026, 1, 1, 12, 0, 0)
    v = Vessel(
        name="TEST SHIP",
        vessel_type=VesselType.TANKER,
        latitude=26.1,
        longitude=-80.1,
        heading_deg=90,
        origin="A",
        destination="B",
        mmsi="123456789",
        speed_kn=12.5,
        status=VesselStatus.UNDERWAY,
        timestamp=now,
    )
    assert v.mmsi == "123456789"
    assert v.speed_kn == 12.5
    assert v.status is VesselStatus.UNDERWAY
    assert v.timestamp == now


def test_vessel_is_immutable():
    v = Vessel("X", VesselType.TUG, 0, 0, 0, "A", "B")
    try:
        v.name = "Y"  # type: ignore[misc]
        assert False, "Vessel should be frozen"
    except AttributeError:
        pass


def test_backward_compatible_aliases():
    """render.py (and any other pre-Sprint-3 code) reads `.lat`, `.lon`,
    and `.kind` -- these must keep working against the new model.
    """
    v = Vessel("X", VesselType.PILOT, 26.5, -80.2, 45, "A", "B")
    assert v.lat == v.latitude == 26.5
    assert v.lon == v.longitude == -80.2
    assert v.kind == "pilot"


def test_vessel_type_compares_equal_to_plain_string():
    """VesselType is a str Enum specifically so old comparisons like
    `vessel.kind == "cruise"` (used throughout chart/render.py) keep
    working without modification.
    """
    v = Vessel("X", VesselType.CRUISE, 0, 0, 0, "A", "B")
    assert v.kind == "cruise"
    assert v.vessel_type == "cruise"
    assert v.vessel_type == VesselType.CRUISE
