"""Harbor View location and viewport configuration.

All configurable values are read from environment variables at process
start, with sensible defaults for the Fort Lauderdale / Port Everglades
installation. A different deployment needs only to set the relevant env
vars — no code changes required.

Environment variables:

  HARBOR_VIEW_LOCATION_NAME   Display name of the location
                              (default: "The Palms")
  HARBOR_VIEW_LOCATION_CITY   City/state line shown in the sidebar
                              (default: "Fort Lauderdale, FL")
  HARBOR_VIEW_VIEWPORT_LAT    Viewport projection center, latitude
                              (default: 26.0906)
  HARBOR_VIEW_VIEWPORT_LON    Viewport projection center, longitude
                              (default: -80.1095)
  HARBOR_VIEW_HOME_LAT        Home-marker latitude
                              (default: 26.1300)
  HARBOR_VIEW_HOME_LON        Home-marker longitude
                              (default: -80.1010)
  HARBOR_VIEW_TIMEZONE        IANA timezone name
                              (default: "America/New_York")

The viewport center (HARBOR_VIEW_VIEWPORT_LAT/LON) is the projection
origin and the composition center of the rendered chart — not
necessarily the same point as the home marker. Adjust it to achieve
the best visual balance for the scene (coastline, open water, vessel
traffic) rather than to pin it to a specific building or landmark.
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
    viewport_lat: float  # projection reference and composition center
    viewport_lon: float
    home_lat: float      # position of the home marker on the chart
    home_lon: float
    timezone: str        # IANA timezone name, e.g. "America/New_York"


DEFAULT_CONFIG = HarborConfig(
    location_name=os.environ.get("HARBOR_VIEW_LOCATION_NAME", "The Palms"),
    location_city=os.environ.get("HARBOR_VIEW_LOCATION_CITY", "Fort Lauderdale, FL"),
    viewport_lat=_float_env("HARBOR_VIEW_VIEWPORT_LAT", 26.0906),
    viewport_lon=_float_env("HARBOR_VIEW_VIEWPORT_LON", -80.1095),
    home_lat=_float_env("HARBOR_VIEW_HOME_LAT", 26.1300),
    home_lon=_float_env("HARBOR_VIEW_HOME_LON", -80.1010),
    timezone=os.environ.get("HARBOR_VIEW_TIMEZONE", "America/New_York"),
)
