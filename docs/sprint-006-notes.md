# Sprint 6 notes — Persistent AIS Cache

This sprint refactored `AISProvider` to maintain an in-memory vessel
cache that persists across successive `get_vessels()` calls. The
renderer, the provider interface, the vessel model, and the visual
design were not changed.

## Motivation

A live run with a 120-second listen window produced:

    39 raw vessel records
    3 drawable vessels

The investigation (documented in this session, see commit history)
traced the 36 dropped vessels to two causes:

**Primary (estimated ~24 vessels): missing ShipStaticData**

AIS splits vessel identity from position across two message types:

| Message type      | Cadence (Class A underway) | Carries |
|-------------------|---------------------------|---------|
| `PositionReport`  | Every 2–10 seconds        | position, heading, speed, nav status |
| `ShipStaticData`  | Every ~6 minutes          | name, AIS type code, destination |

`is_drawable()` requires **both** halves (position + identity) before a
vessel is returned. With a 12–120 second listen window, most vessels
had broadcast several PositionReports but had not yet cycled through a
ShipStaticData broadcast during that specific window. They were in the
feed, correctly identified by MMSI — they just could not be drawn
because their type code had not arrived yet.

**Secondary (estimated ~10 vessels): unmapped AIS type codes**

Fort Lauderdale's ICW and beach waterway carry substantial recreational
and small-craft traffic. Fishing vessels (type 30), pleasure craft
(36/37), and sailing vessels are all correctly filtered out because
Harbor View has no glyph for them. This is intentional behavior, not
a bug.

**Why option B (anonymous vessels) was rejected**

Drawing a vessel as an unlabelled shape of unknown type would misrepresent
what is actually on the water and undermine the "calm, honest ambient
display" intent stated in CLAUDE.md and PRODUCT_SPEC.md. If we do not
know what a vessel is, we should not draw it. This remains the policy.

## Architecture

### Before (Sprint 4)

```python
async def _collect(self) -> dict[str, _PartialVessel]:
    partials: dict[str, _PartialVessel] = {}   # fresh every call
    # ... listen, feed into partials ...
    return partials

def get_vessels(self) -> list[Vessel]:
    partials = asyncio.run(self._collect())      # state discarded after
    return [p.to_vessel() for p in partials.values() if p.is_drawable()]
```

Every call started with an empty dict. Anything not received in this
window was lost.

### After (Sprint 6)

```python
def __init__(self, ...):
    ...
    self._cache: dict[str, _PartialVessel] = {}   # lives for process lifetime

async def _collect(self, cache: dict[str, _PartialVessel]) -> None:
    # ... listen, merge into cache via _handle_message ...
    # Returns None -- caller owns the cache

def get_vessels(self) -> list[Vessel]:
    asyncio.run(self._collect(self._cache))        # merge into persistent cache
    # evict stale entries
    # return drawable from cache
```

`_handle_message` was not changed. It takes whichever dict is passed to
it and uses `setdefault` to create or update the entry for each MMSI.
Passing `self._cache` instead of a fresh local dict is the entire
change that makes enrichment persistent.

## Cache lifecycle

1. **Created**: `__init__` allocates an empty `dict[str, _PartialVessel]`.
2. **Populated**: each `get_vessels()` call opens an AISStream connection,
   listens for `_listen_seconds`, and merges every received message into
   the cache. A vessel's position/heading are updated each PositionReport;
   its name and type code are updated each ShipStaticData (but never
   cleared by a PositionReport that lacks them).
3. **Read**: `get_vessels()` scans the cache for drawable entries after
   the listen window closes and after eviction.
4. **Evicted**: entries not updated within `_stale_seconds` (default
   15 minutes) are deleted before the drawable scan.
5. **Destroyed**: the cache is in-memory only. Process restart or
   provider reconstruction starts from an empty cache again, giving the
   same cold-start behaviour as Sprint 4 for the first call.

## Expiration policy

Vessels not seen in any AIS message (PositionReport or ShipStaticData)
for longer than `HARBOR_VIEW_AIS_STALE_SECONDS` (default 900 seconds,
15 minutes) are evicted.

15 minutes was chosen because:
- ShipStaticData cadence is ~6 minutes for a Class A vessel. Two full
  static-data cycles (12 minutes) gives comfortable margin for an
  intermittently-received feed without requiring the vessel to have
  broadcast recently.
