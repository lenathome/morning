#!/usr/bin/env python3
"""fetch_calendar.py — emit today's calendar events as JSON.

Usage:
    python3 fetch_calendar.py <ekko_email_domain> [<primary_calendar>]
    e.g. python3 fetch_calendar.py @ekko.earth lena.thome@ekko.earth

If <primary_calendar> is provided, the gcalcli query is restricted to that
single calendar so events you're only subscribed to (other people's standups,
team OOO calendars, etc.) are filtered out. Recommended.

Output (stdout): JSON array of events. Each event has:
    {
        "time_start": "YYYY-MM-DD HH:MM",
        "time_end":   "YYYY-MM-DD HH:MM",
        "title": str,
        "attendees": [{"email": str, "name": str}],
        "is_external": bool,
        "conference_link": str,
    }

Implementation note: gcalcli's --tsv mode returns only ONE attendee per event
(typically the organizer). To detect external meetings reliably we need ALL
attendees, so this script uses gcalcli's human-readable text output (with
--nocolor and --details=attendees) and parses it. Brittle vs TSV but correct.

Exit codes:
    0 = success (may print "[]" if no events today, or gcalcli not installed)
    2 = bad args
"""

from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta


# A date header looks like "Fri May 29" (weekday, month, day). Some events
# (all-day) have only a date header on their line, no time; some lines have
# both the date header AND a time + title; some lines have only spaces + time
# + title (a continuation of the most-recent date header).
DATE_HEADER_RE = re.compile(r"^([A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d+)\b")
EVENT_TIME_RE = re.compile(
    r"^(?:[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d+\s+|\s{4,})(?P<time>\d{1,2}:\d{2})\s+(?P<title>.+?)\s*$"
)
LENGTH_RE = re.compile(r"^\s+Length:\s+(?:(?P<days>\d+)\s+days?,\s+)?(?P<h>\d+):(?P<m>\d+):(?P<s>\d+)\s*$")
ATTENDEE_RE = re.compile(r"^\s+[^:]+:\s*<([^>]+)>\s*$")
CONFERENCE_RE = re.compile(r"^\s+Conference Link:\s+video:\s+(\S+)")

# Calendar resource emails (room bookings, equipment) are not real attendees
# and must not flip is_external true.
RESOURCE_DOMAINS = ("resource.calendar.google.com",)


def parse_agenda(text: str, year: int) -> list[dict]:
    """Parse gcalcli's --nocolor agenda output into structured events."""
    events: list[dict] = []
    current: dict | None = None
    current_date: str | None = None
    in_attendees = False

    for line in text.split("\n"):
        # A date header may appear on any "event header" line — capture it
        # before deciding whether the line also includes a time.
        m_date = DATE_HEADER_RE.match(line)
        if m_date:
            current_date = m_date.group(1).strip()

        m_evt = EVENT_TIME_RE.match(line)
        if m_evt:
            if current:
                events.append(current)
            if not current_date:
                current = None
                continue
            current = {
                "_date_header": current_date,
                "start_time": m_evt.group("time"),
                "title": m_evt.group("title").rstrip(),
                "attendees": [],
                "length_min": 60,
                "conference_link": "",
            }
            in_attendees = False
            continue

        # All-day or multi-day event header (date only, no time on this line).
        # We don't surface those — they have no start_time we can sort against.
        if m_date and not m_evt:
            if current:
                events.append(current)
            current = None
            in_attendees = False
            continue

        if current is None:
            continue

        if line.strip().startswith("Attendees:"):
            in_attendees = True
            continue

        m = LENGTH_RE.match(line)
        if m:
            days = int(m.group("days") or 0)
            h, mi = int(m.group("h")), int(m.group("m"))
            current["length_min"] = days * 24 * 60 + h * 60 + mi
            in_attendees = False
            continue

        m = CONFERENCE_RE.match(line)
        if m:
            current["conference_link"] = m.group(1)
            in_attendees = False
            continue

        if in_attendees:
            m = ATTENDEE_RE.match(line)
            if m:
                email = m.group(1)
                # Skip Google resource calendars (room bookings, equipment).
                if any(email.endswith(d) for d in RESOURCE_DOMAINS):
                    continue
                current["attendees"].append({"name": "", "email": email})
                continue
            in_attendees = False

    if current:
        events.append(current)

    # Convert _date_header + start_time + length_min into time_start / time_end.
    out = []
    for e in events:
        try:
            start_dt = datetime.strptime(f"{e['_date_header']} {year} {e['start_time']}", "%a %b %d %Y %H:%M")
        except ValueError:
            continue
        end_dt = start_dt + timedelta(minutes=e["length_min"])
        out.append({
            "time_start": start_dt.strftime("%Y-%m-%d %H:%M"),
            "time_end":   end_dt.strftime("%Y-%m-%d %H:%M"),
            "title": e["title"],
            "attendees": e["attendees"],
            "is_external": False,  # filled in below
            "conference_link": e["conference_link"],
        })
    return out


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: fetch_calendar.py <ekko_email_domain> [<primary_calendar>]", file=sys.stderr)
        sys.exit(2)
    ekko_domain = sys.argv[1]
    primary_calendar = sys.argv[2] if len(sys.argv) > 2 else None

    if shutil.which("gcalcli") is None:
        print("gcalcli not found in PATH", file=sys.stderr)
        print("[]")
        sys.exit(0)

    today_d = date.today()
    today = today_d.isoformat()
    tomorrow = (today_d + timedelta(days=1)).isoformat()

    cmd = ["gcalcli", "--nocolor"]
    if primary_calendar:
        cmd += ["--calendar", primary_calendar]
    cmd += [
        "agenda", today, tomorrow,
        "--details=attendees",
        "--details=length",
        "--details=conference",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("[]")
        return

    events = parse_agenda(result.stdout, today_d.year)

    # Mark external: any attendee email not ending with the configured domain.
    for e in events:
        e["is_external"] = any(
            a["email"] and not a["email"].endswith(ekko_domain)
            for a in e["attendees"]
        )

    print(json.dumps(events, indent=2))


if __name__ == "__main__":
    main()
