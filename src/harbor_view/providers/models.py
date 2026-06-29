"""The shared vessel data model.

`Vessel` is the one object the renderer is allowed to know about. Every
provider (placeholder, AIS, future simulation/playback providers) must
produce a list of these and nothing else -- the renderer has no idea
which provider supplied them, and providers have no idea how they'll be
drawn.

Field choices follow Sprint 3's brief. A few notes on fields the
current renderer doesn't yet use (`mmsi`, `speed_kn`, `status`,
`timestamp`): they're part of the model now because a real AIS feed
will always supply them, and because future Harbor View features
(filtering by status, showing "as of" freshness, etc.) will want them.
Carrying a field the renderer doesn't render yet is normal for a data
model; it does not violate "no new features" -- nothing in the visual
output changes by adding an unused field.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import Enum


class VesselType(str, Enum):
    """The vessel categories Harbor View knows how to draw.

    Backed by `str` so existing code that compares against plain
    strings (e.g. `vessel.kind == "cruise"`) keeps working, and so a
    provider can construct one from a raw string like
    `VesselType("cargo")` without extra ceremony.
    """

    CRUISE = "cruise"
    CARGO = "cargo"
    TANKER = "tanker"
    TUG = "tug"
    PILOT = "pilot"


class VesselStatus(str, Enum):
    """Coarse navigational status, mirroring the AIS "navigation
    status" concept loosely (see ITU-R M.1371) without committing to
    its full enumeration -- Harbor View only needs enough detail to
    eventually decide things like "is this vessel moving."
    """

    UNDERWAY = "underway"
    AT_ANCHOR = "at_anchor"
    MOORED = "moored"
    AT_DOCK = "at_dock"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Vessel:
    """A single vessel, in the form the renderer consumes.

    Required fields are the ones the current renderer actually reads
    (name, type, position, heading). `origin` and `destination`
    default to `""` rather than being strictly required -- as of
    Sprint 4, real AIS data motivated this: AIS has no concept of
    "origin" at all (it only ever broadcasts a destination, and even
    that is frequently blank, abbreviated, or stale free-text typed by
    a crew member), so a provider backed by real data cannot always
    supply either field truthfully. Defaulting to `""` means
    `chart/render.py`'s existing
    `f"{vessel.origin}  ->  {vessel.destination}"` keeps rendering
    without modification (an empty piece just renders as blank space
    next to the arrow) rather than the renderer needing to learn a new
    "unknown route" case. `PlaceholderProvider` continues to supply
    both for every vessel, unchanged.

    Optional fields (`mmsi`, `speed_kn`, `status`, `timestamp`) default
    to `None` so a provider that can't supply them yet (or a fixture
    that never had them) doesn't need to fake a value.
    """

    name: str
    vessel_type: VesselType
    latitude: float
    longitude: float
    heading_deg: float  # 0 = north, clockwise, matching compass bearing

    origin: str = ""
    destination: str = ""
    mmsi: str | None = None
    speed_kn: float | None = None
    status: VesselStatus | None = None
    timestamp: _dt.datetime | None = None

    # --- Backward-compatible aliases -----------------------------------
    # The renderer (chart/render.py) and earlier fixtures referred to
    # these fields as `lat`, `lon`, and `kind`. Rather than touch every
    # call site during this refactor (the brief asks for "no visible
    # changes" and minimal risk), expose the old names as properties so
    # existing rendering code keeps working unchanged. New code should
    # prefer `latitude`/`longitude`/`vessel_type`.
    @property
    def lat(self) -> float:
        return self.latitude

    @property
    def lon(self) -> float:
        return self.longitude

    @property
    def kind(self) -> str:
        return self.vessel_type.value
