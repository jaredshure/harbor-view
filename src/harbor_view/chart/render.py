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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.transforms import Affine2D
import numpy as np

from harbor_view.chart.geometry import build_scene, to_xy, NM
from harbor_view.chart.glyphs import GLYPH_BY_KIND, home_marker_path
from harbor_view.providers import VesselProvider, PlaceholderProvider

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "output", "harbor_view.png"
)

# ---------------------------------------------------------------------------
# Palette — soft, cream/teal NOAA-chart-inspired, deliberately desaturated.
# ---------------------------------------------------------------------------
COLOR_OCEAN = "#CFE3E8"
COLOR_OCEAN_DEEP = "#BCD8DF"
COLOR_LAND = "#EFE6D0"
COLOR_ICW_WATER = "#BFDCE3"
COLOR_SHORE_LINE = "#8C7A56"
COLOR_CONTOUR = "#9FC3CB"
COLOR_LANE = "#8FA9AE"
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
# Canvas + layout
# ---------------------------------------------------------------------------
FIG_W_IN, FIG_H_IN = 10.0, 14.0  # portrait
DPI = 200

SIDEBAR_FRAC = 0.25
MARGIN_FRAC = 0.018


def build_layout():
    fig = plt.figure(figsize=(FIG_W_IN, FIG_H_IN), dpi=DPI)
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
VIEW_HALF_HEIGHT_NM = 7.2
# Sprint 2 composition pass: shift the coastline ~25% further left
# (0.28 -> 0.21 of panel width) than Sprint 1's settings, increasing
# open ocean so the Atlantic reads as the clear visual hero. Offshore
# distance stays within the 5-10 nm requirement (~6.1 nm at this
# setting).
COAST_FRAC_FROM_LEFT = 0.21


def compute_view_window(map_ax):
    """Pick an x/y window (in local meters) whose aspect ratio matches the
    map panel's on-canvas aspect ratio, so set_aspect('equal') fills the
    panel with no letterboxing, and the coastline sits left-of-center.
    """
    bbox = map_ax.get_position()
    panel_w_in = bbox.width * FIG_W_IN
    panel_h_in = bbox.height * FIG_H_IN
    panel_aspect = panel_h_in / panel_w_in

    y_span_m = VIEW_HALF_HEIGHT_NM * 2 * NM
    x_span_m = y_span_m / panel_aspect

    x_min = -COAST_FRAC_FROM_LEFT * x_span_m
    x_max = x_min + x_span_m
    y_min, y_max = -VIEW_HALF_HEIGHT_NM * NM, VIEW_HALF_HEIGHT_NM * NM
    return x_min, x_max, y_min, y_max


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

    map_ax.set_xlim(x_min, x_max)
    map_ax.set_ylim(y_min, y_max)
    map_ax.set_aspect("equal")

    # --- Ocean base ---
    map_ax.add_patch(mpatches.Rectangle(
        (x_min, y_min), x_max - x_min, y_max - y_min,
        facecolor=COLOR_OCEAN, edgecolor="none", zorder=0,
    ))

    # --- Mainland block: from the view's west edge out to mainland_shore.
    # Because mx/my are pinned to exactly y_min..y_max, closing the
    # polygon at (x_min, y_max) -> (x_min, y_min) gives a flush vertical
    # edge with no ragged diagonal.
    # mx/my run from y_min to y_max (pinned). Close the polygon by
    # going up along the mainland curve, then straight back down the
    # panel's west edge -- NOT by jumping corner-to-corner, which would
    # cross the polygon diagonally and produce a bowtie fill.
    land_x = np.concatenate([mx, [x_min, x_min]])
    land_y = np.concatenate([my, [y_max, y_min]])
    map_ax.fill(land_x, land_y, facecolor=COLOR_LAND, edgecolor="none", zorder=1)

    # --- ICW water ribbon: between mainland_shore and icw_shore.
    icw_poly_x = np.concatenate([mx, ix[::-1]])
    icw_poly_y = np.concatenate([my, iy[::-1]])
    map_ax.fill(icw_poly_x, icw_poly_y, facecolor=COLOR_ICW_WATER,
                edgecolor="none", zorder=2)

    # --- Barrier island: between icw_shore and ocean_shore.
    island_x = np.concatenate([ix, ox[::-1]])
    island_y = np.concatenate([iy, oy[::-1]])
    map_ax.fill(island_x, island_y, facecolor=COLOR_LAND, edgecolor="none", zorder=2)

    # --- Inlet channel: built directly from ocean_shore/icw_shore at the
    # gap rows (scene['inlet_channel_polygon']), so it is guaranteed to
    # align with the island polygon above rather than risking drift from
    # independently-chosen coordinates.
    chan_x, chan_y = scene["inlet_channel_polygon"]
    if len(chan_x):
        map_ax.fill(chan_x, chan_y, facecolor=COLOR_ICW_WATER,
                    edgecolor="none", zorder=3)

    # --- Shoreline strokes ---
    map_ax.plot(ox, oy, color=COLOR_SHORE_LINE, lw=1.0, zorder=4, solid_joinstyle="round")
    map_ax.plot(ix[~is_open], iy[~is_open], color=COLOR_SHORE_LINE, lw=0.8,
                zorder=4, solid_joinstyle="round")
    map_ax.plot(mx, my, color=COLOR_SHORE_LINE, lw=0.6, alpha=0.55, zorder=4)


