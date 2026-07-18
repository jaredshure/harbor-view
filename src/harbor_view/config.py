"""Harbor View location and viewport configuration.

All configurable values are read from environment variables at process
start, with sensible defaults for The Palms / Fort Lauderdale
installation.  A different deployment needs only to set the relevant
env vars — no code changes required.

Environment variables:

  HARBOR_VIEW_LOCATION_NAME   Display name of the location
                              (default: "The Palms")
  HARBOR_VIEW_LOCATION_CITY   City/state line shown in the sidebar
                              (default: "Fort Lauderdale, FL")
  HARBOR_VIEW_REFERENCE_LAT   Reference location latitude
                              (default: 26.155531 — The Palms)
  HARBOR_VIEW_REFERENCE_LON   Reference location longitude
                              (default: -80.100832 — The Palms)
  HARBOR_VIEW_HOME_LAT        Home-marker latitude
                              (default: 26.155531 — The Palms)
  HARBOR_VIEW_HOME_LON        Home-marker longitude
                              (default: -80.100832 — The Palms)
  HARBOR_VIEW_TIMEZONE        IANA timezone name
                              (default: "America/New_York")

The reference location (HARBOR_VIEW_REFERENCE_LAT/LON) is the local
coordinate origin and the vertical composition centre of the rendered
chart.  Set it to the observer's actual position; the viewport solver
derives everything else from there and VIEW_OFFSHORE_RANGE_NM.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class HarborConfig:
    """Immutable location/viewport configuration for one Harbor View instance."""

    location_name: str   # e.g. "The Palms"
    location_city: str   # e.g. "Fort Lauderdale, FL" — shown in sidebar
    viewport_lat: float  # reference location (local coordinate origin)
    viewport_lon: float
    home_lat: float      # position of the home marker on the chart
    home_lon: float
    timezone: str        # IANA timezone name, e.g. "America/New_York"


DEFAULT_CONFIG = HarborConfig(
    location_name=os.environ.get("HARBOR_VIEW_LOCATION_NAME", "The Palms"),
    location_city=os.environ.get("HARBOR_VIEW_LOCATION_CITY", "Fort Lauderdale, FL"),
    viewport_lat=_float_env("HARBOR_VIEW_REFERENCE_LAT", 26.155531),
    viewport_lon=_float_env("HARBOR_VIEW_REFERENCE_LON", -80.100832),
    home_lat=_float_env("HARBOR_VIEW_HOME_LAT", 26.155531),
    home_lon=_float_env("HARBOR_VIEW_HOME_LON", -80.100832),
    timezone=os.environ.get("HARBOR_VIEW_TIMEZONE", "America/New_York"),
)
