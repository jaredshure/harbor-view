"""Simulate 5 AISProvider refresh cycles to verify cache accumulation logging.

Models the realistic scenario: several vessels send PositionReports every
cycle, but only a subset send ShipStaticData (their ~6-minute cycle means
one or two arrive per 60-second window on average for a fleet of ~15
vessels).  Runs without a network connection -- useful in sandbox or for
CI smoke-testing the diagnostic log format.

Usage:
    PYTHONPATH=src python3 scripts/simulate_cache_cycles.py
"""
from __future__ import annotations

import json
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from harbor_view.providers.ais import AISProvider, _PartialVessel

# ---------------------------------------------------------------------------
# Fixture data -- a plausible Port Everglades fleet snapshot
# ---------------------------------------------------------------------------

def _pos(mmsi: int, heading: int) -> str:
    return json.dumps({
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi, "ShipName": f"VESSEL {mmsi}",
            "latitude": 26.10, "longitude": -80.09,
        },
        "Message": {"PositionReport": {
            "TrueHeading": heading, "Cog": heading, "Sog": 8.0,
            "NavigationalStatus": 0,
        }},
    })


def _static(mmsi: int, ais_type: int, name: str, dest: str = "") -> str:
    return json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {
            "MMSI": mmsi, "ShipName": name,
            "latitude": 26.10, "longitude": -80.09,
        },
        "Message": {"ShipStaticData": {
            "Name": name, "Type": ais_type, "Destination": dest,
        }},
    })


# 12 vessels that will send PositionReports every cycle
POSITION_FLEET = [
    (3671001, 90), (3671002, 180), (3671003, 270), (3671004, 45),
    (3671005, 135), (3671006, 225), (3671007, 315), (3671008, 10),
    (3671009, 90), (3671010, 180), (3671011, 270), (3671012, 45),
]

# Static data that trickles in across cycles (mimics ~6-minute cadence)
# Each sub-list is the static messages that "arrive" during that cycle.
STATIC_BY_CYCLE: list[list[tuple[int, int, str, str]]] = [
    # cycle 0 -- 2 static messages in first 12s window
    [(3671001, 70, "CARGO QUEEN", "MIAMI"), (3671002, 80, "TANKER ONE", "NASSAU")],
    # cycle 1 -- 1 more
    [(3671003, 70, "BOX CARRIER", "PORT EVG")],
    # cycle 2 -- 2 more including a fishing boat (unmapped type 30)
    [(3671004, 30, "LADY LUCK", ""), (3671005, 60, "CARIBBEAN STAR", "FREEPORT")],
    # cycle 3 -- 3 more
    [(3671006, 70, "ATLANTIC WIND", "SAVANNAH"),
     (3671007, 80, "OIL TRADER", "HOUSTON"),
     (3671008, 52, "TUG MAXWELL", "")],
    # cycle 4 -- 2 more
    [(3671009, 70, "MERIDIAN", "BALTIMORE"), (3671010, 60, "OASIS DREAM", "MIAMI")],
]


def make_cycle_messages(cycle_idx: int) -> list[str]:
    msgs = []
    for mmsi, heading in POSITION_FLEET:
        msgs.append(_pos(mmsi, heading))
    for mmsi, ais_type, name, dest in STATIC_BY_CYCLE[cycle_idx]:
        msgs.append(_static(mmsi, ais_type, name, dest))
    return msgs


# ---------------------------------------------------------------------------
# Drive the provider through 5 fake cycles
# ---------------------------------------------------------------------------

def main() -> None:
    provider = AISProvider(api_key="simulated", stale_seconds=900.0,
                           bounding_box=((25.85, -80.30), (26.45, -79.85)))

    print("=" * 70)
    print("Simulating 5 AISProvider refresh cycles (no live network)")
    print("Each cycle: 12 PositionReports + a few ShipStaticData messages")
    print("=" * 70)

    for cycle in range(5):
        msgs = make_cycle_messages(cycle)
        print(f"\n--- Cycle {cycle} ({len(msgs)} messages: "
              f"{sum(1 for m in msgs if 'PositionReport' in m)} pos + "
              f"{sum(1 for m in msgs if 'ShipStaticData' in m)} static) ---")

        async def fake_collect(cache, _msgs=msgs):
            for m in _msgs:
                provider._handle_message(m, cache)

        import asyncio
        # Monkeypatch _collect for this cycle only
        original = provider._collect
        provider._collect = fake_collect
        provider.get_vessels()
        provider._collect = original

    print("\n" + "=" * 70)
    print("Final cache state:")
    for mmsi, p in sorted(provider._cache.items()):
        drawable = "DRAWABLE" if p.is_drawable() else "not drawable"
        print(f"  {mmsi}  name={p.name or '?':20s}  type={p.ais_type_code!s:>4}  "
              f"heading={p.heading_deg!s:>6}  {drawable}")


if __name__ == "__main__":
    main()
