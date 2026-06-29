# Deployment — Harbor View as an appliance

This document explains the *design* of Sprint 5's appliance layer --
why each piece exists and what it's responsible for. For step-by-step
setup instructions, see `installation.md`. For the application
lifecycle's own design rationale, see the module docstring in
`src/harbor_view/appliance/refresh_loop.py`, which is the authoritative
source -- this document summarizes it but the code is canonical.

## Two layers, deliberately separate

```
+------------------------------+      +------------------------------+
|  harbor-view-render.service  |      |   X session (no desktop)     |
|  (systemd, headless)         |      |   .bash_profile -> startx     |
|                               |      |   -> .xinitrc -> kiosk.sh     |
|  refresh_loop.run():          |      |   -> feh --fullscreen         |
|   - get_configured_provider() |      |                                |
|   - render() every 60s         | ---> |   watches harbor_view.png    |
|   - atomic file replace        | PNG  |   reloads on SIGUSR1           |
|   - SIGUSR1 -> feh's pid       | ---> |   (sent by the render loop)   |
+------------------------------+      +------------------------------+
```

The **render layer** (a systemd service) and the **display layer** (an
X session with one app, no desktop) are independent processes that
only communicate through a file on disk and a Unix signal. Neither
needs to know the other exists in order to function:

- The render service writes a PNG and signals whoever's PID is in the
  pid file (or signals no one, harmlessly, if the display isn't up
  yet -- see `_notify_display`'s docstring).
- The display script just shows whatever's at a fixed path and
  reloads when told to. It doesn't know or care whether the file came
  from `PlaceholderProvider`, `AISProvider`, or someone manually
  `cp`-ing a PNG there for testing.

This separation means either side can be restarted, debugged, or
replaced without touching the other -- e.g. testing a new
`VesselProvider` doesn't require touching the display at all (see
"Testing without a display" below), and swapping `feh` for a different
viewer later wouldn't require touching the render loop.

## Why a render loop instead of a long-running render

`harbor_view.chart.render.render()` was never modified (per the
brief). It's a synchronous, one-shot function: call it, get a PNG path
back. The appliance layer's job is purely to call that function
repeatedly, on a timer, and handle what happens around it -- nothing
about *how a frame is drawn* lives in `refresh_loop.py`.

## Why atomic file replacement

`render()` writes directly via matplotlib's `savefig()`. If a display
process were watching the *same* path `render()` writes to, there's a
window -- however small -- where the file is partially written, and a
viewer that reads it during that window shows a corrupted or truncated
frame. This is a known, documented failure mode for exactly this kind
of "regenerate a PNG that something else is watching" setup.

`render_once()` in `refresh_loop.py` renders to a temp file in the
*same directory* as the real output path, then calls `os.replace()`,
which is atomic on POSIX filesystems when source and destination share
a filesystem. A reader can only ever see the old complete file or the
new complete file -- never something in between.

## Why SIGUSR1 instead of `feh --reload N`

`feh` has a built-in `--reload N` flag that polls its current file
every N seconds. It was deliberately not used here, for two reasons:

1. It decouples *when feh checks* from *when a new frame actually
   exists*, which reintroduces a version of the same race the atomic
   replace was meant to solve (less severe, since `os.replace()` is
   still atomic, but the timing relationship between "render finished"
   and "viewer notices" becomes unpredictable rather than immediate).
2. It's described in `feh`'s own man page as "still experimental" for
   the filelist-reloading case.

Instead, `feh` is started with `--reload 0` (explicitly disabling its
own polling) and the render loop sends `SIGUSR1` -- which `feh`
specifically supports as "reload the current image now" in
single-image mode -- immediately after a successful atomic replace.
This makes the update event-driven: the display refreshes within
moments of a real new frame existing, not on a blind timer that might
fire mid-write or might wait longer than necessary.

## Why two independent restart mechanisms

