#!/usr/bin/env python3
"""triage_state.py — record To Do page triage decisions.

Usage:
    python3 triage_state.py skip <hash> [<hash> ...]
    python3 triage_state.py add <hash> <notion_page_url>

The state file at ~/morning/state/triaged-items.json is a JSON array of records:
    {"hash": "...", "action": "skipped-forever" | "added", "notion_url": "..." (optional), "ts": "..."}

Exit codes:
    0 = success
    2 = bad args
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/triaged-items.json"))


def load() -> list[dict]:
    if not STATE_FILE.exists():
        return []
    try:
        data = json.loads(STATE_FILE.read_text())
        if not isinstance(data, list):
            return []
        return data
    except json.JSONDecodeError:
        return []


def save(records: list[dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(records, indent=2))


def main() -> None:
    if len(sys.argv) < 3:
        print("usage:\n  triage_state.py skip <hash> [<hash> ...]\n  triage_state.py add <hash> <notion_page_url>", file=sys.stderr)
        sys.exit(2)

    action = sys.argv[1]
    records = load()
    seen = {r["hash"] for r in records if "hash" in r}
    now = datetime.now(timezone.utc).isoformat()

    if action == "skip":
        new_hashes = [h.strip() for h in sys.argv[2:] if h.strip()]
        added = 0
        for h in new_hashes:
            if h not in seen:
                records.append({"hash": h, "action": "skipped-forever", "ts": now})
                seen.add(h)
                added += 1
        save(records)
        print(f"skip-forever: {added} new, {len(records)} total triaged")

    elif action == "add":
        if len(sys.argv) < 4:
            print("usage: triage_state.py add <hash> <notion_page_url>", file=sys.stderr)
            sys.exit(2)
        h = sys.argv[2].strip()
        url = sys.argv[3].strip()
        if h in seen:
            print(f"hash already triaged: {h}")
            return
        records.append({"hash": h, "action": "added", "notion_url": url, "ts": now})
        save(records)
        print(f"added: {h} -> {url}")

    else:
        print(f"unknown action: {action}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
