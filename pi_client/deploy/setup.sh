#!/usr/bin/env bash
# pi_client/deploy/setup.sh
#
# One-shot Raspberry Pi bring-up for the surveillance robot client.
# Idempotent: safe to re-run.
#
# Usage (on the Pi, after `git clone <repo> ~/IoT`):
#     bash ~/IoT/pi_client/deploy/setup.sh
#
# After the script exits:
#   1. Edit ~/IoT/pi_client/config.yaml (vm_url, vm_token, GPIO pins).
#   2. sudo systemctl enable --now surveillance-robot
#   3. journalctl -u surveillance-robot -f

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${VENV_DIR:-$HOME/.venvs/surveillance}"
CONFIG_LIVE="$REPO_DIR/pi_client/config.yaml"
CONFIG_EXAMPLE="$REPO_DIR/pi_client/config.yaml.example"
UNIT_SRC="$REPO_DIR/pi_client/deploy/surveillance-robot.service"
UNIT_DST="/etc/systemd/system/surveillance-robot.service"

echo "==> repo:  $REPO_DIR"
echo "==> venv:  $VENV_DIR"

echo "==> apt: install base packages"
sudo apt update
sudo apt install -y \
    python3-pip python3-venv git \
    libopenblas-dev v4l-utils swig \
    python3-lgpio python3-gpiozero

if [[ ! -d "$VENV_DIR" ]]; then
    echo "==> venv: creating $VENV_DIR (with --system-site-packages)"
    python3 -m venv --system-site-packages "$VENV_DIR"
else
    echo "==> venv: $VENV_DIR already exists, reusing"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "==> pip: install pi_client requirements"
pip install --upgrade pip
pip install -r "$REPO_DIR/pi_client/requirements.txt"

if [[ ! -f "$CONFIG_LIVE" ]]; then
    echo "==> config: copying template -> $CONFIG_LIVE"
    cp "$CONFIG_EXAMPLE" "$CONFIG_LIVE"
    NEEDS_EDIT=1
else
    echo "==> config: $CONFIG_LIVE already exists, leaving untouched"
    NEEDS_EDIT=0
fi

echo "==> systemd: install $UNIT_DST"
sudo install -m 644 "$UNIT_SRC" "$UNIT_DST"
sudo systemctl daemon-reload

echo
echo "================================================================"
echo "Setup complete."
echo
if [[ "$NEEDS_EDIT" -eq 1 ]]; then
    echo "NEXT: edit $CONFIG_LIVE — set:"
    echo "  pi.vm_url    = the https://*.trycloudflare.com URL from the VM"
    echo "  pi.vm_token  = the same value as vm_server/config.yaml::server.secret_token"
    echo "  gpio.*       = match your wiring if it differs from the defaults"
    echo
fi
echo "Then start the service:"
echo "  sudo systemctl enable --now surveillance-robot"
echo "  journalctl -u surveillance-robot -f"
echo "================================================================"