- `harbor-view-render.service` has `Restart=on-failure` (systemd).
- `.bash_profile`'s `startx` call is wrapped in a `while true; do ...
  sleep 2; done` loop.

Per the brief's "behave like a finished product" goal, *both* halves
of the appliance should be self-healing, not just the one that happens
to run under systemd. A crashed `feh` (or a startx/X server hiccup)
restarts the display within 2 seconds; a crashed render loop restarts
within 10. Neither failure takes the whole appliance down, and neither
requires an operator to notice and intervene.

## Why `X -nocursor` *and* `feh --hide-pointer`

Two layers, for robustness rather than redundancy for its own sake:
`-nocursor` is the X server itself never drawing a cursor at all
(confirmed as the standard, server-level way to do this); `feh
--hide-pointer` additionally hides the pointer specifically while idle
over feh's window, which matters if `-nocursor` is ever dropped (e.g.
someone customizes `.bash_profile` to plug in a USB mouse for setup)
without re-checking this doc.

## Why console autologin + `.bash_profile` + `startx`, not a desktop kiosk browser

Modern Raspberry Pi OS (Bookworm+) defaults to a Wayland compositor
(Wayfire) with a full desktop session, and a lot of current kiosk
tutorials point at running a browser (Chromium `--kiosk`) inside that
desktop. Harbor View doesn't need a browser at all -- it's a single
static image, regenerated periodically, not a web page. Running a full
desktop environment and a Chromium process just to display one PNG
would be a heavier, slower-booting, larger-attack-surface appliance
for no benefit; "no visible operating system" and "no desktop
interaction" are easier to satisfy honestly by never starting a
desktop in the first place. The X session this appliance starts has no
window manager, no panel, no file manager, and exactly one window
(`feh`'s).

## Configuration

All appliance configuration is environment variables, consistent with
the rest of Harbor View (see `.env.example` for the AIS-specific ones
from Sprint 4, and `deploy/harbor-view.env.example` for this sprint's
additions):

| Variable | Default | Purpose |
|---|---|---|
| `HARBOR_VIEW_PROVIDER` | `placeholder` | which `VesselProvider` to use (`placeholder` or `ais`) |
| `HARBOR_VIEW_OUTPUT_PATH` | `/var/lib/harbor-view/harbor_view.png` | where the rendered PNG is written/read |
| `HARBOR_VIEW_REFRESH_SECONDS` | `60` | render interval |
| `HARBOR_VIEW_DISPLAY_PID_FILE` | `/var/lib/harbor-view/feh.pid` | where `feh`'s PID is recorded for signaling |
| `HARBOR_VIEW_LOG_LEVEL` | `INFO` | refresh loop's Python logging level |

(Plus `AISSTREAM_API_KEY`, `HARBOR_VIEW_AIS_BBOX`,
`HARBOR_VIEW_AIS_LISTEN_SECONDS` from Sprint 4, only relevant when
`HARBOR_VIEW_PROVIDER=ais`.)

## Logging

The render loop logs via Python's standard `logging` module
(`harbor_view.appliance.refresh_loop`, `...provider_selection`, plus
whatever `AISProvider` itself logs). Under systemd, stdout/stderr
(where `logging`'s default handler writes) are captured by journald:

```bash
journalctl -u harbor-view-render.service -f      # follow live
journalctl -u harbor-view-render.service -n 100   # last 100 lines
```

Per requirement 6, a render failure produces an `ERROR`-level log
entry with a full traceback (via `logger.exception(...)`) but never
stops the service or blanks the display.

## Testing without a display

Because the two layers only communicate via a file and a signal, the
render loop can be exercised completely independently of any X
session or Raspberry Pi hardware:

```bash
PYTHONPATH=src python3 -m harbor_view.appliance.refresh_loop --once
```

This renders exactly one frame using the configured provider and
exits -- useful for verifying configuration (especially
`AISSTREAM_API_KEY`) before committing to a full kiosk boot cycle. All
of this sprint's automated tests (`tests/appliance/`) work the same
way: real renders, a real subprocess standing in for `feh` to prove
signal delivery, but no real X server or hardware involved. See those
tests' module docstrings for specifics.

## Known limitations / things a real Pi deployment should double-check

- This appliance layer was developed and tested in a sandboxed Linux
  environment without a physical display, X server, or Raspberry Pi.
  The render loop, file-replacement, and signal-delivery logic were
  verified for real (see `tests/appliance/`); the *display* half
  (`feh` actually opening fullscreen with no cursor on a real
  Pi/HDMI output, `startx`/`X -nocursor` behaving as documented on
  whatever Pi OS version is in use) could not be observed directly
  and should be checked on first boot of real hardware.
- `raspi-config nonint do_boot_behaviour B2` (used by `install.sh` to
  set up console autologin) is the documented non-interactive
  raspi-config invocation as of early-2026 sources; if a future Pi OS
  release renames or restructures this, `install.sh`'s fallback
  (direct `getty@tty1` override) should still work on any
  systemd-based Debian derivative regardless.
- Display sleep/DPMS is disabled (`xset -dpms`, `xset s off`), per
  "the display should stay on" being implicit in "behave like a
  digital picture frame." If a deployment wants the screen to turn off
  overnight, that's a deliberate, separate feature this sprint did not
  add (it wasn't in the brief, and CLAUDE.md's "avoid notification/
  alerting/feature-maximizing" spirit argues for not inventing a
  scheduling feature unprompted) -- see TASKS.md for where a future
  task like this would go.
