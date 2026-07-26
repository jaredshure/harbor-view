"""Tests for MAP_ORIENTATION guarding in render.py.

Covers four invariants:
  1. north_up: map_coords is identity
  2. seaward_up: map_coords transposes axes
  3. vessel heading in seaward_up adds π/2 to the rotation
  4. compass N label is placed to the LEFT of the rose centre in seaward_up
"""
from __future__ import annotations

import math
import types
import sys
import unittest.mock as mock

import pytest
import types


# ---------------------------------------------------------------------------
# Helpers to patch MAP_ORIENTATION at module level
# ---------------------------------------------------------------------------

def _reload_render_with_orientation(orientation: str, monkeypatch):
    """Return the render module re-imported with MAP_ORIENTATION = orientation."""
    import importlib
    import harbor_view.chart.render as render_mod
    monkeypatch.setattr(render_mod, "MAP_ORIENTATION", orientation)
    return render_mod


# ---------------------------------------------------------------------------
# 1. north_up: map_coords(x, y) == (x, y)
# ---------------------------------------------------------------------------

def test_map_coords_north_up_is_identity(monkeypatch):
    mod = _reload_render_with_orientation("north_up", monkeypatch)
    x, y = 1234.5, -678.9
    assert mod.map_coords(x, y) == (x, y)


# ---------------------------------------------------------------------------
# 2. seaward_up: map_coords(x, y) == (y, x)
# ---------------------------------------------------------------------------

def test_map_coords_seaward_up_transposes(monkeypatch):
    mod = _reload_render_with_orientation("seaward_up", monkeypatch)
    x, y = 1234.5, -678.9
    assert mod.map_coords(x, y) == (y, x)


# ---------------------------------------------------------------------------
# 3. vessel heading in seaward_up adds π/2
# ---------------------------------------------------------------------------

def test_vessel_heading_seaward_up_adds_quarter_turn(monkeypatch):
    """A north-heading vessel (heading_deg=0) must get rotation = +π/2 in seaward_up."""
    mod = _reload_render_with_orientation("seaward_up", monkeypatch)

    rotations_captured = []

    # Minimal vessel stub
    vessel = types.SimpleNamespace(
        lat=26.155531,
        lon=-80.100832,
        heading_deg=0.0,
        kind="cargo",
        name="TEST SHIP",
        origin="A",
        destination="B",
    )

    # Capture the rotation passed to Affine2D().rotate()
    class _CapturingAffine:
        def scale(self, s):
            return self
        def rotate(self, r):
            rotations_captured.append(r)
            return self
        def translate(self, tx, ty):
            return self
        def __add__(self, other):
            return mock.MagicMock()

    class _FakeAxes:
        transData = object()
        def add_patch(self, p): pass
        def plot(self, *a, **kw): pass
        def text(self, *a, **kw): pass

    with mock.patch.object(mod, "Affine2D", return_value=_CapturingAffine()):
        with mock.patch.object(mod, "PathPatch", return_value=mock.MagicMock()):
            mod.draw_vessel(_FakeAxes(), vessel)

    assert len(rotations_captured) == 1
    # heading_deg=0 → theta=0; seaward_up rotation = -0 + π/2 = π/2
    assert abs(rotations_captured[0] - math.pi / 2) < 1e-9


def test_vessel_heading_north_up_no_quarter_turn(monkeypatch):
    """In north_up a north-heading vessel gets rotation = 0."""
    mod = _reload_render_with_orientation("north_up", monkeypatch)

    rotations_captured = []

    vessel = types.SimpleNamespace(
        lat=26.155531,
        lon=-80.100832,
        heading_deg=0.0,
        kind="cargo",
        name="TEST SHIP",
        origin="A",
        destination="B",
    )

    class _CapturingAffine:
        def scale(self, s):
            return self
        def rotate(self, r):
            rotations_captured.append(r)
            return self
        def translate(self, tx, ty):
            return self
        def __add__(self, other):
            return mock.MagicMock()

    class _FakeAxes:
        transData = object()
        def add_patch(self, p): pass
        def plot(self, *a, **kw): pass
        def text(self, *a, **kw): pass

    with mock.patch.object(mod, "Affine2D", return_value=_CapturingAffine()):
        with mock.patch.object(mod, "PathPatch", return_value=mock.MagicMock()):
            mod.draw_vessel(_FakeAxes(), vessel, label_side="right")

    assert len(rotations_captured) == 1
    assert abs(rotations_captured[0] - 0.0) < 1e-9


# ---------------------------------------------------------------------------
# 4. compass N label is to the LEFT (higher data-x) in seaward_up
# ---------------------------------------------------------------------------

def test_compass_north_label_left_in_seaward_up(monkeypatch):
    """In seaward_up, the N label x-coord must be GREATER than rose centre x.

    xlim is (y_max, y_min) so higher data-x plots further LEFT = north.
    """
    mod = _reload_render_with_orientation("seaward_up", monkeypatch)

    texts_captured = []

    class _FakeAxes:
        def set_xlim(self, *a, **kw): pass
        def set_ylim(self, *a, **kw): pass
        def set_aspect(self, *a, **kw): pass
        def add_patch(self, p): pass
        def plot(self, *a, **kw): pass
        def text(self, x, y, s, **kw):
            texts_captured.append((x, y, s))

    # Fake limits that match seaward_up geometry (y_max > y_min, x_min < x_max)
    x_min, x_max, y_min, y_max = 0, 14_000, -8_000, 8_000
    _FakeAxes.get_xlim = lambda self: (y_max, y_min)
    _FakeAxes.get_ylim = lambda self: (x_min, x_max)

    mod.draw_compass_rose(_FakeAxes(), x_min, x_max, y_min, y_max)

    n_entries = [(x, y, s) for x, y, s in texts_captured if s == "N"]
    assert n_entries, "No 'N' label text found"
    n_x, n_y, _ = n_entries[0]

    # In seaward_up the rose centre is at y_max + (y_min - y_max)*0.84
    # N label is at cx + r_outer*1.32, which must be > cx (further left on screen)
    cx = y_max + (y_min - y_max) * 0.84
    assert n_x > cx, (
        f"N label x={n_x:.1f} should be > rose centre x={cx:.1f} "
        "(higher x = further left = north in seaward_up)"
    )


def test_compass_north_label_above_in_north_up(monkeypatch):
    """In north_up, the N label y-coord must be GREATER than rose centre y (above)."""
    mod = _reload_render_with_orientation("north_up", monkeypatch)

    texts_captured = []

    class _FakeAxes:
        def set_xlim(self, *a, **kw): pass
        def set_ylim(self, *a, **kw): pass
        def set_aspect(self, *a, **kw): pass
        def add_patch(self, p): pass
        def plot(self, *a, **kw): pass
        def text(self, x, y, s, **kw):
            texts_captured.append((x, y, s))

    x_min, x_max, y_min, y_max = 0, 14_000, -8_000, 8_000
    mod.draw_compass_rose(_FakeAxes(), x_min, x_max, y_min, y_max)

    n_entries = [(x, y, s) for x, y, s in texts_captured if s == "N"]
    assert n_entries, "No 'N' label text found"
    n_x, n_y, _ = n_entries[0]

    cy = y_min + (y_max - y_min) * 0.105
    assert n_y > cy, (
        f"N label y={n_y:.1f} should be > rose centre y={cy:.1f} (above = north in north_up)"
    )
