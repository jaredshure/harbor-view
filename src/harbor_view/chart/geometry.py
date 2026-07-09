"""Coastline geometry for the Harbor View chart scene.

Coordinates are local projected meters in a simple equirectangular
approximation, origin at the configured viewport center
(HARBOR_VIEW_VIEWPORT_LAT/LON). +x = east (offshore), +y = north.

The shoreline control points represent the real Fort Lauderdale
coastline — this is a hand-built approximation, not a literal NOAA
chart extract (see docs/task-001-notes.md for why). The viewport
center shifts which part of that coastline is at the origin, and
therefore which part of the scene occupies the composition's centre.
"""
from __future__ import annotations

import os

import numpy as np
from scipy.interpolate import CubicSpline

# Viewport/projection reference point. Configurable so the composition
# centre can be tuned without touching rendering code. Reads the same
# env vars as harbor_view.config.DEFAULT_CONFIG.
REF_LAT = float(os.environ.get("HARBOR_VIEW_VIEWPORT_LAT", "26.0906"))
REF_LON = float(os.environ.get("HARBOR_VIEW_VIEWPORT_LON", "-80.1095"))
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * np.cos(np.radians(REF_LAT))

NM = 1852.0  # meters per nautical mile


def to_xy(lat: float, lon: float) -> tuple[float, float]:
    """Project lat/lon (degrees) to local meters from the reference point."""
    x = (lon - REF_LON) * _M_PER_DEG_LON
    y = (lat - REF_LAT) * _M_PER_DEG_LAT
    return x, y


# Hand-placed control points approximating the real shoreline curvature
# from south of Port Everglades up past the Galt Ocean Mile stretch
# (where The Palms condominiums sit, ~26.13 N).
_CONTROL_LATLON = [
    (25.950, -80.0905),
    (25.995, -80.0960),
    (26.030, -80.1005),
    (26.060, -80.1035),
    (26.075, -80.1058),
    (26.0906, -80.1095),  # inlet centerline
    (26.106, -80.1062),
    (26.122, -80.1035),
    (26.138, -80.1008),
    (26.160, -80.0980),
    (26.190, -80.0945),
    (26.230, -80.0900),
]


def _spline_curve(n_points: int = 600):
    ctrl = np.array([to_xy(la, lo) for la, lo in _CONTROL_LATLON])
    t = np.linspace(0, 1, len(ctrl))
    t_fine = np.linspace(0, 1, n_points)
    cs_x = CubicSpline(t, ctrl[:, 0])
    cs_y = CubicSpline(t, ctrl[:, 1])
    x, y = cs_x(t_fine), cs_y(t_fine)

    dx = np.gradient(x, t_fine)
    dy = np.gradient(y, t_fine)
    norm = np.hypot(dx, dy)
    tx, ty = dx / norm, dy / norm
    nx, ny = ty, -tx
    if nx.mean() > 0:  # ensure normal points west (into the island)
        nx, ny = -nx, -ny
    return x, y, nx, ny


def _clip_and_pin_to_bounds(x, y, nx, ny, y_min, y_max):
    """Trim (or extrapolate) a curve so it spans exactly [y_min, y_max],
    with each returned array's first/last point pinned exactly at
    y_min/y_max respectively. This guarantees that polygons built from
    these arrays have a flat, axis-aligned closing edge at top and
    bottom instead of a ragged diagonal one.
    """
    # Keep points inside the window, then pin the very first/last sample
    # to the exact bound via linear interpolation/extrapolation using
    # the nearest two samples (curve is densely sampled, so linear is fine).
    def pin_end(y_target, idx_near, idx_next):
        if x[idx_near] == x[idx_next] and y[idx_near] == y[idx_next]:
            return x[idx_near], y_target, nx[idx_near], ny[idx_near]
        frac = (y_target - y[idx_near]) / (y[idx_next] - y[idx_near])
        xt = x[idx_near] + frac * (x[idx_next] - x[idx_near])
        nxt = nx[idx_near] + frac * (nx[idx_next] - nx[idx_near])
        nyt = ny[idx_near] + frac * (ny[idx_next] - ny[idx_near])
        return xt, y_target, nxt, nyt

    inside = (y >= y_min) & (y <= y_max)
    if not inside.any():
        raise ValueError("view window does not overlap curve data")

    first_idx = np.argmax(inside)
    last_idx = len(y) - 1 - np.argmax(inside[::-1])

    # Pin bottom (y_min): interpolate between the last outside-below
    # sample and the first inside sample (or extrapolate if curve
    # doesn't reach that far).
    lo_near = max(first_idx - 1, 0)
    x0, y0, nx0, ny0 = pin_end(y_min, lo_near, first_idx) if lo_near != first_idx else (x[first_idx], y_min, nx[first_idx], ny[first_idx])

    hi_next = min(last_idx + 1, len(y) - 1)
    x1, y1, nx1, ny1 = pin_end(y_max, last_idx, hi_next) if hi_next != last_idx else (x[last_idx], y_max, nx[last_idx], ny[last_idx])

    xs = np.concatenate([[x0], x[first_idx:last_idx + 1], [x1]])
    ys = np.concatenate([[y_min], y[first_idx:last_idx + 1], [y_max]])
    nxs = np.concatenate([[nx0], nx[first_idx:last_idx + 1], [nx1]])
    nys = np.concatenate([[ny0], ny[first_idx:last_idx + 1], [ny1]])
    return xs, ys, nxs, nys


