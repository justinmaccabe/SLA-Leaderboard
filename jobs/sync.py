"""Sync job: pull the current SLA-breached ticket counts from HubSpot and write a
snapshot to the database. Run by the GitHub Action every 15 minutes during office
hours, and by hand for testing.

Usage:
  python jobs/sync.py            # live: query HubSpot, write a snapshot
  python jobs/sync.py --demo     # write the scraped real numbers (no token needed)
  python jobs/sync.py --dry-run  # query HubSpot, print counts, write nothing

The GitHub cron fires on a fixed UTC grid that covers the ET office-hours window
for both EDT and EST; this script gates on the *actual* America/Toronto time so it
only does work between 08:30 and 17:30, Mon-Fri. Manual runs always proceed.
"""
from __future__ import annotations

import os
import sys
import datetime as dt
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

TZ = ZoneInfo("America/Toronto")
WINDOW_START = dt.time(8, 30)
WINDOW_END = dt.time(17, 30)


def in_office_hours(now: dt.datetime) -> bool:
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return WINDOW_START <= now.timetz().replace(tzinfo=None) <= WINDOW_END


def main():
    args = set(sys.argv[1:])
    db.init_db()

    if "--demo" in args:
        ca = db.write_snapshot(db.DEMO_COUNTS, source="demo",
                               note="Manual --demo seed")
        print(f"Wrote demo snapshot at {ca} (total {sum(db.DEMO_COUNTS.values())}).")
        return

    # Scheduled runs respect the office-hours window; manual runs (no --scheduled)
    # always proceed so you can test any time.
    now = dt.datetime.now(TZ)
    if "--scheduled" in args and not in_office_hours(now):
        print(f"{now:%Y-%m-%d %H:%M %Z}: outside office hours — skipping.")
        return

    from hubspot_client import HubSpot
    counts = HubSpot().fetch_breached()
    total = sum(counts.values())
    print(f"HubSpot: {total} breached tickets across {len(counts)} people.")

    expected = os.environ.get("EXPECTED_TOTAL")
    if expected and "--dry-run" in args:
        diff = total - int(expected)
        flag = "OK" if diff == 0 else f"OFF BY {diff} — recalibrate filters"
        print(f"Calibration vs report ({expected}): {flag}")

    if "--dry-run" in args:
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {n:>4}  {name}")
        print("(dry run — nothing written)")
        return

    ca = db.write_snapshot(counts, source="hubspot")
    print(f"Wrote snapshot at {ca}.")


if __name__ == "__main__":
    main()
