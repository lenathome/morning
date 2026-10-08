#!/usr/bin/env python3
"""proposals.py - a queue of proposed edits to ~/product-os/projects/*.md.

An unattended job adds proposals; the user accepts or rejects them later. Accepting
applies the edit to the project file and stamps `last_reviewed:`.

Usage:
    python3 proposals.py [--state FILE] [--projects-dir DIR] add < items.json
    python3 proposals.py [--state FILE] [--projects-dir DIR] list
    python3 proposals.py [--state FILE] [--projects-dir DIR] accept ID [ID ...]
    python3 proposals.py [--state FILE] [--projects-dir DIR] reject ID [ID ...]

--state (default ~/morning/state/project-proposals.json) and --projects-dir
(default ~/product-os/projects) are accepted before or after the subcommand. The
resolved-proposal log sits beside the state file as project-proposals-log.json.
Both files are JSON arrays; a missing file means [].

`add` reads a JSON array from stdin. Item keys:
    slug            project file stem
    kind            "append" or "frontmatter"
    section         append: heading text without "## " (e.g. "Recent decisions")
    field           frontmatter: key that already exists (e.g. "next_milestone")
    text | value    append: bullet text | frontmatter: new raw value
    source          e.g. "ai-log/2026-09-29.md, Morning brief fixes"
    session_title, session_date (YYYY-MM-DD)
Invalid items are reported on stderr and skipped. id = sha1(slug|kind|section-or-
field|text-or-value)[:12]; ids already pending or already in the log are skipped.
An item is also skipped when it says the same thing as a pending proposal for the
same project (any section) or as the project file's current text: same words once
case, punctuation, a leading "YYYY-MM-DD:" and html comments are ignored, or the
shorter of two texts (3+ words) sits inside the longer. A frontmatter proposal is
skipped when the field already holds that value.
Output: {"added": [ids], "skipped": [{"item_index": i, "reason": "..."}]}

`accept` for an append inserts "- <text> <!-- src: <source> -->" after the last
non-blank line of the section; for a frontmatter proposal it replaces the field's
value. Either way `last_reviewed:` is set to today's date if the field exists.
Output: {"accepted": [ids], "unknown": [ids]}; `reject` prints {"rejected": ...}.
An accept that cannot be applied (file or heading gone) is left pending and
listed under "failed".
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

LOG_NAME = "project-proposals-log.json"
KINDS = ("append", "frontmatter")
COMMON_KEYS = ("slug", "kind", "source", "session_title", "session_date")
STORED_KEYS = COMMON_KEYS + ("section", "field", "text", "value")


def load_json_array(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_text_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def proposal_id(item: dict) -> str:
    key = item["section"] if item["kind"] == "append" else item["field"]
    body = item["text"] if item["kind"] == "append" else item["value"]
    raw = "|".join([item["slug"], item["kind"], key, str(body)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def normalise(text: str) -> str:
    """Lowercase words only: html comments, a leading date and punctuation dropped."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"^\s*(?:[-*]\s+)?\d{4}-\d{2}-\d{2}\s*:?", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def same_thing(a: str, b: str) -> bool:
    """True when two normalised texts match, or the shorter (3+ words) sits inside the longer."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short.split()) >= 3 and f" {short} " in f" {long_} "


def current_value(lines: list[str], field: str) -> str:
    idx = find_field(lines, field)
    if idx is None:
        return ""
    return lines[idx].split(":", 1)[1].strip().strip("\"'")


def redundant_reason(item: dict, pending: list[dict], projects_dir: Path) -> str | None:
    """Reason to skip a valid item that repeats a pending proposal or the project file, else None."""
    lines = (projects_dir / f"{item['slug']}.md").read_text(encoding="utf-8").split("\n")
    if item["kind"] == "frontmatter":
        if normalise(current_value(lines, item["field"])) == normalise(item["value"]):
            return f"{item['field']} already set in {item['slug']}.md"
        mine = normalise(item["value"])
        for p in pending:
            if (p["slug"], p["kind"], p.get("field")) == (item["slug"], "frontmatter", item["field"]) \
                    and normalise(p["value"]) == mine:
                return f"same as pending {p['id']}"
        return None
    mine = normalise(item["text"])
    for p in pending:
        if p["slug"] == item["slug"] and p["kind"] == "append" and same_thing(mine, normalise(p["text"])):
            return f"same as pending {p['id']}"
    fm = frontmatter_range(lines)
    body = lines[fm[1] + 1 :] if fm else lines
    if any(same_thing(mine, normalise(line)) for line in body) \
            or (len(mine.split()) >= 3 and f" {mine} " in f" {normalise(' '.join(body))} "):
        return f"already in {item['slug']}.md"
    return None


def frontmatter_range(lines: list[str]) -> tuple[int, int] | None:
    """Return (start, end) line indexes of the frontmatter body, excluding the fences."""
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return 1, i
    return None


def find_field(lines: list[str], field: str) -> int | None:
    fm = frontmatter_range(lines)
    if fm is None:
        return None
    pattern = re.compile(r"^(\s*)" + re.escape(field) + r":(\s|$)")
    for i in range(fm[0], fm[1]):
        if pattern.match(lines[i]):
            return i
    return None


def find_section(lines: list[str], section: str) -> int | None:
    fm = frontmatter_range(lines)
    start = fm[1] + 1 if fm else 0
    for i in range(start, len(lines)):
        if lines[i].rstrip() == f"## {section}":
            return i
    return None


def validate(item, projects_dir: Path) -> str | None:
    """Return a reason string when the item is invalid, else None."""
    if not isinstance(item, dict):
        return "item is not an object"
    for key in COMMON_KEYS:
        if not isinstance(item.get(key), str) or not item[key]:
            return f"missing required key: {key}"
    kind = item["kind"]
    if kind not in KINDS:
        return f"kind must be one of {KINDS}"
    needed = ("section", "text") if kind == "append" else ("field", "value")
    for key in needed:
        if not isinstance(item.get(key), str) or not item[key].strip():
            return f"missing required key: {key}"
    if "/" in item["slug"] or item["slug"].startswith("."):
        return "invalid slug"
    path = projects_dir / f"{item['slug']}.md"
    if not path.is_file():
        return f"project file not found: {item['slug']}.md"
    lines = path.read_text(encoding="utf-8").split("\n")
    if kind == "append" and find_section(lines, item["section"]) is None:
        return f"heading not found: ## {item['section']}"
    if kind == "frontmatter" and find_field(lines, item["field"]) is None:
        return f"frontmatter field not found: {item['field']}"
    return None


def apply_append(lines: list[str], section: str, bullet: str) -> list[str]:
    head = find_section(lines, section)
    if head is None:
        raise ValueError(f"heading not found: ## {section}")
    end = len(lines)
    for i in range(head + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    last = head
    for i in range(head + 1, end):
        if lines[i].strip():
            last = i
    if last > head:
        return lines[: last + 1] + [bullet] + lines[last + 1 :]
    # A trailing "" from split("\n") is the file's final newline, not a blank line.
    real_end = end - 1 if end == len(lines) and lines[-1] == "" else end
    blank_follows = head + 1 < real_end and not lines[head + 1].strip()
    insert = ["", bullet] if blank_follows else [bullet]
    return lines[: head + 1] + insert + lines[head + 1 :]


def apply_frontmatter(lines: list[str], field: str, value: str) -> list[str]:
    idx = find_field(lines, field)
    if idx is None:
        raise ValueError(f"frontmatter field not found: {field}")
    indent = re.match(r"\s*", lines[idx]).group(0)
    out = list(lines)
    out[idx] = f"{indent}{field}: {value}"
    return out


def apply_proposal(prop: dict, projects_dir: Path, today: dt.date) -> None:
    path = projects_dir / f"{prop['slug']}.md"
    if not path.is_file():
        raise ValueError(f"project file not found: {prop['slug']}.md")
    lines = path.read_text(encoding="utf-8").split("\n")
    if prop["kind"] == "append":
        bullet = f"- {prop['text']} <!-- src: {prop['source']} -->"
        lines = apply_append(lines, prop["section"], bullet)
    else:
        lines = apply_frontmatter(lines, prop["field"], prop["value"])
    if find_field(lines, "last_reviewed") is not None:
        lines = apply_frontmatter(lines, "last_reviewed", today.isoformat())
    write_text_atomic(path, "\n".join(lines))


def cmd_add(args, state: Path, log: Path, projects_dir: Path) -> dict:
    items = json.load(sys.stdin)
    if not isinstance(items, list):
        print("error: stdin must be a JSON array", file=sys.stderr)
        sys.exit(2)
    pending = load_json_array(state)
    seen = {p["id"] for p in pending} | {p["id"] for p in load_json_array(log)}
    added, skipped = [], []
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i, item in enumerate(items):
        reason = validate(item, projects_dir)
        if reason:
            print(f"warning: item {i} skipped: {reason}", file=sys.stderr)
            skipped.append({"item_index": i, "reason": reason})
            continue
        pid = proposal_id(item)
        if pid in seen:
            skipped.append({"item_index": i, "reason": f"duplicate of {pid}"})
            continue
        reason = redundant_reason(item, pending, projects_dir)
        if reason:
            skipped.append({"item_index": i, "reason": f"duplicate: {reason}"})
            continue
        record = {"id": pid, **{k: item[k] for k in STORED_KEYS if k in item}, "created_at": now}
        pending.append(record)
        seen.add(pid)
        added.append(pid)
    if added:
        write_json_atomic(state, pending)
    return {"added": added, "skipped": skipped}


def cmd_list(args, state: Path, log: Path, projects_dir: Path) -> list:
    return load_json_array(state)


def cmd_resolve(args, state: Path, log: Path, projects_dir: Path) -> dict:
    accepting = args.command == "accept"
    pending = load_json_array(state)
    by_id = {p["id"]: p for p in pending}
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    done, unknown, failed = [], [], []
    resolved = []
    for pid in args.ids:
        prop = by_id.get(pid)
        if prop is None or pid in done:
            print(f"warning: unknown proposal id {pid}", file=sys.stderr)
            unknown.append(pid)
            continue
        if accepting:
            try:
                apply_proposal(prop, projects_dir, today)
            except (ValueError, OSError) as e:
                print(f"warning: could not apply {pid}: {e}", file=sys.stderr)
                failed.append(pid)
                continue
        resolved.append(
            {
                **prop,
                "outcome": "accepted" if accepting else "rejected",
                "resolved_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        done.append(pid)
    if resolved:
        write_json_atomic(log, load_json_array(log) + resolved)
        write_json_atomic(state, [p for p in pending if p["id"] not in set(done)])
    result = {"accepted" if accepting else "rejected": done, "unknown": unknown}
    if failed:
        result["failed"] = failed
    return result


def build_parser() -> argparse.ArgumentParser:
    def add_common(p: argparse.ArgumentParser, suppress: bool) -> None:
        d = argparse.SUPPRESS if suppress else None
        p.add_argument("--state", default=d or "~/morning/state/project-proposals.json")
        p.add_argument("--projects-dir", default=d or "~/product-os/projects")
        p.add_argument("--today", default=d, help=argparse.SUPPRESS)

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common(ap, suppress=False)
    ap.set_defaults(today=None)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("add")
    sub.add_parser("list")
    for name in ("accept", "reject"):
        p = sub.add_parser(name)
        p.add_argument("ids", nargs="+")
    for p in sub.choices.values():
        add_common(p, suppress=True)
    return ap


def main() -> None:
    args = build_parser().parse_args()
    state = Path(args.state).expanduser()
    log = state.parent / LOG_NAME
    projects_dir = Path(args.projects_dir).expanduser()
    handler = {"add": cmd_add, "list": cmd_list, "accept": cmd_resolve, "reject": cmd_resolve}[args.command]
    print(json.dumps(handler(args, state, log, projects_dir), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