def draw_depth_contours(map_ax, x_min, x_max, y_min, y_max, scene):
    """Very subtle, gently curved depth contours running roughly
    parallel to the coastline, fading into deeper water offshore.
    Purely decorative (not derived from real bathymetry) — this is an
    art piece, not a navigational chart.

    Sprint 2.5 (Priority 7): contrast reduced again from Sprint 2 --
    peak opacity roughly halved once more (0.16 -> 0.09) and the
    nearest, most-visible contour pulled back so even the closest line
    starts faint. The intent is that these are noticed only after the
    viewer has spent several seconds with the chart, not on first
    glance.
    """
    ox, oy = scene["ocean_shore"]
    offsets_m = [350, 750, 1300, 2050, 3000, 4200]
    rng = np.random.default_rng(42)
    for i, off in enumerate(offsets_m):
        jitter = rng.normal(0, 25, size=ox.shape)
        cx = ox + off + jitter
        cy = oy
        alpha = max(0.03, 0.09 - i * 0.013)
        map_ax.plot(cx, cy, color=COLOR_CONTOUR, lw=0.5, alpha=alpha, zorder=5)


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
        map_ax.plot(xs, ys, color=COLOR_LANE, lw=0.9, ls=(0, (6, 5)),
                    alpha=0.55, zorder=6)


def draw_compass_rose(map_ax, x_min, x_max, y_min, y_max):
    """A minimal compass rose in the lower-right of the map, offshore.

    Sprint 2.5 (Priority 6): visual weight reduced roughly 40% from
    Sprint 2 via three compounding changes -- smaller radius (0.052 ->
    0.040 of panel width), thinner strokes throughout, and lower
    opacity on every element -- so it recedes into the chart as a
    background design element rather than a focal point.
    """
    cx = x_min + (x_max - x_min) * 0.84
    cy = y_min + (y_max - y_min) * 0.105
    r_outer = (x_max - x_min) * 0.040

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

    map_ax.text(cx, cy + r_outer * 1.32, "N", ha="center", va="center",
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
}

# Per-tier visual parameters. Icon scale shrinks, label shrinks and
# loses weight, and route-line opacity/length fades, going down the
# hierarchy.
TIER_STYLE = {
    1: dict(icon_scale=460, name_fs=6.4, detail_fs=5.2, route_alpha=0.34, route_len_mult=6.5, name_weight="bold"),
    2: dict(icon_scale=380, name_fs=5.6, detail_fs=4.6, route_alpha=0.28, route_len_mult=5.5, name_weight="normal"),
    3: dict(icon_scale=330, name_fs=5.2, detail_fs=4.4, route_alpha=0.22, route_len_mult=4.5, name_weight="normal"),
    4: dict(icon_scale=270, name_fs=4.8, detail_fs=4.1, route_alpha=0.18, route_len_mult=3.5, name_weight="normal"),
    5: dict(icon_scale=240, name_fs=4.5, detail_fs=3.9, route_alpha=0.14, route_len_mult=2.5, name_weight="normal"),
}


