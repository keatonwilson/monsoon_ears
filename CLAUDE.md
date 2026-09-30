# Working on Monsoon Ears

Orientation, current state, and next steps live in
[`docs/README.md`](./docs/README.md). Read that before planning work.

## Anonymize captured traffic before it goes anywhere public

This pipeline records real emergencies involving real people, usually with an
address attached. Listening is legal; republishing is a separate decision, and
the repo is public.

**Never commit, publish, or display a real captured transmission without masking
it first.** This covers everything outward-facing — `README.md`, `docs/`, the
landing page, screenshots, demo footage, test fixtures, commit messages, PR
descriptions, and issue comments.

When quoting or showing captured traffic:

- **Mask house numbers.** `[200 block] W Irvington Rd`, never `205 W Irvington Rd`.
- **Drop medical nature-of-call entirely.** No cardiac, overdose, psychiatric, injury detail, patient age, or condition — not in a quote, a screenshot, or a structured-extraction example.
- **Remove names and dates of birth**, whether spoken by the dispatcher or appearing in an extracted field.
- **Prefer flood, water-rescue, road-closure, or fire traffic** over medical calls when you need an illustrative example. They make the same technical point.
- **Label masked quotes as masked**, so nobody mistakes the redaction for a transcription artifact.
- **Prefer a synthetic example** over a real capture when the example is only illustrating a format. Say it's illustrative.

Screen recordings and screenshots need the same treatment — the Feed, Threads,
and Map pages render whatever was captured, so film during flood traffic or
scrub the database first.

If you are unsure whether something crosses the line, leave it out and say so
rather than publishing and asking afterward. The dashboard binds to a private
network by default; keep it that way.

The demo-specific version of this rule, with the shot list it applies to, is in
[`docs/demo-script.md`](./docs/demo-script.md#anonymization-rule).

## Conventions

- Phase work is split into per-workstream branches with a PR each, off `main`.
- Location-specific values go in `config/locale.py`, not inline in agents or prompts.
- Don't commit or push unless asked.
