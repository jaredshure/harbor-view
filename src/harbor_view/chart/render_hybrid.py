"""Hybrid renderer — static artwork background + live vessel overlay.

Sprint 7 experiment. Enabled via environment variable:

    HARBOR_VIEW_RENDER_MODE=hybrid

Loads ``assets/design/harbor-view-reference-bw.PNG`` as the cartographic
background, then overlays live vessel data on top using the same coordinate
system and vessel-drawing code as the procedural renderer.

Everything that comes from the base artwork (shoreline, depth contours,
bathymetry, compass, scale bar, sidebar) is left untouched.

Known limitations (first pass, by design):
  - The reference image is 1087×1447 px; the output will be that size
    rather than the procedural renderer's 2000×2800. Vessel glyph sizes
    are proportionally smaller as a result.
  - The reference image's sidebar content (time, weather, tide) is static
    artwork; no live values are overlaid in this pass.
"""
from __future__ import annotations

import logging
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from harbor_view.chart.render import (
    COAST_FRAC_FROM_LEFT,
    MARGIN_FRAC,
    SIDEBAR_FRAC,
    compute_view_window,
    draw_fleet,
)
from harbor_view.providers import PlaceholderProvider, VesselProvider

logger = logging.getLogger("harbor_view.chart.render_hybrid")

# DPI for output; kept the same as the procedural renderer so vessel line
# weights and font sizes render at the same physical size if the image is
# printed at the same dimensions.
_DPI = 200

# Path to the reference artwork background.
_BG_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),   # .../src/harbor_view/chart/
        "..", "..", "..",            # -> repo root
        "assets", "design", "harbor-view-reference-bw.PNG",
    )
)

# ---------------------------------------------------------------------------
# Map calibration constants
# ---------------------------------------------------------------------------
# These align the artwork's map panel with the live vessel overlay's
# geographic coordinate system.  Only the artwork's map strip is adjusted;
# the sidebar region is never touched.
#
# Coordinate convention: scales are multiplicative factors on the viewport
# span, centred on the viewport midpoint; offsets are fractions of the
# viewport span (+ = east / north).  Both are dimensionless and remain
# stable if DPI or figure size changes.
#
# HYBRID_MAP_SCALE_X = 0.95: the artwork was produced at the procedural
# renderer's 2000×2800 figure (aspect 1.40).  The hybrid figure is
# 1087×1447 (aspect 1.331), which causes compute_view_window() to widen
# the x-span by ~5 %.  Scaling the artwork to 0.95 of the viewport width
# corrects this so geographic features stay in register.  Tune the
# remaining three constants if a side-by-side comparison reveals a
# residual north–south or east–west shift.
HYBRID_MAP_SCALE_X  = 0.95  # x-axis scale of artwork map region (< 1 → narrower extent)
HYBRID_MAP_SCALE_Y  = 1.00  # y-axis scale of artwork map region (1.0 = full viewport height)
HYBRID_MAP_OFFSET_X = 0.00  # x-shift as fraction of viewport x-span (+ = east / offshore)
HYBRID_MAP_OFFSET_Y = 0.00  # y-shift as fraction of viewport y-span (+ = north)


def _map_panel_crop_px(
    img_h: int,
    img_w: int,
    margin_frac: float,
    map_left_frac: float,
    map_w_frac: float,
) -> tuple[int, int, int, int]:
    """Return (row_start, row_end, col_start, col_end) for the map panel crop.

    Converts the fractional figure layout to pixel bounds in image
    (numpy array) coordinates, where row 0 is the TOP of the image.

    The figure uses bottom-up y (0 = bottom, 1 = top).  An image uses
    top-down row indexing.  The map panel occupies figure y from
    ``margin_frac`` (bottom) to ``1 - margin_frac`` (top), which maps to
    image rows ``margin_frac * img_h`` (top of panel) through
    ``(1 - margin_frac) * img_h`` (bottom of panel).
    """
    col_start = int(round(map_left_frac * img_w))
    col_end   = int(round((map_left_frac + map_w_frac) * img_w))
    # figure y = 1 - margin_frac (panel top)  →  image row = margin_frac * img_h
    # figure y = margin_frac     (panel bottom) →  image row = (1 - margin_frac) * img_h
    row_start = int(round(margin_frac * img_h))
    row_end   = int(round((1.0 - margin_frac) * img_h))
    return row_start, row_end, col_start, col_end