def draw_vessel(map_ax, vessel, label_side="right", label_dy=0.0):
    x, y = to_xy(vessel.lat, vessel.lon)
    path = GLYPH_BY_KIND[vessel.kind]()
    tier = VESSEL_TIER[vessel.kind]
    style = TIER_STYLE[tier]
    scale = style["icon_scale"]
    theta = math.radians(vessel.heading_deg)
    sin_t, cos_t = math.sin(theta), math.cos(theta)

    # Priority 3 (Sprint 2.5): faint wake instead of a single straight
    # dashed "route" line -- two short diverging strokes trailing the
    # stern, like a real wake, fainter and shorter than the old route
    # hint so it reads as texture rather than a flight-path overlay.
    wake_len = scale * style["route_len_mult"] * 0.55
    wake_spread = scale * 0.16
    stern_x = x - (scale * 0.18) * sin_t
    stern_y = y - (scale * 0.18) * cos_t
    for side in (-1, 1):
        perp_x, perp_y = cos_t * side, -sin_t * side
        tip_x = stern_x - wake_len * sin_t + perp_x * wake_spread
        tip_y = stern_y - wake_len * cos_t + perp_y * wake_spread
        map_ax.plot([stern_x, tip_x], [stern_y, tip_y], color=COLOR_LANE,
                    lw=0.55, alpha=style["route_alpha"], solid_capstyle="round",
                    zorder=8)

    # Hull: softened fill (a hint of ocean blue mixed in rather than
    # flat cream) and a thinner outline than Sprint 2, so the shape
    # reads as drawn-on-the-chart rather than a pasted UI marker.
    transform = (Affine2D().scale(scale).rotate(-theta).translate(x, y)
                 + map_ax.transData)
    patch = PathPatch(path, facecolor=COLOR_VESSEL_FILL, edgecolor=COLOR_INK,
                       lw=0.8 if tier <= 2 else 0.65, transform=transform, zorder=9)
    map_ax.add_patch(patch)

    # Delicate heading indicator: a short fine line extending forward
    # from the bow, distinct from the hull outline -- a small nautical
    # convention (course-over-ground tick) rather than a bold arrow.
    bow_x = x + (scale * 0.55) * sin_t
    bow_y = y + (scale * 0.55) * cos_t
    tick_x = x + (scale * 0.95) * sin_t
    tick_y = y + (scale * 0.95) * cos_t
    map_ax.plot([bow_x, tick_x], [bow_y, tick_y], color=COLOR_INK_SOFT,
                lw=0.6, alpha=0.65, zorder=9)

    # Label: name set in its tier's weight/size. Softer anchoring than
    # Sprint 2 -- a small fixed gap from the hull, with a hairline
    # leader only drawn when the label has been nudged vertically away
    # from the vessel (the inlet cluster), so the label feels loosely
    # associated with the vessel rather than wired to it by a rigid
    # offset rule in every case.
    label_dx = scale * 0.95 if label_side == "right" else -scale * 0.95
    ha = "left" if label_side == "right" else "right"
    y_label = y + label_dy

    if abs(label_dy) > 1e-6:
        leader_x0 = x + (scale * 0.5 if label_side == "right" else -scale * 0.5)
        map_ax.plot([leader_x0, x + label_dx * 0.55], [y, y_label],
                    color=COLOR_INK_SOFT, lw=0.4, alpha=0.45, zorder=9)

    map_ax.text(x + label_dx, y_label, vessel.name, fontsize=style["name_fs"],
                color=COLOR_INK, family=FONT_BODY, ha=ha, va="bottom",
                fontweight=style["name_weight"], zorder=10)
    route_str = f"{vessel.origin}  \u2192  {vessel.destination}"
    map_ax.text(x + label_dx, y_label, route_str, fontsize=style["detail_fs"],
                color=COLOR_METADATA, family=FONT_BODY, ha=ha, va="top",
                zorder=10)


