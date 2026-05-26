#!/usr/bin/env python3
"""fetch_calendar.py — emit today's calendar events as JSON.

Usage:
    python3 fetch_calendar.py <ekko_email_domain>
    e.g. python3 fetch_calendar.py @ekko.earth

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
    0 = success (may print "[]" if no events today)
    1 = gcalcli not installed
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
        print("usage: fetch_calendar.py <ekko_email_domain>", file=sys.stderr)
        sys.exit(2)
    ekko_domain = sys.argv[1]

    if shutil.which("gcalcli") is None:
        print("gcalcli not found in PATH", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # --tsv format with email + conference + length details.
    # Layout per gcalcli docs (subject to version drift):
    #   start_date  start_time  end_date  end_time  length  title  conference  emails
    result = subprocess.run(
        [
            "gcalcli", "agenda", today, tomorrow,
            "--details=email",
            "--details=length",
            "--details=conference",
            "--tsv",
        ],
        capture_output=True,
        text=True,
    )

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
        start_time = fields[1] if len(fields) > 1 else ""
        end_date = fields[2] if len(fields) > 2 else ""
        end_time = fields[3] if len(fields) > 3 else ""
        title = fields[5] if len(fields) > 5 else "(no title)"
        conference = fields[6] if len(fields) > 6 else ""
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
