# Sprint 4 notes — First Live Harbor

This sprint replaced the Sprint 3 `AISProvider` stub with a real
implementation backed by [AISStream.io](https://aisstream.io). The
renderer, the visual design, and `PlaceholderProvider` were not
touched except for one small, additive change to the `Vessel` model
(see "Model change" below) — see "Visual verification" for how that
was confirmed not to affect any rendered pixel.

## What `AISProvider` actually does

1. Reads `AISSTREAM_API_KEY` from the environment. If it's missing,
   logs a warning and returns `[]` immediately — no connection is
   attempted.
2. Opens a WebSocket to `wss://stream.aisstream.io/v0/stream` and
   sends a subscription message (API key + a bounding box around Port
   Everglades / Fort Lauderdale Beach + a filter for `PositionReport`
   and `ShipStaticData` message types).
3. Listens for a configurable window (default 12 seconds — see
   "Configuration"). AIS is a continuous stream, not a request/response
   API, so a single synchronous `get_vessels()` call has to decide when
   to stop listening and return what it has.
4. Merges messages per MMSI in memory. AIS splits "where is it and
   which way is it heading" (`PositionReport`) from "what's it called
   and what kind of vessel is it" (`ShipStaticData`) into two different
   message types that arrive independently — a vessel only becomes
   drawable once both halves have been seen during the listen window.
5. Maps the AIS numeric ship-type code to one of Harbor View's five
   drawable `VesselType`s (`harbor_view/providers/ais_types.py`).
   Vessel types Harbor View has no glyph for — fishing boats, sailing
   vessels, military craft, high-speed craft, and the AIS "other"/
   unspecified codes — are dropped, not guessed at.
6. Returns a plain `list[Vessel]`. Any vessel still missing a position,
   heading, name, or a mappable type by the end of the listen window is
   dropped rather than returned half-filled.
7. **Any failure at any step — no key, DNS failure, refused connection,
   auth rejection, a malformed message, an empty window — results in
   `[]`.** Nothing is raised to the caller; nothing falls back to
   placeholder data. The renderer asked for vessels and got an empty
   list, which it already knows how to draw (zero ships, full chart).

## Why merge two message types instead of just using `PositionReport`

A `PositionReport` alone carries position, heading, speed, and
navigational status — but never a name or a vessel-type code. A chart
that's supposed to show "what's out there" can't responsibly draw an
unnamed, untyped triangle and call it a ship. Waiting for
`ShipStaticData` too (which AIS transmits far less often — every few
minutes, versus every few seconds for `PositionReport` on a moving
Class A vessel) is the cost of actually knowing what a vessel is before
drawing it. The alternative — inventing a name or guessing a type — was
explicitly ruled out by the brief's "gracefully ignore incomplete...
records" instruction.

## Model change: `origin` and `destination` became optional

`Vessel.origin` and `Vessel.destination` were required `str` fields as
of Sprint 3. AIS has **no concept of origin at all** — it is never
broadcast, by any vessel, ever — and `destination` is optional
free-text that's frequently blank, abbreviated, or stale. Making both
fields default to `""` was the minimal change that let `AISProvider`
return honest data without inventing a fictional origin port, and
without needing to touch `chart/render.py`'s existing
`f"{vessel.origin}  ->  {vessel.destination}"` line -- an empty piece
just renders as blank space next to the arrow. `PlaceholderProvider`
is unaffected: it still supplies both fields for every vessel, exactly
as before.

This was the one model change made this sprint. It is additive
(existing code that always supplied both fields keeps working
unchanged) and was verified not to alter the placeholder render's
output -- see "Visual verification."

## AIS ship-type mapping

| AIS code(s)      | Meaning (AIS)              | Harbor View `VesselType` |
|-------------------|----------------------------|---------------------------|
| 50                | Pilot vessel                | `PILOT`                   |
| 31, 32, 52        | Towing / tug / workboat     | `TUG`                      |
| 60-69             | Passenger                   | `CRUISE` *(closest match -- Harbor View has no separate ferry/ropax glyph)* |
| 70-79             | Cargo                       | `CARGO`                    |
| 80-89             | Tanker                       | `TANKER`                   |
| everything else   | fishing, sailing, military, high-speed craft, "other", unspecified/0 | *(dropped -- no glyph)* |

Source: ITU-R M.1371-5 and the NOAA/USCG Marine Cadastre AIS
vessel-type-code reference, cross-checked against MarineTraffic's
published code table. See `providers/ais_types.py` for the exact
ranges and citations.

## Configuration

All configuration is via environment variables -- nothing is
hardcoded. See `.env.example` for the canonical list with
explanations. Summary:

| Variable | Required? | Default | Purpose |
|---|---|---|---|
| `AISSTREAM_API_KEY` | yes, for live data | none | AISStream.io API key. Missing -> empty harbor, no connection attempt. |
| `HARBOR_VIEW_AIS_BBOX` | no | Port Everglades box (`25.85,-80.30,26.45,-79.85`) | `"lat1,lon1,lat2,lon2"` |
| `HARBOR_VIEW_AIS_LISTEN_SECONDS` | no | `12` | How long one `get_vessels()` call listens before returning |

Harbor View does not read `.env` files itself (no `python-dotenv` or
similar was added -- see "Dependency" below for why). Export these as
real environment variables, or source a `.env` file with your shell or
deployment tooling before running Harbor View, e.g.:

```bash
export $(grep -v '^#' .env | xargs)   # bash, simple cases
PYTHONPATH=src python3 src/harbor_view/chart/render.py
```

## Dependency: `websockets`

`AISProvider` needs a WebSocket client; `websockets` was chosen as the
smallest, most widely-used option with no further dependencies of its
own. It's imported lazily inside `AISProvider._collect()`, not at
module level, so importing `harbor_view.providers.ais` (or the
package's `__init__.py`, which re-exports `AISProvider`) doesn't
require the package to be installed unless an `AISProvider` is
actually constructed and used. Added to `requirements.txt` -- see that
file for why a `pyproject.toml` doesn't exist yet.

## Visual verification ("the renderer was not changed")

Before this sprint's changes, the existing Sprint-2.5-frozen reference
render was diffed pixel-by-pixel against a fresh render taken after
every code change in this sprint (the `Vessel` model edit, then the new
`ais_types.py` and `ais.py` files). At each point, the only differing
pixels were inside the sidebar's live clock display -- exactly the
same check used in Sprint 3, and for the same reason (real time
passing between renders, not a code change).
`tests/chart/test_render_providers.py` encodes equivalent checks for
`AISProvider` specifically:

- `test_render_with_ais_provider_and_no_api_key_produces_empty_harbor` --
  confirms `render()` completes successfully (no exception, a non-empty
  file) when driven by an unconfigured `AISProvider`.
- `test_render_with_ais_provider_matches_placeholder_layout_when_empty` --
  confirms an unconfigured `AISProvider`'s render is pixel-identical
  (outside the clock) to a render from a trivial fake provider that
  always returns zero vessels -- i.e. `AISProvider`'s failure path does
  nothing visually different from "there are simply no vessels."

## Assumptions and limitations

- **This sandbox cannot reach AISStream.io.** The environment's network
  egress is allowlisted to package registries only; a direct test
  connection to `wss://stream.aisstream.io` returns `403
  host_not_allowed` from the egress proxy. The deliverable screenshot
  therefore necessarily shows the **empty-harbor failure path**, not a
  populated live chart -- which happens to be exactly the behavior the
  brief asked for in that scenario ("an empty harbor is a valid
  state"). The implementation was still exercised against the real
  protocol up to the point of the network block: a real subscription
  message was sent over a real WebSocket handshake attempt to the real
  host, and the real rejection was caught and handled correctly. A
  deployment with normal internet access (and a real AISStream.io API
  key) should populate the chart with live vessels using the same
  code, unmodified -- but this could not be observed directly in this
  environment.
- **`origin` is always empty for AIS-sourced vessels.** This is a
  property of AIS itself, not a gap in this implementation -- no AIS
  message of any kind carries a "where did this voyage start" field.
- **`destination` is whatever the crew typed**, with AIS's character
  padding stripped. It's frequently a port code, an abbreviation,
  blank, or stale information from a previous voyage leg. No
  validation or geocoding is attempted.
- **The passenger->cruise mapping is an approximation.** AIS type
  codes 60-69 cover everything from a large cruise ship to a small
  passenger ferry; Harbor View has only one glyph for that whole range
  (`VesselType.CRUISE`), so a ferry will be drawn with the cruise-ship
  hull. Splitting this further would require either a new glyph (a
  composition change, out of scope for this sprint) or guessing from
  vessel dimensions, which wasn't pursued.
- **A single `get_vessels()` call is a snapshot, not a continuous
  feed.** Each call opens a fresh WebSocket connection, listens for the
  configured window, and closes it. There's no persistent connection
  or caching between calls -- calling `get_vessels()` twice in a row
  re-listens from scratch both times. A future refresh-loop task
  (Task 007) that calls this repeatedly on an interval should account
  for the cost of repeatedly reconnecting; a longer-lived connection
  with an internal cache was considered out of scope here since the
  brief described `get_vessels()` as the entire interface contract.
- **Class B and small Class A vessels under-report.** Per AIS
  fundamentals, smaller/Class B vessels broadcast static data (name,
  type, destination) far less reliably than larger Class A vessels --
  so the harbor may under-represent small craft even when the feed is
  fully reachable, independent of anything in this implementation.
- **A failure partway through the listen window discards whatever was
  collected so far.** If the socket drops after, say, 8 of 12 seconds,
  the exception propagates out of `_collect()` and is caught by
  `get_vessels()`'s broad `except Exception`, which returns `[]`
  rather than the partial data gathered before the drop. Returning
  partial data on a clean mid-window failure would be a reasonable
  future improvement; it wasn't pursued this sprint given the brief's
  framing that an empty harbor is already an acceptable outcome, and
  to keep the failure path's behavior (always exactly `[]` on any
  exception) simple to reason about and test.

## Files created

```
src/harbor_view/providers/ais_types.py     -- AIS type-code -> VesselType mapping
tests/providers/test_ais_types.py

.env.example                                -- documents env vars, no real secrets
requirements.txt                            -- records the new websockets dependency
docs/sprint-004-notes.md                    -- this file
```

## Files modified

- `src/harbor_view/providers/ais.py` -- replaced the Sprint 3 stub
  (which raised `NotImplementedError`) with the real implementation
  described above.
- `src/harbor_view/providers/models.py` -- `Vessel.origin` and
  `Vessel.destination` changed from required to optional
  (default `""`). See "Model change" above.
- `tests/providers/test_ais.py` -- replaced the Sprint 3 stub tests
  (which only checked that `NotImplementedError` was raised) with real
  coverage of message parsing, merging, the bounding-box filter, and
  the graceful-failure path, all via mocks/fakes per CLAUDE.md (no
  live network calls).
- `tests/chart/test_render_providers.py` -- added the two
  `AISProvider`-specific render tests described under "Visual
  verification."

`src/harbor_view/chart/render.py`, `geometry.py`, and `glyphs.py` were
**not modified** in this sprint.
