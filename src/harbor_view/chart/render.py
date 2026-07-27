"""Harbor View chart renderer.

Produces output/harbor_view.png: a static nautical-chart-style image
showing vessels near Port Everglades / Fort Lauderdale.

As of Sprint 3, this module knows nothing about where vessel data
comes from. `render()` takes a `harbor_view.providers.VesselProvider`
and draws whatever `.get_vessels()` returns -- placeholder fleet, live
AIS (once implemented), recorded playback, or simulation, all look the
same to this file. See docs/sprint-003-notes.md for the provider
architecture this module was refactored to depend on.

The visual design (Sprints 1-2.5) is frozen as of Sprint 2.5; this
module should not change layout, color, typography, or composition
without a functional reason -- see CLAUDE.md.

Run directly: PYTHONPATH=src python3 src/harbor_view/chart/render.py
"""
from __future__ import annotations

import datetime as _dt
import math
import os
from zoneinfo import ZoneInfo

from harbor_view.config import DEFAULT_CONFIG, HarborConfig

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.transforms import Affine2D
import numpy as np

from harbor_view.chart.geometry import build_scene, to_xy, NM
from harbor_view.chart.viewport import solve_viewport
from harbor_view.chart.glyphs import GLYPH_BY_KIND, home_marker_path
from harbor_view.providers import VesselProvider, PlaceholderProvider

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "output", "harbor_view.png"
)

# ---------------------------------------------------------------------------
# Palette — monochrome warm paper, matching the reference design.
# Sprint 7.4: removed blue-teal ocean fill; ocean and land now share the
# same warm cream/gray paper tone, differentiated by shoreline strokes and
# depth contour lines rather than fill color.
# ---------------------------------------------------------------------------
COLOR_OCEAN = "#EAE6DC"
COLOR_OCEAN_DEEP = "#DEDAD0"
COLOR_LAND = "#EFE6D0"
COLOR_ICW_WATER = "#EAE6DC"
COLOR_SHORE_LINE = "#8C7A56"
COLOR_CONTOUR = "#7A7368"
COLOR_LANE = "#8A867A"
COLOR_INK = "#33312C"
COLOR_INK_SOFT = "#5C5A52"
COLOR_SIDEBAR_BG = "#F4EFE3"
COLOR_RULE = "#D9D0B8"
# Sprint 2.5 (Priority 3): a hull fill blended toward the ocean tone
# rather than flat cream, so vessels sit IN the water visually instead
# of looking pasted on top of it.
COLOR_VESSEL_FILL = "#E3EDEE"
# Sprint 2.5 (Priority 4): an even lighter tone than COLOR_INK_SOFT,
# reserved for the smallest "metadata" text (vessel route lines) so
# names clearly outrank routes in the type hierarchy.
COLOR_METADATA = "#7A776C"

FONT_DISPLAY = "DejaVu Serif"
FONT_BODY = "DejaVu Sans"


# ---------------------------------------------------------------------------
# Tuning block — all five experimental knobs live here.
# Change values in this block only; everything else is derived.
# ---------------------------------------------------------------------------
# LAYOUT              "portrait"   tall chart, current production default
#                     "landscape"  wide chart, matches Waveshare 800×480 ratio (5:3)
# MAP_ORIENTATION     "north_up"   x=east, y=north (standard nautical chart)
#                     "seaward_up" rotated 90° CCW: ocean up, coast along bottom,
#                                  north=left, south/PE=right (balcony-facing view)
# INFO_PANEL_FRAC     fraction of figure width for the left info/sidebar panel
# VIEW_SEAWARD_RANGE_NM  seaward depth from The Palms, nautical miles
#                     scales the entire chart uniformly (along-shore and seaward)
# COAST_FRAC_FROM_LEFT   fraction of x-span behind the reference (land context)
#                     0.21 = 21 % land, 79 % ocean; Sprint 2 value (was 0.28)
LAYOUT                = "landscape"   # "portrait" | "landscape"
MAP_ORIENTATION       = "seaward_up"  # "north_up" | "seaward_up"
INFO_PANEL_FRAC       = 0.25
VIEW_SEAWARD_RANGE_NM = float(os.environ.get("HARBOR_VIEW_SEAWARD_RANGE_NM", "8.0"))
COAST_FRAC_FROM_LEFT  = 0.21

