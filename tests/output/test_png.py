"""Tests for harbor_view.output.png.PngBackend.

All tests use a tiny solid-color PIL Image to keep I/O fast; pixel
content is irrelevant -- only file existence, size, and atomicity matter.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from PIL import Image

from harbor_view.output.png import PngBackend


def _tiny_image() -> Image.Image:
    """2x2 white RGB image -- minimal valid PNG."""
    return Image.new("RGB", (2, 2), color=(255, 255, 255))


def test_write_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")
        PngBackend().write(_tiny_image(), out_path)
        assert os.path.isfile(out_path)
        assert os.path.getsize(out_path) > 0


def test_write_creates_parent_directory_if_missing():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "nested", "dir", "out.png")
        PngBackend().write(_tiny_image(), out_path)
        assert os.path.isfile(out_path)


def test_write_leaves_no_temp_files():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")
        PngBackend().write(_tiny_image(), out_path)
        leftovers = [f for f in os.listdir(tmp) if f != "out.png"]
        assert leftovers == [], f"unexpected temp files: {leftovers}"


def test_write_output_is_a_valid_png():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")
        PngBackend().write(_tiny_image(), out_path)
        reloaded = Image.open(out_path)
        reloaded.verify()  # raises on corrupt PNG


def test_write_preserves_pixel_content():
    red_image = Image.new("RGB", (4, 4), color=(255, 0, 0))
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")
        PngBackend().write(red_image, out_path)
        result = Image.open(out_path).convert("RGB")
        px = result.getpixel((0, 0))
        assert px == (255, 0, 0)


def test_write_overwrites_existing_file():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "out.png")
        PngBackend().write(Image.new("RGB", (2, 2), color=(0, 0, 0)), out_path)
        PngBackend().write(Image.new("RGB", (4, 4), color=(255, 0, 0)), out_path)
        result = Image.open(out_path).convert("RGB")
        assert result.size == (4, 4)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_defaults_to_png(monkeypatch):
    monkeypatch.delenv("HARBOR_VIEW_OUTPUT", raising=False)
    from harbor_view.output import get_output_backend
    from harbor_view.output.png import PngBackend
    assert isinstance(get_output_backend(), PngBackend)


def test_factory_png_explicit(monkeypatch):
    monkeypatch.setenv("HARBOR_VIEW_OUTPUT", "png")
    from harbor_view.output import get_output_backend
    from harbor_view.output.png import PngBackend
    assert isinstance(get_output_backend(), PngBackend)


# ---------------------------------------------------------------------------
# Waveshare backend — import-level smoke test using a stub module
# ---------------------------------------------------------------------------

def test_waveshare_backend_calls_epd_api(monkeypatch):
    """WaveshareBackend must call init(), display(), and sleep() in order."""
    calls = []

    class FakeEPD:
        width = 800
        height = 480
        def init(self):       calls.append("init")
        def display(self, buf): calls.append("display")
        def getbuffer(self, img): return b""
        def sleep(self):      calls.append("sleep")

    class FakeModule:
        EPD = FakeEPD

    import sys
    fake_pkg = type(sys)("waveshare_epd")
    fake_pkg.epd7in5_V2 = FakeModule()
    monkeypatch.setitem(sys.modules, "waveshare_epd", fake_pkg)
    monkeypatch.setitem(sys.modules, "waveshare_epd.epd7in5_V2", FakeModule())

    from harbor_view.output.waveshare import WaveshareBackend
    WaveshareBackend().write(_tiny_image(), "ignored.png")

    assert calls == ["init", "display", "sleep"]


# ---------------------------------------------------------------------------
# _fit_to_display — pure geometry, no hardware needed
# ---------------------------------------------------------------------------

def test_fit_produces_exact_display_size():
    from harbor_view.output.waveshare import _fit_to_display
    src = Image.new("RGB", (1200, 1600), color=(128, 128, 128))
    result = _fit_to_display(src, 800, 480)
    assert result.size == (800, 480)


def test_fit_converts_to_1bit():
    from harbor_view.output.waveshare import _fit_to_display
    src = Image.new("RGB", (800, 480), color=(200, 200, 200))
    result = _fit_to_display(src, 800, 480)
    assert result.mode == "1"


def test_fit_preserves_aspect_ratio():
    """A tall image (portrait) scaled to a wide panel must have letterbox bars."""
    from harbor_view.output.waveshare import _fit_to_display
    # 480×960 is 1:2 portrait; panel is 800×480 (landscape).
    # Fit height 480 → width = 240; letterbox bars of 280px each side.
    src = Image.new("RGB", (480, 960), color=(0, 0, 0))
    result = _fit_to_display(src, 800, 480)
    assert result.size == (800, 480)
    # Corners should be white (part of the letterbox canvas).
    # Convert back to RGB to read pixel values easily.
    rgb = result.convert("RGB")
    assert rgb.getpixel((0, 0)) == (255, 255, 255), "top-left corner should be white letterbox"
    assert rgb.getpixel((799, 479)) == (255, 255, 255), "bottom-right corner should be white letterbox"


def test_fit_does_not_upscale():
    """A source image smaller than the panel is centred without upscaling."""
    from harbor_view.output.waveshare import _fit_to_display
    src = Image.new("RGB", (100, 100), color=(0, 0, 0))
    result = _fit_to_display(src, 800, 480)
    assert result.size == (800, 480)
    # Centre pixel should be black (the source); corners should be white.
    rgb = result.convert("RGB")
    cx, cy = 800 // 2, 480 // 2
    assert rgb.getpixel((cx, cy)) == (0, 0, 0), "centre should contain source content"
    assert rgb.getpixel((0, 0)) == (255, 255, 255), "corner should be white canvas"


def test_fit_exact_size_is_identity():
    """An image already at display dimensions should pass through unchanged."""
    from harbor_view.output.waveshare import _fit_to_display
    src = Image.new("RGB", (800, 480), color=(123, 45, 67))
    result = _fit_to_display(src, 800, 480)
    assert result.size == (800, 480)


def test_waveshare_backend_sends_rotated_image(monkeypatch):
    """WaveshareBackend must rotate the fitted image 90° before getbuffer()."""
    received = []

    class FakeEPD:
        width = 800
        height = 480
        def init(self): pass
        def display(self, buf): pass
        def getbuffer(self, img):
            received.append(img)
            return b""
        def sleep(self): pass

    class FakeModule:
        EPD = FakeEPD

    import sys
    fake_pkg = type(sys)("waveshare_epd")
    fake_pkg.epd7in5_V2 = FakeModule()
    monkeypatch.setitem(sys.modules, "waveshare_epd", fake_pkg)
    monkeypatch.setitem(sys.modules, "waveshare_epd.epd7in5_V2", FakeModule())

    # A source image whose content makes rotation detectable: place a
    # red pixel in the top-left corner.  After _fit_to_display() and
    # rotate(90), that pixel should appear in the bottom-left corner.
    src = Image.new("RGB", (800, 480), color=(255, 255, 255))
    src.putpixel((0, 0), (255, 0, 0))

    from harbor_view.output.waveshare import WaveshareBackend
    WaveshareBackend().write(src, "ignored.png")

    assert len(received) == 1
    sent = received[0].convert("RGB")
    # After rotate(90 CCW), the original top-left moves to bottom-left.
    assert sent.getpixel((0, sent.height - 1)) != (255, 255, 255), (
        "Expected rotated content in bottom-left; image may not have been rotated"
    )


def test_factory_selects_waveshare(monkeypatch):
    """get_output_backend() returns WaveshareBackend when env var is set."""
    import sys

    class FakeEPD:
        width = 800
        height = 480
        def init(self): pass
        def display(self, buf): pass
        def getbuffer(self, img): return b""
        def sleep(self): pass

    class FakeModule:
        EPD = FakeEPD

    fake_pkg = type(sys)("waveshare_epd")
    fake_pkg.epd7in5_V2 = FakeModule()
    monkeypatch.setitem(sys.modules, "waveshare_epd", fake_pkg)
    monkeypatch.setitem(sys.modules, "waveshare_epd.epd7in5_V2", FakeModule())
    monkeypatch.setenv("HARBOR_VIEW_OUTPUT", "waveshare")

    from harbor_view.output import get_output_backend
    from harbor_view.output.waveshare import WaveshareBackend
    assert isinstance(get_output_backend(), WaveshareBackend)
