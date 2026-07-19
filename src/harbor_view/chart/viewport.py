"""Viewport geometry solver for Harbor View.

Computes the geographic extent (in local metres) of the map panel from
three user-facing parameters:

  - seaward_range_nm    how far seaward the chart extends (right edge)
  - panel_aspect        map panel height / width (> 1 for portrait)
  - coast_frac_from_left  internal design constant: the fraction of
                          total x-span that lies behind the reference
                          location (land context), default 0.21

Math:

    x_max  = seaward_range_nm * NM         # seaward edge, metres
    x_span = x_max / (1 - coast_frac)      # total cross-shore span
    x_min  = -coast_frac * x_span          # land-side edge
    y_span = panel_aspect * x_span         # along-shore (fills panel)
    y_min  = -y_span / 2
    y_max  =  y_span / 2

The reference location always sits at (0, 0) in local metres and always
appears at `coast_frac_from_left` from the left edge of the panel.
Scaling `seaward_range_nm` proportionally changes the entire viewport —
along-shore, land context, and seaward depth all expand together.

Local coordinate frame:
  +x  seaward (the direction given by HARBOR_VIEW_SEAWARD_BEARING_DEG)
  +y  90 degrees counter-clockwise from seaward (leftward facing seaward)

For an east-facing location (bearing = 90°) +x is east, +y is north —
identical to a standard geographic frame. Use to_local_frame() to rotate
geographic (east, north) metres into this local frame.

This module has no dependencies on matplotlib, numpy, or the rest of
Harbor View, making it straightforward to unit-test in isolation.
"""
from __future__ import annotations

import math

NM = 1852.0  # metres per nautical mile


def to_local_frame(
    x_geo: float,
    y_geo: float,
    seaward_bearing_deg: float,
) -> tuple[float, float]:
    """Rotate geographic (east, north) metres to the seaward local frame.

    The seaward bearing defines which compass direction is positive-x in
    the chart's local coordinate system.  For an east-facing location
    pass 90.0; for a west-facing location pass 270.0.

    For bearing = 90°, this is the identity transform (east stays east,
    north stays north), so Fort Lauderdale's existing geometry is
    unchanged.

    Args:
        x_geo: East displacement from the reference point, metres.
        y_geo: North displacement from the reference point, metres.
        seaward_bearing_deg: Compass bearing of the seaward direction,
            degrees clockwise from north.

    Returns:
        (x_local, y_local) where +x is seaward and +y is 90° CCW from
        seaward (i.e. leftward when facing seaward).
    """
    b = math.radians(seaward_bearing_deg)
    sin_b = math.sin(b)
    cos_b = math.cos(b)
    x_local = x_geo * sin_b + y_geo * cos_b
    y_local = x_geo * (-cos_b) + y_geo * sin_b
    return x_local, y_local


def solve_viewport(
    seaward_range_nm: float,
    panel_aspect: float,
    coast_frac_from_left: float = 0.21,
) -> tuple[float, float, float, float]:
    """Compute the geographic viewport bounds in local metres.

    The reference location (the observer's home) is at the origin (0, 0)
    and appears at ``coast_frac_from_left`` from the left edge of the
    map panel.  The seaward edge is exactly ``seaward_range_nm`` NM from
    the origin.  The along-shore extent is derived from ``panel_aspect``
    so the panel is filled without letterboxing.

    Args:
        seaward_range_nm: Seaward depth to show from the reference, NM.
            Measured from the reference location, not from the shoreline.
        panel_aspect: Map panel height divided by width (> 1 = portrait).
        coast_frac_from_left: Fraction of total x-span lying on the
            land side of the reference location.  0.21 gives 21% land
            context, 79% seaward; do not expose directly to end users.

    Returns:
        (x_min, x_max, y_min, y_max) in local metres, with the reference
        location at (0, 0).  x_max equals seaward_range_nm * NM exactly.
    """
    if seaward_range_nm <= 0:
        raise ValueError(f"seaward_range_nm must be positive, got {seaward_range_nm}")
    if panel_aspect <= 0:
        raise ValueError(f"panel_aspect must be positive, got {panel_aspect}")
    if not (0.0 < coast_frac_from_left < 1.0):
        raise ValueError(
            f"coast_frac_from_left must be in (0, 1), got {coast_frac_from_left}"
        )

    x_max = seaward_range_nm * NM
    x_span = x_max / (1.0 - coast_frac_from_left)
    x_min = -(coast_frac_from_left * x_span)

    y_span = panel_aspect * x_span
    y_min = -y_span / 2.0
    y_max = y_span / 2.0

    return x_min, x_max, y_min, y_max
