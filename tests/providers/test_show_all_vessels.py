"""Tests for HARBOR_VIEW_SHOW_ALL_VESSELS diagnostic mode.

Five invariants:
  1. Default filtering (production mode) is unchanged when the env var is unset.
  2. An unmapped AIS type is non-drawable in production mode.
  3. The same vessel (unmapped type) becomes drawable as UNKNOWN in show-all mode.
  4. A vessel with a mapped AIS type is unaffected by show-all mode.
  5. Invalid coordinates are rejected in show-all mode.
"""
from __future__ import annotations

import json

import pytest

from harbor_view.providers.ais import AISProvider, _PartialVessel
from harbor_view.providers.models import VesselType


# ---------------------------------------------------------------------------
# Fixtures — AIS message JSON helpers
# ---------------------------------------------------------------------------

def _position_msg(mmsi: int, lat: float, lon: float, heading: int = 90) -> str:
    return json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": "",
            "latitude": lat,
            "longitude": lon,
            "time_utc": "2026-01-01 12:00:00 UTC",
        },
        "Message": {
            "PositionReport": {
                "TrueHeading": heading,
                "Cog": heading,
                "Sog": 5.0,
                "NavigationalStatus": 0,
            }
        },
    })


def _static_msg(mmsi: int, name: str, ais_type: int, destination: str = "") -> str:
    return json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": name,
            "latitude": 26.10,
            "longitude": -80.09,
            "time_utc": "2026-01-01 12:00:05 UTC",
        },
        "Message": {
            "ShipStaticData": {
                "Name": name,
                "Type": ais_type,
                "Destination": destination,
                "CallSign": "TEST",
            }
        },
    })


_BBOX = ((25.85, -80.30), (26.45, -79.85))
_LAT, _LON = 26.10, -80.09   # inside bounding box
_UNMAPPED_AIS_TYPE = 37       # pleasure craft — not in Harbor View's type map
_MAPPED_AIS_TYPE = 70         # cargo — maps to VesselType.CARGO


def _provider(show_all: bool = False) -> AISProvider:
    return AISProvider(api_key="x", bounding_box=_BBOX, show_all=show_all)


# ---------------------------------------------------------------------------
# 1. Default filtering unchanged when env var is unset
# ---------------------------------------------------------------------------

def test_default_mode_is_production_when_env_unset(monkeypatch):
    monkeypatch.delenv("HARBOR_VIEW_SHOW_ALL_VESSELS", raising=False)
    provider = AISProvider(api_key="x")
    assert provider._show_all is False


