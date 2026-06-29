"""The appliance layer: turns Harbor View from "a Python script you
run" into "a thing that boots and displays itself."

This package owns the *operational* lifecycle (initialize a provider
once, render on an interval, handle failures without interrupting the
display) and the OS-level integration needed to run unattended on a
Raspberry Pi (see docs/sprint-005-notes.md and docs/deployment.md).

It does not modify, and must not need to modify, `harbor_view.chart`
or `harbor_view.providers` -- this package only calls the public
interfaces those already expose (`render()` and `VesselProvider`).
"""
from __future__ import annotations
