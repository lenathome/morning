#!/usr/bin/env python3
"""waiting_age.py - work out how long each "waiting for others" item has been waiting, and whether to chase it.

Usage:
    python3 waiting_age.py --items items.json --briefs-dir ~/product-os/briefs \\
        --milestones ~/product-os/milestones.md --chased ~/morning/state/chased.json --today 2026-10-27

Input (--items): a JSON list. Each item has `kind` ("notion" or "fathom"), `id` (notion) or `key` (fathom),
and `text`. Optional: who, url, project, project_slug, due (YYYY-MM-DD), meeting_date (YYYY-MM-DD, fathom).
Unknown fields pass through unchanged.

Each item gets five more fields:
    since        YYYY-MM-DD. fathom + meeting_date: that date. Otherwise the earliest past brief
                 (<briefs-dir>/YYYY-MM-DD.json, dated before today) that lists the item: in the top-level
                 `waiting` list by kind and id/key, or, in older briefs, a notion item whose text matches a
                 projects[].waiting_on text, or a fathom item whose key is in actions.product[].key.
                 Not found: today.
    days         whole days from since to today.
    chased_on    date from chased.json ({"<kind>:<id or key>": "YYYY-MM-DD"}), or null.
    gates        name of an open milestone the item's project gates (at-risk, or with a date), else null.
    chase_reason first that applies, else null:
                   "chase-by date <D Mon>"               due is today or earlier
                   "gates <milestone>"                    gates a milestone and days >= 3
                   "waiting <n> days"                    days >= 7
    chase        true when there is a reason and the item was not chased in the last 7 days.

Output (stdout): the list, chase true first, then days descending, then text ascending.

milestones.md holds a `milestones:` list in a fenced yaml block or in frontmatter. A small parser reads it
(no PyYAML). A missing file means no gates. A missing or malformed chased.json counts as {}.

Exit codes:
    0 = success
    1 = invalid input (message on stderr)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BRIEF_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
CHASE_COOLDOWN_DAYS = 7
WAITING_DAYS = 7
GATE_DAYS = 3


class InputError(Exception):
    pass


def norm(text) -> str:
    return " ".join(str(text).split()).casefold()


def parse_date(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


# ---- milestones.md ----------------------------------------------------------

def _scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


def _inline_list(raw: str) -> list:
    inner = raw.strip()[1:-1].strip()
    return [_scalar(p) for p in inner.split(",") if p.strip()] if inner else []


def _yaml_block(text: str) -> list:
    m = re.search(r"```ya?ml[ \t]*\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).splitlines()
    m = re.match(r"\A---[ \t]*\n(.*?)\n---", text, re.DOTALL)
    return m.group(1).splitlines() if m else []


def parse_milestones(text: str) -> list:
    """Return a list of dicts (id, name, date, kind, client, projects, gates, status) from the milestones list."""
    lines = _yaml_block(text)
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "milestones:"), None)
    if start is None:
        return []
    entries, cur, list_key, entry_indent = [], None, None, None
    for ln in lines[start + 1:]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip())
        body = ln.strip()
        if body.startswith("- ") and (entry_indent is None or indent == entry_indent):
            entry_indent = indent
            cur = {}
            entries.append(cur)
            list_key = None
            body = body[2:].strip()
        elif cur is None or indent <= entry_indent:
            continue
        elif body.startswith("- "):
            if list_key:
                cur[list_key].append(_scalar(body[2:]))
            continue
        m = re.match(r"([A-Za-z_][\w-]*):(?:\s+(.*))?$", body)
        if not m:
            continue
        key, val = m.group(1), (m.group(2) or "").strip()
        list_key = None
        if val.startswith("[") and val.endswith("]"):
            cur[key] = _inline_list(val)
        elif val == "" and key in ("projects", "gates"):
            cur[key] = []
            list_key = key
        else:
            cur[key] = _scalar(val)
    return entries


def load_milestones(path) -> list:
    try:
        return parse_milestones(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []


def gating_milestone(slug, milestones):
    if not slug:
        return None
    for ms in milestones:
        if ms.get("status") == "done" or slug not in (ms.get("projects") or []):
            continue
        if ms.get("status") == "at-risk" or ms.get("date"):
            return ms.get("name") or ms.get("id") or "a milestone"
    return None


# ---- brief history ----------------------------------------------------------

def load_brief_history(briefs_dir, today: dt.date) -> list:
    """[(date, brief dict)] for readable briefs dated before today, oldest first."""
    out = []
    try:
        files = sorted(Path(briefs_dir).iterdir())
    except OSError:
        return out
    for f in files:
        m = BRIEF_FILE_RE.match(f.name)
        d = parse_date(m.group(1)) if m else None
        if d is None or d >= today:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append((d, data))
    return sorted(out, key=lambda p: p[0])


def _dicts(x):
    return [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []


def in_brief(item, brief) -> bool:
    kind = item["kind"]
    ident = item.get("id") if kind == "notion" else item.get("key")
    for w in _dicts(brief.get("waiting")):
        if w.get("kind") == kind and (w.get("id") if kind == "notion" else w.get("key")) == ident:
            return True
    if kind == "notion":
        want = norm(item["text"])
        for p in _dicts(brief.get("projects")):
            for e in p.get("waiting_on") if isinstance(p.get("waiting_on"), list) else []:
                t = e.get("text") if isinstance(e, dict) else e
                if isinstance(t, str) and norm(t) == want:
                    return True
    elif kind == "fathom":
        actions = brief.get("actions")
        if isinstance(actions, dict):
            return any(a.get("key") == ident for a in _dicts(actions.get("product")))
    return False


# ---- main logic -------------------------------------------------------------

def validate(items) -> list:
    if not isinstance(items, list):
        raise InputError("items must be a JSON list")
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise InputError(f"item {i} is not an object")
        kind = it.get("kind")
        if kind not in ("notion", "fathom"):
            raise InputError(f"item {i} needs kind 'notion' or 'fathom'")
        field = "id" if kind == "notion" else "key"
        if not isinstance(it.get(field), str) or not it[field]:
            raise InputError(f"item {i} ({kind}) needs a non-empty '{field}'")
        if not isinstance(it.get("text"), str) or not it["text"].strip():
            raise InputError(f"item {i} needs non-empty 'text'")
    return items


def load_chased(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enrich(items, history, milestones, chased, today: dt.date) -> list:
    out = []
    for it in items:
        ident = it["id"] if it["kind"] == "notion" else it["key"]
        since = None
        if it["kind"] == "fathom":
            since = parse_date(it.get("meeting_date"))
        if since is None:
            since = next((d for d, b in history if in_brief(it, b)), today)
        days = max((today - since).days, 0)
        chased_on = parse_date(chased.get(f"{it['kind']}:{ident}"))
        due = parse_date(it.get("due"))
        gate = gating_milestone(it.get("project_slug"), milestones)
        if due and due <= today:
            reason = f"chase-by date {due.day} {MONTHS[due.month - 1]}"
        elif gate and days >= GATE_DAYS:
            reason = f"gates {gate}"
        elif days >= WAITING_DAYS:
            reason = f"waiting {days} days"
        else:
            reason = None
        recent = chased_on is not None and (today - chased_on).days < CHASE_COOLDOWN_DAYS
        res = dict(it)
        res.update({
            "since": since.isoformat(),
            "days": days,
            "chased_on": chased_on.isoformat() if chased_on else None,
            "gates": gate,
            "chase_reason": reason,
            "chase": reason is not None and not recent,
        })
        out.append(res)
    out.sort(key=lambda r: (not r["chase"], -r["days"], r["text"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Add age and chase flags to waiting-for-others items.")
    ap.add_argument("--items", required=True)
    ap.add_argument("--briefs-dir", required=True)
    ap.add_argument("--milestones", required=True)
    ap.add_argument("--chased", required=True)
    ap.add_argument("--today", required=True, help="YYYY-MM-DD")
    args = ap.parse_args(argv)
    try:
        today = dt.date.fromisoformat(args.today)
    except ValueError:
        print(f"error: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        return 1
    try:
        items = validate(json.loads(Path(args.items).read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        print(f"error: cannot read items: {e}", file=sys.stderr)
        return 1
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    result = enrich(items, load_brief_history(args.briefs_dir, today), load_milestones(args.milestones),
                    load_chased(args.chased), today)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
