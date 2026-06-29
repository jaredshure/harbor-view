"""Deprecated -- superseded by the Sprint 3 provider architecture.

The placeholder fleet that used to live in this module
(`PLACEHOLDER_FLEET`, as a list of `PlaceholderVessel`) has moved to
`harbor_view.providers.placeholder.PlaceholderProvider`, which returns
the same fleet as a list of `harbor_view.providers.models.Vessel`
objects. See docs/sprint-003-notes.md for why.

This module is kept (rather than deleted outright) only as a pointer
for anyone with the old import path memorized. It defines nothing and
should not be imported by new code.
"""
from __future__ import annotations

raise ImportError(
    "harbor_view.chart.fixtures has moved. Use "
    "harbor_view.providers.placeholder.PlaceholderProvider instead "
    "(see docs/sprint-003-notes.md)."
)
