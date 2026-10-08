#!/usr/bin/env python3
"""ack_task.py — record Notion to-do(s) ticked off in the brief, so they never come back.

Usage:
    python3 ack_task.py <notion_page_id> [<notion_page_id> ...]

Each id is the `id` of a `notion` entry in the brief's number map. Step 7 sets
the page's Status to Done in Notion and records the id here as well, so the
brief can still drop the task if that Notion write failed or was reverted.

The script appends new keys to ~/morning/state/acknowledged-tasks.json
(a JSON array of strings) and writes it back. Existing keys are not
duplicated. The state file is created lazily if it doesn't exist.

Exit codes:
    0 = success
    2 = no keys provided
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/acknowledged-tasks.json"))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ack_task.py <notion_page_id> [<notion_page_id> ...]", file=sys.stderr)
        sys.exit(2)

    new_keys = [k.strip() for k in sys.argv[1:] if k.strip()]
    if not new_keys:
        print("no valid keys provided", file=sys.stderr)
        sys.exit(2)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text())
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []
    else:
        existing = []

    seen = set(existing)
    added = []
    for k in new_keys:
        if k not in seen:
            existing.append(k)
            seen.add(k)
            added.append(k)

    STATE_FILE.write_text(json.dumps(existing, indent=2))
    print(f"acknowledged {len(added)} new task(s); total acked: {len(existing)}")


if __name__ == "__main__":
    main()
