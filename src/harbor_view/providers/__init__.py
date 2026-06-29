"""Vessel data providers for Harbor View.

This package is the seam between "where vessel data comes from" and
"how Harbor View draws it." See base.py's VesselProvider docstring for
the contract every provider must satisfy.

Public surface:
    Vessel, VesselType, VesselStatus  -- the shared data model
    VesselProvider                     -- the abstract provider interface
    PlaceholderProvider                -- the fixed demo fleet
    AISProvider                        -- live-AIS stub (not yet implemented)
"""
from __future__ import annotations

from harbor_view.providers.ais import AISProvider
from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselStatus, VesselType
from harbor_view.providers.placeholder import PlaceholderProvider

__all__ = [
    "Vessel",
    "VesselStatus",
    "VesselType",
    "VesselProvider",
    "PlaceholderProvider",
    "AISProvider",
]
