#!/usr/bin/env python3
"""ack_action.py — mark Fathom action item(s) as done.

Usage:
    python3 ack_action.py <key1> [<key2> ...]

Each key is a stable hash computed by SKILL.md as:
    sha1(meeting_id + lowercased_whitespace_normalised_action_text)[:16]

The script appends new keys to ~/morning/state/acknowledged-actions.json
(a JSON array of strings) and writes it back. Existing keys are not
duplicated. The state file is created lazily if it doesn't exist.

Exit codes:
    0 = success (always, unless arg parsing fails)
    2 = no keys provided
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/acknowledged-actions.json"))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ack_action.py <key> [<key> ...]", file=sys.stderr)
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
    print(f"acknowledged {len(added)} new action(s); total acked: {len(existing)}")


if __name__ == "__main__":
    main()
