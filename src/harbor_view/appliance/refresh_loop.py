"""The appliance refresh loop.

This is Harbor View's lifecycle as a standalone process, per Sprint
5's brief:

    1. Start Harbor View.
    2. Initialize the configured VesselProvider.
    3. Render the current scene.
    4. Refresh every 60 seconds.
    5. If data retrieval fails, continue displaying the previous
       successful render.
    6. Log errors without interrupting the display.

This module does not modify `harbor_view.chart.render` or
`harbor_view.providers` in any way -- it only calls `render()`
repeatedly, on a timer, and handles the result. See
docs/sprint-005-notes.md for the full design writeup.

Two distinct kinds of failure are handled differently, deliberately:

  - A VesselProvider failing to retrieve data (e.g. AISProvider's feed
    being unreachable) is NOT an error from this loop's point of
    view. Per Sprint 4, every provider already degrades to an empty
    vessel list rather than raising. An empty harbor is a complete,
    valid, successfully-rendered scene -- it gets displayed like any
    other render.
  - The render itself failing (a matplotlib error, a full disk, an
    unexpected exception from anywhere in the call stack) IS an error
    this loop catches. When that happens, the on-disk image is left
    untouched -- whatever was successfully rendered last stays on
    screen -- and the failure is logged. The loop does not exit and
    does not crash; it simply tries again next cycle.

The render-then-atomically-replace pattern (render to a temp path,
then os.replace() it into place) exists so a display process reading
the output path (e.g. `feh` in single-image mode) never sees a
half-written file. os.replace() is atomic on POSIX systems when source
and destination are on the same filesystem, which is the case here
since the temp file is written into the same directory as the final
target.
"""
from __future__ import annotations

import logging
import os
import signal
import time

from harbor_view.appliance.provider_selection import get_configured_provider
from harbor_view.chart.render import render_to_image

logger = logging.getLogger("harbor_view.appliance.refresh_loop")


def _get_render_fn():
    """Return the render-to-image callable selected by HARBOR_VIEW_RENDER_MODE.

    'procedural' (default): the existing matplotlib chart renderer.
    'hybrid': static artwork background + live vessel overlay.

    The returned callable accepts vessel_provider as a keyword argument
    and returns a PIL Image; delivery to disk or display is handled
    separately by the output backend (see harbor_view.output).
    """
    mode = os.environ.get("HARBOR_VIEW_RENDER_MODE", "procedural").strip().lower()
    if mode == "hybrid":
        from harbor_view.chart.render_hybrid import render_hybrid_to_image
        return render_hybrid_to_image
    return render_to_image

DEFAULT_OUTPUT_PATH = "/var/lib/harbor-view/harbor_view.png"
DEFAULT_REFRESH_SECONDS = 60.0
DEFAULT_PID_FILE = "/var/lib/harbor-view/feh.pid"


def _read_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using default %.0f.", name, raw, default)
        return default


def render_once(output_path: str, vessel_provider) -> bool:
    """Render one frame and deliver it via the configured output backend.

    Calls the renderer to produce a PIL Image, then hands it to the
    output backend selected by HARBOR_VIEW_OUTPUT (default: png).  The
    PNG backend writes atomically so a concurrent reader never observes
    a partially-written file; the Waveshare backend pushes directly to
    the display.

    Returns True on success, False on any failure. Never raises --
    per requirement 6 ("log errors without interrupting the display"),
    the caller (the loop below) treats a False return as "nothing
    changed, try again next cycle," not as a reason to stop.
    """
    from harbor_view.output import get_output_backend
    try:
        image = _get_render_fn()(vessel_provider=vessel_provider)
        get_output_backend().write(image, output_path)
    except Exception:
        logger.exception(
            "Render failed; the previously displayed image (if any) at "
            "%s is unchanged.", output_path,
        )
        return False
    return True


