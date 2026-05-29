#!/usr/bin/env python3
"""ack_pr.py — record that a PR has been engaged with (commented, partially reviewed).

Usage:
    python3 ack_pr.py <pr_url> <updated_at_iso>

The morning brief surfaces PRs from `gh search prs --review-requested=@me`.
Once you've engaged with a PR (commented, partially reviewed) but not yet
submitted a formal Approve / Request changes, the PR keeps appearing daily
because GitHub still lists you as a requested reviewer. This script lets you
hide it until the PR has new activity.

State file at ~/morning/state/acknowledged-prs.json:
    [{"pr_url": "...", "last_seen_updated_at": "ISO-8601"}, ...]

The brief shows a PR only if its current updatedAt is strictly greater than
the recorded last_seen_updated_at (i.e. the PR has moved since you parked it).

Exit codes:
    0 = success
    2 = bad args
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/acknowledged-prs.json"))


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: ack_pr.py <pr_url> <updated_at_iso>", file=sys.stderr)
        sys.exit(2)

    pr_url = sys.argv[1].strip()
    updated_at = sys.argv[2].strip()
    if not pr_url or not updated_at:
        print("both pr_url and updated_at_iso required", file=sys.stderr)
        sys.exit(2)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        try:
            records = json.loads(STATE_FILE.read_text())
            if not isinstance(records, list):
                records = []
        except json.JSONDecodeError:
            records = []
    else:
        records = []

    # Update existing entry or append new.
    updated = False
    for r in records:
        if r.get("pr_url") == pr_url:
            r["last_seen_updated_at"] = updated_at
            updated = True
            break
    if not updated:
        records.append({"pr_url": pr_url, "last_seen_updated_at": updated_at})

    STATE_FILE.write_text(json.dumps(records, indent=2))
    print(f"{'updated' if updated else 'added'}: {pr_url} parked at {updated_at}")


if __name__ == "__main__":
    main()
