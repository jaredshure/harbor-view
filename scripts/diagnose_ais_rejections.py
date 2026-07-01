"""Diagnostic script: why did AISProvider drop vessels?

Calls AISProvider._collect() directly to get the full set of raw
_PartialVessel records (drawable and non-drawable alike), then
classifies every non-drawable record by the first failing condition
in is_drawable().

Run like this (same env vars as the appliance):

    AISSTREAM_API_KEY=<key> \\
    HARBOR_VIEW_AIS_LISTEN_SECONDS=120 \\
    PYTHONPATH=src python3 scripts/diagnose_ais_rejections.py

Output: a per-rejection-reason count table and one line per vessel
(sorted by rejection reason) so you can see what's in each bucket.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import sys

# Ensure the src tree is importable when the script is run from the
# project root without PYTHONPATH set.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

from harbor_view.providers.ais import AISProvider, _PartialVessel  # noqa: E402
from harbor_view.providers.ais_types import vessel_type_for_ais_code  # noqa: E402


def rejection_reason(p: _PartialVessel) -> str:
    """Return a short label for the first failing condition, or 'drawable'."""
    if p.latitude is None or p.longitude is None:
        return "missing position"
    if p.heading_deg is None:
        return "missing heading"
    if not p.name or not p.name.strip():
        return "missing name"
    if p.ais_type_code is None:
        return "missing ShipStaticData (no type code)"
    if vessel_type_for_ais_code(p.ais_type_code) is None:
        return f"unmapped AIS type {p.ais_type_code}"
    return "drawable"


def fmt_vessel(p: _PartialVessel) -> str:
    name = (p.name or "").strip() or "<no name>"
    return (
        f"  mmsi={p.mmsi}  name={name!r:25s}  "
        f"type={p.ais_type_code!s:>4}  "
        f"heading={p.heading_deg!s:>6}  "
        f"pos=({'ok' if p.latitude is not None else 'NONE'})"
    )


def main() -> None:
    provider = AISProvider()

    if not provider._api_key:
        print("ERROR: AISSTREAM_API_KEY is not set. Cannot connect to AISStream.io.")
        sys.exit(1)

    listen = provider._listen_seconds
    print(f"Listening for {listen:.0f}s…  (this will block until the window closes)")
    print()

    # _collect() now merges into a supplied cache dict rather than
    # returning one, so we pass a fresh dict to isolate this run.
    partials: dict[str, _PartialVessel] = {}
    asyncio.run(provider._collect(partials))

    total = len(partials)
    buckets: dict[str, list[_PartialVessel]] = collections.defaultdict(list)
    for p in partials.values():
        buckets[rejection_reason(p)].append(p)

    drawable_count = len(buckets.get("drawable", []))

    print(f"Raw records collected : {total}")
    print(f"Drawable              : {drawable_count}")
    print(f"Dropped               : {total - drawable_count}")
    print()
    print("─" * 60)
    print("REJECTION BREAKDOWN")
    print("─" * 60)

    order = [
        "missing position",
        "missing heading",
        "missing name",
        "missing ShipStaticData (no type code)",
    ]
    # Collect any unmapped-type labels dynamically.
    for key in sorted(buckets):
        if key not in order and key != "drawable":
            order.append(key)

    for reason in order:
        vessels = buckets.get(reason, [])
        if not vessels:
            continue
        print(f"\n[{len(vessels)}]  {reason}")
        for p in sorted(vessels, key=lambda v: v.name or ""):
            print(fmt_vessel(p))

    if buckets.get("drawable"):
        print(f"\n[{drawable_count}]  drawable (would have been returned)")
        for p in sorted(buckets["drawable"], key=lambda v: v.name or ""):
            print(fmt_vessel(p))


if __name__ == "__main__":
    main()