def _notify_display(pid_file: str) -> None:
    """Tell a running display process (feh) to reload the image it's
    showing, by sending it SIGUSR1 -- feh's documented signal for
    "reload the current image" in single-image mode. If no display
    process is registered (no pid file, or the process named in it is
    no longer running), this is a no-op logged at DEBUG: the refresh
    loop's job is to keep the file on disk current regardless of
    whether anything is currently watching it.
    """
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGUSR1)
    except FileNotFoundError:
        logger.debug("No display pid file at %s; skipping reload signal.", pid_file)
    except (ValueError, ProcessLookupError, PermissionError) as exc:
        logger.debug("Could not signal display process via %s: %s", pid_file, exc)


def run(
    output_path: str | None = None,
    refresh_seconds: float | None = None,
    pid_file: str | None = None,
    max_iterations: int | None = None,
    vessel_provider=None,
) -> None:
    """Run the refresh loop: initialize the provider once, then render
    on a fixed interval forever (or `max_iterations` times, for tests
    and for the `--once` CLI flag below).

    Configuration follows the same "environment variables, sensible
    defaults" approach as the rest of Harbor View's appliance layer
    (see docs/sprint-005-notes.md):

      HARBOR_VIEW_OUTPUT_PATH       default /var/lib/harbor-view/harbor_view.png
      HARBOR_VIEW_REFRESH_SECONDS   default 60
      HARBOR_VIEW_DISPLAY_PID_FILE  default /var/lib/harbor-view/feh.pid

    `vessel_provider`, if given, is used as-is instead of consulting
    HARBOR_VIEW_PROVIDER -- this is what `main()` does NOT do (the CLI
    entry point always uses the configured provider), but it's useful
    for tests and for any future caller that already has a specific
    provider in hand and wants this loop's lifecycle around it without
    going through environment-variable selection.
    """
    output_path = output_path or os.environ.get(
        "HARBOR_VIEW_OUTPUT_PATH", DEFAULT_OUTPUT_PATH
    )
    refresh_seconds = (
        refresh_seconds
        if refresh_seconds is not None
        else _read_float_env("HARBOR_VIEW_REFRESH_SECONDS", DEFAULT_REFRESH_SECONDS)
    )
    pid_file = pid_file or os.environ.get(
        "HARBOR_VIEW_DISPLAY_PID_FILE", DEFAULT_PID_FILE
    )

    logger.info(
        "Harbor View appliance starting. output_path=%s refresh_seconds=%.0f",
        output_path, refresh_seconds,
    )

    # Step 2: initialize the configured VesselProvider, ONCE, for the
    # lifetime of this process -- not re-constructed every cycle. This
    # matters for AISProvider in particular: construction just reads
    # configuration (cheap, side-effect-free), while get_vessels()
    # does the actual network work every call regardless, so
    # constructing once vs. per-cycle doesn't change behavior today,
    # but it does mean a future provider with persistent connection
    # state (a documented possibility -- see docs/sprint-004-notes.md's
    # "snapshot, not a continuous feed" limitation) would keep that
    # state across cycles for free, with no change needed here.
    if vessel_provider is None:
        vessel_provider = get_configured_provider()
    logger.info("Using provider: %s", type(vessel_provider).__name__)

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        # Step 3 / Step 4: render the current scene, then wait.
        success = render_once(output_path, vessel_provider)
        if success:
            logger.info("Render succeeded (%s).", output_path)
            _notify_display(pid_file)
        # Step 5/6 already happened inside render_once(): on failure it
        # logged the exception and left the on-disk file untouched.
        # There is nothing further to do here on failure except wait
        # and try again next cycle -- which is exactly what happens
        # whether this render succeeded or not.

        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            break
        time.sleep(refresh_seconds)


def main() -> None:
    """CLI entry point: `python3 -m harbor_view.appliance.refresh_loop`.

    Supports `--once` for a single render-and-exit cycle, useful for
    testing a deployment's configuration without waiting for the full
    refresh interval. See docs/deployment.md.
    """
    import argparse

    logging.basicConfig(
        level=os.environ.get("HARBOR_VIEW_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Harbor View appliance refresh loop")
    parser.add_argument(
        "--once", action="store_true",
        help="Render a single frame and exit, instead of looping forever.",
    )
    args = parser.parse_args()

    run(max_iterations=1 if args.once else None)


if __name__ == "__main__":
    main()
