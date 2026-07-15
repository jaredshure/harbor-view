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
    MARGIN_FRAC,
    SIDEBAR_FRAC,
    VIEW_HALF_HEIGHT_NM,
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


def render_hybrid(
    output_path: str = "output/harbor_view_hybrid.png",
    vessel_provider: VesselProvider | None = None,
) -> str:
    """Render Harbor View in hybrid mode and write a PNG to output_path.

    The reference artwork provides the cartographic background;
    vessel_provider supplies the live vessel data to draw on top.

    Three-layer compositing:
      Layer 0 (bg_ax): full artwork, uncalibrated — sidebar preserved.
      Layer 1 (map_bg_ax): artwork map strip at calibrated geographic
        coordinates — overwrites the map region of layer 0.
      Layer 2 (map_ax): live vessel overlay, transparent background.
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
    # The sidebar columns are only shown here; the map panel region is
    # overwritten by the calibrated layer below.
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

    # --- Layer 1: calibrated map artwork -----------------------------------
    # Crop the artwork to the column range that corresponds to the map
    # panel, then display it at calibrated geographic coordinates so its
    # geographic features align with the vessel overlay.
    # Areas outside the calibrated extent that are still within the panel
    # (can occur if scale < 1) show the uncalibrated artwork from layer 0.
    map_col_px = int(round(map_left * img_w))
    map_crop = bg[:, map_col_px:]

    cal_x_min, cal_x_max, cal_y_min, cal_y_max = _calibrated_map_extent(
        x_min, x_max, y_min, y_max,
        scale_x=HYBRID_MAP_SCALE_X,
        scale_y=HYBRID_MAP_SCALE_Y,
        offset_x=HYBRID_MAP_OFFSET_X,
        offset_y=HYBRID_MAP_OFFSET_Y,
    )
    logger.debug(
        "Calibrated map extent: x=[%.1f, %.1f] y=[%.1f, %.1f]",
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

    # --- Save --------------------------------------------------------------
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fig.savefig(output_path, dpi=_DPI, facecolor="white")
    plt.close(fig)
    logger.info("Hybrid render saved to %s", output_path)
    return output_path
