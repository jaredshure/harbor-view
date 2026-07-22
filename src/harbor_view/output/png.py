"""PNG file output backend.

Writes a PIL Image to disk atomically using a temp-file rename so a
concurrent reader (e.g. feh in single-image mode) never observes a
half-written file.  os.replace() is atomic on POSIX when source and
destination are on the same filesystem, which is guaranteed here because
the temp file is always created in the same directory as the final target.
"""
from __future__ import annotations

import os
import tempfile

from PIL import Image


class PngBackend:
    """Atomically write a PIL Image to a PNG file on disk."""

    def write(self, image: Image.Image, output_path: str) -> None:
        out_dir = os.path.dirname(output_path) or "."
        os.makedirs(out_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=out_dir, prefix=".harbor_view_tmp_", suffix=".png"
        )
        try:
            os.close(fd)
            image.save(tmp_path, format="PNG")
            os.replace(tmp_path, output_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
