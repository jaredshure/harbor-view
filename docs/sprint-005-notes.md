# Sprint 5 notes — Appliance Mode

This sprint added an operational lifecycle and OS-level deployment
around Harbor View, per the brief's "behave like a finished product
rather than a Python application" goal. `harbor_view.chart` and
`harbor_view.providers` were not modified -- see "Verification" below.

## A note on task ordering

`TASKS.md` lists Task 007 (refresh loop) and Task 010 (Raspberry Pi
deployment, explicitly marked a stretch goal) after Phase 3 polish
tasks (008, 009) that are still open. This sprint's brief covers
exactly that territory -- effectively Tasks 007 and 010 together, done
ahead of 008/009. CLAUDE.md says not to implement ahead of the task
list without flagging it; this is exactly that flag. Given the brief
was explicit and self-contained, the work proceeded, and `TASKS.md` has
been updated to reflect what was actually built rather than silently
drift out of sync (consistent with how Sprint 1 handled an equivalent
reordering).

## New package: `harbor_view.appliance`

A third top-level package, alongside `chart` and `providers`:

```
harbor_view/
  chart/        rendering (untouched this sprint)
  providers/     vessel data sourcing (untouched this sprint)
  appliance/     NEW: operational lifecycle
    provider_selection.py   reads HARBOR_VIEW_PROVIDER, builds the provider
    refresh_loop.py          the render-every-60s lifecycle
```

This mirrors the precedent CLAUDE.md set for `providers/` in Sprint 3:
a new, clearly-scoped package for a genuinely new concern, rather than
bolting lifecycle logic onto `render.py` itself.

### `provider_selection.get_configured_provider()`

Reads `HARBOR_VIEW_PROVIDER` (`"placeholder"` or `"ais"`, defaulting to
`"placeholder"`) and constructs the corresponding, *already-existing*
provider class. It adds no capability to the provider layer -- it's a
small piece of glue that lets the appliance pick between providers
that were already there.

Defaulting to `"placeholder"` rather than `"ais"` was a deliberate
choice: a freshly-imaged Pi that hasn't had `AISSTREAM_API_KEY`
configured yet should show the complete, calm placeholder fleet, not
an intentionally-empty harbor because nobody's set up live data yet.

### `refresh_loop`

Implements the brief's six-step lifecycle exactly:

1. **Start Harbor View** -- `main()` / `run()`.
2. **Initialize the configured VesselProvider** -- once, at loop start,
   not re-constructed every cycle (see the docstring in `run()` for
   why that's the right call even though it currently makes no
   behavioral difference for either existing provider).
3. **Render the current scene** -- calls `harbor_view.chart.render.
   render()`, unmodified.
4. **Refresh every 60 seconds** -- `time.sleep(refresh_seconds)`
   between iterations; configurable via `HARBOR_VIEW_REFRESH_SECONDS`.
