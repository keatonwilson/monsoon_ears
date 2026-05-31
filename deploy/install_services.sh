#!/usr/bin/env bash
# Install (or refresh) the Monsoon Ears systemd services on the Pi.
#
# Run this ON THE PI, from the repo root:
#     sudo deploy/install_services.sh
#
# It symlinks the unit files from the repo into /etc/systemd/system so that
# `git pull` keeps the running services in sync, reloads systemd, and enables
# the always-on services so they start on boot and restart on crash.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$SCRIPT_DIR/systemd"
SYSTEMD_DIR="/etc/systemd/system"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must run as root (use sudo)." >&2
  exit 1
fi

# Always-on services. monsoon-p25.service is intentionally excluded here — it
# cannot run until op25 is built on the Pi and PCWIN decode is confirmed (see
# deploy/op25_setup.md). Enable it by hand once validated.
SERVICES=(monsoon-runner monsoon-worker monsoon-aprs monsoon-gauges)

for svc in "${SERVICES[@]}"; do
  unit="$UNIT_DIR/$svc.service"
  if [[ ! -f "$unit" ]]; then
    echo "Missing unit file: $unit" >&2
    exit 1
  fi
  echo "Linking $svc.service"
  ln -sf "$unit" "$SYSTEMD_DIR/$svc.service"
done

echo "Reloading systemd"
systemctl daemon-reload

for svc in "${SERVICES[@]}"; do
  echo "Enabling + starting $svc"
  systemctl enable --now "$svc.service"
done

echo
echo "Done. Check status with:"
for svc in "${SERVICES[@]}"; do
  echo "    systemctl status $svc"
done
echo "Tail logs with: journalctl -u monsoon-runner -f"