def _calibrated_map_extent(
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    scale_x: float = HYBRID_MAP_SCALE_X,
    scale_y: float = HYBRID_MAP_SCALE_Y,
    offset_x: float = HYBRID_MAP_OFFSET_X,
    offset_y: float = HYBRID_MAP_OFFSET_Y,
) -> tuple[float, float, float, float]:
    """Return the calibrated imshow extent for the artwork map crop.

    The extent defines the geographic coordinates that the artwork's
    left, right, bottom, and top edges correspond to, letting imshow
    align the artwork with the overlay coordinate system.  Scaling is
    centred on the viewport midpoint; offsets are in fractions of the
    full viewport span.

    Returns (cal_x_min, cal_x_max, cal_y_min, cal_y_max).
    """
    x_span = x_max - x_min
    y_span = y_max - y_min
    x_center = (x_min + x_max) / 2
    y_center = (y_min + y_max) / 2

    cal_x_min = x_center - (x_span / 2) * scale_x + offset_x * x_span
    cal_x_max = x_center + (x_span / 2) * scale_x + offset_x * x_span
    cal_y_min = y_center - (y_span / 2) * scale_y + offset_y * y_span
    cal_y_max = y_center + (y_span / 2) * scale_y + offset_y * y_span

    return cal_x_min, cal_x_max, cal_y_min, cal_y_max


