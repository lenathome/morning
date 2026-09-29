#!/usr/bin/env python3
"""extract_sessions.py - condense recent Claude Code session transcripts into JSON.

Usage:
    python3 extract_sessions.py --since <ISO8601> [--projects-dir DIR] [--exclude-session ID]

Scans <projects-dir>/<project>/<session>.jsonl (default projects-dir:
~/.claude/projects). Only files directly inside an immediate subdirectory are read;
deeper files are subagent transcripts and are ignored. Files last modified before
--since are skipped without being opened.

Kept entries: timestamp strictly after --since and isSidechain not true. Kept
messages are assistant text blocks and genuine human user turns. A user entry is
a human turn only when its origin is human (or unset) and its text is not
machine-injected (see MACHINE_PREFIXES: task notifications, system reminders,
messages from other Claude sessions, agent messages, skill base-directory
banners, local-command and bash echoes, interrupt markers, app-quit notices).
Those are Claude- or harness-generated, not the user's words, so they are left
out of messages, human_turns and the started_at/ended_at range. Tool calls, tool
results and thinking blocks are dropped. Malformed lines are skipped.
scheduled_task, cwd and git_branch are still read from every user entry, so a
<scheduled-task name="..."> wrapper is detected even when its entry is not kept.

Output (stdout): JSON array sorted by started_at, one object per session:
    {session_id, cwd, git_branch, title, started_at, ended_at,
     scheduled_task, human_turns, messages: [{role, at, text}]}

Each message is truncated to 2000 chars. When a session's message text exceeds
40000 chars, the first 5 messages and as many of the last messages as fit are
kept, with a {"role": "note"} entry between them. Sessions with no human turn in
the window, and the --exclude-session session, are dropped.

Exit codes:
    0 = success (possibly [])
    2 = --since does not parse
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

MAX_MESSAGE_CHARS = 2000
MAX_SESSION_CHARS = 40000
KEEP_HEAD = 5
TRUNCATED_SUFFIX = "…[truncated]"
MACHINE_PREFIXES = (
    "<task-notification",
    "<system-reminder",
    "Another Claude session sent a message:",
    "<agent-message",
    "Base directory for this skill:",
    "<local-command-caveat>",
    "<command-name>",
    "<local-command-stdout>",
    "<bash-stdout>",
    "<bash-input>",
    "[Request interrupted by user",
    "The app was quit while you were working",
)
SCHEDULED_RE = re.compile(r'<scheduled-task name="([^"]*)"')


def parse_ts(value) -> dt.datetime | None:
    """Parse an ISO8601 string (Z or offset) to an aware datetime; naive means UTC."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def truncate(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS] + TRUNCATED_SUFFIX


def user_text(message: dict) -> str | None:
    """Return the text of a user message, or None for tool results / empty content."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            return None
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    text = "\n".join(parts).strip()
    return text or None


def assistant_text(message: dict) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    parts = [
        b["text"]
        for b in content
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
    ]
    text = "\n".join(parts).strip()
    return text or None


def is_human_origin(entry: dict) -> bool:
    turn_origin = entry.get("turnOrigin")
    origin = entry.get("origin")
    origin_kind = origin.get("kind") if isinstance(origin, dict) else None
    if turn_origin is None and origin_kind is None:
        return True
    return turn_origin == "human" or origin_kind == "human"


def is_machine_text(text: str) -> bool:
    return text.lstrip().startswith(MACHINE_PREFIXES)


def cap_session(messages: list[dict]) -> list[dict]:
    """Bound total text; keep the head and as many tail messages as fit."""
    if sum(len(m["text"]) for m in messages) <= MAX_SESSION_CHARS:
        return messages
    head = messages[:KEEP_HEAD]
    rest = messages[KEEP_HEAD:]
    budget = MAX_SESSION_CHARS - sum(len(m["text"]) for m in head)
    tail: list[dict] = []
    for m in reversed(rest):
        if len(m["text"]) > budget:
            break
        budget -= len(m["text"])
        tail.append(m)
    tail.reverse()
    omitted = len(rest) - len(tail)
    if omitted <= 0:
        return messages
    note = {"role": "note", "at": None, "text": f"[{omitted} messages omitted]"}
    return head + [note] + tail


def extract_file(path: Path, since: dt.datetime) -> dict | None:
    session = {
        "session_id": None,
        "cwd": None,
        "git_branch": None,
        "title": None,
        "started_at": None,
        "ended_at": None,
        "scheduled_task": None,
        "human_turns": 0,
        "messages": [],
    }
    first_dt = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            kind = entry.get("type")
            if kind == "custom-title":
                title = entry.get("customTitle") or entry.get("title")
                if isinstance(title, str) and title:
                    session["title"] = title
                continue
            if kind not in ("user", "assistant") or entry.get("isSidechain") is True:
                continue
            ts = parse_ts(entry.get("timestamp"))
            if ts is None or ts <= since:
                continue
            message = entry.get("message")
            if not isinstance(message, dict):
                continue
            if kind == "user":
                text = user_text(message)
            else:
                text = assistant_text(message)
            if text is None:
                continue
            if session["session_id"] is None and entry.get("sessionId"):
                session["session_id"] = entry["sessionId"]
            if kind == "user":
                if session["cwd"] is None and entry.get("cwd"):
                    session["cwd"] = entry["cwd"]
                if session["git_branch"] is None and entry.get("gitBranch"):
                    session["git_branch"] = entry["gitBranch"]
                if session["scheduled_task"] is None:
                    m = SCHEDULED_RE.search(text)
                    if m:
                        session["scheduled_task"] = m.group(1)
                if not is_human_origin(entry) or is_machine_text(text):
                    continue
                session["human_turns"] += 1
            raw_ts = entry["timestamp"]
            if first_dt is None or ts < first_dt:
                first_dt = ts
                session["started_at"] = raw_ts
            if session["ended_at"] is None or ts >= parse_ts(session["ended_at"]):
                session["ended_at"] = raw_ts
            session["messages"].append({"role": kind, "at": raw_ts, "text": truncate(text)})
    if session["human_turns"] == 0:
        return None
    if session["session_id"] is None:
        session["session_id"] = path.stem
    session["messages"] = cap_session(session["messages"])
    return session


def find_transcripts(projects_dir: Path, since: dt.datetime) -> list[Path]:
    since_epoch = since.timestamp()
    found = []
    for project in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        for path in sorted(project.glob("*.jsonl")):
            if path.is_file() and path.stat().st_mtime >= since_epoch:
                found.append(path)
    return found


def extract(projects_dir: Path, since: dt.datetime, exclude: str | None) -> list[dict]:
    if not projects_dir.is_dir():
        return []
    results = []
    for path in find_transcripts(projects_dir, since):
        session = extract_file(path, since)
        if session is None or (exclude and session["session_id"] == exclude):
            continue
        results.append(session)
    return sorted(results, key=lambda s: parse_ts(s["started_at"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True, help="ISO8601 timestamp; only later entries are kept")
    ap.add_argument("--projects-dir", default="~/.claude/projects")
    ap.add_argument("--exclude-session", default=None, help="session id to drop (the current session)")
    args = ap.parse_args()

    since = parse_ts(args.since)
    if since is None:
        print(f"error: cannot parse --since {args.since!r} as ISO8601", file=sys.stderr)
        sys.exit(2)
    sessions = extract(Path(args.projects_dir).expanduser(), since, args.exclude_session)
    print(json.dumps(sessions, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
