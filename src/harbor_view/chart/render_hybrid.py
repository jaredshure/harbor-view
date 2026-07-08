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
  - The map panel's geographic extent is derived from compute_view_window()
    using the reference image's figure size. This produces a viewport
    aspect ratio (≈ 1.78) that differs slightly from the procedural
    renderer (≈ 1.87), so vessel positions may be offset a few hundred
    metres from the background coastline. Acceptable for a concept proof;
    a later pass could calibrate reference tie-points.
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
        "assets", "harbor-view-reference-bw.PNG",
    )
)


def render_hybrid(
    output_path: str = "output/harbor_view_hybrid.png",
    vessel_provider: VesselProvider | None = None,
) -> str:
    """Render Harbor View in hybrid mode and write a PNG to output_path.

    The reference artwork provides the cartographic background;
    vessel_provider supplies the live vessel data to draw on top.
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
    # Avoids stretching the artwork. Vessel sizes will be proportionally
    # smaller than the procedural renderer (image is roughly half the
    # linear size), which is acceptable for a concept proof.
    fig_w_in = img_w / _DPI
    fig_h_in = img_h / _DPI
    fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=_DPI)
    fig.patch.set_facecolor("white")

    # --- Full-figure axes: reference artwork as background -----------------
    bg_ax = fig.add_axes([0, 0, 1, 1])
    bg_ax.imshow(bg, aspect="auto", origin="upper")
    bg_ax.set_axis_off()
    bg_ax.set_zorder(0)

    # --- Map overlay axes --------------------------------------------------
    # Positioned at the same fractional coordinates as the procedural
    # renderer's map panel. The background is transparent so the artwork
    # shows through; only vessel marks and labels are added.
    m = MARGIN_FRAC
    map_left = SIDEBAR_FRAC + m * 0.6
    map_w = 1.0 - map_left - m
    map_ax = fig.add_axes([map_left, m, map_w, 1.0 - 2 * m])
    map_ax.patch.set_alpha(0.0)
    map_ax.set_axis_off()
    map_ax.set_zorder(1)

    # Coordinate system: same derivation as the procedural renderer.
    # compute_view_window() uses the axes physical size in inches, which
    # differs from the procedural renderer because this figure is smaller.
    # See module docstring for the known offset this introduces.
    x_min, x_max, y_min, y_max = compute_view_window(map_ax)
    map_ax.set_xlim(x_min, x_max)
    map_ax.set_ylim(y_min, y_max)
    map_ax.set_aspect("equal")

    # --- Vessel overlay ----------------------------------------------------
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