# Derived — do not edit below this line in the tuning block
# portrait : 10×14 in → 2000×2800 px at DPI 200
# landscape: 10×6 in  → 2000×1200 px at DPI 200  (5:3, matches Waveshare 800×480)
FIG_W_IN, FIG_H_IN = (10.0, 14.0) if LAYOUT == "portrait" else (10.0, 6.0)
DPI          = 200
SIDEBAR_FRAC = INFO_PANEL_FRAC   # alias — render_hybrid imports this name
MARGIN_FRAC  = 0.018


def map_coords(x, y):
    """Return (plot_x, plot_y) for the active MAP_ORIENTATION.

    In north_up, local x (seaward) is the horizontal axis and local y
    (along-shore) is vertical — identical to the geographic frame for an
    east-facing site.  In seaward_up the axes are transposed: y_local
    (along-shore) is horizontal and x_local (seaward) is vertical, so
    ocean extends upward and the coastline runs along the bottom.
    """
    if MAP_ORIENTATION == "seaward_up":
        return y, x
    return x, y


def build_layout(fig_w_in=FIG_W_IN, fig_h_in=FIG_H_IN):
    fig = plt.figure(figsize=(fig_w_in, fig_h_in), dpi=DPI)
    fig.patch.set_facecolor("#FFFFFF")

    m = MARGIN_FRAC
    sidebar_w = SIDEBAR_FRAC - m * 1.3
    map_left = SIDEBAR_FRAC + m * 0.6
    map_w = 1 - map_left - m

    sidebar_ax = fig.add_axes([m, m, sidebar_w, 1 - 2 * m])
    map_ax = fig.add_axes([map_left, m, map_w, 1 - 2 * m])

    for ax in (sidebar_ax, map_ax):
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

    sidebar_ax.set_facecolor(COLOR_SIDEBAR_BG)
    map_ax.set_facecolor(COLOR_OCEAN)
    return fig, sidebar_ax, map_ax


# ---------------------------------------------------------------------------
# Map geography
# ---------------------------------------------------------------------------
# VIEW_SEAWARD_RANGE_NM and COAST_FRAC_FROM_LEFT are defined in the tuning
# block above.  solve_viewport() in harbor_view.chart.viewport derives all
# geographic bounds from those two values and the map panel's aspect ratio.


def compute_view_window(map_ax) -> tuple[float, float, float, float]:
    """Return the geographic viewport in local metres for the given map panel.

    Reads the panel's physical size from the axes' figure position, then
    delegates to solve_viewport() to derive (x_min, x_max, y_min, y_max)
    so that set_aspect('equal') fills the panel with no letterboxing and
    VIEW_SEAWARD_RANGE_NM of water appears seaward of the reference.
    """
    bbox = map_ax.get_position()
    fig_w_in, fig_h_in = map_ax.get_figure().get_size_inches()
    panel_w_in = bbox.width * fig_w_in
    panel_h_in = bbox.height * fig_h_in
    panel_aspect = panel_h_in / panel_w_in

    return solve_viewport(VIEW_SEAWARD_RANGE_NM, panel_aspect, COAST_FRAC_FROM_LEFT)


