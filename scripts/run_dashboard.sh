#!/usr/bin/env bash
# Run the Streamlit dashboard on the Pi. Defaults assume the API is on the
# same host at :8000.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

PORT="${DASHBOARD_PORT:-8501}"
export MONSOON_API_URL="${MONSOON_API_URL:-http://localhost:8000}"

exec "$HOME/.local/bin/uv" run --no-sync streamlit run dashboard/app.py \
    --server.port "$PORT" --server.address 0.0.0.0 \
    --browser.gatherUsageStats false