5. **If data retrieval fails, continue displaying the previous
   successful render** -- enforced two ways: (a) every `VesselProvider`
   already degrades failed data retrieval to an empty list rather than
   raising (Sprint 4's contract), so "data retrieval fails" most often
   just means a render of zero vessels, which is a normal successful
   render; (b) if the render itself fails for any other reason,
   `render_once()` renders to a temp file and only `os.replace()`s it
   over the real output path on success -- a failure leaves the
   previous file completely untouched, proven at the byte level in
   `tests/appliance/test_refresh_loop.py`.
6. **Log errors without interrupting the display** -- `render_once()`
   catches every exception, logs it via `logger.exception(...)` (full
   traceback, standard `logging` module), and returns `False`; the
   loop continues to the next cycle regardless.

### Why atomic writes and `SIGUSR1`, not `feh --reload N`

Covered in full in `docs/deployment.md`. Summary: rendering to a temp
file and `os.replace()`-ing it avoids a display process ever reading a
half-written frame; sending `feh` `SIGUSR1` (its documented "reload
now" signal in single-image mode) after a successful replace makes the
display update event-driven rather than polling-based.

## New deploy/ directory

OS-level artifacts, not Python source, so they live outside `src/`:

```
deploy/
  install.sh                    the installer (see docs/installation.md)
  harbor-view-render.service    systemd unit for the render loop
  harbor-view.env.example       systemd EnvironmentFile template
  harbor-view-kiosk.sh           launches feh, records its PID
  xinitrc                        minimal X session (no WM, no desktop)
  bash_profile                   console-autologin -> startx hook
```

## How each "no X" requirement is satisfied

| Requirement | How |
|---|---|
| Start automatically on boot | systemd `WantedBy=multi-user.target` (render) + console autologin (display) |
| Open full screen | `feh --fullscreen` |
| No visible operating system | no desktop environment is ever started; X runs exactly one app |
| No mouse cursor | `X -nocursor` (server level) + `feh --hide-pointer` (app level) |
| No terminal windows | nothing in the boot path opens a terminal emulator; the console tty itself is not visible once X starts |
| No desktop interaction | no window manager, no panel, no file manager; `feh --no-menus` disables even feh's own right-click menu |

## Verification ("the renderer/composition/typography/provider architecture were not changed")

No file under `src/harbor_view/chart/` or `src/harbor_view/providers/`
was modified this sprint. Confirmed the same way as every prior
sprint's "no visible change" claim: a render taken before this
sprint's work began was diffed pixel-by-pixel against a render taken
after all of this sprint's code was written, with the sidebar's live
clock region masked out (the only region allowed to differ between two
renders taken at different real times). Result: identical.

The appliance layer's own correctness (atomic writes, failure
isolation, signal delivery) was verified with real, executable proof
rather than mocks alone where it mattered most:

- `render_once()`'s atomicity and failure-isolation: tested with a
  real broken provider and a real successful one, asserting file
  bytes are unchanged after a failure (SHA-256 comparison).
- `SIGUSR1` delivery: tested by spawning a **real separate OS
  process** (`subprocess.Popen`) that installs a real `SIGUSR1`
  handler and records each signal it receives to a file, then running
  the real `run()` loop against it. Two tests cover both directions:
  a working provider produces exactly one signal per successful
  render, and a permanently-broken provider produces *zero* signals
  across three attempted cycles -- i.e. the display is never told to
  reload a frame that was never produced.

## Assumptions and limitations

- **No physical Raspberry Pi or X server was available to test
  against.** The render loop and signal-delivery mechanics were
  verified for real, as described above; the *display* half (`feh`
  actually appearing fullscreen with no cursor on real Pi/HDMI
  hardware, `startx`/console-autologin behaving as the cited
  documentation describes on whatever exact Pi OS build is in use) is
  implemented according to current, cited best practice but was not
  observed running on real hardware. Flagged explicitly in
  `docs/deployment.md`'s "Known limitations" section as the first
  thing to verify on real hardware.
- **No `pyproject.toml` exists yet** (Task 001b, still open), so the
  systemd service sets `PYTHONPATH` directly rather than relying on an
  installed package. This is a known, temporary seam -- revisit when
  Task 001b lands.
- **Display sleep/DPMS is disabled entirely** (the screen never turns
  off). A scheduling feature (e.g. dim overnight) was not added --
  it's outside this sprint's brief and would be a new feature, which
  CLAUDE.md asks to avoid adding speculatively.
- **The render and display layers don't share a process tree.** This
  is by design (see `deployment.md`), but it does mean there's a brief
  window after boot (bounded by `harbor-view-kiosk.sh`'s 30-second
  wait) before the first frame exists, during which the display layer
  is waiting rather than showing anything. A future improvement could
  have the render service produce a guaranteed first frame
  synchronously before the display layer starts (the `--once` CLI flag
  exists partly to support this if it's ever wired up via
  `ExecStartPre`), but doing so wasn't necessary to satisfy this
  sprint's brief and was left as documented future work rather than
  added speculatively.

## Files created

```
src/harbor_view/appliance/__init__.py
src/harbor_view/appliance/provider_selection.py
src/harbor_view/appliance/refresh_loop.py

tests/appliance/test_provider_selection.py
tests/appliance/test_refresh_loop.py

deploy/install.sh
deploy/harbor-view-render.service
deploy/harbor-view.env.example
deploy/harbor-view-kiosk.sh
deploy/xinitrc
deploy/bash_profile

docs/deployment.md
docs/installation.md
docs/sprint-005-notes.md   (this file)
```

## Files modified

- `TASKS.md` -- Task 007 marked done; Task 010 marked done (no longer
  a stretch goal); the task-ordering note above added.
- `README.md` -- status section and project layout updated to mention
  the appliance layer and `deploy/`.

`src/harbor_view/chart/*.py` and `src/harbor_view/providers/*.py`:
**not modified.**
