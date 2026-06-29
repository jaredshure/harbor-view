"""Tests for harbor_view.providers.placeholder."""
from __future__ import annotations

from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel
from harbor_view.providers.placeholder import (
    PLACEHOLDER_FLEET,
    PlaceholderProvider,
)


def test_placeholder_provider_is_a_vessel_provider():
    assert isinstance(PlaceholderProvider(), VesselProvider)


def test_get_vessels_returns_the_fixed_fleet():
    provider = PlaceholderProvider()
    vessels = provider.get_vessels()
    assert len(vessels) == len(PLACEHOLDER_FLEET) == 10
    assert all(isinstance(v, Vessel) for v in vessels)


def test_get_vessels_returns_a_fresh_list_each_call():
    """Callers must not be able to corrupt the module-level fleet by
    mutating what get_vessels() returns.
    """
    provider = PlaceholderProvider()
    first = provider.get_vessels()
    first.clear()
    second = provider.get_vessels()
    assert len(second) == 10


def test_fleet_contains_expected_vessel_names():
    """Pins the fleet's identity so a future edit that accidentally
    drops or renames a vessel (changing the rendered chart) gets
    caught here rather than only by eyeballing the PNG.
    """
    provider = PlaceholderProvider()
    names = {v.name for v in provider.get_vessels()}
    assert names == {
        "OCEAN MAJESTY",
        "CARIBBEAN STAR",
        "MAERSK HORIZON",
        "EVER GRANITE",
        "ATLANTIC TRADER",
        "STAR ENDEAVOR",
        "GULF VOYAGER",
        "HARBOR KING",
        "MISS CARLA",
        "EVERGLADES PILOT",
    }
