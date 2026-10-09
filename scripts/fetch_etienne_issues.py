#!/usr/bin/env python3
"""fetch_etienne_issues.py — list GitHub issues raised by Etienne that we have not yet answered.

Usage:
    python3 fetch_etienne_issues.py [check] [--authors a,b]
    python3 fetch_etienne_issues.py pending

An issue on lenathome/product-os qualifies when it is open, its author is in
AUTHORS, and it has the label "from-etienne" or a title starting with
"[from-etienne]" (case-insensitive).

There is no state file. "Seen" is derived from the issue's own comments: any
comment whose author is NOT in AUTHORS is ours, and the acknowledgement comment
we post is what marks an item seen.

check (the default) prints {"items": [...]} to stdout, sorted by issue number.
  - No comment by us at all: item with kind "new", the issue body and all
    comments by AUTHORS.
  - Otherwise, comments by AUTHORS created strictly after our latest comment.
    If there are any, item with kind "update", an empty body and those comments
    in new_comments. If none, the issue is not listed.
pending prints {"items": [{"number", "title", "url"}, ...]} for open qualifying
  issues carrying the label "needs-lena", sorted by number. Local sessions use
  it to pick up items the cloud run escalated.

Exit codes:
    0 = success
    1 = gh failed (first line of its stderr is printed, prefixed "gh failed: ")
    2 = usage error
"""

from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone


REPO = "lenathome/product-os"
AUTHORS = {"EtienneEkko"}
NEEDS_LENA = "needs-lena"

LABEL = "from-etienne"
TITLE_PREFIX = "[from-etienne]"
SUBCOMMANDS = {"check", "pending"}


def run_gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def login_of(obj: dict | None) -> str:
    return ((obj or {}).get("login") or "").lower()


def qualifies(issue: dict, authors: set[str]) -> bool:
    if login_of(issue.get("author")) not in authors:
        return False
    labels = {(l.get("name") or "").lower() for l in issue.get("labels") or []}
    title = (issue.get("title") or "").lower()
    return LABEL in labels or title.startswith(TITLE_PREFIX)


def fetch_comments(number: int) -> list[dict]:
    raw = run_gh(["issue", "view", str(number), "-R", REPO, "--json", "comments"])
    return json.loads(raw).get("comments") or []


def shape_comment(c: dict) -> dict:
    return {
        "id": c.get("id"),
        "author": (c.get("author") or {}).get("login", ""),
        "created_at": c.get("createdAt"),
        "body": c.get("body", ""),
        "url": c.get("url"),
    }


def parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def list_qualifying(authors: set[str]) -> list[dict]:
    raw = run_gh(["issue", "list", "-R", REPO, "--state", "open", "--limit", "100",
                  "--json", "number,title,url,author,labels,updatedAt,body"])
    issues = [i for i in json.loads(raw) if qualifies(i, authors)]
    return sorted(issues, key=lambda i: i["number"])


def cmd_check(authors: set[str]) -> dict:
    items = []
    for issue in list_qualifying(authors):
        comments = fetch_comments(issue["number"])
        theirs = [c for c in comments if login_of(c.get("author")) in authors]
        ours = [c for c in comments if login_of(c.get("author")) not in authors]
        base = {"number": issue["number"], "title": issue["title"], "url": issue["url"]}
        if not ours:
            items.append({**base, "kind": "new", "body": issue.get("body", ""),
                          "new_comments": [shape_comment(c) for c in theirs]})
            continue
        latest = max(parse_ts(c.get("createdAt")) for c in ours)
        fresh = [c for c in theirs if parse_ts(c.get("createdAt")) > latest]
        if fresh:
            items.append({**base, "kind": "update", "body": "",
                          "new_comments": [shape_comment(c) for c in fresh]})
    return {"items": items}


def cmd_pending(authors: set[str]) -> dict:
    items = []
    for issue in list_qualifying(authors):
        labels = {(l.get("name") or "").lower() for l in issue.get("labels") or []}
        if NEEDS_LENA in labels:
            items.append({"number": issue["number"], "title": issue["title"], "url": issue["url"]})
    return {"items": items}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--authors", help="comma-separated GitHub logins (default: %s)" % ",".join(sorted(AUTHORS)))
    p = argparse.ArgumentParser(prog="fetch_etienne_issues.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")
    for name in ("check", "pending"):
        sub.add_parser(name, parents=[common])
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help")):
        argv.insert(0, "check")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    authors = AUTHORS
    if args.authors is not None:
        authors = {a.strip() for a in args.authors.split(",") if a.strip()}
    authors = {a.lower() for a in authors}

    try:
        if args.cmd == "check":
            result = cmd_check(authors)
        else:
            result = cmd_pending(authors)
    except subprocess.CalledProcessError as e:
        lines = (e.stderr or "").strip().splitlines()
        print("gh failed: " + (lines[0] if lines else str(e)), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
