"""Smoke tests for the hybrid renderer.

These tests verify the render path runs end-to-end and produces a
non-empty PNG. They use PlaceholderProvider so no AIS connection is
needed. The background image must be present in the repository.
"""
from __future__ import annotations

import os
import pytest

from harbor_view.chart.render_hybrid import render_hybrid, _BG_PATH
from harbor_view.providers import PlaceholderProvider


@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path / "harbor_view_hybrid.png")


def test_background_image_exists():
    assert os.path.isfile(_BG_PATH), (
        f"Reference artwork not found at {_BG_PATH!r}. "
        "The hybrid renderer cannot run without it."
    )


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_hybrid_render_produces_output(tmp_output):
    result = render_hybrid(output_path=tmp_output, vessel_provider=PlaceholderProvider())
    assert result == tmp_output
    assert os.path.isfile(tmp_output)
    assert os.path.getsize(tmp_output) > 10_000  # non-trivial PNG


@pytest.mark.skipif(
    not os.path.isfile(_BG_PATH),
    reason="Reference artwork not present; skipping render test",
)
def test_hybrid_render_default_provider(tmp_output):
    # vessel_provider=None should default to PlaceholderProvider without raising
    render_hybrid(output_path=tmp_output)
    assert os.path.isfile(tmp_output)
