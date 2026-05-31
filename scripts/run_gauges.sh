#!/usr/bin/env bash
# Run the stream/rain gauge feed (USGS + optional Pima ALERT). Polls every
# GAUGE_POLL_MIN minutes and writes gauge_readings rows for the monsoon digest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

exec "$HOME/.local/bin/uv" run --no-sync python -m ingestion.runner_gauges
