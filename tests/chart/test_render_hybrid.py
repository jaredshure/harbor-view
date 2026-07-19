"""Tests for the hybrid renderer: calibration geometry and render smoke tests.

Calibration geometry tests exercise _calibrated_map_extent() with explicit
constants and require no background image.  Render smoke tests verify the
full render path end-to-end and require the reference artwork to be present.
"""
from __future__ import annotations

import os
import pytest
import numpy as np
import matplotlib.image as mpimg

from harbor_view.chart.render_hybrid import (
    _calibrated_map_extent,
    _map_panel_crop_px,
    render_hybrid,
    _BG_PATH,
    HYBRID_MAP_SCALE_X,
    HYBRID_MAP_SCALE_Y,
    HYBRID_MAP_OFFSET_X,
    HYBRID_MAP_OFFSET_Y,
)
from harbor_view.chart.render import MARGIN_FRAC, SIDEBAR_FRAC
from harbor_view.providers import PlaceholderProvider


# ---------------------------------------------------------------------------
# _calibrated_map_extent — pure geometry, no image needed
# ---------------------------------------------------------------------------

def test_neutral_calibration_returns_viewport_unchanged():
    """scale=1.0 / offset=0.0 → calibrated extent equals input viewport."""
    result = _calibrated_map_extent(
        -100, 100, -200, 200,
        scale_x=1.0, scale_y=1.0, offset_x=0.0, offset_y=0.0,
    )
    assert result == pytest.approx((-100.0, 100.0, -200.0, 200.0))


def test_scale_x_widens_extent_symmetrically():
    """scale_x=2.0 → x-span doubles, centred on the viewport midpoint."""
    cx_min, cx_max, cy_min, cy_max = _calibrated_map_extent(
        -100, 100, -200, 200,
        scale_x=2.0, scale_y=1.0, offset_x=0.0, offset_y=0.0,
    )
    assert cx_min == pytest.approx(-200.0)
    assert cx_max == pytest.approx( 200.0)
    assert cy_min == pytest.approx(-200.0)   # y unchanged
    assert cy_max == pytest.approx( 200.0)


def test_scale_y_narrows_extent_symmetrically():
    """scale_y=0.5 → y-span halves, centred on the viewport midpoint."""
    cx_min, cx_max, cy_min, cy_max = _calibrated_map_extent(
        -100, 100, -200, 200,
        scale_x=1.0, scale_y=0.5, offset_x=0.0, offset_y=0.0,
    )
    assert cx_min == pytest.approx(-100.0)   # x unchanged
    assert cx_max == pytest.approx( 100.0)
    assert cy_min == pytest.approx(-100.0)   # -200 * 0.5
    assert cy_max == pytest.approx( 100.0)


def test_offset_x_shifts_extent_eastward():
    """offset_x=0.5 → extent shifts east by 50 % of the viewport x-span."""
    x_min, x_max = -100.0, 100.0
    x_span = x_max - x_min  # 200
    cx_min, cx_max, cy_min, cy_max = _calibrated_map_extent(
        x_min, x_max, -200, 200,
        scale_x=1.0, scale_y=1.0, offset_x=0.5, offset_y=0.0,
    )
    shift = 0.5 * x_span  # +100
    assert cx_min == pytest.approx(x_min + shift)   # 0.0
    assert cx_max == pytest.approx(x_max + shift)   # 200.0
    assert cy_min == pytest.approx(-200.0)           # y unchanged
    assert cy_max == pytest.approx( 200.0)


def test_offset_y_shifts_extent_southward():
    """offset_y=-0.25 → extent shifts south by 25 % of the viewport y-span."""
    y_min, y_max = -200.0, 200.0
    y_span = y_max - y_min  # 400
    cx_min, cx_max, cy_min, cy_max = _calibrated_map_extent(
        -100, 100, y_min, y_max,
        scale_x=1.0, scale_y=1.0, offset_x=0.0, offset_y=-0.25,
    )
    shift = -0.25 * y_span  # -100
    assert cx_min == pytest.approx(-100.0)           # x unchanged
    assert cx_max == pytest.approx( 100.0)
    assert cy_min == pytest.approx(y_min + shift)   # -300.0
    assert cy_max == pytest.approx(y_max + shift)   # +100.0


def test_scale_and_offset_combine():
    """scale and offset apply independently and additively on the same axis."""
    # scale_x=0.5 halves x-span → [-50, +50]; offset_x=0.25 shifts +50 → [0, +100]
    cx_min, cx_max, cy_min, cy_max = _calibrated_map_extent(
        -100, 100, -200, 200,
        scale_x=0.5, scale_y=1.0, offset_x=0.25, offset_y=0.0,
    )
    assert cx_min == pytest.approx(  0.0)
    assert cx_max == pytest.approx(100.0)
    assert cy_min == pytest.approx(-200.0)
    assert cy_max == pytest.approx( 200.0)


def test_default_constants_produce_ordered_extent():
    """The module-level calibration constants must produce a valid, non-empty extent."""
    cx_min, cx_max, cy_min, cy_max = _calibrated_map_extent(
        -100, 100, -200, 200,
        scale_x=HYBRID_MAP_SCALE_X,
        scale_y=HYBRID_MAP_SCALE_Y,
        offset_x=HYBRID_MAP_OFFSET_X,
        offset_y=HYBRID_MAP_OFFSET_Y,
    )
    assert cx_min < cx_max, "calibrated x-extent must be non-empty"
    assert cy_min < cy_max, "calibrated y-extent must be non-empty"


# ---------------------------------------------------------------------------
# _map_panel_crop_px — pure geometry, no image needed
# ---------------------------------------------------------------------------