def draw_basemap(map_ax, scene, x_min, x_max, y_min, y_max):
    """Ocean, mainland, ICW, barrier island, and the inlet channel cut.

    All land/water polygons are built from the SAME shoreline arrays
    (scene['ocean_shore'], scene['icw_shore'], scene['mainland_shore']),
    which are pinned exactly to [y_min, y_max] by geometry.build_scene.
    This keeps every polygon's top/bottom edge flush and axis-aligned,
    and keeps the inlet channel cut geometrically consistent with the
    island fill (both come from the same is_open mask).
    """
    ox, oy = scene["ocean_shore"]
    ix, iy = scene["icw_shore"]
    mx, my = scene["mainland_shore"]
    is_open = scene["is_open"]

    if MAP_ORIENTATION == "seaward_up":
        # y_local (north-south) on horizontal axis: north=left, south=right.
        # x_local (seaward) on vertical axis: inland=bottom, ocean=top.
        map_ax.set_xlim(y_max, y_min)
        map_ax.set_ylim(x_min, x_max)
    else:
        map_ax.set_xlim(x_min, x_max)
        map_ax.set_ylim(y_min, y_max)
    map_ax.set_aspect("equal")

    # --- Ocean base: depth gradient (shore→offshore) ---
    _ocean_cmap = mcolors.LinearSegmentedColormap.from_list(
        "ocean_depth", [COLOR_OCEAN, COLOR_OCEAN_DEEP]
    )
    if MAP_ORIENTATION == "seaward_up":
        # gradient runs bottom (inland/shore) → top (offshore) as a column vector
        ocean_grad = np.linspace(0, 1, 400).reshape(-1, 1)
        grad_extent = [y_max, y_min, x_min, x_max]
    else:
        ocean_grad = np.linspace(0, 1, 400).reshape(1, -1)
        grad_extent = [x_min, x_max, y_min, y_max]
    map_ax.imshow(
        ocean_grad,
        extent=grad_extent,
        aspect="auto",
        cmap=_ocean_cmap,
        origin="lower",
        zorder=0,
    )

    # --- Mainland block ---
    land_x = np.concatenate([mx, [x_min, x_min]])
    land_y = np.concatenate([my, [y_max, y_min]])
    map_ax.fill(*map_coords(land_x, land_y), facecolor=COLOR_LAND, edgecolor="none", zorder=1)

    # --- ICW water ribbon ---
    icw_poly_x = np.concatenate([mx, ix[::-1]])
    icw_poly_y = np.concatenate([my, iy[::-1]])
    map_ax.fill(*map_coords(icw_poly_x, icw_poly_y), facecolor=COLOR_ICW_WATER,
                edgecolor="none", zorder=2)

    # --- Barrier island ---
    island_x = np.concatenate([ix, ox[::-1]])
    island_y = np.concatenate([iy, oy[::-1]])
    map_ax.fill(*map_coords(island_x, island_y), facecolor=COLOR_LAND, edgecolor="none", zorder=2)

    # --- Inlet channel ---
    chan_x, chan_y = scene["inlet_channel_polygon"]
    if len(chan_x):
        map_ax.fill(*map_coords(chan_x, chan_y), facecolor=COLOR_ICW_WATER,
                    edgecolor="none", zorder=3)

    # --- Shoreline strokes ---
    map_ax.plot(*map_coords(ox, oy), color=COLOR_SHORE_LINE, lw=1.0, zorder=4, solid_joinstyle="round")
    map_ax.plot(*map_coords(ix[~is_open], iy[~is_open]), color=COLOR_SHORE_LINE, lw=0.8,
                zorder=4, solid_joinstyle="round")
    map_ax.plot(*map_coords(mx, my), color=COLOR_SHORE_LINE, lw=0.6, alpha=0.55, zorder=4)


def draw_depth_contours(map_ax, x_min, x_max, y_min, y_max, scene):
    """Bathymetric-style depth contours spanning the full ocean width,
    labeled with approximate depths. Purely decorative — art piece, not
    navigational. Approximate Fort Lauderdale coastal profile.

    Sprint 7.3: extended to cover the full ~6 nm viewport and opacity
    raised to legible levels, matching the reference design where
    contour lines are the primary treatment of the ocean surface.
    """
    ox, oy = scene["ocean_shore"]

    # (offshore_m, depth_label_ft) — approx. Fort Lauderdale shelf profile
    contour_defs = [
        (700,   20),
        (1500,  40),
        (2500,  60),
        (3800,  80),
        (5400, 100),
        (7200, 120),
        (9200, 140),
    ]

    # Label y-positions: spread top-to-bottom so successive labels don't collide
    label_y_fracs = [0.87, 0.73, 0.58, 0.42, 0.27, 0.14, 0.04]

    rng = np.random.default_rng(42)
    for i, (off, depth_ft) in enumerate(contour_defs):
        jitter = rng.normal(0, 35, size=ox.shape)
        cx = ox + off + jitter
        cy = oy
        mask = cx <= x_max
        if not mask.any():
            continue
        alpha = max(0.12, 0.30 - i * 0.023)
        map_ax.plot(*map_coords(cx[mask], cy[mask]), color=COLOR_CONTOUR, lw=0.65,
                    alpha=alpha, zorder=5)
        # Depth label: near the far-offshore edge, spread along-shore.
        # In seaward_up offshore is the top (high x_local) and along-shore
        # is horizontal (y_local), so we swap the label coordinates.
        label_x = x_min + (x_max - x_min) * 0.95
        label_y = y_min + (y_max - y_min) * label_y_fracs[i]
        if MAP_ORIENTATION == "seaward_up":
            text_px, text_py = label_y, label_x
        else:
            text_px, text_py = label_x, label_y
        map_ax.text(
            text_px, text_py, str(depth_ft),
            ha="center", va="center",
            fontsize=5.5, color=COLOR_CONTOUR, alpha=0.60,
            fontstyle="italic", family=FONT_BODY, zorder=5,
        )


