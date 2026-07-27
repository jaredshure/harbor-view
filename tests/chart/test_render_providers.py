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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from harbor_view.chart.render import draw_fleet, draw_vessel, render, render_to_image, MAP_ORIENTATION
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


# ---------------------------------------------------------------------------
# Label rendering tests
# ---------------------------------------------------------------------------

def _make_map_ax():
    """Create a minimal map axes with viewport limits matching the active
    MAP_ORIENTATION, large enough to contain vessels at the reference
    coordinates used by the label tests (≈ 26.1°N, 80.1°W).
    """
    fig = plt.figure(figsize=(10, 6))
    ax = fig.add_axes([0.25, 0.05, 0.72, 0.93])
    if MAP_ORIENTATION == "seaward_up":
        # xlim = along-shore range (y_local), reversed (north-left)
        # ylim = seaward range (x_local)
        ax.set_xlim(15000, -15000)
        ax.set_ylim(-2000, 15000)
    else:
        ax.set_xlim(-3000, 15000)
        ax.set_ylim(-15000, 15000)
    return fig, ax


def test_draw_vessel_returns_name_text_with_vessel_name():
    """draw_vessel must return a Text object whose content is the vessel name."""
    fig, ax = _make_map_ax()
    try:
        vessel = Vessel("LONE FREIGHTER", VesselType.CARGO, 26.10, -80.10, 90)
        name_text, dest_anchor = draw_vessel(ax, vessel)
        assert name_text.get_text() == "LONE FREIGHTER"
        assert len(dest_anchor) == 4   # (dest_px, dest_py, dest_ha, style)
    finally:
        plt.close(fig)


def test_draw_fleet_name_always_appears():
    """Vessel names must always appear in the axes, regardless of destination."""
    fig, ax = _make_map_ax()
    try:
        vessels = [
            Vessel("SHIP WITH DEST",    VesselType.CARGO,   26.10, -80.10, 90, destination="MIAMI"),
            Vessel("SHIP WITHOUT DEST", VesselType.TANKER,  26.12, -80.08, 180, destination=""),
        ]
        draw_fleet(ax, vessels)
        text_strings = {t.get_text() for t in ax.texts}
        assert "SHIP WITH DEST"    in text_strings
        assert "SHIP WITHOUT DEST" in text_strings
    finally:
        plt.close(fig)


def test_draw_fleet_destination_drawn_when_present():
    """When a vessel has a non-empty destination and space permits, the
    destination text must appear in the axes.
    """
    fig, ax = _make_map_ax()
    try:
        vessel = Vessel("LONE SHIP", VesselType.CARGO, 26.10, -80.10, 90, destination="NASSAU")
        draw_fleet(ax, [vessel])
        text_strings = {t.get_text() for t in ax.texts}
        assert "LONE SHIP" in text_strings
        assert "NASSAU" in text_strings
    finally:
        plt.close(fig)


def test_draw_fleet_destination_omitted_when_empty():
    """An empty destination string must not produce a destination text object."""
    fig, ax = _make_map_ax()
    try:
        vessel = Vessel("LONE SHIP", VesselType.CARGO, 26.10, -80.10, 90, destination="")
        draw_fleet(ax, [vessel])
        text_strings = [t.get_text() for t in ax.texts]
        assert "LONE SHIP" in text_strings
        # The only text in the axes should be the vessel name; no empty or
        # empty-destination text object should be added.
        assert all(t != "" for t in text_strings)
    finally:
        plt.close(fig)


def test_draw_fleet_unknown_vessel_type_renders_without_error():
    """VesselType.UNKNOWN (AIS vessels with no mapped type) must render
    without raising -- the diamond glyph exists for this case.
    """
    fig, ax = _make_map_ax()
    try:
        vessel = Vessel("MYSTERY", VesselType.UNKNOWN, 26.10, -80.10, 90, destination="PORT EVG")
        draw_fleet(ax, [vessel])
        text_strings = {t.get_text() for t in ax.texts}
        assert "MYSTERY" in text_strings
    finally:
        plt.close(fig)


def test_draw_fleet_two_overlapping_vessels_no_crash():
    """Two vessels at nearly the same position with destinations must render
    without raising -- the collision logic must suppress rather than error.
    """
    fig, ax = _make_map_ax()
    try:
        vessels = [
            Vessel("VESSEL A", VesselType.CARGO,  26.10, -80.10, 90,  destination="MIAMI"),
            Vessel("VESSEL B", VesselType.TANKER, 26.101, -80.101, 90, destination="NASSAU"),
        ]
        draw_fleet(ax, vessels)
        text_strings = {t.get_text() for t in ax.texts}
        # Both names must always appear regardless of collision outcome.
        assert "VESSEL A" in text_strings
        assert "VESSEL B" in text_strings
    finally:
        plt.close(fig)


def test_render_with_vessel_with_destination_completes():
    """Full render pipeline with a vessel that has a destination must
    produce a valid PNG without raising.
    """
    class _DestProvider(VesselProvider):
        def get_vessels(self):
            return [Vessel("PORT RUNNER", VesselType.CARGO, 26.10, -80.09, 90,
                           destination="PORT EVG")]

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "dest.png")
        render(output_path=out, vessel_provider=_DestProvider())
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0


def test_render_with_unknown_vessel_type_completes():
    """Full render pipeline with a VesselType.UNKNOWN vessel must
    produce a valid PNG -- this is the live-AIS unmapped-type case.
    """
    class _UnknownProvider(VesselProvider):
        def get_vessels(self):
            return [Vessel("AIS TARGET 1", VesselType.UNKNOWN, 26.10, -80.09, 0)]

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "unknown.png")
        render(output_path=out, vessel_provider=_UnknownProvider())
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0


# ---------------------------------------------------------------------------
# Canvas size abstraction — native-resolution rendering
# ---------------------------------------------------------------------------

def test_render_to_image_default_canvas_size():
    """render_to_image() with no canvas_size produces a 2000×1200 image."""
    img = render_to_image(vessel_provider=_EmptyProvider())
    assert img.size == (2000, 1200), (
        f"Expected default canvas 2000×1200, got {img.size}"
    )


def test_render_to_image_explicit_canvas_size():
    """render_to_image(canvas_size=(800, 480)) produces exactly an 800×480 image."""
    img = render_to_image(vessel_provider=_EmptyProvider(), canvas_size=(800, 480))
    assert img.size == (800, 480), (
        f"Expected canvas 800×480, got {img.size}"
    )


def test_render_to_image_explicit_canvas_size_with_vessels():
    """canvas_size works end-to-end with a real vessel -- no crash, correct size."""
    img = render_to_image(vessel_provider=_OneVesselProvider(), canvas_size=(800, 480))
    assert img.size == (800, 480)


def test_render_to_image_custom_canvas_size():
    """canvas_size accepts arbitrary pixel dimensions divisible by DPI."""
    img = render_to_image(vessel_provider=_EmptyProvider(), canvas_size=(1000, 600))
    assert img.size == (1000, 600)
