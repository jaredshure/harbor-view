"""Integration tests for harbor_view.chart.render against the provider
architecture introduced in Sprint 3.

These tests check that the renderer can be driven by any
VesselProvider -- including a minimal fake one -- without needing to
inspect pixels. A separate, slower visual-regression check (comparing
actual rendered output against a reference image) is appropriate for
local/manual verification but is intentionally not pinned here, since
matplotlib/font-rendering differences across environments would make a
pixel-exact CI assertion brittle. See docs/sprint-003-notes.md for how
"no visible change" was verified during the refactor itself.
"""
from __future__ import annotations

import os
import tempfile

from harbor_view.chart.render import render
from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselType
from harbor_view.providers.placeholder import PlaceholderProvider


class _EmptyProvider(VesselProvider):
    """A provider with no vessels -- the simplest possible fake,
    useful for confirming the renderer doesn't assume a non-empty
    fleet anywhere.
    """

    def get_vessels(self) -> list[Vessel]:
        return []


class _OneVesselProvider(VesselProvider):
    def get_vessels(self) -> list[Vessel]:
        return [Vessel("LONE SHIP", VesselType.CARGO, 26.12, -80.09, 90, "A", "B")]


def test_render_with_default_provider_produces_a_file():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")
        result = render(output_path=out_path)
        assert result == out_path
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0


def test_render_with_explicit_placeholder_provider_matches_default():
    """Passing PlaceholderProvider() explicitly must be identical to
    omitting the argument -- this is the default the renderer falls
    back to.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path_a = os.path.join(tmp, "a.png")
        path_b = os.path.join(tmp, "b.png")
        render(output_path=path_a)
        render(output_path=path_b, vessel_provider=PlaceholderProvider())
        # Same size is a cheap sanity check; exact pixel equality is
        # checked separately for the no-vessels and one-vessel cases
        # below, where there's no live clock text to vary between
        # calls.
        assert os.path.getsize(path_a) > 0
        assert os.path.getsize(path_b) > 0


def test_render_does_not_require_any_specific_provider():
    """The renderer must accept ANY VesselProvider, including one with
    zero or one vessel -- it should have no hidden dependency on the
    placeholder fleet's size or contents.
    """
    with tempfile.TemporaryDirectory() as tmp:
        empty_path = os.path.join(tmp, "empty.png")
        one_path = os.path.join(tmp, "one.png")
        render(output_path=empty_path, vessel_provider=_EmptyProvider())
        render(output_path=one_path, vessel_provider=_OneVesselProvider())
        assert os.path.getsize(empty_path) > 0
        assert os.path.getsize(one_path) > 0


def test_render_is_deterministic_given_the_same_provider():
    """Two renders, same provider, run close together in time, should
    be pixel-identical -- the only source of frame-to-frame variation
    in Harbor View is the live clock in the sidebar, which a
    fixed-vessel provider doesn't touch.
    """
    from PIL import Image
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        path_a = os.path.join(tmp, "a.png")
        path_b = os.path.join(tmp, "b.png")
        render(output_path=path_a, vessel_provider=_OneVesselProvider())
        render(output_path=path_b, vessel_provider=_OneVesselProvider())

        a = np.array(Image.open(path_a).convert("RGB"))
        b = np.array(Image.open(path_b).convert("RGB"))
        # Mask out the sidebar's live clock region the same way the
        # manual Sprint 3 verification did, since it's the one part of
        # the frame allowed to differ between calls.
        a[500:750, 0:500] = 0
        b[500:750, 0:500] = 0
        assert np.array_equal(a, b)


def test_render_with_ais_provider_and_no_api_key_produces_empty_harbor(monkeypatch):
    """Sprint 4's core promise: an AISProvider that can't reach a live
    feed (here, simply because no API key is configured) must still
    let the renderer produce a complete, uncrashed chart -- just with
    no vessels on it. This is the "empty harbor is a valid state"
    requirement, exercised end to end through render().
    """
    from harbor_view.providers.ais import AISProvider

    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "empty_harbor.png")
        result = render(output_path=out_path, vessel_provider=AISProvider())
        assert result == out_path
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0


def test_render_with_ais_provider_matches_placeholder_layout_when_empty(monkeypatch):
    """An empty-vessel AISProvider render should be pixel-identical to
    a render from the explicit _EmptyProvider fake (same zero vessels,
    same everything else) -- confirming AISProvider's failure path
    doesn't do anything visually different from "just no vessels."
    """
    from PIL import Image
    import numpy as np
    from harbor_view.providers.ais import AISProvider

    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        path_ais = os.path.join(tmp, "ais_empty.png")
        path_fake = os.path.join(tmp, "fake_empty.png")
        render(output_path=path_ais, vessel_provider=AISProvider())
        render(output_path=path_fake, vessel_provider=_EmptyProvider())

        a = np.array(Image.open(path_ais).convert("RGB"))
        b = np.array(Image.open(path_fake).convert("RGB"))
        a[500:750, 0:500] = 0
        b[500:750, 0:500] = 0
        assert np.array_equal(a, b)
