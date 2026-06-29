"""The provider interface.

`VesselProvider` is the seam between "where vessel data comes from" and
"how Harbor View draws it." The renderer talks to exactly one method on
this interface:

    ships = vessel_provider.get_vessels()

and nothing else -- no knowledge of placeholders, AIS, file formats, or
network calls leaks past this boundary. Every concrete provider
(`PlaceholderProvider`, `AISProvider`, and whatever comes after) must
satisfy this interface and only this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from harbor_view.providers.models import Vessel


class VesselProvider(ABC):
    """Abstract base for anything that can supply a list of vessels.

    Implementations decide how vessels are obtained (a fixed list, a
    live feed, a recorded file, a simulation step) but must always
    return plain `Vessel` objects -- the renderer's only contract.
    """

    @abstractmethod
    def get_vessels(self) -> list[Vessel]:
        """Return the vessels currently in view.

        Implementations should return a fresh list each call rather
        than a shared mutable one, so callers can't accidentally
        mutate provider-internal state by editing the result.
        """
        raise NotImplementedError