def build_scene(view_half_height_nm: float = 4.5):
    """Build all chart geometry, clipped to exactly +/- view_half_height_nm.

    Returns a dict of named arrays/values in local meters:
      - 'ocean_shore': (x, y) the barrier island's ocean-facing edge,
         spanning exactly the view's y-bounds (flat top/bottom ends)
      - 'icw_shore': (x, y) the barrier island's ICW-facing edge, same
         y-bounds
      - 'mainland_shore': (x, y) far (west) edge of the ICW, same y-bounds
      - 'is_open': boolean mask over those arrays marking the inlet gap
      - 'inlet_channel_polygon': (x, y) closed polygon for the inlet
         channel cut, built directly from ocean_shore/icw_shore at the
         gap so it is guaranteed to align with the island fill
      - 'y_bounds': (y_min, y_max) actually used
    """
    raw_x, raw_y, raw_nx, raw_ny = _spline_curve()

    y_min, y_max = -view_half_height_nm * NM, view_half_height_nm * NM
    ox, oy, nx, ny = _clip_and_pin_to_bounds(raw_x, raw_y, raw_nx, raw_ny, y_min, y_max)

    # Priority 1 (Sprint 2.5): the ocean-facing shoreline itself -- a
    # clean cubic spline -- reads as too uniform/too straight at chart
    # scale. Perturb it with the same family of low-frequency,
    # deterministic sine terms used for island_width below, applied
    # along the LOCAL NORMAL direction (not raw x) so the wobble stays
    # geometrically sensible as the shore's bearing changes, and fades
    # to zero near the inlet so the channel cut remains clean and the
    # endpoints stay pinned exactly at y_min/y_max.
    dist_from_inlet_raw = np.abs(oy - 0.0)
    shore_wobble = (
        14 * np.sin(oy / NM * 2.3 + 1.1)
        + 8 * np.sin(oy / NM * 5.1 + 0.4)
        + 5 * np.sin(oy / NM * 9.7 + 2.6)
    )
    fade_in = 1 - np.exp(-(dist_from_inlet_raw / 280) ** 2)
    # Also fade out within ~150m of the exact pinned endpoints so the
    # flush top/bottom polygon edges used elsewhere are undisturbed.
    dist_from_top = np.abs(oy - y_max)
    dist_from_bottom = np.abs(oy - y_min)
    edge_fade = np.minimum(dist_from_top, dist_from_bottom)
    edge_fade = np.clip(edge_fade / 150.0, 0, 1)
    shore_wobble *= fade_in * edge_fade
    ox = ox - nx * shore_wobble
    oy = oy - ny * shore_wobble
    oy[0], oy[-1] = y_min, y_max  # re-pin exactly (edge_fade already ~0 here, but be exact)

    # Island width: narrows to a real gap right at the inlet (y=0),
    # widens away from it. The base taper establishes the inlet's
    # "waist"; layered low-frequency sine/cosine terms (NOT random
    # noise, so the result is deterministic and reproducible) add
    # gentle, irregular undulation along the island's length so it
    # reads as a natural barrier-island edge rather than a uniform,
    # too-clean band. Amplitude is kept well within the island's own
    # width so it can't widen the visible land area or create new
    # inlets -- it only perturbs the existing edge.
    dist_from_inlet = np.abs(oy - 0.0)
    base_width = 360 - 360 * np.exp(-(dist_from_inlet / 230) ** 1.5)
    y_nm = oy / NM
    irregularity = (
        18 * np.sin(y_nm * 1.7 + 0.6)
        + 11 * np.sin(y_nm * 3.9 + 2.1)
        + 7 * np.sin(y_nm * 7.3 + 0.2)
    )
    # Fade the irregularity to zero right at the inlet so the channel
    # cut stays clean and geometrically simple there.
    irregularity *= 1 - np.exp(-(dist_from_inlet / 260) ** 2)
    island_width = np.clip(base_width + irregularity, 0, 380)

    icw_x = ox + nx * island_width
    icw_y = oy + ny * island_width
    icw_y[0], icw_y[-1] = y_min, y_max  # snap endpoints exactly to bounds

    # Mainland edge: offset from a SMOOTHED version of the shoreline
    # normal/position (rather than the raw curve) so the offset doesn't
    # amplify the shoreline's curvature into an exaggerated wiggle once
    # pushed far inland. This keeps the mainland edge calm, since it's
    # mostly a background shape the eye shouldn't catch on.
    from scipy.ndimage import uniform_filter1d
    smooth_win = max(5, len(ox) // 12)
    ox_smooth = uniform_filter1d(ox, smooth_win, mode="nearest")
    oy_smooth = oy  # y already pinned/monotonic; keep as-is
    nx_smooth = uniform_filter1d(nx, smooth_win, mode="nearest")
    ny_smooth = uniform_filter1d(ny, smooth_win, mode="nearest")
    renorm = np.hypot(nx_smooth, ny_smooth)
    nx_smooth, ny_smooth = nx_smooth / renorm, ny_smooth / renorm

    mainland_inland_offset = 780
    mainland_x = ox_smooth + nx_smooth * (island_width * 0.55 + mainland_inland_offset)
    mainland_y = oy_smooth + ny_smooth * (island_width * 0.55 + mainland_inland_offset)
    mainland_y[0], mainland_y[-1] = y_min, y_max  # snap endpoints exactly to bounds

    # Inlet gap mask, with a little extra padding so the visible channel
    # reads clearly rather than as a thin pinch point.
    GAP_PAD_M = 90.0
    near_zero_width = island_width < 25
    if near_zero_width.any():
        gap_lo = oy[near_zero_width].min() - GAP_PAD_M
        gap_hi = oy[near_zero_width].max() + GAP_PAD_M
    else:
        gap_lo, gap_hi = -GAP_PAD_M, GAP_PAD_M
    is_open = (oy >= gap_lo) & (oy <= gap_hi)

    # Build the channel polygon DIRECTLY from ocean_shore/icw_shore at
    # the gap rows, so it is geometrically guaranteed to align with
    # whatever the island fill boundary actually is at those same rows
    # (no hardcoded coordinates).
    gap_idx = np.where(is_open)[0]
    if len(gap_idx) >= 2:
        i0, i1 = gap_idx[0], gap_idx[-1]
        # Channel spans from the ICW-side shore out past the ocean
        # shore, across the full open rows, as a simple quad strip.
        chan_ocean_x = ox[i0:i1 + 1]
        chan_ocean_y = oy[i0:i1 + 1]
        chan_icw_x = icw_x[i0:i1 + 1]
        chan_icw_y = icw_y[i0:i1 + 1]
        # Extend slightly past the ocean shore so the channel visually
        # connects to open water rather than stopping exactly at the
        # (now-removed) shoreline.
        ext = 250.0
        chan_outer_x = chan_ocean_x + ext  # push east into the ocean
        poly_x = np.concatenate([chan_icw_x, chan_outer_x[::-1]])
        poly_y = np.concatenate([chan_icw_y, chan_ocean_y[::-1]])
    else:
        poly_x, poly_y = np.array([]), np.array([])

    return {
        "ocean_shore": (ox, oy),
        "icw_shore": (icw_x, icw_y),
        "mainland_shore": (mainland_x, mainland_y),
        "is_open": is_open,
        "island_width": island_width,
        "inlet_channel_polygon": (poly_x, poly_y),
        "y_bounds": (y_min, y_max),
    }
