# Harbor View — Task List

This is the ordered implementation plan. Tasks should generally be done
in sequence — later tasks assume earlier ones are complete.

**Current status: Tasks 000, 001, 003, 005, 006, 007, and 010 done
(Task 003's live-data verification is implemented but unobserved
end-to-end in this sandbox; Task 010's display layer is implemented
but unobserved on real Pi hardware -- see each entry below). Task 008
in progress. Task 002, 004, and 009 still open. See each task below
for specifics.**

## Conventions for this file

- `[ ]` not started · `[~]` in progress · `[x]` done
- Each task should result in a working, reviewable increment — not a
  half-finished feature.
- If a task turns out to be too large once started, split it rather
  than rushing it.

---

## Phase 0 — Foundation

- [x] **Task 000** — Initialize repository structure (this scaffold:
  `README.md`, `CLAUDE.md`, `PRODUCT_SPEC.md`, `TASKS.md`, `docs/`,
  `assets/`, `src/`, `tests/`, `output/`).
- [x] **Task 001** — Compose the chart: a single static PNG
  (`output/harbor_view.png`) matching the approved Harbor View visual
  concept — portrait layout, sidebar + map, Fort Lauderdale / Port
  Everglades coastline approximation, placeholder vessel fleet with
  icons and FROM/TO labels, home marker, depth contours, shipping
  lanes, compass rose, and sidebar content (time/wind/weather/tide/
  legend). This combined what the original plan below had split across
  Tasks 005-006, done early and visually-first per the project's "art
  first, data second" principle. See `docs/task-001-notes.md` for
  assumptions made (no real GIS data source was reachable; several
  features are scaled up from real proportions for legibility).
- [ ] **Task 001b** — *(carried over from the original Task 001)*
  Project packaging (`pyproject.toml`), dependency management
  (matplotlib, numpy, scipy), linting/formatting config.

## Phase 1 — Data

- [ ] **Task 002** — Define the observer configuration model (location,
  field of view, units) and a config file format.
- [x] **Task 003** — Choose and integrate a maritime vessel data source;
  define an internal data model for "a vessel currently in view."
  **Sprint 3:** the internal data model (`Vessel`, `VesselType`,
  `VesselStatus`) and a provider abstraction (`VesselProvider`,
  `PlaceholderProvider`, `AISProvider` stub) — see
  `docs/sprint-003-notes.md`. **Sprint 4:** chose AISStream.io as the
  live source and implemented `AISProvider` against it (WebSocket
  connection, message merging, AIS-type-to-VesselType mapping,
  graceful empty-list-on-any-failure) — see
  `docs/sprint-004-notes.md`. Note: live data could not be observed
  end-to-end in the sandbox this was built in (network egress blocks
  the AISStream.io host); the implementation is real and tested via
  mocks, but field verification against an actual populated chart is
  still outstanding for whoever runs this with normal network access.
- [ ] **Task 004** — Implement filtering of raw vessel data down to the
  configured field of view. **Note:** `AISProvider` already filters to
  a configurable bounding box (`HARBOR_VIEW_AIS_BBOX`), which may
  satisfy this task or may need to be reconciled with however Task 002
  ends up defining "field of view" (bearing+range vs. a box) once that
  task is picked up.

## Phase 2 — Rendering

- [x] ~~**Task 005** — Define the visual design language...~~ done as
  part of Task 001 (`src/harbor_view/chart/glyphs.py`, palette in
  `render.py`).
- [x] ~~**Task 006** — Implement a static renderer...~~ done as part of
  Task 001 (`src/harbor_view/chart/render.py`). Currently driven by
  `fixtures.py`'s placeholder fleet, not live data — rewiring to real
  data is Tasks 002-004.
- [x] **Task 007** — Implement a refresh loop (live display or scheduled
  regeneration) tying data retrieval to rendering. **Sprint 5:**
  `src/harbor_view/appliance/refresh_loop.py` — initializes the
  configured `VesselProvider` once, renders every 60s (configurable),
  atomically replaces the output file, signals the display to reload,
  and isolates render failures so the previous successful frame stays
  on screen. See `docs/sprint-005-notes.md`.

## Phase 3 — Polish & distribution

- [~] **Task 008** — Packaging for end users (installation instructions,
  example configuration, sample output in `docs/`). **Sprint 5**
  delivered installation instructions for the Raspberry Pi appliance
  specifically (`docs/installation.md`, `deploy/install.sh`) and
  example configuration (`deploy/harbor-view.env.example`). Still
  open: general (non-Pi) packaging — see Task 001b — so this is a
  partial overlap with Task 008, not its full completion.
- [ ] **Task 009** — Choose and add a license; finalize contribution
  guidelines.
- [x] ~~**Task 010** — *(stretch)* Physical display target...~~ done
  in Sprint 5: full Raspberry Pi kiosk-mode deployment (systemd render
  service, minimal X session, console autologin, installer). See
  `docs/deployment.md` and `docs/installation.md`. E-ink was not
  pursued — the brief specified a standard HDMI display via `feh`;
  e-ink would need a different display layer (no X server, direct
  framebuffer writes) and remains open if ever wanted.

---

## Notes

- Tasks 003 and 005 likely carry the most product judgment (data source
  choice; visual identity) and may be worth pausing on for explicit
  sign-off before implementation, even once started.
- This list will evolve. Update it as tasks are completed or as scope
  is refined — but keep changes to scope consistent with
  `PRODUCT_SPEC.md`.
