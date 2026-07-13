"""Tests for harbor_view.providers.ais.

Per CLAUDE.md, no live network calls happen here. Message-handling
logic is tested by feeding `_handle_message` raw JSON strings directly
(exactly the shape AISStream sends, taken from their published
examples); connection failures are tested by monkeypatching
`AISProvider._collect` so `get_vessels()`'s error handling is exercised
without touching a socket.

Sprint 6 adds cache tests that drive `get_vessels()` through successive
monkeypatched `_collect()` calls to confirm that ShipStaticData
learned in one window survives into the next.
"""
from __future__ import annotations

import json
import time

import pytest

from harbor_view.providers.ais import AISProvider, _PartialVessel, _in_bounding_box
from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselStatus, VesselType


# ---------------------------------------------------------------------------
# Construction / configuration
# ---------------------------------------------------------------------------

def test_ais_provider_is_a_vessel_provider():
    assert isinstance(AISProvider(api_key="x"), VesselProvider)


def test_invalid_filter_mode_falls_back_to_production(monkeypatch, caplog):
    """An unrecognized HARBOR_VIEW_FILTER_MODE value must log a warning
    and fall back to production mode rather than silently misbehaving.
    """
    import logging
    monkeypatch.setenv("HARBOR_VIEW_FILTER_MODE", "foobar")
    with caplog.at_level(logging.WARNING, logger="harbor_view.providers.ais"):
        provider = AISProvider(api_key="x")
    assert provider._filter_mode is None
    assert "foobar" in caplog.text
    assert "falling back to production mode" in caplog.text


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
    empty list rather than letting the exception propagate.  A fresh
    provider with an empty cache still returns [] on failure (same as
    Sprint 4).
    """
    provider = AISProvider(api_key="x")

    async def _boom(cache):
        raise ConnectionRefusedError("simulated network failure")

    monkeypatch.setattr(provider, "_collect", _boom)
    result = provider.get_vessels()
    assert result == []


def test_get_vessels_never_raises_for_any_exception_type(monkeypatch):
    """A broader sweep than the test above -- several different
    exception types, all of which must be swallowed.  Fresh provider,
    empty cache, so the result is [] in every case.
    """
    for exc in (TimeoutError("x"), ValueError("x"), OSError("x"), RuntimeError("x")):
        provider = AISProvider(api_key="x")

        async def _boom(cache, exc=exc):
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


def test_position_report_outside_bbox_is_rejected():
    """A PositionReport with coordinates outside the subscribed bounding
    box must not update the cache.  The lat/lon in PositionReport
    metadata is the vessel's actual current position; bbox filtering is
    appropriate and must remain in force.
    """
    provider = AISProvider(api_key="x", bounding_box=((25.85, -80.30), (26.45, -79.85)))
    far_away = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 1, "ShipName": "FAR", "latitude": 51.4, "longitude": 3.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Cog": 90}},
    })
    partials = {}
    provider._handle_message(far_away, partials)
    assert partials == {}


def test_static_data_outside_bbox_is_accepted():
    """A ShipStaticData with AISStream metadata coordinates outside the
    bbox must still be accepted.  AIS type 5 carries no position;
    AISStream synthesizes MetaData.latitude/longitude from their MMSI
    database, which may be stale or point to a different port.  Applying
    the bbox guard to this synthetic value was silently dropping identity
    data for vessels physically inside the viewport.

    Acceptance means the type code and name are written into the cache.
    The synthetic coordinates from ShipStaticData metadata must NOT be
    written to the cache's lat/lon fields (those only come from a
    bbox-validated PositionReport).
    """
    provider = _provider()
    partials = {}
    static_outside = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {
            "MMSI": 367719770, "ShipName": "TEST VESSEL",
            "latitude": 51.4, "longitude": 4.1,  # Netherlands — far outside box
        },
        "Message": {
            "ShipStaticData": {"Name": "TEST VESSEL", "Type": 70, "Destination": "PORT EVG"},
        },
    })
    provider._handle_message(static_outside, partials)
    assert "367719770" in partials
    p = partials["367719770"]
    assert p.ais_type_code == 70
    assert p.name == "TEST VESSEL"
    assert p.latitude is None   # synthetic coord must not populate position
    assert p.longitude is None


def test_static_data_with_no_lat_lon_is_accepted():
    """A ShipStaticData with no latitude/longitude in MetaData must still
    update the cache.  AIS type 5 carries no position at all, so the
    absence of coordinates in AISStream's metadata is expected and must
    not cause the message to be silently dropped.
    """
    provider = _provider()
    partials = {}
    static_no_coords = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 367719770},
        "Message": {
            "ShipStaticData": {"Name": "TEST VESSEL", "Type": 52, "Destination": ""},
        },
    })
    provider._handle_message(static_no_coords, partials)
    assert "367719770" in partials
    p = partials["367719770"]
    assert p.ais_type_code == 52
    assert p.name == "TEST VESSEL"
    assert p.latitude is None
    assert p.longitude is None


def test_static_data_joins_to_existing_position_record_by_mmsi():
    """Static data arriving with out-of-bbox (or absent) coordinates
    must merge into the existing cache entry for the same MMSI, leaving
    the position from the earlier PositionReport intact.

    Canonical scenario: a harbor tug broadcasts PositionReport (inside
    bbox, position accepted) then ShipStaticData (AISStream metadata
    outside bbox due to stale database position, previously dropped, now
    accepted).  After both messages the vessel must be drawable.
    """
    provider = _provider()
    partials = {}

    provider._handle_message(_POSITION_REPORT, partials)
    assert partials["367719770"].latitude == 26.10
    assert partials["367719770"].ais_type_code is None  # type not yet known

    static_outside = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {
            "MMSI": 367719770, "ShipName": "TEST VESSEL",
            "latitude": 51.4, "longitude": 4.1,
        },
        "Message": {
            "ShipStaticData": {"Name": "TEST VESSEL", "Type": 70, "Destination": "NASSAU"},
        },
    })
    provider._handle_message(static_outside, partials)

    p = partials["367719770"]
    assert p.ais_type_code == 70       # identity from ShipStaticData
    assert p.latitude == 26.10         # position preserved from PositionReport
    assert p.longitude == -80.09
    assert p.is_drawable() is True
    vessel = p.to_vessel()
    assert vessel.vessel_type is VesselType.CARGO
    assert vessel.latitude == 26.10
    assert vessel.destination == "NASSAU"


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


# ---------------------------------------------------------------------------
# Sprint 6 — persistent cache
# ---------------------------------------------------------------------------

def test_ship_static_data_in_cache_enables_drawable_on_next_call(monkeypatch):
    """Core Sprint 6 requirement: once ShipStaticData is received in
    one listen window, the vessel remains drawable in subsequent
    windows that only deliver PositionReports.  The AIS type code and
    name from the first window must survive into the second.
    """
    provider = _provider()

    async def first_window(cache):
        provider._handle_message(_POSITION_REPORT, cache)
        provider._handle_message(_SHIP_STATIC_DATA, cache)

    monkeypatch.setattr(provider, "_collect", first_window)
    vessels = provider.get_vessels()
    assert len(vessels) == 1
    assert vessels[0].vessel_type is VesselType.CARGO

    # Second window: only a PositionReport arrives -- no ShipStaticData.
    async def second_window(cache):
        provider._handle_message(_POSITION_REPORT, cache)

    monkeypatch.setattr(provider, "_collect", second_window)
    vessels = provider.get_vessels()
    assert len(vessels) == 1  # still drawable: type code came from cache
    assert vessels[0].vessel_type is VesselType.CARGO
    assert vessels[0].name == "TEST VESSEL"


def test_cache_persists_across_multiple_get_vessels_calls(monkeypatch):
    """The cache entry for a known MMSI must survive repeated
    get_vessels() calls and remain accessible by MMSI.
    """
    provider = _provider()

    async def window(cache):
        provider._handle_message(_POSITION_REPORT, cache)
        provider._handle_message(_SHIP_STATIC_DATA, cache)

    monkeypatch.setattr(provider, "_collect", window)
    provider.get_vessels()
    assert "367719770" in provider._cache

    monkeypatch.setattr(provider, "_collect", window)
    provider.get_vessels()
    assert "367719770" in provider._cache


def test_stale_vessels_are_evicted(monkeypatch):
    """Vessels not seen for longer than stale_seconds must be removed
    from the cache so a vessel that has left the area does not remain
    on the chart indefinitely.
    """
    provider = AISProvider(
        api_key="x",
        bounding_box=((25.85, -80.30), (26.45, -79.85)),
        stale_seconds=10.0,
    )

    async def first_window(cache):
        provider._handle_message(_POSITION_REPORT, cache)
        provider._handle_message(_SHIP_STATIC_DATA, cache)

    monkeypatch.setattr(provider, "_collect", first_window)
    vessels = provider.get_vessels()
    assert len(vessels) == 1

    # Artificially age the cache entry past the staleness threshold.
    provider._cache["367719770"].last_seen_unix = time.time() - 20.0

    async def empty_window(cache):
        pass  # no new messages arrive this cycle

    monkeypatch.setattr(provider, "_collect", empty_window)
    vessels = provider.get_vessels()
    assert "367719770" not in provider._cache
    assert vessels == []


def test_connection_failure_with_populated_cache_returns_cached_vessels(monkeypatch):
    """If the connection fails but the cache is not yet stale, the
    provider must return whatever drawable vessels it already knows
    about rather than clearing to an empty list.  This keeps the chart
    populated during transient network hiccups.
    """
    provider = _provider()

    async def first_window(cache):
        provider._handle_message(_POSITION_REPORT, cache)
        provider._handle_message(_SHIP_STATIC_DATA, cache)

    monkeypatch.setattr(provider, "_collect", first_window)
    assert len(provider.get_vessels()) == 1

    async def boom(cache):
        raise ConnectionRefusedError("network down")

    monkeypatch.setattr(provider, "_collect", boom)
    vessels = provider.get_vessels()
    assert len(vessels) == 1  # cached vessel survives the failure
    assert vessels[0].name == "TEST VESSEL"


# ---------------------------------------------------------------------------
# Sprint 6.2 — heading is optional; three-step fallback
# ---------------------------------------------------------------------------

def test_drawable_when_true_heading_available():
    """Step 1: vessel with TrueHeading is drawable and uses that value."""
    provider = _provider()
    partials = {}
    provider._handle_message(_POSITION_REPORT, partials)   # TrueHeading=205
    provider._handle_message(_SHIP_STATIC_DATA, partials)
    partial = partials["367719770"]
    assert partial.is_drawable() is True
    assert partial.to_vessel().heading_deg == 205


def test_drawable_when_only_cog_available():
    """Step 2: TrueHeading=511 (unavailable), COG present — vessel is
    drawable using COG as the heading.
    """
    pos = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 111111111, "ShipName": "CARGO A",
                     "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {
            "TrueHeading": 511, "Cog": 180.0, "Sog": 8.0, "NavigationalStatus": 0,
        }},
    })
    static = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 111111111, "ShipName": "CARGO A",
                     "latitude": 26.1, "longitude": -80.1},
        "Message": {"ShipStaticData": {"Name": "CARGO A", "Type": 70, "Destination": "MIAMI"}},
    })
    provider = _provider()
    partials = {}
    provider._handle_message(pos, partials)
    provider._handle_message(static, partials)
    partial = partials["111111111"]
    assert partial.is_drawable() is True
    assert partial.to_vessel().heading_deg == 180.0


def test_drawable_when_heading_and_cog_both_unavailable():
    """Step 3: TrueHeading=511 and no COG field at all — vessel is still
    drawable, rendered with a default orientation of 0° (due north).
    This is the ASG KHERSON case: a commercial cargo vessel (AIS type
    70) with a malfunctioning or non-reporting heading sensor.
    """
    pos = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 222222222, "ShipName": "ASG KHERSON",
                     "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {
            "TrueHeading": 511, "Sog": 0.0, "NavigationalStatus": 5,
        }},
    })
    static = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 222222222, "ShipName": "ASG KHERSON",
                     "latitude": 26.1, "longitude": -80.1},
        "Message": {"ShipStaticData": {"Name": "ASG KHERSON", "Type": 70, "Destination": "PORT EVG"}},
    })
    provider = _provider()
    partials = {}
    provider._handle_message(pos, partials)
    provider._handle_message(static, partials)
    partial = partials["222222222"]
    assert partial.heading_deg is None           # no usable heading data stored
    assert partial.is_drawable() is True         # no longer blocked by missing heading
    vessel = partial.to_vessel()
    assert vessel.heading_deg == 0.0             # default orientation: due north
    assert vessel.vessel_type is VesselType.CARGO


# ---------------------------------------------------------------------------
# Development filter mode (HARBOR_VIEW_FILTER_MODE=development)
# ---------------------------------------------------------------------------

def _dev_provider():
    return AISProvider(
        api_key="x",
        bounding_box=((25.85, -80.30), (26.45, -79.85)),
        filter_mode="development",
    )


def test_dev_mode_unknown_ais_type_is_rendered(monkeypatch):
    """In development mode, a vessel with an AIS type that has no Harbor
    View mapping (e.g. type 30, fishing) must appear in get_vessels()
    output as VesselType.UNKNOWN rather than being dropped.
    """
    provider = _dev_provider()
    fishing_pos = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 111222333, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Cog": 90, "Sog": 4.0, "NavigationalStatus": 0}},
    })
    fishing_static = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 111222333, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"ShipStaticData": {"Name": "FISHY", "Type": 30, "Destination": ""}},
    })

    async def window(cache):
        provider._handle_message(fishing_pos, cache)
        provider._handle_message(fishing_static, cache)

    monkeypatch.setattr(provider, "_collect", window)
    vessels = provider.get_vessels()
    assert len(vessels) == 1
    assert vessels[0].vessel_type is VesselType.UNKNOWN
    assert vessels[0].name == "FISHY"


def test_dev_mode_missing_ais_type_is_rendered(monkeypatch):
    """In development mode, a vessel that has only a PositionReport
    (no ShipStaticData, ais_type_code=None) must still appear in
    get_vessels() output as VesselType.UNKNOWN.
    """
    provider = _dev_provider()

    async def window(cache):
        provider._handle_message(_POSITION_REPORT, cache)  # no ShipStaticData

    monkeypatch.setattr(provider, "_collect", window)
    vessels = provider.get_vessels()
    assert len(vessels) == 1
    assert vessels[0].vessel_type is VesselType.UNKNOWN


def test_production_mode_unknown_ais_type_is_filtered(monkeypatch):
    """In production mode (the default), a vessel with no mapped AIS type
    must be absent from get_vessels() even in development mode is NOT active.
    Contrasts directly with test_dev_mode_unknown_ais_type_is_rendered.
    """
    provider = _provider()  # production mode; no filter_mode argument
    fishing_pos = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 111222333, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Cog": 90, "Sog": 4.0, "NavigationalStatus": 0}},
    })
    fishing_static = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 111222333, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"ShipStaticData": {"Name": "FISHY", "Type": 30, "Destination": ""}},
    })

    async def window(cache):
        provider._handle_message(fishing_pos, cache)
        provider._handle_message(fishing_static, cache)

    monkeypatch.setattr(provider, "_collect", window)
    vessels = provider.get_vessels()
    assert vessels == []


def test_dev_mode_known_type_uses_correct_symbol(monkeypatch):
    """In development mode, a vessel with a recognized AIS type must
    still use that type's symbol -- VesselType.UNKNOWN must not
    override a vessel that has a valid mapping.
    """
    provider = _dev_provider()

    async def window(cache):
        provider._handle_message(_POSITION_REPORT, cache)
        provider._handle_message(_SHIP_STATIC_DATA, cache)  # Type=70 -> CARGO

    monkeypatch.setattr(provider, "_collect", window)
    vessels = provider.get_vessels()
    assert len(vessels) == 1
    assert vessels[0].vessel_type is VesselType.CARGO  # not UNKNOWN


# ---------------------------------------------------------------------------
# Debug table mode-awareness
# ---------------------------------------------------------------------------

def _make_in_viewport_partial(mmsi: str, ais_type_code: int | None = 30):
    """Return a _PartialVessel placed inside the chart viewport.

    lat=26.1, lon=-80.1 projects to roughly (948 m, 856 m) in the
    equirectangular chart space, well inside the 14.4 NM tall / ~7.7 NM
    wide viewport centered on REF_LAT=26.0906, REF_LON=-80.1095.
    """
    p = _PartialVessel(mmsi=mmsi)
    p.latitude = 26.1
    p.longitude = -80.1
    p.name = "FISHY"
    p.ais_type_code = ais_type_code
    return p


def test_debug_table_dev_mode_unmapped_vessel_is_rendered(capsys):
    """In development mode, an unmapped vessel (type 30, fishing) with a
    valid in-viewport position must show Rndr=YES and be counted in
    'Vessels rendered', not 'Vessels filtered'.
    """
    provider = _dev_provider()
    provider._cache["111000001"] = _make_in_viewport_partial("111000001", ais_type_code=30)
    provider._print_debug_table()
    out = capsys.readouterr().out

    assert "YES " in out                                        # row-level Rndr column
    assert "Vessels rendered                       : 1" in out
    assert "Vessels filtered (missing data/type)   : 0" in out


def test_debug_table_production_mode_unmapped_vessel_is_filtered(capsys):
    """In production mode, the same unmapped vessel must show Rndr=NO
    and be counted in 'Vessels filtered', not 'Vessels rendered'.
    """
    provider = _provider()
    provider._cache["111000001"] = _make_in_viewport_partial("111000001", ais_type_code=30)
    provider._print_debug_table()
    out = capsys.readouterr().out

    assert "NO  " in out                                        # row-level Rndr column
    assert "Vessels rendered                       : 0" in out
    assert "Vessels filtered (missing data/type)   : 1" in out


def test_debug_table_counts_reflect_mode(capsys):
    """With one in-viewport vessel of unmapped type and one of known type
    (cargo), dev mode must count both as rendered while production mode
    counts only the cargo vessel as rendered and the fishing vessel as
    filtered.
    """
    fishing = _make_in_viewport_partial("111000001", ais_type_code=30)
    cargo = _make_in_viewport_partial("111000002", ais_type_code=70)
    cargo.name = "FREIGHTER"

    dev = _dev_provider()
    dev._cache["111000001"] = fishing
    dev._cache["111000002"] = cargo
    dev._print_debug_table()
    dev_out = capsys.readouterr().out
    assert "Vessels rendered                       : 2" in dev_out
    assert "Vessels filtered (missing data/type)   : 0" in dev_out

    prod = _provider()
    prod._cache["111000001"] = fishing
    prod._cache["111000002"] = cargo
    prod._print_debug_table()
    prod_out = capsys.readouterr().out
    assert "Vessels rendered                       : 1" in prod_out
    assert "Vessels filtered (missing data/type)   : 1" in prod_out


def test_unmapped_vessel_type_never_enters_drawable_pool(monkeypatch):
    """Fishing/pleasure/sailing vessels (no Harbor View glyph) must
    never appear in get_vessels() output even after accumulating a
    complete record in the cache across multiple calls.
    """
    provider = _provider()
    fishing_position = json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 999999999, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"PositionReport": {"TrueHeading": 90, "Cog": 90, "Sog": 4.0, "NavigationalStatus": 0}},
    })
    fishing_static = json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 999999999, "ShipName": "FISHY", "latitude": 26.1, "longitude": -80.1},
        "Message": {"ShipStaticData": {"Name": "FISHY", "Type": 30, "Destination": ""}},
    })

    async def window(cache):
        provider._handle_message(fishing_position, cache)
        provider._handle_message(fishing_static, cache)

    monkeypatch.setattr(provider, "_collect", window)
    vessels = provider.get_vessels()
    assert vessels == []
    # The vessel is held in the cache (position + static data received)
    # but is_drawable() must still return False because AIS type 30
    # (fishing) has no Harbor View glyph.
    assert "999999999" in provider._cache
    assert provider._cache["999999999"].is_drawable() is False
