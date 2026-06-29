"""Selects which VesselProvider the appliance should use, based on
configuration.

This is deliberately a small, separate piece of glue living in the
*appliance* layer, not in `harbor_view.providers` itself. Sprint 5's
brief is explicit that the provider architecture should not be
modified -- `VesselProvider`, `PlaceholderProvider`, and `AISProvider`
are untouched. All this module does is read one environment variable
and construct the provider that already exists; it adds no new
capability to the provider layer itself.
"""
from __future__ import annotations

import logging
import os

from harbor_view.providers import AISProvider, PlaceholderProvider, VesselProvider

logger = logging.getLogger("harbor_view.appliance.provider_selection")

# Defaults to "placeholder" rather than "ais" -- a freshly-imaged Pi
# that hasn't had AISSTREAM_API_KEY configured yet should display the
# calm, fully-populated placeholder fleet out of the box, not silently
# attempt (and fail) a live connection. An operator opts into live
# data explicitly by setting HARBOR_VIEW_PROVIDER=ais (and, separately,
# AISSTREAM_API_KEY -- see docs/sprint-004-notes.md).
_DEFAULT_PROVIDER_NAME = "placeholder"

_PROVIDER_FACTORIES = {
    "placeholder": PlaceholderProvider,
    "ais": AISProvider,
}


def get_configured_provider() -> VesselProvider:
    """Construct the VesselProvider named by HARBOR_VIEW_PROVIDER.

    Recognized values: "placeholder" (default), "ais". An unrecognized
    value is logged as a warning and falls back to the placeholder
    provider -- a typo in configuration should degrade to "the chart
    still looks right," not crash the appliance before it ever
    displays anything.
    """
    name = os.environ.get("HARBOR_VIEW_PROVIDER", _DEFAULT_PROVIDER_NAME).strip().lower()
    factory = _PROVIDER_FACTORIES.get(name)
    if factory is None:
        logger.warning(
            "HARBOR_VIEW_PROVIDER=%r is not recognized (expected one of %s); "
            "falling back to %r.",
            name, sorted(_PROVIDER_FACTORIES), _DEFAULT_PROVIDER_NAME,
        )
        factory = _PROVIDER_FACTORIES[_DEFAULT_PROVIDER_NAME]
    return factory()
