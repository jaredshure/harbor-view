"""Mapping from AIS numeric ship-type codes to Harbor View's VesselType.

AIS's "Type of ship and cargo" field (carried in `ShipStaticData`'s
`Type`) is a two-digit code defined by ITU-R M.1371. Harbor View only
knows how to draw five kinds of vessel (see
`harbor_view.providers.models.VesselType` and
`harbor_view.chart.glyphs.GLYPH_BY_KIND`), so most of the real AIS
type space -- fishing boats, sailing yachts, military vessels,
high-speed craft, dredgers, and so on -- has nowhere to go.

`vessel_type_for_ais_code` returns `None` for any code Harbor View
can't draw. Callers (here, `AISProvider`) are expected to drop such
vessels rather than guess -- silently mapping a fishing trawler to
"cargo" would misrepresent what's actually on the water, which matters
more for a piece meant to be looked at closely than it would for a
generic tracker.

Sources for the ranges below: ITU-R M.1371-5 (the AIS standard itself)
and the U.S. Coast Guard / NOAA Marine Cadastre vessel-type-code
reference (coast.noaa.gov/data/marinecadastre/ais/VesselTypeCodes2018.pdf),
cross-checked against MarineTraffic's published code table.
"""
from __future__ import annotations

from harbor_view.providers.models import VesselType

# Exact-code matches, checked first.
_EXACT_CODE_TO_TYPE: dict[int, VesselType] = {
    50: VesselType.PILOT,  # Pilot vessel
    52: VesselType.TUG,    # Tugs, light boats, fleet boats, similar workboats
    31: VesselType.TUG,    # Towing (ahead/alongside)
    32: VesselType.TUG,    # Towing astern / large tow
}

# Range matches, checked if no exact match applies.
_RANGE_TO_TYPE: list[tuple[range, VesselType]] = [
    (range(61, 70), VesselType.CRUISE),  # Passenger sub-categories 61-69.
                                          # Code 60 ("Passenger, unspecified")
                                          # is excluded: it is too broad to
                                          # map honestly to a cruise-ship
                                          # glyph -- harbor ferries and water
                                          # taxis use it as often as large
                                          # passenger vessels.
    (range(70, 80), VesselType.CARGO),   # Cargo, all sub-categories
    (range(80, 90), VesselType.TANKER),  # Tanker, all sub-categories
]


def vessel_type_for_ais_code(ais_type_code: int | None) -> VesselType | None:
    """Map an AIS numeric ship-type code to a Harbor View VesselType.

    Returns `None` if the code doesn't correspond to anything Harbor
    View can draw (fishing, sailing, military, high-speed craft,
    "other"/unspecified, or the code is missing/None) -- callers
    should treat `None` as "drop this vessel," not as a reason to
    guess a default category.
    """
    if ais_type_code is None:
        return None
    if ais_type_code in _EXACT_CODE_TO_TYPE:
        return _EXACT_CODE_TO_TYPE[ais_type_code]
    for code_range, vessel_type in _RANGE_TO_TYPE:
        if ais_type_code in code_range:
            return vessel_type
    return None