def test_show_all_false_when_env_is_empty_string(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_SHOW_ALL_VESSELS", "")
    provider = AISProvider(api_key="x")
    assert provider._show_all is False


def test_production_mode_returns_only_mapped_vessels(monkeypatch):
    """With show-all off, a vessel with an unmapped type must not appear in
    get_vessels() output, while a vessel with a mapped type must appear."""
    monkeypatch.delenv("HARBOR_VIEW_SHOW_ALL_VESSELS", raising=False)
    provider = _provider(show_all=False)

    async def _inject(cache):
        provider._handle_message(_position_msg(111111111, _LAT, _LON), cache)
        provider._handle_message(_static_msg(111111111, "PLEASURE BOAT", _UNMAPPED_AIS_TYPE), cache)
        provider._handle_message(_position_msg(222222222, _LAT, _LON), cache)
        provider._handle_message(_static_msg(222222222, "CARGO SHIP", _MAPPED_AIS_TYPE), cache)

    monkeypatch.setattr(provider, "_collect", _inject)
    vessels = provider.get_vessels()

    names = {v.name for v in vessels}
    assert "PLEASURE BOAT" not in names, "unmapped vessel must be filtered in production mode"
    assert "CARGO SHIP" in names, "mapped vessel must be included in production mode"


# ---------------------------------------------------------------------------
# 2. Unmapped type is non-drawable in production mode
# ---------------------------------------------------------------------------

def test_unmapped_ais_type_not_drawable_in_production():
    p = _PartialVessel(
        mmsi="123456789",
        latitude=_LAT,
        longitude=_LON,
        name="FREE SPIRIT",
        ais_type_code=_UNMAPPED_AIS_TYPE,
    )
    assert p.is_drawable() is False


def test_partial_vessel_is_drawable_requires_mapped_type():
    """is_drawable() must return False even when position and name are present
    if the AIS type code has no Harbor View mapping."""
    p = _PartialVessel(
        mmsi="999888777",
        latitude=26.15,
        longitude=-80.10,
        name="STATUS QUO",
        ais_type_code=37,
    )
    assert p.is_drawable() is False
    assert p.is_drawable_show_all() is True


# ---------------------------------------------------------------------------
# 3. Unmapped type becomes drawable as UNKNOWN in show-all mode
# ---------------------------------------------------------------------------

def test_show_all_enabled_by_constructor_arg():
    provider = _provider(show_all=True)
    assert provider._show_all is True


def test_show_all_env_var_truthy_values(monkeypatch):
    for val in ("1", "true", "yes"):
        monkeypatch.setenv("HARBOR_VIEW_SHOW_ALL_VESSELS", val)
        provider = AISProvider(api_key="x")
        assert provider._show_all is True, f"Expected True for HARBOR_VIEW_SHOW_ALL_VESSELS={val!r}"


def test_is_drawable_show_all_requires_position_and_name():
    # Missing position → not drawable even in show-all.
    p_no_pos = _PartialVessel(mmsi="111", name="NADAN", ais_type_code=37)
    assert p_no_pos.is_drawable_show_all() is False

    # Missing name → not drawable even in show-all.
    p_no_name = _PartialVessel(mmsi="222", latitude=_LAT, longitude=_LON, ais_type_code=37)
    assert p_no_name.is_drawable_show_all() is False

    # Position + name, unmapped type → drawable.
    p_ok = _PartialVessel(mmsi="333", latitude=_LAT, longitude=_LON,
                          name="FREE SPIRIT", ais_type_code=37)
    assert p_ok.is_drawable_show_all() is True


def test_to_vessel_show_all_assigns_unknown_for_unmapped_type():
    p = _PartialVessel(
        mmsi="123456789",
        latitude=_LAT,
        longitude=_LON,
        name="M3",
        ais_type_code=_UNMAPPED_AIS_TYPE,
        heading_deg=90.0,
        destination="FORT LAUDERDALE",
    )
    vessel = p.to_vessel_show_all()
    assert vessel.vessel_type is VesselType.UNKNOWN
    assert vessel.name == "M3"
    assert vessel.latitude == _LAT
    assert vessel.longitude == _LON
    assert vessel.heading_deg == 90.0


def test_to_vessel_show_all_does_not_misclassify_unmapped():
    """Must not assign cruise/cargo/tanker/tug/pilot to an unmapped type."""
    p = _PartialVessel(
        mmsi="777",
        latitude=_LAT,
        longitude=_LON,
        name="SHEPSL XII",
        ais_type_code=37,
    )
    vessel = p.to_vessel_show_all()
    assert vessel.vessel_type not in (
        VesselType.CRUISE,
        VesselType.CARGO,
        VesselType.TANKER,
        VesselType.TUG,
        VesselType.PILOT,
    )
    assert vessel.vessel_type is VesselType.UNKNOWN


def test_show_all_get_vessels_includes_unmapped_type(monkeypatch):
    """With show-all on, an otherwise-filtered vessel appears in get_vessels()."""
    provider = _provider(show_all=True)

    async def _inject(cache):
        provider._handle_message(_position_msg(111111111, _LAT, _LON), cache)
        provider._handle_message(_static_msg(111111111, "NADAN", _UNMAPPED_AIS_TYPE), cache)

    monkeypatch.setattr(provider, "_collect", _inject)
    vessels = provider.get_vessels()

    assert len(vessels) == 1
    assert vessels[0].name == "NADAN"
    assert vessels[0].vessel_type is VesselType.UNKNOWN


# ---------------------------------------------------------------------------
# 4. Mapped vessel behavior is unchanged by show-all mode
# ---------------------------------------------------------------------------

def test_show_all_does_not_alter_mapped_vessel_type():
    """A vessel with a mapped AIS type must keep that type in show-all mode."""
    p = _PartialVessel(
        mmsi="555",
        latitude=_LAT,
        longitude=_LON,
        name="EVER GRANITE",
        ais_type_code=_MAPPED_AIS_TYPE,  # 70 = cargo
    )
    assert p.to_vessel_show_all().vessel_type is VesselType.CARGO


def test_show_all_get_vessels_preserves_mapped_type(monkeypatch):
    provider = _provider(show_all=True)

    async def _inject(cache):
        provider._handle_message(_position_msg(333333333, _LAT, _LON), cache)
        provider._handle_message(_static_msg(333333333, "CARGO SHIP", _MAPPED_AIS_TYPE), cache)

    monkeypatch.setattr(provider, "_collect", _inject)
    vessels = provider.get_vessels()

    assert len(vessels) == 1
    assert vessels[0].vessel_type is VesselType.CARGO


# ---------------------------------------------------------------------------
# 5. Invalid coordinates are rejected in show-all mode
# ---------------------------------------------------------------------------

def test_show_all_rejects_vessel_with_no_position():
    """Vessels lacking a valid position must not be drawable in show-all mode."""
    p = _PartialVessel(
        mmsi="888",
        name="GHOST SHIP",
        ais_type_code=_UNMAPPED_AIS_TYPE,
        # latitude and longitude are None (default)
    )
    assert p.is_drawable_show_all() is False


def test_show_all_get_vessels_excludes_no_position(monkeypatch):
    """A vessel with only static data (no PositionReport ever received) must
    not appear in show-all output — no position means no drawable location."""
    provider = _provider(show_all=True)

    async def _inject(cache):
        # Inject only ShipStaticData — no PositionReport.
        provider._handle_message(_static_msg(444444444, "POSITIONLESS", _UNMAPPED_AIS_TYPE), cache)

    monkeypatch.setattr(provider, "_collect", _inject)
    vessels = provider.get_vessels()
    assert vessels == []