def draw_shipping_lanes(map_ax, x_min, x_max, y_min, y_max):
    """A couple of subtle dashed shipping-lane lines running offshore,
    roughly parallel to the coast, converging toward the inlet — quiet
    background structure, not a navigational instrument.
    """
    lane_defs = [
        # (offshore_x, y_start_frac_of_range, y_end_frac_of_range)
        (1900, 0.92, -0.15),
        (3400, 0.85, -0.55),
    ]
    for x_off, y0f, y1f in lane_defs:
        y0 = y0f * y_max
        y1 = y1f * y_max
        xs = np.linspace(x_off, 60, 60)
        ys = np.linspace(y0, y1, 60)
        # gentle curve toward the inlet (60, 0)
        bend = np.linspace(0, 1, 60) ** 1.6
        ys = y0 + (ys - y0) * bend + (1 - bend) * 0
        map_ax.plot(*map_coords(xs, ys), color=COLOR_LANE, lw=0.9, ls=(0, (6, 5)),
                    alpha=0.55, zorder=6)


def draw_compass_rose(map_ax, x_min, x_max, y_min, y_max):
    """A minimal compass rose in the lower-right of the map, offshore.

    Sprint 2.5 (Priority 6): visual weight reduced roughly 40% from
    Sprint 2 via three compounding changes -- smaller radius (0.052 ->
    0.040 of panel width), thinner strokes throughout, and lower
    opacity on every element -- so it recedes into the chart as a
    background design element rather than a focal point.
    """
    if MAP_ORIENTATION == "seaward_up":
        # Rose in the bottom-right corner of the seaward_up display:
        # right = south (high display-x, i.e. low y_local), bottom = near-shore.
        # xlim=(y_max, y_min): center is at y_local = y_max+(y_min-y_max)*0.84
        # ylim=(x_min, x_max): center is at x_local = x_min+(x_max-x_min)*0.105
        cx = y_max + (y_min - y_max) * 0.84
        cy = x_min + (x_max - x_min) * 0.105
        r_outer = (x_max - x_min) * 0.040
        # In seaward_up, xlim=(y_max, y_min) so higher data-x is further LEFT
        # (toward y_max = north).  N label goes left of the rose.
        n_label_x = cx + r_outer * 1.32
        n_label_y = cy
    else:
        cx = x_min + (x_max - x_min) * 0.84
        cy = y_min + (y_max - y_min) * 0.105
        r_outer = (x_max - x_min) * 0.040
        n_label_x = cx
        n_label_y = cy + r_outer * 1.32

    circle = mpatches.Circle((cx, cy), r_outer, facecolor="none",
                              edgecolor=COLOR_INK_SOFT, lw=0.55, alpha=0.6, zorder=7)
    map_ax.add_patch(circle)
    circle2 = mpatches.Circle((cx, cy), r_outer * 0.62, facecolor="none",
                               edgecolor=COLOR_INK_SOFT, lw=0.4, alpha=0.6, zorder=7)
    map_ax.add_patch(circle2)

    # Four-point star / compass needle
    star_pts = []
    for k in range(8):
        ang = math.pi / 2 - k * math.pi / 4
        rad = r_outer * (0.92 if k % 2 == 0 else 0.30)
        star_pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    star_path = Path(star_pts + [star_pts[0]],
                      [Path.MOVETO] + [Path.LINETO] * len(star_pts))
    map_ax.add_patch(PathPatch(star_path, facecolor=COLOR_INK_SOFT,
                                edgecolor="none", alpha=0.5, zorder=7))

    map_ax.text(n_label_x, n_label_y, "N", ha="center", va="center",
                fontsize=7, color=COLOR_INK_SOFT, alpha=0.7,
                family=FONT_DISPLAY, zorder=7)


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------
# Sprint 2: visual hierarchy. Each kind gets a tier (1 = most prominent)
# driving icon scale, label font size/weight, label content (full vs.
# abbreviated route), and route-line emphasis -- so a cruise ship reads
# as a presence and a tug reads as a quiet detail, per the brief's
# star-rating hierarchy (cruise highest, tug lowest).
VESSEL_TIER = {
    "cruise": 1,
    "cargo": 2,
    "tanker": 3,
    "pilot": 4,
    "tug": 5,
    "unknown": 5,  # development mode: unidentified target, same visual weight as tug
}

# Per-tier visual parameters. Icon scale shrinks, label shrinks and
# loses weight, and route-line opacity/length fades, going down the
# hierarchy.
TIER_STYLE = {
    # name_fs ~30% larger than before; detail_fs ~75% of name_fs so the
    # destination line is clearly subordinate but still legible at chart
    # scale. icon_scale unchanged.
    1: dict(icon_scale=360, name_fs=7.2, detail_fs=5.4, name_weight="bold"),
    2: dict(icon_scale=300, name_fs=6.2, detail_fs=4.7, name_weight="normal"),
    3: dict(icon_scale=260, name_fs=5.7, detail_fs=4.3, name_weight="normal"),
    4: dict(icon_scale=210, name_fs=5.2, detail_fs=3.9, name_weight="normal"),
    5: dict(icon_scale=190, name_fs=4.8, detail_fs=3.6, name_weight="normal"),
}

