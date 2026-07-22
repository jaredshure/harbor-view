"""Waveshare 7.5" V2 e-paper output backend.

Requires the waveshare_epd library bundled with the Waveshare Pi demo
package.  It is intentionally not listed as a Python dependency because
it is only needed on the target hardware; PNG-only deployments run
without it.

Usage: set HARBOR_VIEW_OUTPUT=waveshare.  The display is initialised,
updated, and put back to sleep on every call, matching the recommended
e-paper duty cycle.

The renderer produces a high-resolution PIL Image at its native size;
this backend is solely responsible for adapting it to the panel:
  1. Scale to fit within epd.width × epd.height, preserving aspect ratio.
  2. Center on a white canvas of exactly that size.
  3. Convert to 1-bit black/white (mode "1") as required by getbuffer().
"""
from __future__ import annotations

import logging

from PIL import Image

logger = logging.getLogger(__name__)


def _fit_to_display(image: Image.Image, display_w: int, display_h: int) -> Image.Image:
    """Return a 1-bit image sized exactly display_w × display_h.

    The source image is scaled down (never up) to fit within the panel
    while preserving its aspect ratio, then centred on a white canvas.
    """
    src_w, src_h = image.size
    scale = min(display_w / src_w, display_h / src_h, 1.0)
    fit_w = int(src_w * scale)
    fit_h = int(src_h * scale)

    resized = image.resize((fit_w, fit_h), Image.LANCZOS)

    canvas = Image.new("RGB", (display_w, display_h), color=(255, 255, 255))
    x_off = (display_w - fit_w) // 2
    y_off = (display_h - fit_h) // 2
    canvas.paste(resized, (x_off, y_off))

    return canvas.convert("1")


class WaveshareBackend:
    """Push a PIL Image to a Waveshare 7.5" V2 e-paper display."""

    def write(self, image: Image.Image, output_path: str) -> None:
        from waveshare_epd import epd7in5_V2
        epd = epd7in5_V2.EPD()
        panel = _fit_to_display(image, epd.width, epd.height)
        logger.debug(
            "Sending to Waveshare display: %dx%d (panel %dx%d)",
            panel.width, panel.height, epd.width, epd.height,
        )
        epd.init()
        epd.display(epd.getbuffer(panel))
        epd.sleep()
