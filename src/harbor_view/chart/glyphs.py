"""Simple monochrome line-art vessel glyphs, drawn as small matplotlib
Path/Patch shapes. Each glyph is defined in a local unit box, nose
pointing +y (north/"up"), and rotated/scaled/translated at draw time.

These are deliberately simple — silhouettes, not detailed ship
drawings — to keep the chart calm and legible at small sizes.
"""
from __future__ import annotations

import numpy as np
from matplotlib.path import Path


def _hull_path(length: float, beam: float, bow_taper: float, stern_taper: float = 0.0) -> Path:
    """A simple elongated hull silhouette, nose at +y."""
    hl, hb = length / 2, beam / 2
    verts = [
        (0, hl),                          # bow tip
        (hb, hl - bow_taper),             # bow shoulder right
        (hb, -hl + stern_taper),          # stern right
        (hb * 0.55, -hl),                 # stern corner right
        (-hb * 0.55, -hl),                # stern corner left
        (-hb, -hl + stern_taper),         # stern left
        (-hb, hl - bow_taper),            # bow shoulder left
        (0, hl),
    ]
    codes = [Path.MOVETO] + [Path.LINETO] * (len(verts) - 2) + [Path.CLOSEPOLY]
    return Path(verts, codes)


def cruise_ship_path() -> Path:
    # Long, full hull with a near-vertical bow and a flat, squared-off
    # stern (reads as a tall superstructure silhouette).
    return _hull_path(length=1.0, beam=0.34, bow_taper=0.10, stern_taper=0.42)


def cargo_ship_path() -> Path:
    # Long and narrow with a sharp, pronounced bow taper.
    return _hull_path(length=1.0, beam=0.20, bow_taper=0.34, stern_taper=0.06)


def tanker_path() -> Path:
    # Long, full, blunt at both ends — low taper front and back.
    return _hull_path(length=0.95, beam=0.30, bow_taper=0.08, stern_taper=0.08)


def tug_path() -> Path:
    # Short and stubby, blunt bow.
    return _hull_path(length=0.42, beam=0.30, bow_taper=0.06, stern_taper=0.06)


def pilot_boat_path() -> Path:
    # Small and sleek, sharp bow.
    return _hull_path(length=0.40, beam=0.16, bow_taper=0.18, stern_taper=0.03)


GLYPH_BY_KIND = {
    "cruise": cruise_ship_path,
    "cargo": cargo_ship_path,
    "tanker": tanker_path,
    "tug": tug_path,
    "pilot": pilot_boat_path,
}


def home_marker_path(scale: float = 1.0):
    """A small architectural line drawing inspired by twin condominium
    towers (The Palms) — meant to read as a tiny elevation drawing
    printed directly on the chart, not as a map icon. No fill, no text,
    no pin, no label.

    Returns a dict with two path lists, drawn at different line weights
    by the caller:
      - 'structure': the building outlines and base (heavier strokes)
      - 'detail': floor lines and roofline ticks (lighter strokes) --
        the "more architectural detail" the brief asks for, kept as a
        separate, thinner layer so it reads as fine linework rather
        than adding visual weight.

    Unit box is roughly [-1.1, 1.1] x [0, 2.55] before the caller's
    `scale`.
    """
    tower_w, gap, base_h, tower_h = 0.6, 0.30, 0.20, 2.0
    x0 = -(tower_w * 2 + gap) / 2
    # A small setback near the top, as real towers like this often have
    # a slightly narrower crown -- reads as architectural rather than a
    # plain box.
    setback_h = 0.22
    setback_w = 0.10

    def tower_outline(x_left):
        top = base_h + tower_h
        verts = [
            (x_left, base_h),
            (x_left, top - setback_h),
            (x_left + setback_w, top - setback_h),
            (x_left + setback_w, top),
            (x_left + tower_w - setback_w, top),
            (x_left + tower_w - setback_w, top - setback_h),
            (x_left + tower_w, top - setback_h),
            (x_left + tower_w, base_h),
            (x_left, base_h),
        ]
        codes = [Path.MOVETO] + [Path.LINETO] * (len(verts) - 2) + [Path.CLOSEPOLY]
        return Path(verts, codes)

    def floor_lines(x_left, n=6):
        # Thin horizontal strata suggesting individual floors -- detail
        # that only resolves on close inspection, per the brief's
        # "reward discovery rather than demand attention."
        top = base_h + tower_h - setback_h
        paths = []
        for i in range(1, n + 1):
            yy = base_h + (top - base_h) * i / (n + 1)
            paths.append(Path([(x_left + 0.05, yy), (x_left + tower_w - 0.05, yy)],
                               [Path.MOVETO, Path.LINETO]))
        return paths

    base_left = x0 - 0.18
    base_right = x0 + tower_w * 2 + gap + 0.18
    base = Path(
        [(base_left, 0), (base_right, 0), (base_right, base_h),
         (base_left, base_h), (base_left, 0)],
        [Path.MOVETO, Path.LINETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY],
    )

    left_x, right_x = x0, x0 + tower_w + gap
    structure = [base, tower_outline(left_x), tower_outline(right_x)]
    detail = floor_lines(left_x) + floor_lines(right_x)
    # A single faint vertical mullion line down the center of each
    # tower -- another small architectural cue rather than a plain box.
    for tx in (left_x, right_x):
        detail.append(Path([(tx + tower_w / 2, base_h + 0.05),
                             (tx + tower_w / 2, base_h + tower_h - setback_h - 0.05)],
                            [Path.MOVETO, Path.LINETO]))

    if scale != 1.0:
        structure = [Path(p.vertices * scale, p.codes) for p in structure]
        detail = [Path(p.vertices * scale, p.codes) for p in detail]

    return {"structure": structure, "detail": detail}
