# Proposals

Reviewable output from the `source-scout` skill (run it with `/source-scout`).

Each `source-scout-<date>.md` is a **proposal only** — candidate data sources
(stream gauges, PCWIN talkgroups, analog frequencies, web/API feeds) the scout
found, each with a citation and the exact edit it would imply. Nothing here is
applied automatically; you review a proposal and hand-merge whatever is worth
adding into `config/frequencies.py` / `config/gauges.py` (and re-run
`scripts/gen_op25_config.py` if you add a talkgroup).
