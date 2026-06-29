#!/bin/bash
# Harbor View installer -- sets up a fresh Raspberry Pi OS (Bookworm
# or later, Lite or Desktop) to boot directly into Harbor View.
#
# Run as: sudo ./install.sh
#
# What this does, in order (see docs/installation.md for the prose
# version and docs/deployment.md for *why* each piece exists):
#   1. Installs system packages (Xorg, feh, Python, venv).
#   2. Creates a dedicated, unprivileged `harborview` system user.
#   3. Copies this repository to /opt/harbor-view.
#   4. Creates a Python virtualenv there and installs requirements.txt.
#   5. Installs the systemd render service.
#   6. Installs the kiosk display files (.xinitrc, .bash_profile) into
#      the harborview user's home directory.
#   7. Configures console autologin for the harborview user via
#      raspi-config (if present) or a direct systemd override
#      (if raspi-config isn't available, e.g. on Pi OS Lite without
#      it, or a non-Pi Debian system used for testing this installer).
#
# This script is idempotent: re-running it after a `git pull` updates
# the installed copy and restarts the services, without duplicating
# users or config.
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="/opt/harbor-view"
DATA_DIR="/var/lib/harbor-view"
CONFIG_DIR="/etc/harbor-view"
SERVICE_USER="harborview"

if [ "$(id -u)" -ne 0 ]; then
    echo "This installer must be run as root (sudo ./install.sh)." >&2
    exit 1
fi

echo "==> Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    xserver-xorg xinit x11-xserver-utils \
    feh \
    python3 python3-venv python3-pip

echo "==> Creating service user '$SERVICE_USER' (if needed)"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    # A system account with a real home directory (needed for
    # .bash_profile/.xinitrc) but no login shell beyond what
    # autologin grants it, and no sudo/admin group membership --
    # this account can boot the kiosk and nothing else.
    useradd --system --create-home --shell /bin/bash "$SERVICE_USER"
fi
# Console autologin and X both need this user able to use the video/
# input devices directly (no desktop session manager is granting that
# via logind/seatd the way it normally would).
usermod -aG video,input,tty "$SERVICE_USER"

echo "==> Copying Harbor View to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
# rsync (not cp -r) so re-running this installer after a `git pull`
# updates changed files and removes files that were deleted upstream,
# without needing to wipe and recopy everything.
rsync -a --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'output' \
    "$REPO_DIR"/ "$INSTALL_DIR"/
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> Setting up Python virtual environment"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
fi
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "==> Creating data and config directories"
mkdir -p "$DATA_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/harbor-view.env" ]; then
    cp "$INSTALL_DIR/deploy/harbor-view.env.example" "$CONFIG_DIR/harbor-view.env"
    echo "    Created $CONFIG_DIR/harbor-view.env from the example."
    echo "    Edit it to set HARBOR_VIEW_PROVIDER=ais and AISSTREAM_API_KEY"
    echo "    for live data -- it defaults to the placeholder fleet."
else
    echo "    $CONFIG_DIR/harbor-view.env already exists; leaving it as-is."
fi

echo "==> Installing the render service (systemd)"
cp "$INSTALL_DIR/deploy/harbor-view-render.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable harbor-view-render.service
systemctl restart harbor-view-render.service

echo "==> Installing kiosk display files for $SERVICE_USER"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 \
    "$INSTALL_DIR/deploy/xinitrc" "/home/$SERVICE_USER/.xinitrc"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0644 \
    "$INSTALL_DIR/deploy/bash_profile" "/home/$SERVICE_USER/.bash_profile"
chmod +x "$INSTALL_DIR/deploy/harbor-view-kiosk.sh"

echo "==> Configuring console autologin for $SERVICE_USER"
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_boot_behaviour B2  # B2 = Console Autologin
else
    # Not a Raspberry Pi OS image with raspi-config (e.g. a generic
    # Debian box used to test this installer) -- configure console
    # autologin directly via a getty override, which is what
    # raspi-config itself does under the hood.
    mkdir -p /etc/systemd/system/getty@tty1.service.d
    cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $SERVICE_USER --noclear %I \$TERM
EOF
    systemctl daemon-reload
fi

echo ""
echo "==> Done."
echo ""
echo "Harbor View is installed. Reboot to see it start automatically:"
echo "    sudo reboot"
echo ""
echo "To check the render service without rebooting:"
echo "    sudo systemctl status harbor-view-render.service"
echo "    sudo journalctl -u harbor-view-render.service -f"
echo ""
echo "Configuration lives in $CONFIG_DIR/harbor-view.env -- see"
echo "docs/deployment.md and docs/sprint-004-notes.md for details,"
echo "particularly to enable live AIS data (it defaults to the"
echo "placeholder fleet)."
