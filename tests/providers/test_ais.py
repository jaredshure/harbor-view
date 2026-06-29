"""Tests for harbor_view.providers.ais.

Per CLAUDE.md, no live network calls happen here. Message-handling
logic is tested by feeding `_handle_message` raw JSON strings directly
(exactly the shape AISStream sends, taken from their published
examples); connection failures are tested by monkeypatching
`AISProvider._collect` so `get_vessels()`'s error handling is exercised
without touching a socket.
"""
from __future__ import annotations

import json

import pytest

from harbor_view.providers.ais import AISProvider, _PartialVessel, _in_bounding_box
from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselStatus, VesselType


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------

def test_ais_provider_is_a_vessel_provider():
    assert isinstance(AISProvider(api_key="x"), VesselProvider)


def test_no_api_key_returns_empty_list_without_connecting(monkeypatch):
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    provider = AISProvider()  # no explicit key, none in the environment
    assert provider.get_vessels() == []


def test_explicit_api_key_overrides_environment(monkeypatch):
    monkeypatch.setenv("AISSTREAM_API_KEY", "env-key")
    provider = AISProvider(api_key="explicit-key")
    assert provider._api_key == "explicit-key"


def test_default_bbox_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("HARBOR_VIEW_AIS_BBOX", raising=False)
    provider = AISProvider(api_key="x")
    assert provider._bbox == ((25.85, -80.30), (26.45, -79.85))


def test_malformed_bbox_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_AIS_BBOX", "not,a,valid,bbox,too,many")
    provider = AISProvider(api_key="x")
    assert provider._bbox == ((25.85, -80.30), (26.45, -79.85))