# Spacing fractions relative to the per-tier icon_scale (in data-coord metres).
# _LABEL_SYMBOL_GAP: multiple of scale for the gap from symbol centre to the
#   name-label anchor (was 1.10; increased for breathing room with larger fonts).
# _LABEL_INTER_LINE: multiple of scale for the gap between the name-label anchor
#   and the destination-label anchor (destination sits below the name, between
#   the name and the vessel symbol).
_LABEL_SYMBOL_GAP  = 1.30
_LABEL_INTER_LINE  = 0.25


def draw_vessel(map_ax, vessel, label_side="right", label_dy=0.0):
    """Draw the vessel symbol and its name label.

    Returns (name_text, dest_anchor) where dest_anchor is
    (dest_px, dest_py, dest_ha, style) — the coordinates and style needed
    to draw the destination line.  draw_fleet handles destination placement
    after checking for label collisions; draw_vessel never draws it.
    """
    x, y = to_xy(vessel.lat, vessel.lon)
    path = GLYPH_BY_KIND[vessel.kind]()
    tier = VESSEL_TIER[vessel.kind]
    style = TIER_STYLE[tier]
    scale = style["icon_scale"]
    theta = math.radians(vessel.heading_deg)

    if MAP_ORIENTATION == "seaward_up":
        # Plot coords are (y_local, x_local).
        # The display frame is rotated 90° CCW vs the geographic frame, so
        # each heading needs +π/2: a north-heading vessel (θ=0) points LEFT
        # in the display (north=left), which is +π/2 from the glyph's
        # default "up" orientation.
        rotation = -theta + math.pi / 2
        translate_x, translate_y = y, x
        # Labels: place above the hull (seaward = upward in display).
        # label_dy nudges horizontally (along-shore = horizontal axis).
        label_px = y + label_dy
        label_py = x + scale * _LABEL_SYMBOL_GAP
        dest_py  = label_py - scale * _LABEL_INTER_LINE
        label_ha = "center"
        if abs(label_dy) > 1e-6:
            map_ax.plot([y + label_dy * 0.55, y], [x + scale * 0.5, x + scale * 0.55],
                        color=COLOR_INK_SOFT, lw=0.35, alpha=0.30, zorder=9)
    else:
        rotation = -theta
        translate_x, translate_y = x, y
        label_dx = scale * _LABEL_SYMBOL_GAP if label_side == "right" else -scale * _LABEL_SYMBOL_GAP
        label_ha = "left" if label_side == "right" else "right"
        label_px = x + label_dx
        label_py = y + label_dy
        dest_py  = label_py - scale * _LABEL_INTER_LINE
        if abs(label_dy) > 1e-6:
            leader_x0 = x + (scale * 0.5 if label_side == "right" else -scale * 0.5)
            map_ax.plot([leader_x0, x + label_dx * 0.55], [y, y + label_dy],
                        color=COLOR_INK_SOFT, lw=0.35, alpha=0.30, zorder=9)

    transform = (Affine2D().scale(scale).rotate(rotation).translate(translate_x, translate_y)
                 + map_ax.transData)
    patch = PathPatch(path, facecolor=COLOR_VESSEL_FILL, edgecolor=COLOR_INK,
                       lw=0.7, transform=transform, zorder=9)
    map_ax.add_patch(patch)

    name_text = map_ax.text(
        label_px, label_py, vessel.name,
        fontsize=style["name_fs"],
        color=COLOR_INK, family=FONT_BODY, ha=label_ha, va="bottom",
        fontweight=style["name_weight"], zorder=10, clip_on=True,
    )
    return name_text, (label_px, dest_py, label_ha, style)


# Per-vessel label placement, keyed by name, chosen against the fixed
# positions in fixtures.py so labels don't collide. "side" puts the
# label to the right or left of the vessel icon; "dy" is a small extra
# vertical nudge in meters for tight clusters.
LABEL_PLACEMENT = {
    "OCEAN MAJESTY":    ("right",    0),
    "HARBOR KING":      ("right",  180),
    "EVERGLADES PILOT": ("right",   60),
    "MISS CARLA":       ("right", -180),
    "GULF VOYAGER":   ("right", 0),
    "EVER GRANITE":   ("right", 0),
    "STAR ENDEAVOR":  ("right", 0),
    "ATLANTIC TRADER":("right", 0),
    "MAERSK HORIZON": ("right", 0),
    "CARIBBEAN STAR": ("right", 0),
}


