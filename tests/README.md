# tests/

Test suite for `harbor_view`, mirroring the structure of
`src/harbor_view/`:

- `tests/providers/` — the vessel data model, the `VesselProvider`
  interface, `PlaceholderProvider`, the AIS ship-type mapping
  (`test_ais_types.py`), and `AISProvider` itself (Sprints 3-4).
  `AISProvider`'s tests mock or fake every network interaction; no
  test connects to AISStream.io.
- `tests/chart/` — renderer integration tests confirming `render()`
  works with any `VesselProvider`, not just the placeholder one,
  including `AISProvider`'s graceful-empty-list behavior.
- `tests/appliance/` — the Sprint 5 operational lifecycle: provider
  selection from `HARBOR_VIEW_PROVIDER`, and the refresh loop's atomic
  file writes, failure isolation, and display-signaling. The
  signal-delivery tests spawn a real short-lived OS process to prove
  `SIGUSR1` is actually received, rather than only asserting that a
  Python function was called.

Run with `PYTHONPATH=src python3 -m pytest tests/` from the repo root.

Conventions (see also `CLAUDE.md`):

- Files named `test_*.py`, one per module under test.
- No live network calls to external vessel-data APIs in tests — mock
  any external data source. `AISProvider`'s message-handling logic is
  tested by feeding it raw JSON strings in AISStream's documented
  shape; its connection-failure handling is tested by monkeypatching
  its internal `_collect()` coroutine to raise, never by attempting a
  real connection.
- No real X server, display, or Raspberry Pi hardware is touched by
  any test. The appliance layer's display-facing behavior (signal
  delivery) is tested against a real OS process standing in for
  `feh`, not against `feh` itself or a real screen.
