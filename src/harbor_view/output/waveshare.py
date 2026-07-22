"""Waveshare 7.5" V2 e-paper output backend.

Requires the waveshare_epd library bundled with the Waveshare Pi demo
package.  It is intentionally not listed as a Python dependency because
it is only needed on the target hardware; PNG-only deployments run
without it.

Usage: set HARBOR_VIEW_OUTPUT=waveshare.  The display is initialised,
updated, and put back to sleep on every call, matching the recommended
e-paper duty cycle.
"""
from __future__ import annotations

from PIL import Image


class WaveshareBackend:
    """Push a PIL Image to a Waveshare 7.5" V2 e-paper display."""

    def write(self, image: Image.Image, output_path: str) -> None:
        from waveshare_epd import epd7in5_V2
        epd = epd7in5_V2.EPD()
        epd.init()
        epd.display(epd.getbuffer(image))
        epd.sleep()
