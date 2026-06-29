# Harbor View — Product Specification

## 1. Vision

Harbor View is a piece of nautical art. It shows, quietly and
continuously, the commercial vessels currently visible from one fixed
waterfront vantage point — a window, a deck, a balcony.

The experience it's after is closer to a tide clock or a barometer than
a piece of software: something you glance at, not something you operate.

## 2. Problem statement

People who live or work on the water often develop a quiet, ongoing
curiosity about what's passing by — the tanker easing toward port, the
tug working a barge upriver, the container ship on the horizon at dusk.
Existing tools for this (MarineTraffic, VesselFinder, and similar) are
built for professional or hobbyist tracking: dense maps, filters,
search, fleet history. They are useful, but they are not *calm*, and
they are not scoped to a single, personal vantage point.

Harbor View exists to answer one narrow question, beautifully: *what
ships can I see from here, right now?*

## 3. Target experience

- A single fixed location (the residence) with a defined field of view.
- A display — physical screen, frame, or browser tab — showing the
  vessels currently within that field of view.
- Visual presentation that favors restraint: typography, whitespace,
  and a limited, considered color palette over data density.
- Updates happen, but the interface should never feel like it's
  demanding attention.

## 4. Scope

### 4.1 In scope

- Determining which commercial vessels are within a configured
  geographic field of view from a fixed observer location.
- Retrieving vessel position/identity data from a suitable maritime
  traffic data source (exact source to be decided in implementation
  tasks).
- Rendering a calm, art-like visual representation of those vessels
  (e.g., minimalist iconography, labels, distance/heading framed
  gently rather than as raw telemetry).
- Configuration of the observer's location, field of view (bearing
  range and/or distance range), and basic display preferences.
- Producing output suitable for display — to a screen, or exported as
  static images/video frames.

### 4.2 Out of scope (explicitly)

- General-purpose vessel search or lookup by name/MMSI/IMO.
- Historical playback, route history, or voyage logs.
- Global or multi-region tracking — Harbor View cares about one place.
- Alerts, notifications, or anything designed to interrupt the viewer.
- Multi-user accounts, sharing, or social features.
- Becoming a competitor to professional AIS tracking platforms. If a
  feature request sounds like "what MarineTraffic does," that's a
  signal it's probably out of scope.

## 5. Users

A single primary user: the person living at (or visiting) the
waterfront residence the system is configured for. Harbor View is not
designed for multi-tenant or public deployment, though the
configuration should be clear enough that someone else could adapt it
to their own vantage point.

## 6. Design principles

1. **Calm over comprehensive.** When a feature could go either way,
   prefer the version that's quieter.
2. **One view, not the world.** Scope stays anchored to the configured
   vantage point.
3. **Art first, data second.** The display should be pleasant to look
   at even on a slow day with one distant ship on the horizon.
4. **Small and legible.** The codebase should stay small enough that
   one person can hold the whole thing in their head.

## 7. Open questions

These will be resolved as implementation tasks are reached, not here:

- Which maritime data source/API will supply vessel position data.
- How the observer's field of view is calculated and configured
  (bearing + range vs. polygon vs. simple radius).
- Whether the rendering target is a live-updating screen, a
  periodically-regenerated static image, or both.
- Update frequency and caching/rate-limit strategy against the chosen
  data source.

## 8. Success criteria

Harbor View succeeds if someone can glance at it — without reading a
manual, without clicking anything — and immediately understand what's
out on the water in front of them, and find it pleasant to look at.