# Per-vessel label placement, keyed by name, chosen against the fixed
# positions in fixtures.py so labels don't collide. "side" puts the
# label to the right or left of the vessel icon; "dy" is a small extra
# vertical nudge in meters for tight clusters (only the inlet trio of
# tug/tug/pilot needs this -- everything else has comfortable room).
LABEL_PLACEMENT = {
    "GULF VOYAGER": ("right", 0),
    "EVER GRANITE": ("right", 0),
    "MISS CARLA": ("right", -60),
    "EVERGLADES PILOT": ("right", 70),
    "HARBOR KING": ("right", 0),
    "OCEAN MAJESTY": ("right", 0),
    "STAR ENDEAVOR": ("right", 0),
    "ATLANTIC TRADER": ("right", 0),
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
    """
    for vessel in vessels:
        side, dy = LABEL_PLACEMENT.get(vessel.name, ("right", 0))
        draw_vessel(map_ax, vessel, label_side=side, label_dy=dy)


# ---------------------------------------------------------------------------
# Home marker
# ---------------------------------------------------------------------------
HOME_LAT, HOME_LON = 26.1300, -80.1010  # approx. Galt Ocean Mile stretch


def draw_home_marker(map_ax, scene):
    x, y = to_xy(HOME_LAT, HOME_LON)
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
    for p in paths["structure"]:
        verts = p.vertices + np.array([x_mid, y_mid])
        placed = Path(verts, p.codes)
        # Lighter line weight than Sprint 2 (1.6 -> 1.0) so the whole
        # mark sits closer to the chart's other linework rather than
        # standing out as a bold icon.
        map_ax.add_patch(PathPatch(placed, facecolor="none",
                                    edgecolor=COLOR_INK, lw=1.0, zorder=11,
                                    joinstyle="miter", capstyle="butt"))
    for p in paths["detail"]:
        verts = p.vertices + np.array([x_mid, y_mid])
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
def draw_sidebar(sidebar_ax, now: _dt.datetime):
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
    ax.text(0.09, y, "Port Everglades, Florida", fontsize=8.5,
            family=FONT_BODY, color=COLOR_INK_SOFT, ha="left", va="top",
            style="italic")
    y -= 0.052
    ax.plot([0.09, 0.91], [y, y], color=COLOR_RULE, lw=0.5)

    # Current time: quiet, not shouting -- closer to a chart's printed
    # marginal note than a clock-app readout. Slightly smaller than
    # Sprint 2 so it no longer competes with the title for top billing.
    y -= 0.07
    time_str = now.strftime("%-I:%M %p") if hasattr(now, "strftime") else str(now)
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
    sidebar_w_in = sidebar_bbox.width * FIG_W_IN
    sidebar_h_in = sidebar_bbox.height * FIG_H_IN
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
def render(output_path: str = OUTPUT_PATH, vessel_provider: VesselProvider | None = None) -> str:
    """Render Harbor View to a PNG.

    `vessel_provider` supplies the vessels to draw via its
    `get_vessels()` method -- the renderer calls that one method and
    nothing else. Defaults to `PlaceholderProvider`, preserving the
    exact behavior Harbor View has always had when run with no
    arguments. Pass a different `VesselProvider` (e.g. a future
    `AISProvider`, once implemented) to draw different vessels with no
    other code changes.
    """
    if vessel_provider is None:
        vessel_provider = PlaceholderProvider()

    fig, sidebar_ax, map_ax = build_layout()

    scene = build_scene(view_half_height_nm=VIEW_HALF_HEIGHT_NM)
    x_min, x_max, y_min, y_max = compute_view_window(map_ax)

    draw_basemap(map_ax, scene, x_min, x_max, y_min, y_max)
    draw_depth_contours(map_ax, x_min, x_max, y_min, y_max, scene)
    draw_shipping_lanes(map_ax, x_min, x_max, y_min, y_max)
    draw_compass_rose(map_ax, x_min, x_max, y_min, y_max)
    draw_fleet(map_ax, vessel_provider.get_vessels())
    draw_home_marker(map_ax, scene)

    draw_sidebar(sidebar_ax, _dt.datetime.now())

    out_dir = os.path.dirname(output_path)
    os.makedirs(out_dir, exist_ok=True)
    fig.savefig(output_path, dpi=DPI, facecolor="white")
    plt.close(fig)
    return output_path


if __name__ == "__main__":
    path = render()
    print(f"Saved chart to {path}")
