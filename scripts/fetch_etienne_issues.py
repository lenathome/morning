#!/usr/bin/env python3
"""fetch_etienne_issues.py — list GitHub issues raised by Etienne that are new or have new comments from him.

Usage:
    python3 fetch_etienne_issues.py [check] [--authors a,b]
    python3 fetch_etienne_issues.py mark <number> [<number> ...] [--authors a,b]
    python3 fetch_etienne_issues.py forget <number> [<number> ...]

An issue on lenathome/product-os qualifies when it is open, its author is in
AUTHORS, and it has the label "from-etienne" or a title starting with
"[from-etienne]" (case-insensitive).

check (the default) prints {"items": [...]} to stdout, sorted by issue number.
  - Issue not in state: item with kind "new", the issue body and all comments
    by AUTHORS.
  - Issue in state: comments by AUTHORS whose id is not in seen_comment_ids.
    If there are any, item with kind "update" and an empty body.
  Comments by anyone outside AUTHORS are ignored. check never writes state.
mark records ALL current comment ids (any author) for each issue as seen and
  prints {"marked": [...]}.
forget drops issues from state (e.g. once closed) and prints {"forgotten": [...]}.

State lives in ~/morning/state/etienne-issues.json:
    {"issues": {"<number>": {"seen_comment_ids": [...], "seen_at": "<iso utc>"}}}
A missing file is empty state; parent dirs are created lazily on write.

Exit codes:
    0 = success
    1 = gh failed (first line of its stderr is printed, prefixed "gh failed: ")
    2 = usage error
"""

from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO = "lenathome/product-os"
AUTHORS = {"EtienneEkko"}
STATE_FILE = Path(os.path.expanduser("~/morning/state/etienne-issues.json"))

LABEL = "from-etienne"
TITLE_PREFIX = "[from-etienne]"
SUBCOMMANDS = {"check", "mark", "forget"}


def run_gh(args: list[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"issues": {}}
    if not isinstance(data, dict) or not isinstance(data.get("issues"), dict):
        return {"issues": {}}
    return data


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


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


def cmd_check(authors: set[str]) -> dict:
    raw = run_gh(["issue", "list", "-R", REPO, "--state", "open", "--limit", "100",
                  "--json", "number,title,url,author,labels,updatedAt,body"])
    issues = [i for i in json.loads(raw) if qualifies(i, authors)]
    state = load_state()["issues"]
    items = []
    for issue in sorted(issues, key=lambda i: i["number"]):
        key = str(issue["number"])
        by_authors = [c for c in fetch_comments(issue["number"]) if login_of(c.get("author")) in authors]
        base = {"number": issue["number"], "title": issue["title"], "url": issue["url"]}
        if key not in state:
            items.append({**base, "kind": "new", "body": issue.get("body", ""),
                          "new_comments": [shape_comment(c) for c in by_authors]})
            continue
        seen = set(state[key].get("seen_comment_ids") or [])
        fresh = [c for c in by_authors if c.get("id") not in seen]
        if fresh:
            items.append({**base, "kind": "update", "body": "",
                          "new_comments": [shape_comment(c) for c in fresh]})
    return {"items": items}


def cmd_mark(numbers: list[int]) -> dict:
    fetched = {n: [c.get("id") for c in fetch_comments(n)] for n in numbers}
    state = load_state()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for n, ids in fetched.items():
        state["issues"][str(n)] = {"seen_comment_ids": ids, "seen_at": now}
    save_state(state)
    return {"marked": numbers}


def cmd_forget(numbers: list[int]) -> dict:
    state = load_state()
    for n in numbers:
        state["issues"].pop(str(n), None)
    save_state(state)
    return {"forgotten": numbers}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--authors", help="comma-separated GitHub logins (default: %s)" % ",".join(sorted(AUTHORS)))
    p = argparse.ArgumentParser(prog="fetch_etienne_issues.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("check", parents=[common])
    for name in ("mark", "forget"):
        s = sub.add_parser(name, parents=[common])
        s.add_argument("numbers", nargs="+", type=int)
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
        elif args.cmd == "mark":
            result = cmd_mark(args.numbers)
        else:
            result = cmd_forget(args.numbers)
    except subprocess.CalledProcessError as e:
        lines = (e.stderr or "").strip().splitlines()
        print("gh failed: " + (lines[0] if lines else str(e)), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
