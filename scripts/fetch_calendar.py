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

Exit codes:
    0 = success (may print "[]" if no events today, or gcalcli not installed — stderr carries the reason)
    2 = bad args
"""

from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta


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

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # --tsv format with email + conference + length details.
    # Actual layout observed at runtime (gcalcli emits a header row first):
    #   start_date  start_time  end_date  end_time  length  conference_uri  title  email
    cmd = ["gcalcli"]
    if primary_calendar:
        cmd += ["--calendar", primary_calendar]
    cmd += [
        "agenda", today, tomorrow,
        "--details=email",
        "--details=length",
        "--details=conference",
        "--tsv",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        # Don't fail the brief — emit empty array so the section just says "no events".
        print("[]")
        return

    events = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 6:
            continue

        start_date = fields[0]
        # Skip the header row that gcalcli --tsv emits as the first non-empty line.
        # The first column on the header is literally "start_date".
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_date):
            continue

        start_time = fields[1] if len(fields) > 1 else ""
        end_date = fields[2] if len(fields) > 2 else ""
        end_time = fields[3] if len(fields) > 3 else ""
        conference = fields[5] if len(fields) > 5 else ""
        title = fields[6] if len(fields) > 6 else "(no title)"
        emails_field = fields[7] if len(fields) > 7 else ""

        attendees = []
        for raw_email in emails_field.split(","):
            e = raw_email.strip()
            if not e:
                continue
            m = re.match(r"^(.*?)\s*<(.+?)>$", e)
            if m:
                attendees.append({"name": m.group(1).strip(), "email": m.group(2).strip()})
            elif "@" in e:
                attendees.append({"name": "", "email": e})

        is_external = any(
            a["email"] and not a["email"].endswith(ekko_domain)
            for a in attendees
        )

        events.append({
            "time_start": f"{start_date} {start_time}".strip(),
            "time_end":   f"{end_date} {end_time}".strip(),
            "title": title,
            "attendees": attendees,
            "is_external": is_external,
            "conference_link": conference,
        })

    print(json.dumps(events, indent=2))


if __name__ == "__main__":
    main()
