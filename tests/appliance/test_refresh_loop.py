"""Tests for harbor_view.appliance.refresh_loop.

These exercise the lifecycle logic (atomic writes, failure isolation,
the display-notification no-op path) without needing a real display
or a real 60-second wait -- refresh_seconds is always set to a tiny
value or max_iterations is used to bound the loop.
"""
from __future__ import annotations

import hashlib
import os
import signal
import tempfile

from harbor_view.appliance.refresh_loop import _notify_display, render_once, run
from harbor_view.providers import VesselProvider
from harbor_view.providers.models import Vessel, VesselType


class _OkProvider(VesselProvider):
    def get_vessels(self) -> list[Vessel]:
        return [Vessel("X", VesselType.TUG, 26.1, -80.1, 0)]


class _BrokenProvider(VesselProvider):
    def get_vessels(self) -> list[Vessel]:
        raise RuntimeError("simulated provider crash")


# ---------------------------------------------------------------------------
# render_once
# ---------------------------------------------------------------------------

def test_render_once_succeeds_and_produces_a_file():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        assert render_once(out_path, _OkProvider()) is True
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0


def test_render_once_leaves_no_temp_files_behind():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        render_once(out_path, _OkProvider())
        leftovers = [f for f in os.listdir(tmp) if f != "harbor_view.png"]
        assert leftovers == []


def test_render_once_failure_returns_false_and_does_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        result = render_once(out_path, _BrokenProvider())
        assert result is False  # must not raise -- this line proves it didn't


def test_failed_render_does_not_create_or_corrupt_the_output_file():
    """No prior render exists yet -- a failure must not leave behind a
    zero-byte or partial file at the real output path.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        render_once(out_path, _BrokenProvider())
        assert not os.path.exists(out_path)


def test_failed_render_after_a_success_leaves_the_previous_image_untouched():
    """This is Sprint 5's core requirement #5, proven at the file level:
    a render failure must not alter the previously displayed image.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        assert render_once(out_path, _OkProvider()) is True
        before = hashlib.sha256(open(out_path, "rb").read()).hexdigest()

        assert render_once(out_path, _BrokenProvider()) is False
        after = hashlib.sha256(open(out_path, "rb").read()).hexdigest()

        assert before == after


def test_failed_render_leaves_no_temp_files_behind():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        render_once(out_path, _BrokenProvider())
        leftovers = os.listdir(tmp)
        assert leftovers == []


def test_render_once_creates_output_directory_if_missing():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "nested", "dir", "harbor_view.png")
        assert render_once(out_path, _OkProvider()) is True
        assert os.path.exists(out_path)


# ---------------------------------------------------------------------------
# _notify_display
# ---------------------------------------------------------------------------

def test_notify_display_with_no_pid_file_is_a_silent_noop():
    with tempfile.TemporaryDirectory() as tmp:
        pid_file = os.path.join(tmp, "does_not_exist.pid")
        _notify_display(pid_file)  # must not raise


def test_notify_display_with_garbage_pid_file_is_a_silent_noop():
    with tempfile.TemporaryDirectory() as tmp:
        pid_file = os.path.join(tmp, "feh.pid")
        with open(pid_file, "w") as f:
            f.write("not-a-number")
        _notify_display(pid_file)  # must not raise


def test_notify_display_sends_sigusr1_to_a_real_process(monkeypatch):
    sent = {}

    def fake_kill(pid, sig):
        sent["pid"] = pid
        sent["sig"] = sig

    monkeypatch.setattr(os, "kill", fake_kill)
    with tempfile.TemporaryDirectory() as tmp:
        pid_file = os.path.join(tmp, "feh.pid")
        with open(pid_file, "w") as f:
            f.write("12345")
        _notify_display(pid_file)
    assert sent == {"pid": 12345, "sig": signal.SIGUSR1}


def test_notify_display_handles_process_lookup_error(monkeypatch):
    def fake_kill(pid, sig):
        raise ProcessLookupError("no such process")

    monkeypatch.setattr(os, "kill", fake_kill)
    with tempfile.TemporaryDirectory() as tmp:
        pid_file = os.path.join(tmp, "feh.pid")
        with open(pid_file, "w") as f:
            f.write("99999")
        _notify_display(pid_file)  # must not raise


# ---------------------------------------------------------------------------
# run() -- the full loop, bounded with max_iterations
# ---------------------------------------------------------------------------

def test_run_with_max_iterations_renders_the_requested_number_of_times(monkeypatch):
    calls = []

    def fake_render_once(output_path, provider):
        calls.append(output_path)
        return True

    import harbor_view.appliance.refresh_loop as loop_module
    monkeypatch.setattr(loop_module, "render_once", fake_render_once)

    with tempfile.TemporaryDirectory() as tmp:
        loop_module.run(
            output_path=os.path.join(tmp, "out.png"),
            refresh_seconds=0.01,
            pid_file=os.path.join(tmp, "feh.pid"),
            max_iterations=3,
        )
    assert len(calls) == 3


