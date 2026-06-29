#!/bin/sh
# Harbor View kiosk display script.
#
# Launches feh, fullscreen, showing the single image the render loop
# (harbor-view-render.service) keeps up to date, and records feh's PID
# so that service can signal it (SIGUSR1) to reload after each
# successful render -- see refresh_loop.py's _notify_display().
#
# This script assumes it is already running inside an X session with
# no window manager and no desktop -- see xinitrc and
# docs/deployment.md for how that session itself is started at boot.
# This script's only job is to put feh on screen and keep it there.
set -eu

OUTPUT_PATH="${HARBOR_VIEW_OUTPUT_PATH:-/var/lib/harbor-view/harbor_view.png}"
PID_FILE="${HARBOR_VIEW_DISPLAY_PID_FILE:-/var/lib/harbor-view/feh.pid}"

mkdir -p "$(dirname "$OUTPUT_PATH")"

# The render loop may not have produced a first frame yet (e.g. on a
# brand-new install, or if the render service is slow to start). feh
# refuses to open a nonexistent file, so wait briefly rather than
# crashing the display session before it ever shows anything. This
# does not block forever: after the timeout, feh is started anyway --
# if the file appears moments later, the render loop's next successful
# render will SIGUSR1 it into showing the real chart.
WAIT_SECONDS=30
waited=0
while [ ! -f "$OUTPUT_PATH" ] && [ "$waited" -lt "$WAIT_SECONDS" ]; do
    sleep 1
    waited=$((waited + 1))
done

# --fullscreen + --hide-pointer: per Sprint 5's "open full screen" /
# "no mouse cursor" requirements at the application level (the X
# server itself is also started with -nocursor -- see xinitrc -- as a
# second, more robust layer per docs/deployment.md's research notes).
# --borderless: no window decoration of any kind.
# --no-menus: feh's own right-click menu is part of the application
# the brief asks to disappear ("no desktop interaction") just as much
# as a taskbar would be.
# --reload 0: explicitly disable feh's own polling-based reload. This
# appliance updates the display via SIGUSR1 from the render loop
# instead (see refresh_loop.py), which is event-driven rather than a
# blind timer and avoids ever reloading mid-write -- see
# docs/deployment.md for why polling reload was rejected.
exec feh \
    --fullscreen \
    --hide-pointer \
    --borderless \
    --no-menus \
    --image-bg black \
    --reload 0 \
    --on-last-slide hold \
    "$OUTPUT_PATH" &

FEH_PID=$!
echo "$FEH_PID" > "$PID_FILE"

# Replace this script's process with a wait on feh, so systemd/the
# X session's process supervision sees feh's own exit status rather
# than this wrapper's, and so the PID file is cleaned up if feh exits.
trap 'rm -f "$PID_FILE"' EXIT
wait "$FEH_PID"