- The refresh loop calls `get_vessels()` every 60 seconds (the default).
  A vessel present in the bounding box will typically generate a
  PositionReport every few seconds, so 15 minutes of silence is a strong
  signal that it has left the area or gone off-air.
- A tidal cycle at Port Everglades is roughly 12 hours; 15 minutes of
  cache lifetime keeps the display honest on the timescale of actual
  vessel transits without being so aggressive that a momentary signal
  dropout removes a vessel from the chart.

The eviction check happens in `get_vessels()` immediately after
`_collect()` returns, before the drawable-vessel list is assembled.
Evicted vessels do not appear in that call's output.

## Failure handling

With a persistent cache, the Sprint 4 rule "any failure → return []"
would unnecessarily clear a populated, valid cache on transient network
hiccups. The revised policy:

- Connection failure → log the exception, skip the listen window,
  proceed to eviction and drawable-filter with whatever is already in
  `self._cache`.
- Fresh provider (empty cache) + connection failure → cache is empty →
  return [] (same as Sprint 4 on the first call).

The "empty harbor is a valid state" principle is preserved: an empty
cache is honest and the renderer handles it correctly. What changes is
that a non-empty cache is no longer discarded on failure.

## Why this preserves the provider abstraction

`VesselProvider.get_vessels()` is defined only as "return the vessels
currently in view." Nothing in the interface specifies that the
implementation must be stateless. `PlaceholderProvider` is trivially
stateless (it returns the same fixed list every time); `AISProvider`
now maintains state between calls. Both are conforming implementations.

The renderer still calls exactly one method (`vessel_provider.get_vessels()`)
and receives a plain `list[Vessel]`. It has no knowledge of caches,
listen windows, or MMSI keys.

## Configuration

One new environment variable:

| Variable | Required? | Default | Purpose |
|---|---|---|---|
| `HARBOR_VIEW_AIS_STALE_SECONDS` | no | `900` | Seconds since last AIS message before a vessel is evicted from the cache |

All other variables (`AISSTREAM_API_KEY`, `HARBOR_VIEW_AIS_BBOX`,
`HARBOR_VIEW_AIS_LISTEN_SECONDS`) are unchanged.

## Amendment — Sprint 6.2: heading is now optional

A live investigation after Sprint 6 merged revealed a commercial cargo vessel
(ASG KHERSON, AIS type 70) that was present in the cache with both a
`PositionReport` and a `ShipStaticData` but still not drawable. The rejection
reason: `heading_deg` was `None` because the vessel's PositionReports carried
`TrueHeading=511` ("not available") and no COG field.

**Decision**: heading is now an optional rendering attribute, not a drawable
requirement. The three-step fallback that already existed in `_handle_message`
(1. TrueHeading, 2. COG) is extended with a third step (3. default to 0°/north)
applied at render time in `to_vessel()`.

Heading is treated as an optional rendering attribute. When unavailable, Harbor
View renders the vessel with a default orientation rather than suppressing it
entirely, because many legitimate AIS targets (especially anchored commercial
vessels) report heading as unavailable.

`_PartialVessel.heading_deg` remains `None` in the cache when no heading data
has been received. The default of `0.0` is applied only in `to_vessel()` when
constructing a `Vessel` for the renderer; this means any subsequent
`PositionReport` that does carry real heading data will correctly update the
stored value.

AIS type filtering, name requirements, and position requirements are unchanged.

## Files changed

```
src/harbor_view/providers/ais.py          -- persistent cache; _collect() signature
tests/providers/test_ais.py               -- updated stubs; 5 new cache tests
scripts/diagnose_ais_rejections.py        -- updated for new _collect() signature
deploy/harbor-view.env.example            -- HARBOR_VIEW_AIS_STALE_SECONDS documented
docs/sprint-006-notes.md                  -- this file
```

Files **not** changed:

```
src/harbor_view/chart/render.py           -- untouched
src/harbor_view/chart/geometry.py         -- untouched
src/harbor_view/chart/glyphs.py           -- untouched
src/harbor_view/providers/base.py         -- untouched
src/harbor_view/providers/models.py       -- untouched
src/harbor_view/providers/ais_types.py    -- untouched
src/harbor_view/providers/placeholder.py  -- untouched
src/harbor_view/appliance/refresh_loop.py -- untouched
```
