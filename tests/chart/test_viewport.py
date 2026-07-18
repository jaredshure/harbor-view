"""Tests for the viewport geometry solver.

All tests in this file are pure-math: they call solve_viewport() with
explicit arguments and assert on the return values.  No matplotlib, no
images, no filesystem — the solver has no dependencies beyond Python.
"""
from __future__ import annotations

import pytest

from harbor_view.chart.viewport import NM, solve_viewport
from harbor_view.chart.geometry import REF_LAT, REF_LON


# ---------------------------------------------------------------------------
# solve_viewport — pure geometry
# ---------------------------------------------------------------------------

def test_x_max_matches_offshore_range():
    """x_max must be exactly offshore_range_nm * NM metres east of origin."""
    _, x_max, _, _ = solve_viewport(offshore_range_nm=8.0, panel_aspect=1.78)
    assert x_max == pytest.approx(8.0 * NM)


def test_reference_at_coast_frac_from_left():
    """The origin (0) must appear at coast_frac_from_left from the west edge."""
    frac = 0.21
    x_min, x_max, _, _ = solve_viewport(8.0, 1.78, coast_frac_from_left=frac)
    x_span = x_max - x_min
    # origin (0) is at fraction -x_min / x_span from the left
    origin_frac = -x_min / x_span
    assert origin_frac == pytest.approx(frac, abs=1e-9)


def test_aspect_ratio_fills_panel():
    """y_span / x_span must equal panel_aspect so set_aspect('equal') fills exactly."""
    aspect = 1.78
    x_min, x_max, y_min, y_max = solve_viewport(8.0, aspect)
    x_span = x_max - x_min
    y_span = y_max - y_min
    assert y_span / x_span == pytest.approx(aspect, rel=1e-9)


def test_y_symmetric_around_origin():
    """The reference location is vertically centred: y_min == -y_max."""
    _, _, y_min, y_max = solve_viewport(8.0, 1.78)
    assert y_min == pytest.approx(-y_max, rel=1e-9)


def test_scaling_is_proportional():
    """Doubling offshore_range_nm uniformly doubles all four bounds."""
    x_min_8, x_max_8, y_min_8, y_max_8 = solve_viewport(8.0, 1.78)
    x_min_4, x_max_4, y_min_4, y_max_4 = solve_viewport(4.0, 1.78)
    assert x_min_8 == pytest.approx(2 * x_min_4)
    assert x_max_8 == pytest.approx(2 * x_max_4)
    assert y_min_8 == pytest.approx(2 * y_min_4)
    assert y_max_8 == pytest.approx(2 * y_max_4)


def test_x_min_is_negative():
    """x_min must be negative: the viewport extends west (land) of the origin."""
    x_min, _, _, _ = solve_viewport(8.0, 1.78)
    assert x_min < 0.0


def test_all_bounds_ordered():
    """Bounds must be a valid non-empty interval in both axes."""
    x_min, x_max, y_min, y_max = solve_viewport(8.0, 1.78)
    assert x_min < x_max
    assert y_min < y_max


def test_coast_frac_zero_land_is_left_edge():
    """coast_frac_from_left=0 means the reference is flush with the west edge."""
    with pytest.raises(ValueError):
        # Exactly 0 is not a valid design choice (zero land context)
        solve_viewport(8.0, 1.78, coast_frac_from_left=0.0)


def test_invalid_offshore_range_raises():
    with pytest.raises(ValueError):
        solve_viewport(offshore_range_nm=0.0, panel_aspect=1.78)


def test_invalid_panel_aspect_raises():
    with pytest.raises(ValueError):
        solve_viewport(offshore_range_nm=8.0, panel_aspect=0.0)


def test_invalid_coast_frac_raises():
    with pytest.raises(ValueError):
        solve_viewport(8.0, 1.78, coast_frac_from_left=1.0)


def test_wider_panel_gives_smaller_y_span():
    """A wider (lower aspect) panel shows less north/south for the same offshore range."""
    _, _, y_min_tall, y_max_tall = solve_viewport(8.0, panel_aspect=2.0)
    _, _, y_min_wide, y_max_wide = solve_viewport(8.0, panel_aspect=1.0)
    y_span_tall = y_max_tall - y_min_tall
    y_span_wide = y_max_wide - y_min_wide
    assert y_span_tall > y_span_wide


def test_representative_hybrid_renderer_values():
    """For the hybrid renderer panel (~1.78 aspect, 8 NM offshore) the viewport
    should extend roughly 9 NM north and south and about 2 NM west."""
    x_min, x_max, y_min, y_max = solve_viewport(
        offshore_range_nm=8.0,
        panel_aspect=1.779,
        coast_frac_from_left=0.21,
    )
    # x_max = 8 NM exactly
    assert x_max == pytest.approx(8.0 * NM)
    # x_min ≈ -2.13 NM (land context)
    assert x_min == pytest.approx(-0.21 / 0.79 * 8.0 * NM, rel=1e-3)
    # y_half ≈ 9 NM (panels differ slightly so use ±10 % tolerance)
    y_half_nm = (y_max - y_min) / 2 / NM
    assert 8.0 < y_half_nm < 10.5


# ---------------------------------------------------------------------------
# Reference location — The Palms by default
# ---------------------------------------------------------------------------

def test_reference_location_is_the_palms():
    """Default reference must be The Palms (26.155531°N, 80.100832°W)."""
    assert REF_LAT == pytest.approx(26.155531, abs=1e-4)
    assert REF_LON == pytest.approx(-80.100832, abs=1e-4)


def test_port_everglades_is_south_of_reference():
    """Port Everglades inlet (26.09°N) must be south of The Palms (26.16°N)."""
    from harbor_view.chart.geometry import to_xy
    _x_pe, y_pe = to_xy(26.0906, -80.1095)
    assert y_pe < 0.0, (
        "Port Everglades should be south (negative y) of The Palms reference"
    )


def test_port_everglades_within_8nm_offshore_viewport():
    """Port Everglades inlet must be visible in the default 8 NM viewport."""
    from harbor_view.chart.geometry import to_xy
    x_pe, y_pe = to_xy(26.0906, -80.1095)
    # Use a conservative aspect (the procedural renderer's ~1.87)
    x_min, x_max, y_min, y_max = solve_viewport(8.0, panel_aspect=1.87)
    assert x_min <= x_pe <= x_max, f"Port Everglades x={x_pe:.0f} outside [{x_min:.0f}, {x_max:.0f}]"
    assert y_min <= y_pe <= y_max, f"Port Everglades y={y_pe:.0f} outside [{y_min:.0f}, {y_max:.0f}]"
