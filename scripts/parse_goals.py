#!/usr/bin/env python3
"""parse_goals.py - parse ~/product-os/goals.md into JSON for the morning brief.

Usage:
    python3 parse_goals.py <path-to-goals.md>

Expected format:

    ---
    quarter: Q4 2026
    status: draft              # draft | agreed
    status_note: one line
    ---

    # Goals
    intro paragraph (ignored)

    ## Goal 1: <title>

    **Why:** <text>

    **Done when:**
    - <item>

    ## Not doing this quarter

    - <item>

    ## <any other section> (ignored)

HTML comments (<!-- ... -->) are removed first.

Output (stdout), the shape the brief JSON's `goals` key takes:
    {"quarter": str, "status": str, "status_note": str,
     "goals": [{"title": str, "why": str, "done_when": [str]}],
     "not_doing": [str]}

Exit codes: 0 ok, 1 file missing or unreadable.
Stdlib only: the frontmatter is three flat `key: value` lines, so no YAML parser.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FRONTMATTER_RE = re.compile(r"\A\s*---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
GOAL_RE = re.compile(r"^##\s+Goal\s+\d+\s*:\s*(.+?)\s*$")
H2_RE = re.compile(r"^##\s+(.*?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
WHY_RE = re.compile(r"^\*\*Why:\*\*\s*(.*)$")
DONE_RE = re.compile(r"^\*\*Done when:\*\*\s*(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "#")):
            meta[key.strip()] = _unquote(value)
    return meta, text[m.end():]


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def parse_goals(text: str) -> dict:
    text = COMMENT_RE.sub("", text)
    meta, body = _frontmatter(text)
    goals: list[dict] = []
    not_doing: list[str] = []
    section = None      # "goal", "not_doing" or None (ignored)
    mode = None         # inside a goal: "why" or "done"
    goal: dict | None = None
    why_parts: list[str] = []

    def close_goal() -> None:
        if goal is not None:
            goal["why"] = _clean(" ".join(why_parts))
            goals.append(goal)

    for line in body.splitlines():
        g = GOAL_RE.match(line)
        h = H2_RE.match(line)
        if g or h:
            close_goal()
            goal, why_parts, mode = None, [], None
            if g:
                section = "goal"
                goal = {"title": _clean(g.group(1)), "why": "", "done_when": []}
            elif h.group(1).lower().startswith("not doing"):
                section = "not_doing"
            else:
                section = None
            continue
        if section == "not_doing":
            b = BULLET_RE.match(line)
            if b:
                not_doing.append(_clean(b.group(1)))
        elif section == "goal" and goal is not None:
            w, d = WHY_RE.match(line), DONE_RE.match(line)
            if w:
                mode = "why"
                why_parts.append(w.group(1))
            elif d:
                mode = "done"
                if d.group(1).strip():
                    goal["done_when"].append(_clean(d.group(1)))
            elif mode == "why" and line.strip():
                why_parts.append(line)
            elif mode == "done":
                b = BULLET_RE.match(line)
                if b:
                    goal["done_when"].append(_clean(b.group(1)))
                elif line.strip() and goal["done_when"] and line.startswith((" ", "\t")):
                    goal["done_when"][-1] = _clean(goal["done_when"][-1] + " " + line)
    close_goal()

    return {
        "quarter": meta.get("quarter", ""),
        "status": meta.get("status", ""),
        "status_note": meta.get("status_note", ""),
        "goals": goals,
        "not_doing": not_doing,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: parse_goals.py <path-to-goals.md>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1]).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: cannot read {path}: {e.strerror or e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(parse_goals(text), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
