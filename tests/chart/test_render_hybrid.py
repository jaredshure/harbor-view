"""Tests for the hybrid renderer: calibration geometry and render smoke tests.

Calibration geometry tests exercise _calibrated_map_extent() with explicit
constants and require no background image.  Render smoke tests verify the
full render path end-to-end and require the reference artwork to be present.
"""
from __future__ import annotations

import os
import pytest

from harbor_view.chart.render_hybrid import (
    _calibrated_map_extent,
    render_hybrid,
    _BG_PATH,
    HYBRID_MAP_SCALE_X,
    HYBRID_MAP_SCALE_Y,
    HYBRID_MAP_OFFSET_X,
    HYBRID_MAP_OFFSET_Y,
)
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