def draw_fleet(map_ax, vessels):
    """Draw every vessel in `vessels`.

    `vessels` is a plain list of `harbor_view.providers.models.Vessel`
    objects -- this function (and everything it calls) has no idea
    whether they came from the placeholder fleet, a live AIS feed, or
    anything else. That's the whole point of Sprint 3's provider
    refactor: the renderer only ever sees `Vessel` objects.

    Label placement is two-pass:
      Pass 1 — draw all symbols and name labels (always shown, no collision
               check; higher-tier vessels are drawn first so they claim
               space before lower-priority vessels are checked).
      Pass 2 — draw destination lines only where they would not overlap an
               already-placed label bbox.  The name line is always kept;
               the destination line is silently omitted when space is tight.
    """
    if not vessels:
        return

    # Higher-tier vessels (cruise > cargo > tanker > pilot/tug) claim label
    # space first, so their destination lines are the least likely to be
    # suppressed in a crowded scene.
    priority_sorted = sorted(vessels, key=lambda v: VESSEL_TIER.get(v.kind, 99))

    # Pass 1: draw all vessel symbols and name labels.
    label_info = []
    for vessel in priority_sorted:
        side, dy = LABEL_PLACEMENT.get(vessel.name, ("right", 0))
        name_text, dest_anchor = draw_vessel(map_ax, vessel, label_side=side, label_dy=dy)
        label_info.append((vessel, name_text, dest_anchor))

    # Pass 2: draw destination lines with collision avoidance.
    # get_renderer() is available on the Agg backend without a prior draw()
    # call, which is what render_to_image() uses (matplotlib.use("Agg")).
    renderer = map_ax.get_figure().canvas.get_renderer()

    # Seed the placed-bbox list with every name label's bounding box,
    # padded by a small margin so adjacent labels don't feel cramped.
    placed = [
        name_text.get_window_extent(renderer).expanded(1.08, 1.15)
        for _, name_text, _ in label_info
    ]

    for i, (vessel, _name_text, (dest_px, dest_py, dest_ha, style)) in enumerate(label_info):
        dest = vessel.destination
        if not dest:
            continue
        dest_text = map_ax.text(
            dest_px, dest_py, dest,
            fontsize=style["detail_fs"],
            color=COLOR_METADATA, family=FONT_BODY, ha=dest_ha, va="top",
            alpha=0.75, zorder=10, clip_on=True,
        )
        dest_bbox = dest_text.get_window_extent(renderer).expanded(1.05, 1.10)
        # Check against every OTHER placed bbox (skip index i = this vessel's
        # own name label, which would always overlap the destination).
        if any(dest_bbox.overlaps(bb) for j, bb in enumerate(placed) if j != i):
            dest_text.remove()
        else:
            placed.append(dest_bbox)


