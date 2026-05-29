# Monsoon Ears

Multi-agent SDR radio intelligence pipeline for Tucson emergency frequencies, running on a Raspberry Pi 5 + RTL-SDR Blog V3.

Full spec: [`.claude/plan.md`](./.claude/plan.md).
Current phase: **02 — Ingestion** (analog FM → Whisper → SQLite). See [`.claude/plans/`](../../.claude/plans/) for the active build plan.

## Quick start (Pi)

```bash
cd ~/Documents/projects/monsoon_ears
uv venv
uv pip install -e ".[pi,dev]"
cp .env.example .env
# edit .env as needed
uv run python -m ingestion.runner_analog
```

## Quick start (Mac, tests only)

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest -v
```

The `pi` extras (pyrtlsdr, openai-whisper, aprs3) are skipped on Mac because
Torch has no Intel-Mac wheel.

## Syncing Mac → Pi

```bash
./scripts/sync_to_pi.sh
```
