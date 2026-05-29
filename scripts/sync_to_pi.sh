#!/usr/bin/env bash
# Mac → Pi rsync. Use for tight dev iteration; commit + push via git for canon.
set -euo pipefail

PI_HOST="${PI_HOST:-keaton@monsoon-ears.local}"
PI_PATH="${PI_PATH:-~/Documents/projects/monsoon_ears/}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
rsync -av --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude 'data/' \
  --exclude '*.wav' \
  --exclude '.env' \
  --exclude '.pytest_cache' \
  --exclude '.DS_Store' \
  ./ "$PI_HOST:$PI_PATH"

echo "Synced $REPO_ROOT → $PI_HOST:$PI_PATH"
