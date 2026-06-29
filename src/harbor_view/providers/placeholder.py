"""The placeholder provider.

Supplies the same fixed, hand-placed fleet that has powered every
Harbor View render since Task 001/Sprint 1, now expressed as `Vessel`
objects instead of the old `PlaceholderVessel` dataclass that lived in
`chart/fixtures.py`. Positions, headings, names, and origin/destination
pairs are unchanged from the prior fixture data -- this refactor moves
where the data lives, not what it says. See docs/sprint-003-notes.md
for the migration details.

These vessels are entirely fake, used to validate the chart's visual
composition. Real AIS integration is a separate provider
(`harbor_view.providers.ais.AISProvider`).
"""
from __future__ import annotations

from harbor_view.providers.base import VesselProvider
from harbor_view.providers.models import Vessel, VesselType

# Sprint 2 recomposition: positions chosen for visual balance rather
# than even spacing --
#   - one cruise ship prominent, close to Port Everglades
#   - cargo vessels pushed farther offshore (they're the workhorses,
#     not the foreground subject)
#   - one tanker farthest east of all (a distant, minor presence)
#   - the pilot boat close to the inlet (its actual job)
#   - tugs close to shore, small and quiet
# Carried over unchanged from chart/fixtures.py during the Sprint 3
# provider refactor.
PLACEHOLDER_FLEET: list[Vessel] = [
    # The hero vessel: large, close to the inlet, unmistakably the
    # first thing the eye should land on after the open water itself.
    Vessel("OCEAN MAJESTY", VesselType.CRUISE, 26.1010, -80.0905, 205,
           "PORT EVERGLADES", "NASSAU", speed_kn=19.0),
    # Second cruise ship kept but moved to a quiet, distant corner.
    Vessel("CARIBBEAN STAR", VesselType.CRUISE, 26.2050, -80.0680, 25,
           "COZUMEL", "PORT EVERGLADES", speed_kn=17.5),

    # Cargo: farther offshore than the cruise ship, mid-distance.
    Vessel("MAERSK HORIZON", VesselType.CARGO, 26.1680, -80.0640, 205,
           "SAVANNAH", "PORT EVERGLADES", speed_kn=16.0),
    Vessel("EVER GRANITE", VesselType.CARGO, 26.0150, -80.0700, 350,
           "FREEPORT", "PORT EVERGLADES", speed_kn=14.5),
    Vessel("ATLANTIC TRADER", VesselType.CARGO, 26.1480, -80.0590, 190,
           "PORT EVERGLADES", "SAN JUAN", speed_kn=15.0),

    # Tanker: the farthest-east vessel on the chart, a minor presence
    # near the horizon. Second tanker kept but tucked to the south,
    # similarly distant.
    Vessel("STAR ENDEAVOR", VesselType.TANKER, 26.1250, -80.0420, 160,
           "PORT EVERGLADES", "TAMPA", speed_kn=11.0),
    Vessel("GULF VOYAGER", VesselType.TANKER, 26.0070, -80.0640, 340,
           "HOUSTON", "PORT EVERGLADES", speed_kn=12.0),

    # Tugs: small, close to shore, near the inlet they service.
    Vessel("HARBOR KING", VesselType.TUG, 26.0945, -80.0935, 80,
           "PORT EVERGLADES", "PORT EVERGLADES", speed_kn=6.5),
    Vessel("MISS CARLA", VesselType.TUG, 26.0835, -80.0955, 260,
           "PORT EVERGLADES", "PORT EVERGLADES", speed_kn=5.0),

    # Pilot boat: right at the inlet mouth, its actual working ground.
    Vessel("EVERGLADES PILOT", VesselType.PILOT, 26.0906, -80.0880, 270,
           "PILOT STATION", "PORT EVERGLADES", speed_kn=9.0),
]


class PlaceholderProvider(VesselProvider):
    """Returns the fixed placeholder fleet, unchanged, every call.

    This is what has powered every Harbor View render to date. It
    takes no arguments and needs no configuration -- the fleet is
    intentionally hand-tuned for the chart's composition (see comments
    above and in docs/sprint-002-notes.md), not meant to be
    parameterized.
    """

    def get_vessels(self) -> list[Vessel]:
        # Return a copy so callers can't mutate the module-level fleet
        # by editing the list they get back.
        return list(PLACEHOLDER_FLEET)