def test_run_continues_after_a_failed_iteration(monkeypatch):
    """The loop itself must not stop just because one render_once()
    call returned False.
    """
    results = [True, False, True]
    calls = []

    def fake_render_once(output_path, provider):
        calls.append(output_path)
        return results[len(calls) - 1]

    import harbor_view.appliance.refresh_loop as loop_module
    monkeypatch.setattr(loop_module, "render_once", fake_render_once)

    with tempfile.TemporaryDirectory() as tmp:
        loop_module.run(
            output_path=os.path.join(tmp, "out.png"),
            refresh_seconds=0.01,
            pid_file=os.path.join(tmp, "feh.pid"),
            max_iterations=3,
        )
    assert len(calls) == 3  # all three ran despite the middle failure


def test_run_uses_real_render_end_to_end_with_placeholder_provider(monkeypatch):
    """One true end-to-end pass: real provider selection, real
    render(), real file on disk -- the only thing bounded is the loop
    length and sleep duration.
    """
    monkeypatch.delenv("HARBOR_VIEW_PROVIDER", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        run(
            output_path=out_path,
            refresh_seconds=0.01,
            pid_file=os.path.join(tmp, "feh.pid"),
            max_iterations=1,
        )
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0


def test_run_accepts_an_explicit_vessel_provider_override():
    """run()'s vessel_provider parameter, when given, is used instead
    of the environment-configured provider -- this is what lets a
    caller (or a test) bypass HARBOR_VIEW_PROVIDER entirely.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "harbor_view.png")
        run(
            output_path=out_path,
            refresh_seconds=0.01,
            pid_file=os.path.join(tmp, "feh.pid"),
            max_iterations=1,
            vessel_provider=_OkProvider(),
        )
        assert os.path.exists(out_path)


def test_run_never_signals_the_display_when_every_render_fails(monkeypatch):
    """End-to-end (real render_once, real run() loop, a real OS
    process standing in for feh) proof of Sprint 5's requirement 5/6:
    if data retrieval/rendering fails, the display is left alone --
    it is never told to reload a frame that was never produced.

    This spawns a real short-lived helper process that records each
    SIGUSR1 it receives, so the assertion is about actual signal
    delivery, not just about which Python function got called.
    """
    import subprocess
    import sys
    import time as time_module

    with tempfile.TemporaryDirectory() as tmp:
        reload_log = os.path.join(tmp, "reload_log.txt")
        pid_file = os.path.join(tmp, "feh.pid")
        helper_src = (
            "import signal, sys, time\n"
            "count = [0]\n"
            "def handle(signum, frame):\n"
            "    count[0] += 1\n"
            "    with open(sys.argv[1], 'a') as f:\n"
            "        f.write(f'reload {count[0]}\\n')\n"
            "signal.signal(signal.SIGUSR1, handle)\n"
            "while True:\n"
            "    time.sleep(0.02)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", helper_src, reload_log])
        try:
            with open(pid_file, "w") as f:
                f.write(str(proc.pid))
            time_module.sleep(0.2)  # let the helper install its signal handler

            run(
                output_path=os.path.join(tmp, "harbor_view.png"),
                refresh_seconds=0.05,
                pid_file=pid_file,
                max_iterations=3,
                vessel_provider=_BrokenProvider(),
            )
            time_module.sleep(0.2)
            assert not os.path.exists(reload_log), (
                "the display helper received a reload signal despite "
                "every render failing"
            )
        finally:
            proc.kill()
            proc.wait(timeout=5)


def test_run_signals_the_display_only_on_successful_renders(monkeypatch):
    """Companion to the test above: a working provider DOES result in
    exactly one reload signal per successful render, via a real OS
    process, end to end.
    """
    import subprocess
    import sys
    import time as time_module

    with tempfile.TemporaryDirectory() as tmp:
        reload_log = os.path.join(tmp, "reload_log.txt")
        pid_file = os.path.join(tmp, "feh.pid")
        helper_src = (
            "import signal, sys, time\n"
            "count = [0]\n"
            "def handle(signum, frame):\n"
            "    count[0] += 1\n"
            "    with open(sys.argv[1], 'a') as f:\n"
            "        f.write(f'reload {count[0]}\\n')\n"
            "signal.signal(signal.SIGUSR1, handle)\n"
            "while True:\n"
            "    time.sleep(0.02)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", helper_src, reload_log])
        try:
            with open(pid_file, "w") as f:
                f.write(str(proc.pid))
            time_module.sleep(0.2)

            run(
                output_path=os.path.join(tmp, "harbor_view.png"),
                refresh_seconds=0.05,
                pid_file=pid_file,
                max_iterations=3,
                vessel_provider=_OkProvider(),
            )
            time_module.sleep(0.2)
            with open(reload_log) as f:
                lines = f.read().strip().splitlines()
            assert len(lines) == 3
        finally:
            proc.kill()
            proc.wait(timeout=5)
