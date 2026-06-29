"""Tests for harbor_view.providers.ais_types."""
from __future__ import annotations

from harbor_view.providers.ais_types import vessel_type_for_ais_code
from harbor_view.providers.models import VesselType


def test_pilot_vessel_code():
    assert vessel_type_for_ais_code(50) is VesselType.PILOT


def test_tug_codes():
    for code in (31, 32, 52):
        assert vessel_type_for_ais_code(code) is VesselType.TUG


def test_passenger_range_maps_to_cruise():
    for code in (60, 65, 69):
        assert vessel_type_for_ais_code(code) is VesselType.CRUISE


def test_cargo_range():
    for code in (70, 75, 79):
        assert vessel_type_for_ais_code(code) is VesselType.CARGO


def test_tanker_range():
    for code in (80, 85, 89):
        assert vessel_type_for_ais_code(code) is VesselType.TANKER


def test_unmapped_codes_return_none():
    """Fishing (30), sailing/pleasure (36, 37), military (35),
    high-speed craft (40-49), "other" (90-99), and missing/unspecified
    (0, None) all have no Harbor View glyph and must be dropped, not
    guessed at.
    """
    for code in (0, 30, 35, 36, 37, 40, 49, 90, 99, None):
        assert vessel_type_for_ais_code(code) is None


def test_boundary_codes():
    """59 (still "special craft") and 90 ("other") sit just outside
    the mapped ranges -- pins the exact boundaries rather than just
    spot-checking the middle of each range.
    """
    assert vessel_type_for_ais_code(59) is None
    assert vessel_type_for_ais_code(60) is VesselType.CRUISE
    assert vessel_type_for_ais_code(69) is VesselType.CRUISE
    assert vessel_type_for_ais_code(70) is VesselType.CARGO
    assert vessel_type_for_ais_code(79) is VesselType.CARGO
    assert vessel_type_for_ais_code(80) is VesselType.TANKER
    assert vessel_type_for_ais_code(89) is VesselType.TANKER
    assert vessel_type_for_ais_code(90) is None