# ---------------------------------------------------------------------------
# Home marker
# ---------------------------------------------------------------------------
def draw_home_marker(map_ax, scene, config: HarborConfig):
    x, y = to_xy(config.home_lat, config.home_lon)
    # Snap to the mid-line of the island at this latitude, so the
    # marker reliably sits on land regardless of small lat/lon tuning.
    ox, oy = scene["ocean_shore"]
    ix, iy = scene["icw_shore"]
    idx = int(np.argmin(np.abs(oy - y)))
    x_mid = (ox[idx] + ix[idx]) / 2.0
    y_mid = oy[idx]

    # Sprint 2.5 (Priority 2): a modest 20-30% increase over Sprint 2's
    # 340 (-> ~410-420 here), NOT the more aggressive jump Sprint 2 made
    # over Sprint 1. Combined with the lighter line weight below, the
    # goal is a small architectural line drawing printed onto the
    # chart -- present enough to notice on a careful look, not a bold
    # icon competing with the vessels for attention.
    scale = 410.0
    paths = home_marker_path(scale=scale)
    offset = np.array([y_mid, x_mid] if MAP_ORIENTATION == "seaward_up" else [x_mid, y_mid])
    for p in paths["structure"]:
        verts = p.vertices + offset
        placed = Path(verts, p.codes)
        # Lighter line weight than Sprint 2 (1.6 -> 1.0) so the whole
        # mark sits closer to the chart's other linework rather than
        # standing out as a bold icon.
        map_ax.add_patch(PathPatch(placed, facecolor="none",
                                    edgecolor=COLOR_INK, lw=1.0, zorder=11,
                                    joinstyle="miter", capstyle="butt"))
    for p in paths["detail"]:
        verts = p.vertices + offset
        placed = Path(verts, p.codes)
        # Floor lines and the central mullion are finer still and a
        # touch softer in color -- detail that rewards a closer look
        # rather than announcing itself.
        map_ax.add_patch(PathPatch(placed, facecolor="none",
                                    edgecolor=COLOR_INK_SOFT, lw=0.5,
                                    alpha=0.75, zorder=11))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def draw_sidebar(sidebar_ax, now: _dt.datetime, config: HarborConfig):
    """Sprint 2.5 (Priority 5): pushed further toward an antique chart
    margin than Sprint 2 -- hairline rules (0.8 -> 0.5), a slightly
    smaller/quieter time treatment, and a touch more breathing room
    between blocks. Still no new information; only weight and spacing.
    """
    ax = sidebar_ax
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    y = 0.95
    ax.text(0.09, y, "Harbor View", fontsize=20, family=FONT_DISPLAY,
            color=COLOR_INK, ha="left", va="top")
    y -= 0.034
    ax.text(0.09, y, config.location_city, fontsize=8.5,
            family=FONT_BODY, color=COLOR_INK_SOFT, ha="left", va="top",
            style="italic")
    y -= 0.052
    ax.plot([0.09, 0.91], [y, y], color=COLOR_RULE, lw=0.5)

    # Current time: quiet, not shouting -- closer to a chart's printed
    # marginal note than a clock-app readout. Slightly smaller than
    # Sprint 2 so it no longer competes with the title for top billing.
    y -= 0.07
    time_str = now.strftime("%-I:%M %p %Z") if hasattr(now, "strftime") else str(now)
    ax.text(0.09, y, time_str, fontsize=18, family=FONT_DISPLAY,
            color=COLOR_INK, ha="left", va="top")

    y -= 0.095

    def caption(label, y):
        # Letter-spaced caption by joining characters with a thin space
        # -- a cheap but effective stand-in for true typographic
        # tracking, evoking engraved chart labels.
        spaced = "\u2009".join(label)
        ax.text(0.09, y, spaced, fontsize=8.5, family=FONT_BODY,
                color=COLOR_INK_SOFT, ha="left", va="top")
        return y - 0.030

    def section(label, lines, y):
        y = caption(label, y)
        for line in lines:
            ax.text(0.105, y, line, fontsize=10, family=FONT_BODY,
                    color=COLOR_INK, ha="left", va="top")
            y -= 0.0285
        return y - 0.038

    y = section("WIND", ["ENE 11 kn", "Gusts 16 kn"], y)
    y = section("WEATHER", ["Partly cloudy", "84\u00b0F  /  29\u00b0C"], y)
    y = section("TIDE", ["High 7:42 AM (+3.1 ft)", "Low 2:05 PM (+0.4 ft)"], y)

    ax.plot([0.09, 0.91], [y, y], color=COLOR_RULE, lw=0.5)
    y -= 0.048

    y = caption("VESSEL LEGEND", y)
    y -= 0.014

    legend_items = [
        ("cruise", "Cruise ship"),
        ("cargo", "Cargo ship"),
        ("tanker", "Tanker"),
        ("tug", "Tug"),
        ("pilot", "Pilot boat"),
    ]
    icon_x = 0.15
    label_x = 0.26
    # The sidebar axes spans (0,1)x(0,1) in DATA units but the axes box
    # itself is narrower than it is tall on the figure (sidebar_w fraction
    # of FIG_W_IN wide vs (1-2m) fraction of FIG_H_IN tall). A glyph drawn
    # with equal x/y data-unit scale would look squashed; correct for the
    # real on-figure aspect so hulls keep their intended proportions.
    sidebar_bbox = ax.get_position()
    actual_fig_w, actual_fig_h = ax.get_figure().get_size_inches()
    sidebar_w_in = sidebar_bbox.width * actual_fig_w
    sidebar_h_in = sidebar_bbox.height * actual_fig_h
    # data-units-per-inch differs between x and y since both span 0..1
    # over different physical inches; aspect_correction makes 1 unit of
    # glyph-y look the same physical length as 1 unit of glyph-x.
    aspect_correction = sidebar_w_in / sidebar_h_in

    for kind, label in legend_items:
        path = GLYPH_BY_KIND[kind]()
        scale_x = 0.058
        scale_y = scale_x * aspect_correction
        # path's own y-range is roughly [-0.5*len, 0.5*len] in unit
        # space already (hull paths are centered on origin), so
        # offsetting by (icon_x, y) centers the icon on the label's
        # vertical position directly -- no extra -0.010 fudge needed.
        verts = path.vertices * np.array([scale_x, scale_y]) + np.array([icon_x, y])
        placed = Path(verts, path.codes)
        ax.add_patch(PathPatch(placed, facecolor=COLOR_SIDEBAR_BG,
                                edgecolor=COLOR_INK, lw=0.7, zorder=5))
        ax.text(label_x, y, label, fontsize=9.5, family=FONT_BODY,
                color=COLOR_INK, ha="left", va="center")
        y -= 0.044


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def render_to_image(
    vessel_provider: VesselProvider | None = None,
    config: HarborConfig | None = None,
    canvas_size: tuple[int, int] | None = None,
) -> "PIL.Image.Image":
    """Render Harbor View and return the result as a PIL Image.

    This is the primary rendering entry point.  All drawing happens here;
    delivery to disk or display is the caller's responsibility via an
    output backend (see harbor_view.output).

    `vessel_provider` supplies the vessels to draw.  Defaults to
    `PlaceholderProvider`.

    `config` controls location name, city, home-marker position, and
    timezone.  Defaults to `DEFAULT_CONFIG`.

    `canvas_size` overrides the default 2000×1200 canvas with an explicit
    (width, height) in pixels.  The figure dimensions are derived by
    dividing by DPI (200) so the resulting image is exactly canvas_size.
    Omit (or pass None) to use the module-level FIG_W_IN × FIG_H_IN default.
    """
    import io
    import PIL.Image

    if vessel_provider is None:
        vessel_provider = PlaceholderProvider()
    if config is None:
        config = DEFAULT_CONFIG

    _fig_w = canvas_size[0] / DPI if canvas_size is not None else FIG_W_IN
    _fig_h = canvas_size[1] / DPI if canvas_size is not None else FIG_H_IN
    fig, sidebar_ax, map_ax = build_layout(fig_w_in=_fig_w, fig_h_in=_fig_h)

    # Compute geographic extent first so build_scene clips the coastline
    # geometry to exactly the rendered viewport, not a fixed constant.
    x_min, x_max, y_min, y_max = compute_view_window(map_ax)
    if MAP_ORIENTATION == "seaward_up":
        # compute_view_window uses panel_h/panel_w; in seaward_up the local
        # x-axis (seaward depth) maps to the display height and y-axis
        # (along-shore) maps to the display width, so the aspect must be
        # inverted.  We re-derive here so the hybrid renderer's call to
        # compute_view_window remains unaffected.
        bbox = map_ax.get_position()
        fig_w_in, fig_h_in = map_ax.get_figure().get_size_inches()
        panel_aspect = (bbox.height * fig_h_in) / (bbox.width * fig_w_in)
        x_min, x_max, y_min, y_max = solve_viewport(
            VIEW_SEAWARD_RANGE_NM, 1.0 / panel_aspect, COAST_FRAC_FROM_LEFT
        )
    y_half_nm = (y_max - y_min) / 2.0 / NM
    scene = build_scene(view_half_height_nm=y_half_nm)

    draw_basemap(map_ax, scene, x_min, x_max, y_min, y_max)
    draw_depth_contours(map_ax, x_min, x_max, y_min, y_max, scene)
    draw_shipping_lanes(map_ax, x_min, x_max, y_min, y_max)
    draw_compass_rose(map_ax, x_min, x_max, y_min, y_max)
    draw_fleet(map_ax, vessel_provider.get_vessels())
    draw_home_marker(map_ax, scene, config)

    now = _dt.datetime.now(tz=ZoneInfo(config.timezone))
    draw_sidebar(sidebar_ax, now, config)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = PIL.Image.open(buf)
    img.load()  # detach from the BytesIO before it goes out of scope
    return img


def render(
    output_path: str = OUTPUT_PATH,
    vessel_provider: VesselProvider | None = None,
    config: HarborConfig | None = None,
) -> str:
    """Render Harbor View to a PNG file at output_path.

    Thin wrapper around render_to_image() that writes the result to disk
    via PngBackend (atomic temp-file rename).  Kept for backwards
    compatibility with callers and tests that expect a path-based API.
    """
    from harbor_view.output.png import PngBackend
    image = render_to_image(vessel_provider, config)
    PngBackend().write(image, output_path)
    return output_path


if __name__ == "__main__":
    path = render()
    print(f"Saved chart to {path}")
