#!/usr/bin/env bash
# Run the Monsoon Ears FastAPI server. Bound to 0.0.0.0 so any host on the
# LAN can reach the dashboard's backend.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

PORT="${API_PORT:-8000}"
HOST="${API_HOST:-0.0.0.0}"

exec "$HOME/.local/bin/uv" run --no-sync uvicorn api.main:app \
    --host "$HOST" --port "$PORT" --log-level info
