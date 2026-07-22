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


def test_factory_selects_waveshare(monkeypatch):
    """get_output_backend() returns WaveshareBackend when env var is set."""
    import sys

    class FakeEPD:
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
