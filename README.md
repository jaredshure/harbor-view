# Harbor View

> A quiet piece of nautical art for a waterfront window.

Harbor View is not a ship-tracking dashboard. It is a small, ambient
display — intended for a screen, a picture frame, or a tucked-away corner
of a room — that shows the commercial vessels currently visible from a
specific waterfront vantage point.

It is built for people who like to glance, not monitor.

## What it is

- A **single-purpose** display of vessel traffic within sight of one
  fixed location.
- Designed to feel like a piece of art or a window, not a control panel.
- Quiet by default: minimal text, minimal chrome, no alerts or sirens.

## What it is *not*

- It is not a general-purpose AIS tracker.
- It is not a MarineTraffic, VesselFinder, or MarineTraffic-style
  clone — there is no search, no fleet management, no history scrubbing.
- It is not trying to cover the world's oceans. It cares about one view,
  from one place.

## Status

The visual design (chart composition, palette, typography, layout) is
frozen as of Sprint 2.5 — see `docs/` for the design-pass notes. The
renderer is decoupled from its data source via a provider architecture
(Sprint 3, `docs/sprint-003-notes.md`). A real `AISProvider` backed by
[AISStream.io](https://aisstream.io) exists alongside the placeholder
fleet (Sprint 4, `docs/sprint-004-notes.md`); set `AISSTREAM_API_KEY`
to use it, or omit it for an intentionally empty harbor. As of Sprint
5, Harbor View can run as a self-contained appliance — boots directly
into a fullscreen display on a Raspberry Pi with no desktop, no
cursor, and a self-healing 60-second refresh loop (`docs/deployment.md`,
`docs/installation.md`).

See [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) for the product vision and
[`TASKS.md`](TASKS.md) for the implementation plan.

## Project layout

```
harbor-view/
├── README.md           This file
├── CLAUDE.md            Guidance for AI coding assistants working in this repo
├── PRODUCT_SPEC.md       Product vision, scope, and design intent
├── TASKS.md              Ordered implementation plan
├── requirements.txt      Runtime dependencies (pyproject.toml is still TODO)
├── .env.example           Documents required/optional environment variables
├── docs/                 Additional design and technical documentation
├── deploy/                Raspberry Pi appliance deployment artifacts --
│                            installer, systemd service, kiosk display
│                            scripts; see docs/deployment.md and
│                            docs/installation.md
├── assets/               Static assets (fonts, icons, reference imagery)
├── src/
│   └── harbor_view/
│       ├── chart/        Rendering: geometry, glyphs, the renderer itself
│       ├── providers/    Vessel data model + provider architecture --
│       │                  placeholder fleet, live AISStream.io provider;
│       │                  see docs/sprint-003-notes.md and
│       │                  docs/sprint-004-notes.md
│       └── appliance/    Operational lifecycle -- the refresh loop and
│                           provider selection that power the Pi appliance;
│                           see docs/sprint-005-notes.md
├── tests/                Test suite, mirroring src/harbor_view/
└── output/                Generated/rendered output (gitignored contents)
```

## Getting started

```bash
pip install -r requirements.txt --break-system-packages  # or in a venv
PYTHONPATH=src python3 src/harbor_view/chart/render.py
```

This writes `output/harbor_view.png` using the placeholder fleet (the
default). There's no CLI yet — the renderer's tunable constants live
at the top of `src/harbor_view/chart/render.py`, `geometry.py`, and
`providers/placeholder.py`.

To use a different vessel source, pass a `VesselProvider` to `render()`
directly (see `docs/sprint-003-notes.md`):

```python
from harbor_view.chart.render import render
from harbor_view.providers import PlaceholderProvider, AISProvider

render(vessel_provider=PlaceholderProvider())  # the default
render(vessel_provider=AISProvider())  # live AIS -- see below
```

For live data, copy `.env.example` to `.env`, fill in
`AISSTREAM_API_KEY` (free at [aisstream.io](https://aisstream.io)), and
export it before running. See `docs/sprint-004-notes.md` for full
configuration details, the AIS-to-Harbor-View vessel-type mapping, and
known limitations. Without a key, `AISProvider` renders an
intentionally empty harbor rather than erroring or substituting
placeholder data.

## Running as an appliance (Raspberry Pi)

To run Harbor View unattended on a Raspberry Pi -- booting straight
into a fullscreen, self-refreshing display with no desktop and no
cursor -- see `docs/installation.md` for setup steps and
`docs/deployment.md` for how the appliance layer (`deploy/`,
`src/harbor_view/appliance/`) is put together and why.

## License

TBD — a license will be chosen before the first public release.

## Contributing

This project is in early scaffolding. Contribution guidelines will be
added once the core implementation begins.
