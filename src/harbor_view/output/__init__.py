"""Output backend factory for Harbor View.

Selects the delivery mechanism via the HARBOR_VIEW_OUTPUT environment variable:

  png         (default) write PNG to configured output path using an atomic
              temp-file rename so a concurrent reader never sees a partial file
  waveshare   push PIL Image to a Waveshare 7.5" V2 e-paper display via
              the waveshare_epd library (must be installed on the target Pi)

New backends (framebuffer, web preview, etc.) follow the same pattern:
add a module under harbor_view/output/ with a class that implements write().
"""
from __future__ import annotations

import os


def get_output_backend():
    """Return an OutputBackend instance selected by HARBOR_VIEW_OUTPUT."""
    mode = os.environ.get("HARBOR_VIEW_OUTPUT", "png").strip().lower()
    if mode == "waveshare":
        from harbor_view.output.waveshare import WaveshareBackend
        return WaveshareBackend()
    from harbor_view.output.png import PngBackend
    return PngBackend()