def test_custom_bbox_env_is_parsed(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_AIS_BBOX", "25.0,-81.0,27.0,-79.0")
    provider = AISProvider(api_key="x")
    assert provider._bbox == ((25.0, -81.0), (27.0, -79.0))


# ---------------------------------------------------------------------------
# Connection-failure handling -- the brief's core requirement
# ---------------------------------------------------------------------------

def test_connection_failure_returns_empty_list_not_an_exception(monkeypatch):
    """Simulates ANY failure during _collect() (network, auth, DNS --
    doesn't matter which) and confirms get_vessels() degrades to an
    empty list rather than letting the exception propagate.
    """
    provider = AISProvider(api_key="x")

    async def _boom():
        raise ConnectionRefusedError("simulated network failure")

    monkeypatch.setattr(provider, "_collect", _boom)
    result = provider.get_vessels()
    assert result == []


def test_get_vessels_never_raises_for_any_exception_type(monkeypatch):
    """A broader sweep than the test above -- several different
    exception types, all of which must be swallowed into [].
    """
    for exc in (TimeoutError("x"), ValueError("x"), OSError("x"), RuntimeError("x")):
        provider = AISProvider(api_key="x")

        async def _boom(exc=exc):
            raise exc

        monkeypatch.setattr(provider, "_collect", _boom)
        assert provider.get_vessels() == []


# ---------------------------------------------------------------------------
# Bounding box helper
# ---------------------------------------------------------------------------

def test_in_bounding_box():
    bbox = ((25.0, -81.0), (27.0, -79.0))
    assert _in_bounding_box(26.0, -80.0, bbox) is True
    assert _in_bounding_box(24.0, -80.0, bbox) is False  # south of the box
    assert _in_bounding_box(26.0, -82.0, bbox) is False  # west of the box


# ---------------------------------------------------------------------------
# Message parsing / merging -- using AISStream's documented message shapes
# ---------------------------------------------------------------------------

_POSITION_REPORT = json.dumps({
    "MessageType": "PositionReport",
    "MetaData": {
        "MMSI": 367719770,
        "ShipName": "TEST VESSEL",
        "latitude": 26.10,
        "longitude": -80.09,
        "time_utc": "2026-01-01 12:00:00 UTC",
    },
    "Message": {
        "PositionReport": {
            "Cog": 200.0,
            "TrueHeading": 205,
            "Sog": 12.3,
            "NavigationalStatus": 0,
        }
    },
})

_SHIP_STATIC_DATA = json.dumps({
    "MessageType": "ShipStaticData",
    "MetaData": {
        "MMSI": 367719770,
        "ShipName": "TEST VESSEL",
        "latitude": 26.10,
        "longitude": -80.09,
        "time_utc": "2026-01-01 12:00:05 UTC",
    },
    "Message": {
        "ShipStaticData": {
            "Name": "TEST VESSEL",
            "Type": 70,  # cargo
            "Destination": "NASSAU@@@@@@@@",
            "CallSign": "ABC123",
        }
    },
})


def _provider():
    return AISProvider(api_key="x", bounding_box=((25.85, -80.30), (26.45, -79.85)))


def test_position_report_alone_is_not_drawable():
    provider = _provider()
    partials = {}
    provider._handle_message(_POSITION_REPORT, partials)
    assert len(partials) == 1
    partial = partials["367719770"]
    assert partial.latitude == 26.10
    assert partial.heading_deg == 205
    assert partial.speed_kn == 12.3
    # No Type code yet (that comes from ShipStaticData) -> not drawable.
    assert partial.is_drawable() is False


def test_merging_position_and_static_data_becomes_drawable():
    provider = _provider()
    partials = {}
    provider._handle_message(_POSITION_REPORT, partials)
    provider._handle_message(_SHIP_STATIC_DATA, partials)

    assert len(partials) == 1  # same MMSI, merged into one record
    partial = partials["367719770"]
    assert partial.is_drawable() is True

    vessel = partial.to_vessel()
    assert isinstance(vessel, Vessel)
    assert vessel.name == "TEST VESSEL"
    assert vessel.vessel_type is VesselType.CARGO
    assert vessel.latitude == 26.10
    assert vessel.longitude == -80.09
    assert vessel.heading_deg == 205
    assert vessel.speed_kn == 12.3
    assert vessel.origin == ""  # AIS has no origin concept
    assert vessel.destination == "NASSAU"  # "@" padding stripped
    assert vessel.mmsi == "367719770"
    assert vessel.status is VesselStatus.UNDERWAY


def test_order_independent_merging():
    """Static data arriving BEFORE the position report must merge into
    the same record, not create a duplicate.
    """
    provider = _provider()
    partials = {}
    provider._handle_message(_SHIP_STATIC_DATA, partials)
    provider._handle_message(_POSITION_REPORT, partials)
    assert len(partials) == 1
    assert partials["367719770"].is_drawable() is True


def test_message_with_unmapped_vessel_type_never_becomes_drawable():
    """A fishing boat (Type 30) has a real position and a real name
    but no Harbor View glyph -- it must never be returned as drawable,
    confirming the AIS-types mapping is actually enforced here, not
    just defined in isolation.
    """
    static_data = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 999999999, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"ShipStaticData": {"Name": "FISHY", "Type": 30, "Destination": ""}},
    })
    position = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 999999999, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Cog": 90, "Sog": 4.0, "NavigationalStatus": 0}},
    })
    provider = _provider()
    partials = {}
    provider._handle_message(static_data, partials)
    provider._handle_message(position, partials)
    assert partials["999999999"].is_drawable() is False


def test_malformed_json_is_ignored_not_raised():
    provider = _provider()
    partials = {}
    provider._handle_message("not valid json {{{", partials)
    assert partials == {}


def test_missing_required_keys_are_ignored_not_raised():
    provider = _provider()
    partials = {}
    provider._handle_message(json.dumps({"nothing": "useful"}), partials)
    assert partials == {}


def test_message_outside_bounding_box_is_ignored():
    provider = AISProvider(api_key="x", bounding_box=((25.85, -80.30), (26.45, -79.85)))
    far_away = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 1, "ShipName": "FAR", "latitude": 51.4, "longitude": 3.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Cog": 90}},
    })
    partials = {}
    provider._handle_message(far_away, partials)
    assert partials == {}


def test_unavailable_heading_falls_back_to_cog():
    """AIS reports TrueHeading=511 when the heading sensor doesn't
    have a value; Cog (course over ground) should be used instead
    rather than discarding the vessel.
    """
    msg = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 5, "ShipName": "X", "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {"TrueHeading": 511, "Cog": 123.4}},
    })
    provider = _provider()
    partials = {}
    provider._handle_message(msg, partials)
    assert partials["5"].heading_deg == 123.4


def test_unavailable_speed_is_not_recorded():
    """102.3 is AIS's sentinel for "speed not available" and must not
    be recorded as a real speed.
    """
    msg = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 6, "ShipName": "X", "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Sog": 102.3}},
    })
    provider = _provider()
    partials = {}
    provider._handle_message(msg, partials)
    assert partials["6"].speed_kn is None
