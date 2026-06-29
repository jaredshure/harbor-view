# Installation — booting a Raspberry Pi straight into Harbor View

This is the step-by-step guide. For *why* the setup is built this way,
see `deployment.md`.

## What you need

- A Raspberry Pi (any model that runs current Raspberry Pi OS;
  developed against Bookworm-or-later) with a display attached.
- Raspberry Pi OS flashed onto the SD card -- either the **Lite** or
  **Desktop** image works; this setup does not use or need the
  desktop environment if you choose Desktop.
- Network access (only required if you intend to use live AIS data;
  the placeholder fleet works fully offline).
- SSH access or a keyboard attached, for the one-time setup below.

## Quick start

```bash
# On the Pi, after first boot:
git clone <this-repository-url> harbor-view
cd harbor-view
sudo ./deploy/install.sh
sudo reboot
```

That's it for the default (placeholder fleet) appliance. After
rebooting, the Pi should boot directly to the Harbor View chart, full
screen, with no desktop or cursor visible at any point.

## What the installer does

`deploy/install.sh` (see that file's own header comment for the
authoritative list) will:

1. Install `xserver-xorg`, `xinit`, `x11-xserver-utils`, `feh`, and
   Python (`python3`, `python3-venv`) via `apt-get`.
2. Create a dedicated `harborview` system user with no sudo access.
3. Copy this repository to `/opt/harbor-view`.
4. Create a Python virtual environment there and install
   `requirements.txt`.
5. Install and enable `harbor-view-render.service` (systemd) -- the
   background process that renders the chart every 60 seconds.
6. Install `.xinitrc` and `.bash_profile` into the `harborview` user's
   home directory -- these are what turn a console login into "the
   kiosk starts."
7. Configure console autologin for `harborview` (via `raspi-config` if
   present, or a direct `getty` override otherwise).

It is safe to re-run after pulling updates (`git pull && sudo
./deploy/install.sh`) -- it updates the installed copy and restarts
the render service without duplicating any configuration.

## Enabling live AIS data

By default, Harbor View displays the placeholder fleet -- a complete,
calm chart that works with zero configuration and no network access.
To switch to live vessel data:

1. Get a free API key at [aisstream.io](https://aisstream.io).
2. Edit `/etc/harbor-view/harbor-view.env` (created by the installer
   from `deploy/harbor-view.env.example`):
   ```
   HARBOR_VIEW_PROVIDER=ais
   AISSTREAM_API_KEY=your-real-key-here
   ```
3. Restart the render service:
   ```bash
   sudo systemctl restart harbor-view-render.service
   ```

See `docs/sprint-004-notes.md` for what live AIS data does and doesn't
provide (e.g. no "origin" port, since AIS itself has no such concept),
and `docs/deployment.md` for the full list of configuration variables.

If `AISSTREAM_API_KEY` is set but the feed is unreachable for any
reason, Harbor View displays an empty harbor rather than erroring or
silently substituting placeholder data -- this is intentional (see the
Sprint 4 and Sprint 5 briefs).

## Verifying it's working without waiting for a reboot

```bash
# Render a single frame right now and check the result:
cd /opt/harbor-view
sudo -u harborview env PYTHONPATH=src venv/bin/python3 \
    -m harbor_view.appliance.refresh_loop --once
ls -la /var/lib/harbor-view/harbor_view.png

# Check the render service is running and see its recent logs:
sudo systemctl status harbor-view-render.service
sudo journalctl -u harbor-view-render.service -n 50
```

## Troubleshooting

**The Pi boots to a black screen or a login prompt, not the chart.**
Check that console autologin actually took effect:
`sudo raspi-config nonint get_boot_behaviour` should print `B2`. If it
doesn't, run `sudo raspi-config` manually -> System Options -> Boot /
Auto Login -> Console Autologin, then reboot.

**The chart appears but never updates.**
Check the render service: `sudo systemctl status
harbor-view-render.service`. If it's not running,
`sudo journalctl -u harbor-view-render.service -n 100` will show why
(common causes: a typo in `/etc/harbor-view/harbor-view.env`, or the
venv at `/opt/harbor-view/venv` being missing/corrupted -- re-run
`install.sh` to recreate it).

**The chart shows but the mouse cursor is visible.**
Confirm `.xinitrc` and the `startx -- -nocursor` invocation in
`.bash_profile` were actually installed for the `harborview` user:
`cat ~harborview/.bash_profile` should show the `startx -- -nocursor`
line. If a USB mouse is attached and still shows a cursor immediately
after boot, that can be the X server's brief startup state before
`-nocursor` takes effect -- it should disappear once feh's window is
up; if it persists, see `docs/deployment.md`'s troubleshooting notes
on cursor handling.

**I want to go back to a normal desktop / stop the appliance.**
```bash
sudo systemctl disable --now harbor-view-render.service
sudo raspi-config  # System Options -> Boot / Auto Login -> Desktop Autologin (or Console, without autologin)
sudo reboot
```

## Uninstalling

```bash
sudo systemctl disable --now harbor-view-render.service
sudo rm /etc/systemd/system/harbor-view-render.service
sudo systemctl daemon-reload
sudo rm -rf /opt/harbor-view /var/lib/harbor-view /etc/harbor-view
sudo userdel -r harborview
# Then re-run raspi-config to change the boot behaviour back, as above.
```
