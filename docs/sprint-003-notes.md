# Sprint 3 notes — Data Architecture

This sprint separated the rendering engine from the data source. It
changed no visual output (see "Visual verification" below) and added
no new features to what's displayed — only where the displayed data
comes from, structurally.

## The architecture

```
render()                     -- knows nothing below this line
   |
   |  vessel_provider.get_vessels()
   v
VesselProvider (abstract)    -- the one method the renderer calls
   |
   +-- PlaceholderProvider   -- the fixed demo fleet (default)
   +-- AISProvider           -- stub; raises NotImplementedError
   +-- (future providers: recorded playback, simulation, ...)
```

Every provider returns the same thing: a plain `list[Vessel]`. The
renderer (`harbor_view.chart.render`) imports `Vessel` and
`VesselProvider` for type purposes, and `PlaceholderProvider` only as
its *default* — nothing in `render.py` or any function it calls
branches on which provider supplied the data, checks its type, or
imports anything provider-specific beyond that default.

### The `Vessel` model

`harbor_view.providers.models.Vessel` is the one object every provider
must produce and the renderer is allowed to consume:

| Field          | Type                    | Required? |
|----------------|-------------------------|-----------|
| `name`         | `str`                   | yes       |
| `vessel_type`  | `VesselType` enum       | yes       |
| `latitude`     | `float`                 | yes       |
| `longitude`    | `float`                 | yes       |
| `heading_deg`  | `float`                 | yes       |
| `origin`       | `str`                   | yes       |
| `destination`  | `str`                   | yes       |
| `mmsi`         | `str \| None`           | no        |
| `speed_kn`     | `float \| None`         | no        |
| `status`       | `VesselStatus \| None`  | no        |
| `timestamp`    | `datetime \| None`      | no        |

The "required" fields are exactly what the current renderer reads. The
optional fields exist because a real AIS feed will always have them
and a future feature (e.g. showing data freshness, or filtering by
navigation status) will want them — but nothing in this sprint's
renderer reads `mmsi`, `speed_kn`, `status`, or `timestamp` yet, so
adding them changes no visual output.

