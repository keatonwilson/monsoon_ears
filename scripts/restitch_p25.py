"""Re-stitch P25 event threads by talkgroup.

Before Phase 10, threads were clustered purely by `frequency_mhz`. Every P25
event carries `frequency_mhz=0.0`, so all P25 talkgroups within the gap window
got merged into a single thread. Phase 10 keys P25 clustering on `talkgroup_id`
instead. This rebuilds the historical P25 threads under the new rule: it deletes
the old P25 threads (the 0.0 MHz placeholders) and re-stitches their events so
each talkgroup gets its own thread. Analog threads are left untouched.

    uv run python scripts/restitch_p25.py            # do it
    uv run python scripts/restitch_p25.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_  # noqa: E402
from sqlmodel import select  # noqa: E402

from db.database import EventThreadRow, TranscriptionEventRow, get_session  # noqa: E402
from db.queries import stitch_events_into_threads  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, don't write")
    args = ap.parse_args()

    with get_session() as session:
        p25_event_ids = [
            r.id for r in session.exec(
                select(TranscriptionEventRow).where(TranscriptionEventRow.source == "p25")
            )
        ]
        # Old P25 threads: the 0.0 MHz placeholders, plus any already tagged p25
        # (so re-runs are idempotent — they rebuild what they previously built).
        stale = list(session.exec(
            select(EventThreadRow).where(
                or_(EventThreadRow.frequency_mhz == 0.0, EventThreadRow.source == "p25")
            )
        ))
        print(f"{len(p25_event_ids)} P25 event(s); {len(stale)} P25 thread(s) to rebuild.")
        if args.dry_run or not p25_event_ids:
            return 0
        for t in stale:
            session.delete(t)
        session.commit()

    touched = stitch_events_into_threads(p25_event_ids)
    print(f"Done: re-stitched {len(p25_event_ids)} event(s) into {touched} talkgroup thread(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
