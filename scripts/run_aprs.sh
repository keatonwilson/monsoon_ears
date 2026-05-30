#!/usr/bin/env bash
# Run the APRS-IS weather packet feed. Requires APRS_IS_ENABLED=true in the
# environment (or .env); otherwise the client logs and exits cleanly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

exec "$HOME/.local/bin/uv" run --no-sync python -m ingestion.aprs_is_client