def test_map_panel_crop_simple_geometry():
    """Round-number inputs produce exact integer multiples."""
    row_start, row_end, col_start, col_end = _map_panel_crop_px(
        img_h=1000,
        img_w=1000,
        margin_frac=0.1,
        map_left_frac=0.25,
        map_w_frac=0.5,
    )
    assert row_start == 100    # 0.1 * 1000
    assert row_end   == 900    # (1 - 0.1) * 1000
    assert col_start == 250    # 0.25 * 1000
    assert col_end   == 750    # (0.25 + 0.5) * 1000


def test_map_panel_crop_artwork_dimensions():
    """For the reference artwork (1087×1447) the crop must be bg[26:1421, 283:1067]."""
    m        = MARGIN_FRAC
    map_left = SIDEBAR_FRAC + m * 0.6
    map_w    = 1.0 - map_left - m

    row_start, row_end, col_start, col_end = _map_panel_crop_px(
        img_h=1447,
        img_w=1087,
        margin_frac=m,
        map_left_frac=map_left,
        map_w_frac=map_w,
    )
    assert row_start == 26,   f"expected row_start=26, got {row_start}"
    assert row_end   == 1421, f"expected row_end=1421, got {row_end}"
    assert col_start == 283,  f"expected col_start=283, got {col_start}"
    assert col_end   == 1067, f"expected col_end=1067, got {col_end}"


def test_map_panel_crop_row_span_less_than_col_span():
    """Sanity: crop height should be taller than it is wide for a portrait artwork."""
    m        = MARGIN_FRAC
    map_left = SIDEBAR_FRAC + m * 0.6
    map_w    = 1.0 - map_left - m

    row_start, row_end, col_start, col_end = _map_panel_crop_px(
        img_h=1447,
        img_w=1087,
        margin_frac=m,
        map_left_frac=map_left,
        map_w_frac=map_w,
    )
    crop_h = row_end - row_start   # 1395
    crop_w = col_end - col_start   # 784
    assert crop_h > crop_w, "map panel crop should be taller than wide (portrait)"


# ---------------------------------------------------------------------------
# Render smoke tests — require reference artwork
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path / "harbor_view_hybrid.png")


def test_background_image_exists():
    assert os.path.isfile(_BG_PATH), (
        f"Reference artwork not found at {_BG_PATH!r}. "
        "The hybrid renderer cannot run without it."
    )


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_hybrid_render_produces_output(tmp_output):
    result = render_hybrid(output_path=tmp_output, vessel_provider=PlaceholderProvider())
    assert result == tmp_output
    assert os.path.isfile(tmp_output)
    assert os.path.getsize(tmp_output) > 10_000  # non-trivial PNG


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_hybrid_render_default_provider(tmp_output):
    # vessel_provider=None should default to PlaceholderProvider without raising
    render_hybrid(output_path=tmp_output)
    assert os.path.isfile(tmp_output)


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_hybrid_render_output_dimensions(tmp_output):
    """Output PNG must be exactly 1087×1447 px (the reference artwork's native size)."""
    render_hybrid(output_path=tmp_output, vessel_provider=PlaceholderProvider())
    out = mpimg.imread(tmp_output)
    h, w = out.shape[:2]
    assert w == 1087, f"expected width 1087, got {w}"
    assert h == 1447, f"expected height 1447, got {h}"


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_sidebar_pixels_unchanged(tmp_output):
    """Sidebar columns in the rendered output closely match the reference artwork."""
    orig = mpimg.imread(_BG_PATH)
    render_hybrid(output_path=tmp_output, vessel_provider=PlaceholderProvider())
    out = mpimg.imread(tmp_output)

    img_h, img_w = orig.shape[:2]
    m = MARGIN_FRAC
    # Sidebar occupies columns 0 .. SIDEBAR_FRAC * img_w; sample the central rows
    # to stay well away from any margins where sub-pixel blending might vary.
    sidebar_col_end = int(SIDEBAR_FRAC * img_w * 0.85)  # stay clear of the sidebar/map border
    row_s = int(m * img_h) + 20
    row_e = int((1.0 - m) * img_h) - 20

    orig_region = orig[row_s:row_e, :sidebar_col_end, :3]
    out_region  = out[row_s:row_e, :sidebar_col_end, :3]

    # atol=0.05 allows for integer rounding (1/255 ≈ 0.004) plus minor
    # sub-pixel interpolation differences; the overall shape must match.
    assert np.allclose(orig_region, out_region, atol=0.05), (
        "Sidebar pixel values diverged from reference artwork by more than 5 %."
    )


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_map_panel_blank_prevents_uncalibrated_art(tmp_output, monkeypatch):
    """With an extreme x-scale the uncovered map-panel margins are white (masked)."""
    import harbor_view.chart.render_hybrid as rh

    # Drive scale to nearly zero so the calibrated image occupies only a
    # tiny central strip; the large uncovered margins must show white from
    # the mask layer, not the uncalibrated artwork from the base layer.
    monkeypatch.setattr(rh, "HYBRID_MAP_SCALE_X", 0.01)
    monkeypatch.setattr(rh, "HYBRID_MAP_SCALE_Y", 0.01)

    render_hybrid(output_path=tmp_output, vessel_provider=PlaceholderProvider())
    out = mpimg.imread(tmp_output)

    img_h, img_w = out.shape[:2]
    m        = MARGIN_FRAC
    map_left = SIDEBAR_FRAC + m * 0.6

    # Sample a pixel near the LEFT edge of the map panel (well inside the
    # panel but far from the tiny calibrated strip in the centre).
    col = int(map_left * img_w) + 8
    row = img_h // 2
    pixel = out[row, col, :3]

    assert np.all(pixel > 0.85), (
        f"Expected near-white mask pixel at row={row}, col={col}, got RGB={pixel}. "
        "The map-mask layer may not be covering the uncalibrated base artwork."
    )
