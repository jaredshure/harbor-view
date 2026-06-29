"""Tests for harbor_view.providers.base."""
from __future__ import annotations

import pytest

from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselType


def test_cannot_instantiate_abstract_provider():
    """VesselProvider is an interface, not a usable class on its own."""
    with pytest.raises(TypeError):
        VesselProvider()  # type: ignore[abstract]


def test_subclass_must_implement_get_vessels():
    """A subclass that doesn't implement get_vessels() is still
    abstract and can't be instantiated -- this is what guarantees every
    real provider satisfies the renderer's one-method contract.
    """

    class IncompleteProvider(VesselProvider):
        pass

    with pytest.raises(TypeError):
        IncompleteProvider()  # type: ignore[abstract]


def test_minimal_subclass_works():
    class MinimalProvider(VesselProvider):
        def get_vessels(self) -> list[Vessel]:
            return [Vessel("X", VesselType.TUG, 0, 0, 0, "A", "B")]

    provider = MinimalProvider()
    vessels = provider.get_vessels()
    assert len(vessels) == 1
    assert vessels[0].name == "X"
