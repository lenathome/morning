#!/usr/bin/env python3
"""mark_chased.py - record that Lena chased someone on a waiting-for-others item, so it stops showing as "chase" for 7 days.

Usage:
    python3 mark_chased.py <kind:id> [<kind:id> ...] [--today YYYY-MM-DD] [--state PATH]

Each key is "notion:<page id>" or "fathom:<action key>", the same key waiting_age.py reads.

The script sets each key to today's date in ~/morning/state/chased.json (a JSON object of key -> YYYY-MM-DD),
drops entries older than 30 days, and writes it back. The state file is created lazily if it doesn't exist;
a corrupt one is reset.

Exit codes:
    0 = success
    2 = no keys provided, or a bad --today
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

STATE_FILE = Path(os.path.expanduser("~/morning/state/chased.json"))
KEEP_DAYS = 30


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Record chased waiting-for-others items.")
    ap.add_argument("keys", nargs="*", help="<kind:id> ...")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--state", default=None, help="state file path (default: ~/morning/state/chased.json)")
    args = ap.parse_args(argv)

    keys = [k.strip() for k in args.keys if k.strip()]
    if not keys:
        print("usage: mark_chased.py <kind:id> [<kind:id> ...]", file=sys.stderr)
        sys.exit(2)
    try:
        today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    except ValueError:
        print(f"error: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        sys.exit(2)

    state = Path(args.state) if args.state else STATE_FILE
    state.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(state.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}

    for k in keys:
        data[k] = today.isoformat()
    kept = {}
    for k, v in data.items():
        try:
            age = (today - dt.date.fromisoformat(v)).days
        except (TypeError, ValueError):
            continue
        if age <= KEEP_DAYS:
            kept[k] = v

    state.write_text(json.dumps(kept, indent=2))
    print(f"marked {len(keys)} item(s) as chased on {today.isoformat()}; total tracked: {len(kept)}")


if __name__ == "__main__":
    main()
