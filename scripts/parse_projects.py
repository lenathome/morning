#!/usr/bin/env python3
"""parse_projects.py - parse ~/product-os/projects/*.md into JSON for the morning brief.

Usage:
    python3 parse_projects.py <projects-dir> [--today YYYY-MM-DD] [--stale-days N]

Each project is a markdown file with YAML frontmatter:

    ---
    name: PPP localisation
    status: active            # active | blocked | waiting | done
    owner: Lena
    repos: [ekko-api]         # GitHub repo names for PR signal
    keywords: []              # optional PR title keywords
    notion: https://...
    next_milestone: one line
    target_date: 2026-09-12
    last_reviewed: 2026-09-01
    ---
    ## Where it is
    ...

Output (stdout): JSON array sorted by name, one object per file:
    {slug, name, status, owner, repos, keywords, notion, next_milestone,
     target_date, last_reviewed, stale, body}
`stale` is true when last_reviewed is missing or older than --stale-days (default 14).

Files whose name starts with "_" (the template) and anything in subdirectories
(_archive/) are ignored. Files without frontmatter are skipped with a warning.

Exit codes:
    0 = success (possibly [])
    1 = directory missing, or pyyaml not installed
    2 = bad YAML in any file (whole parse fails so the file gets fixed)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: pyyaml not installed. Run: python3 -m pip install --user pyyaml", file=sys.stderr)
    sys.exit(1)

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _to_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None


def _iso(value):
    d = _to_date(value)
    return d.isoformat() if d else (value if isinstance(value, str) else None)


def parse_file(path: Path, today: dt.date, stale_days: int) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        print(f"warning: {path.name} has no frontmatter, skipped", file=sys.stderr)
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        print(f"error: bad YAML in {path.name}: {e}", file=sys.stderr)
        sys.exit(2)

    last = _to_date(meta.get("last_reviewed"))
    stale = last is None or (today - last).days > stale_days

    return {
        "slug": path.stem,
        "name": str(meta.get("name") or path.stem),
        "status": str(meta.get("status") or "unknown"),
        "owner": meta.get("owner"),
        "repos": [str(r) for r in (meta.get("repos") or [])],
        "keywords": [str(k) for k in (meta.get("keywords") or [])],
        "notion": meta.get("notion") or None,
        "next_milestone": meta.get("next_milestone") or None,
        "target_date": _iso(meta.get("target_date")),
        "last_reviewed": last.isoformat() if last else None,
        "stale": stale,
        "body": text[m.end():].strip(),
    }


def parse_dir(directory: Path, today: dt.date, stale_days: int) -> list[dict]:
    if not directory.is_dir():
        print(f"error: {directory} not found", file=sys.stderr)
        sys.exit(1)
    results = []
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        parsed = parse_file(path, today, stale_days)
        if parsed:
            results.append(parsed)
    return sorted(results, key=lambda r: r["name"].lower())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects_dir")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, defaults to today (for tests)")
    ap.add_argument("--stale-days", type=int, default=14)
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    results = parse_dir(Path(args.projects_dir).expanduser(), today, args.stale_days)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
