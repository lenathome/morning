#!/usr/bin/env python3
"""compute_gaps.py — find free-time gaps in today's calendar.

Usage:
    cat calendar.json | python3 compute_gaps.py [--min-minutes 45] [--day-start 09:00] [--day-end 18:00]

Input (stdin): JSON array of events (output of fetch_calendar.py).
Output (stdout): JSON array of free gaps, each:
    {"start": "HH:MM", "end": "HH:MM", "minutes": int}

The day window defaults to 09:00–18:00 local time and counts gaps INSIDE that window only.
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timedelta


def parse_hhmm(s: str) -> datetime:
    """Parse 'HH:MM' against today's date."""
    today = datetime.now().replace(second=0, microsecond=0)
    h, m = s.split(":")
    return today.replace(hour=int(h), minute=int(m))


def parse_event_time(ts: str) -> datetime | None:
    """Parse the time_start/time_end fields from fetch_calendar.py.

    Format is `YYYY-MM-DD HH:MM` typically. All-day events use just `YYYY-MM-DD`.
    Returns None for all-day events (they don't block free time).
    """
    ts = ts.strip()
    if not ts:
        return None
    # All-day: just a date, no time → skip.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts):
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-minutes", type=int, default=45)
    parser.add_argument("--day-start", type=str, default="09:00")
    parser.add_argument("--day-end", type=str, default="18:00")
    args = parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        print("[]")
        return
    events = json.loads(raw)

    day_start = parse_hhmm(args.day_start)
    day_end = parse_hhmm(args.day_end)

    # Build a list of (start, end) tuples for timed events that fall in the day window.
    intervals: list[tuple[datetime, datetime]] = []
    for e in events:
        s = parse_event_time(e.get("time_start", ""))
        en = parse_event_time(e.get("time_end", ""))
        if s is None or en is None:
            continue
        # Clip to day window.
        s = max(s, day_start)
        en = min(en, day_end)
        if en > s:
            intervals.append((s, en))

    # Sort and merge overlapping intervals.
    intervals.sort()
    merged: list[tuple[datetime, datetime]] = []
    for s, en in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], en))
        else:
            merged.append((s, en))

    # Compute gaps inside the day window.
    gaps = []
    cursor = day_start
    for s, en in merged:
        if s > cursor:
            mins = int((s - cursor).total_seconds() // 60)
            if mins >= args.min_minutes:
                gaps.append({"start": cursor.strftime("%H:%M"), "end": s.strftime("%H:%M"), "minutes": mins})
        cursor = max(cursor, en)
    if day_end > cursor:
        mins = int((day_end - cursor).total_seconds() // 60)
        if mins >= args.min_minutes:
            gaps.append({"start": cursor.strftime("%H:%M"), "end": day_end.strftime("%H:%M"), "minutes": mins})

    print(json.dumps(gaps, indent=2))


if __name__ == "__main__":
    main()
