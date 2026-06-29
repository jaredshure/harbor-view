# Task 001 notes — Compose the Chart

Notes on assumptions and decisions made while building
`output/harbor_view.png`, for whoever (human or AI) picks up the next
task.

## Task numbering

`TASKS.md` originally defined "Task 001" as packaging/dependency setup
and reserved visual design (Task 005) and the static renderer
(Task 006) for later. The Task 001 brief that actually arrived asked
for the chart's visual composition instead. That's a reasonable
reordering — calibrating the art before building data plumbing fits
the project's "art first, data second" principle — so this work
proceeded under the new brief, and `TASKS.md` has been updated to
reflect what was actually built rather than the original plan.

## No real chart/GIS data source was reachable

The sandbox's network access is limited to package registries (pypi,
npm, etc.) — there's no route to NOAA's ENC servers, Natural Earth,
OpenStreetMap, or any other coastline dataset. "Real geographic data"
in the literal sense (surveyed coastline vectors) wasn't available.

Instead, `geometry.py` hand-builds an approximation of the real Fort
Lauderdale / Port Everglades shoreline: known real-world reference
coordinates (the inlet, the barrier island's general path) feed a
smoothed spline, offset to produce the island's ICW-facing edge and
the mainland edge. This is faithful to the *place* — the inlet is
roughly where it really is, the barrier island runs the right
direction — but it is not survey-accurate and shouldn't be mistaken
for one. If literal NOAA chart data becomes available in a later task
(e.g. via an allowlisted API), `geometry.py`'s output shape is the
natural place to swap in real vectors.

## Scale is exaggerated for legibility, not realistic

A few things are deliberately larger than real life because this is
meant to be looked at, not surveyed:

- **Barrier island width** is roughly 2-4x its real proportion.
  Rendered at true scale, the island all but disappears at this
  chart's zoom level (the brief's "ocean ~70%" target needs the
  island to read as a visible band, not a hairline).
- **Vessel icon sizes** (`KIND_SCALE_M` in `render.py`) are exaggerated
  similarly, especially tugs and pilot boats, which would otherwise be
  a few pixels across.
- **Home marker scale** (~230m footprint) was sized for legibility at
  this chart's zoom rather than matching "half the size of the earlier
  concept" literally — that concept was apparently drawn at a closer
  zoom, and halving its pixel size here would have made it invisible
  (it rendered as roughly 20px tall at literal half-scale; see
  render history for that intermediate, since-corrected attempt).

None of this affects the geographic *position* of anything — only the
width/size of features once drawn.

## View window math

The map panel is tall and narrow (portrait, ~1.87:1 height:width). To
fill it with `set_aspect("equal")` and avoid letterboxing, the
lat/lon (here: local meters) window's aspect ratio has to match the
panel's on-figure aspect ratio exactly — `render.py`'s
`compute_view_window()` derives the window from the panel's actual
size rather than picking offshore/inshore distances independently,
since the two are coupled once the aspect ratio is fixed. Current
settings (`VIEW_HALF_HEIGHT_NM = 7.2`, `COAST_FRAC_FROM_LEFT = 0.28`)
land at ~5.5 nm offshore (within the requested 5-10 nm) and ~69% ocean
coverage (within "roughly 70%").

## Known remaining visual rough edges

- The inlet channel cut is geometrically correct (built directly from
  the same shore arrays as the island fill, so it can't drift out of
  alignment) but the seam where it meets the open ocean is a hard
  polygon edge — a future pass could feather/blend this.
- Vessel route "tracks" (short dashed lines trailing each vessel) are
  a fixed length/style for all vessel kinds; could vary by speed or
  vessel size.
- The sidebar's wind/weather/tide values are static placeholder
  numbers, not wired to anything (no live data source exists yet —
  that's Tasks 002+).
- Land/ICW colors are flat fills; no texture or shading. Consistent
  with "calm" but worth a look once the palette is otherwise settled.

## Regenerating the chart

```
cd harbor-view
PYTHONPATH=src python3 src/harbor_view/chart/render.py
```

Output goes to `output/harbor_view.png`. The script has no CLI
arguments yet — all tunable constants live at the top of
`render.py` and in `geometry.py`/`fixtures.py`.
