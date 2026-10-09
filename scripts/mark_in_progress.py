#!/usr/bin/env python3
"""mark_in_progress.py - mark Fathom action item(s) as in progress.

Usage:
    python3 mark_in_progress.py <key1> [<key2> ...]

Each key is the same stable hash ack_action.py takes (see SKILL.md Step 3a).

The script appends new keys to ~/morning/state/in-progress.json (a JSON
array of strings) and writes it back. Existing keys are not duplicated. The
state file is created lazily if it doesn't exist. The next brief lists these
actions under "In progress" instead of Your actions / Product actions, until
ack_action.py marks them done (which also removes them from this file).

Exit codes:
    0 = success (always, unless arg parsing fails)
    2 = no keys provided
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/in-progress.json"))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: mark_in_progress.py <key> [<key> ...]", file=sys.stderr)
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
    print(f"marked {len(added)} new action(s) in progress; total in progress: {len(existing)}")


if __name__ == "__main__":
    main()
