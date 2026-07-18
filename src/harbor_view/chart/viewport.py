"""Viewport geometry solver for Harbor View.

Computes the geographic extent (in local meters) of the map panel from
three user-facing parameters:

  - offshore_range_nm   how far offshore the chart extends (east edge)
  - panel_aspect        map panel height / width (> 1 for portrait)
  - coast_frac_from_left  internal design constant: the fraction of
                          total x-span that lies west of the reference
                          location (land context), default 0.21

Math:

    x_max  = offshore_range_nm * NM          # east edge, metres
    x_span = x_max / (1 - coast_frac)        # total east–west span
    x_min  = -coast_frac * x_span            # west edge (land context)
    y_span = panel_aspect * x_span           # north–south (fills panel)
    y_min  = -y_span / 2
    y_max  =  y_span / 2

The reference location always sits at (0, 0) in local metres and always
appears at `coast_frac_from_left` from the left edge of the panel.
Scaling `offshore_range_nm` proportionally changes the entire viewport —
north/south, land context, and offshore depth all expand together.

This module has no dependencies on matplotlib, numpy, or the rest of
Harbor View, making it straightforward to unit-test in isolation.
"""
from __future__ import annotations

NM = 1852.0  # metres per nautical mile


def solve_viewport(
    offshore_range_nm: float,
    panel_aspect: float,
    coast_frac_from_left: float = 0.21,
) -> tuple[float, float, float, float]:
    """Compute the geographic viewport bounds in local metres.

    The reference location (the observer's home) is at the origin (0, 0)
    and appears at ``coast_frac_from_left`` from the western edge of the
    map panel.  The eastern edge is exactly ``offshore_range_nm`` NM from
    the origin.  The north–south extent is derived from ``panel_aspect``
    so the panel is filled without letterboxing.

    Args:
        offshore_range_nm: Ocean depth to show east of the reference, NM.
        panel_aspect: Map panel height divided by width (> 1 = portrait).
        coast_frac_from_left: Fraction of total x-span lying west of the
            reference location.  0.21 gives 21 % land context, 79 %
            ocean; do not expose directly to end users.

    Returns:
        (x_min, x_max, y_min, y_max) in metres, with the reference
        location at (0, 0).
    """
    if offshore_range_nm <= 0:
        raise ValueError(f"offshore_range_nm must be positive, got {offshore_range_nm}")
    if panel_aspect <= 0:
        raise ValueError(f"panel_aspect must be positive, got {panel_aspect}")
    if not (0.0 < coast_frac_from_left < 1.0):
        raise ValueError(
            f"coast_frac_from_left must be in (0, 1), got {coast_frac_from_left}"
        )

    x_max = offshore_range_nm * NM
    x_span = x_max / (1.0 - coast_frac_from_left)
    x_min = -(coast_frac_from_left * x_span)

    y_span = panel_aspect * x_span
    y_min = -y_span / 2.0
    y_max = y_span / 2.0

    return x_min, x_max, y_min, y_max