`Vessel` also exposes `.lat`, `.lon`, and `.kind` as read-only
properties aliasing `.latitude`, `.longitude`, and `.vessel_type.value`
respectively. These exist purely so `chart/render.py`'s existing code
(written against the old `PlaceholderVessel` dataclass's field names)
kept working with zero changes to its vessel-reading logic. New code
should prefer the full names.

`VesselType` and `VesselStatus` are `str` subclasses (`Enum` mixed
with `str`), so old code comparing `vessel.kind == "cargo"` keeps
working without modification, while new code can use
`VesselType.CARGO` for clarity and IDE support.

### The `VesselProvider` interface

```python
class VesselProvider(ABC):
    @abstractmethod
    def get_vessels(self) -> list[Vessel]:
        ...
```

That's the entire contract. `render()` calls exactly this method, once
per render, on whatever provider it's given.

### `PlaceholderProvider`

Returns the same ten-vessel fleet that has powered every Harbor View
render since Sprint 1, now expressed as `Vessel` objects. Positions,
headings, names, and origin/destination pairs are unchanged byte-for-
byte from the old `chart/fixtures.py` data — see "Visual verification"
below for how that was confirmed.

### `AISProvider` (stub)

Satisfies the `VesselProvider` interface but its `get_vessels()`
raises `NotImplementedError` with a message pointing back to this
document. Its constructor accepts arbitrary arguments (and ignores
them) so call sites can start writing `AISProvider(endpoint=..., ...)`
today without the stub breaking — though there's nothing to actually
connect to yet.

The stub's docstring (`src/harbor_view/providers/ais.py`) sketches the
shape a real implementation will need: connection details, a
field-of-view filter, AIS-to-`Vessel` field mapping, and an error
policy for feed outages. None of that is implemented — it's there so
the next sprint has a concrete starting point instead of a blank file.

## Files created

```
src/harbor_view/providers/__init__.py     -- public exports
src/harbor_view/providers/models.py        -- Vessel, VesselType, VesselStatus
src/harbor_view/providers/base.py          -- VesselProvider (abstract)
src/harbor_view/providers/placeholder.py   -- PlaceholderProvider + fleet data
src/harbor_view/providers/ais.py           -- AISProvider (stub)

tests/providers/test_models.py
tests/providers/test_base.py
tests/providers/test_placeholder.py
tests/providers/test_ais.py
tests/chart/test_render_providers.py

docs/sprint-003-notes.md                   -- this file
```

## Files modified

- `src/harbor_view/chart/render.py` — replaced the direct
  `from harbor_view.chart.fixtures import PLACEHOLDER_FLEET` import
  with `from harbor_view.providers import VesselProvider,
  PlaceholderProvider`. `render()` gained an optional
  `vessel_provider` parameter (defaulting to `PlaceholderProvider()`,
  preserving old behavior exactly). `draw_fleet()` now takes a
  `vessels` list parameter instead of reading a module-level constant.
  Module docstring updated to describe the new architecture. No
  drawing code, layout, color, or typography changed.
- `src/harbor_view/chart/fixtures.py` — emptied to a deprecation
  pointer that raises `ImportError` with guidance to the new location,
  rather than deleted outright (nothing else imports it, but this
  keeps the failure loud and informative for anyone with the old path
  memorized).
- `tests/README.md` — updated to describe the now-populated test
  suite and how to run it.
- `TASKS.md` — Task 003 marked in progress / partially addressed (see
  that file for specifics); this sprint built the internal vessel
  model and provider seam, but did not choose or integrate a live
  data source, which remains open.

## Visual verification ("no visible changes")

Before changing `render.py`, a render was produced with the
pre-refactor code and saved as a reference. After the refactor, the
same scene was rendered again and the two PNGs were compared pixel by
pixel (NumPy array diff over the full 2000x2800 image).

Result: the only pixels that differed were inside the sidebar's clock
display — because real time had passed between the two renders, not
because of anything in the refactor. Two additional renders, run back
to back with an explicitly-constructed `PlaceholderProvider()`, were
checked the same way and came back **exactly pixel-identical**,
including the clock (no minute boundary crossed between calls).
`tests/chart/test_render_providers.py::test_render_is_deterministic_given_the_same_provider`
encodes this same check (using a single-vessel fake provider so the
test doesn't depend on the placeholder fleet's specific layout) so a
future change that accidentally alters rendering behavior gets caught
automatically.

## How live AIS plugs in next sprint

1. **Choose a data source.** This was flagged as an open product
   decision in `PRODUCT_SPEC.md` and remains one — a commercial AIS
   API, a local SDR/AIS receiver, or some other feed. Whoever picks
   this should also resolve the field-of-view configuration question
   (Task 002 in `TASKS.md`), since the provider needs to know what
   "in view" means before it can filter anything.
2. **Implement `AISProvider.__init__`** to accept whatever connection
   details the chosen source needs (and the observer's field-of-view
   config), instead of today's permissive `*args, **kwargs`.
3. **Implement `AISProvider.get_vessels()`** to fetch current
   positions, filter to the configured field of view, and construct
   one `Vessel` per in-view vessel — translating the source's native
   fields (MMSI, navigation status codes, course-over-ground, etc.)
   into `Vessel`'s fields. This is the only place AIS-specific
   concepts should exist in the whole codebase, per CLAUDE.md's "don't
   scope-creep into a general AIS library" guidance.
4. **Decide an error policy** for feed outages (return stale data?
   empty list? something else?) — explicitly called out as unresolved
   in the stub's docstring rather than guessed at here.
5. **Switch the default**, if/when live AIS should become Harbor
   View's normal mode, by changing what `render()` defaults to, or
   (more likely) by having whatever calls `render()` — a future
   refresh loop, Task 007 — construct an `AISProvider` explicitly and
   pass it in. `render()` itself should not need to change again for
   this; that's the entire point of this sprint's refactor.
6. **Add tests that mock the feed** rather than calling it live, per
   CLAUDE.md's testing conventions — `tests/providers/test_ais.py` is
   the natural place to extend.

At no point in the above does `chart/render.py`, `geometry.py`, or
`glyphs.py` need to change. That boundary holding is the actual
deliverable of this sprint.
