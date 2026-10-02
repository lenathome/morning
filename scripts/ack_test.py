#!/usr/bin/env python3
"""ack_test.py — mark merged PR(s) as tested, so they leave the Testing tab.

Usage:
    python3 ack_test.py <repo#number> [<repo#number> ...]

Each key is the `key` of a `test` entry in the brief's number map, e.g.
`ekko-checkout#142`.

The script appends new keys to ~/morning/state/acknowledged-tests.json
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


STATE_FILE = Path(os.path.expanduser("~/morning/state/acknowledged-tests.json"))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ack_test.py <repo#number> [<repo#number> ...]", file=sys.stderr)
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
    print(f"acknowledged {len(added)} new test(s); total acked: {len(existing)}")


if __name__ == "__main__":
    main()