def _draw_calibration_debug(
    ax,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> None:
    """Overlay calibration guide lines on the map axes.

    Only called when HARBOR_VIEW_HYBRID_CALIBRATION_DEBUG is set.
    Normal output is never affected.

    Draws:
      - Dashed panel centrelines (red) at the viewport midpoint
      - Primary landmark crosshair (red) at (0, 0) — The Palms, the reference
        location and local coordinate origin
      - Port Everglades secondary landmark (blue) at its position in local
        coords from The Palms (~865 m west, ~7 229 m south), if within viewport
      - Calibrated extent boundary (dark grey dashes) showing the four edges of
        the artwork's calibrated geographic coverage
      - Viewport bounds label (grey) for screenshot comparison
    """
    from harbor_view.chart.geometry import to_xy

    x_span = x_max - x_min
    y_span = y_max - y_min
    x_center = (x_min + x_max) / 2
    y_center = (y_min + y_max) / 2
    cr = x_span * 0.018  # crosshair arm radius

    red  = "#E8003A"
    blue = "#0055CC"
    grey = "#444444"
    Z    = 30  # zorder above vessels

    # --- Panel centrelines --------------------------------------------------
    ax.axhline(y_center, color=red, ls="--", lw=0.8, alpha=0.70, zorder=Z)
    ax.axvline(x_center, color=red, ls="--", lw=0.8, alpha=0.70, zorder=Z)
    ax.text(
        x_center + x_span * 0.01, y_max - y_span * 0.02,
        "panel centre",
        color=red, fontsize=5.0, ha="left", va="top", zorder=Z + 1, alpha=0.85,
    )

    # --- Primary landmark: The Palms (origin) --------------------------------
    # The Palms is the reference location and local coordinate origin (0, 0).
    ax.plot([-cr, cr], [0.0, 0.0], color=red, lw=1.2, zorder=Z + 1, alpha=0.90)
    ax.plot([0.0, 0.0], [-cr, cr], color=red, lw=1.2, zorder=Z + 1, alpha=0.90)
    ax.scatter([0.0], [0.0], color=red, s=12, zorder=Z + 2, alpha=0.95)
    ax.text(
        cr * 1.3, cr * 0.4,
        "The Palms\n(origin, x=0, y=0)",
        color=red, fontsize=4.8, ha="left", va="bottom", zorder=Z + 1, alpha=0.85,
    )

    # --- Secondary landmark: Port Everglades inlet ---------------------------
    # The old reference point, kept as a geographic landmark.
    # Position derived from the actual coordinates via to_xy() using the
    # current REF_LAT/REF_LON (The Palms), so it stays correct if the
    # reference location is reconfigured via env vars.
    PORT_EVERGLADES_LAT = 26.0906
    PORT_EVERGLADES_LON = -80.1095
    x_pe, y_pe = to_xy(PORT_EVERGLADES_LAT, PORT_EVERGLADES_LON)

    if x_min <= x_pe <= x_max and y_min <= y_pe <= y_max:
        cr_pe = cr * 0.65
        ax.plot([x_pe - cr_pe, x_pe + cr_pe], [y_pe, y_pe],
                color=blue, lw=1.0, zorder=Z + 1, alpha=0.85)
        ax.plot([x_pe, x_pe], [y_pe - cr_pe, y_pe + cr_pe],
                color=blue, lw=1.0, zorder=Z + 1, alpha=0.85)
        ax.scatter([x_pe], [y_pe], color=blue, s=8, zorder=Z + 2, alpha=0.90)
        ax.text(
            x_pe + cr_pe * 1.3, y_pe,
            f"Port Everglades\ninlet  ({x_pe/1852:.1f},{y_pe/1852:.1f}) NM",
            color=blue, fontsize=4.5, ha="left", va="center",
            zorder=Z + 1, alpha=0.80,
        )

    # --- Calibrated extent boundary -----------------------------------------
    cal = _calibrated_map_extent(
        x_min, x_max, y_min, y_max,
        scale_x=HYBRID_MAP_SCALE_X,
        scale_y=HYBRID_MAP_SCALE_Y,
        offset_x=HYBRID_MAP_OFFSET_X,
        offset_y=HYBRID_MAP_OFFSET_Y,
    )
    cal_x_min, cal_x_max, cal_y_min, cal_y_max = cal
    dash = (0, (4, 2))
    for xv in (cal_x_min, cal_x_max):
        ax.axvline(xv, color=grey, ls=dash, lw=0.7, alpha=0.60, zorder=Z)
    for yv in (cal_y_min, cal_y_max):
        ax.axhline(yv, color=grey, ls=dash, lw=0.7, alpha=0.60, zorder=Z)
    ax.text(
        cal_x_max - x_span * 0.01, cal_y_max + y_span * 0.005,
        "cal extent",
        color=grey, fontsize=4.5, ha="right", va="bottom", zorder=Z + 1, alpha=0.70,
    )

    # --- Viewport info label ------------------------------------------------
    _NM = 1852.0
    ax.text(
        x_max - x_span * 0.01, y_max - y_span * 0.01,
        (
            f"offshore  {x_max/_NM:.1f} NM\n"
            f"x [{x_min/_NM:.2f}, {x_max/_NM:.2f}] NM\n"
            f"y [{y_min/_NM:.2f}, {y_max/_NM:.2f}] NM"
        ),
        color=grey, fontsize=4.5, ha="right", va="top", zorder=Z + 1, alpha=0.65,
    )


def render_hybrid(
    output_path: str = "output/harbor_view_hybrid.png",
    vessel_provider: VesselProvider | None = None,
) -> str:
    """Render Harbor View in hybrid mode and write a PNG to output_path.

    The reference artwork provides the cartographic background;
    vessel_provider supplies the live vessel data to draw on top.

    Three-layer compositing (by zorder):
      0  bg_ax       — Full artwork, uncalibrated; sidebar preserved here.
      0.5 map_mask_ax — Opaque neutral fill over the map panel only.
                        Prevents the uncalibrated map region in layer 0
                        from bleeding through around the calibrated image.
      1  map_bg_ax   — Artwork cropped to the exact map-panel rectangle,
                        placed at calibrated geographic coordinates.
      2  map_ax      — Live vessel overlay, transparent background.

    Set HARBOR_VIEW_HYBRID_CALIBRATION_DEBUG=1 to add guide lines useful
    for screenshot comparison.  Normal output is never affected.
    """
    if vessel_provider is None:
        vessel_provider = PlaceholderProvider()

    if not os.path.exists(_BG_PATH):
        raise FileNotFoundError(
            f"Hybrid renderer requires the reference artwork at {_BG_PATH!r}. "
            "Check that the file is present in the repository."
        )

    # --- Load background ---------------------------------------------------
    bg = mpimg.imread(_BG_PATH)   # (H, W, 3) float32 in [0, 1]
    img_h, img_w = bg.shape[:2]
    logger.info("Hybrid renderer: background image %d×%d px", img_w, img_h)

    # --- Figure at the reference image's native pixel dimensions -----------
    fig_w_in = img_w / _DPI
    fig_h_in = img_h / _DPI
    fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=_DPI)
    fig.patch.set_facecolor("white")

    # --- Layout constants (same fractional coords as procedural renderer) --
    m = MARGIN_FRAC
    map_left = SIDEBAR_FRAC + m * 0.6
    map_w = 1.0 - map_left - m

    # --- Layer 0: full artwork as uncalibrated base ------------------------
    # The sidebar columns are rendered exclusively here; no other layer
    # touches them.
    bg_ax = fig.add_axes([0, 0, 1, 1], label="bg")
    bg_ax.imshow(bg, aspect="auto", origin="upper")
    bg_ax.set_axis_off()
    bg_ax.set_zorder(0)

    # --- Derive geographic limits from the map panel's physical size -------
    # Create map_ax first so compute_view_window() can read its position.
    map_ax = fig.add_axes([map_left, m, map_w, 1.0 - 2 * m], label="map_overlay")
    map_ax.patch.set_alpha(0.0)
    map_ax.set_axis_off()
    map_ax.set_zorder(2)
    x_min, x_max, y_min, y_max = compute_view_window(map_ax)

    # --- Layer 0.5: neutral mask over map panel ----------------------------
    # Sits between the uncalibrated full-artwork base and the calibrated
    # map layer.  Opaque white fill ensures no uncalibrated shoreline,
    # contour, or compass artwork from layer 0 shows through around the
    # edges of the calibrated image (which may not fill 100 % of the panel
    # when scale < 1 or offsets push part of the image out of view).
    map_mask_ax = fig.add_axes([map_left, m, map_w, 1.0 - 2 * m], label="map_mask")
    map_mask_ax.set_axis_off()
    map_mask_ax.patch.set_facecolor("white")
    map_mask_ax.set_zorder(0.5)

    # --- Layer 1: calibrated map artwork -----------------------------------
    # Crop the artwork to the exact pixel rectangle that corresponds to the
    # map panel in the artwork image (excluding sidebar, top/bottom margins).
    # This crop is then placed at calibrated geographic coordinates via the
    # imshow extent parameter, so the artwork's geographic features align
    # with the vessel overlay.
    row_start, row_end, col_start, col_end = _map_panel_crop_px(
        img_h, img_w, m, map_left, map_w,
    )
    map_crop = bg[row_start:row_end, col_start:col_end]
    logger.debug(
        "Map panel crop: rows %d–%d, cols %d–%d  (%d×%d px)",
        row_start, row_end, col_start, col_end,
        col_end - col_start, row_end - row_start,
    )

    cal_x_min, cal_x_max, cal_y_min, cal_y_max = _calibrated_map_extent(
        x_min, x_max, y_min, y_max,
        scale_x=HYBRID_MAP_SCALE_X,
        scale_y=HYBRID_MAP_SCALE_Y,
        offset_x=HYBRID_MAP_OFFSET_X,
        offset_y=HYBRID_MAP_OFFSET_Y,
    )
    logger.debug(
        "Calibrated extent: x=[%.1f, %.1f] y=[%.1f, %.1f]",
        cal_x_min, cal_x_max, cal_y_min, cal_y_max,
    )

    map_bg_ax = fig.add_axes([map_left, m, map_w, 1.0 - 2 * m], label="map_bg")
    map_bg_ax.set_axis_off()
    map_bg_ax.patch.set_alpha(0.0)
    map_bg_ax.set_zorder(1)
    map_bg_ax.imshow(
        map_crop,
        extent=[cal_x_min, cal_x_max, cal_y_min, cal_y_max],
        aspect="auto",
        origin="upper",
        zorder=0,
    )
    map_bg_ax.set_xlim(x_min, x_max)
    map_bg_ax.set_ylim(y_min, y_max)
    map_bg_ax.set_aspect("equal")

    # --- Layer 2: vessel overlay -------------------------------------------
    map_ax.set_xlim(x_min, x_max)
    map_ax.set_ylim(y_min, y_max)
    map_ax.set_aspect("equal")

    vessels = vessel_provider.get_vessels()
    logger.info("Hybrid renderer: drawing %d vessel(s)", len(vessels))
    draw_fleet(map_ax, vessels)

    # --- Optional calibration debug guides ---------------------------------
    if os.environ.get("HARBOR_VIEW_HYBRID_CALIBRATION_DEBUG"):
        _draw_calibration_debug(map_ax, x_min, x_max, y_min, y_max)

    # --- Save --------------------------------------------------------------
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fig.savefig(output_path, dpi=_DPI, facecolor="white")
    plt.close(fig)
    logger.info("Hybrid render saved to %s", output_path)
    return output_path
