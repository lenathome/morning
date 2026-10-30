#!/usr/bin/env python3
"""render_brief.py - turn the brief JSON into markdown, HTML and a number map.

Usage:
    python3 render_brief.py <brief.json> [--md OUT.md] [--shared-md OUT.md] [--html OUT.html] [--map OUT.json]
                           [--background PATH_OR_DIR] [--triage TRIAGE.json]

The model writes the brief's content once as JSON (contract in
docs/plans/2026-10-01-brief-html-page.md). This script owns the numbering, so
the markdown archive, the page and the Step 7 tick-off map always agree.

--shared-md writes the same markdown as --md without the "External meeting
prep" section, which holds research on named external people and must not go
to a shared repo.

--background takes an image file, or a folder holding spring/summer/autumn/winter
.jpg/.jpeg/.webp/.png (the season comes from the brief's date). The image is
embedded in the HTML as a data: URI; a missing file means no background.

--triage takes the file triage_from_notion.py wrote (~/morning/state/triage-<date>.json,
read from the Notion triage database)
and joins it onto the Testing items by `repo#number`, for the page only: the
markdown and the shared markdown never carry triage data (product-os#5, rule 6).
An item with no match gets "No triage today". A missing or unreadable file, or
a run for another date, means no triage on the page at all.

stdout: one JSON line of counts, e.g. {"urgent": 8, "overdue": 5, ...}, which
the skill prints as the chat header.

Exit codes: 0 ok, 1 invalid brief JSON, 2 bad args.
"""

from __future__ import annotations
import argparse
import base64
import copy
import json
import re
import sys
from datetime import datetime
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "brief_template.html"
IDEA_BUCKETS = (("strategic", "Strategic"), ("other", "Operational"))
TAG_VERDICTS = ("needs-lena", "split", "handoff")
TAG_LABELS = {"needs-lena": "needs-Lena", "split": "split", "handoff": "handoff"}
BG_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".png": "image/png"}
BG_WARN_BYTES = 600 * 1024
DRIFT_CHANGES = ("removed", "added")
DRIFT_STATUSES = ("stale", "upload_pending", "draft")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def check_tag(item: dict, label: str) -> None:
    """Validate the optional `tag` on a to-do-like item. `label` names the item in errors."""
    if "tag" not in item or item["tag"] is None:
        return
    tag = item["tag"]
    if not isinstance(tag, dict):
        raise ValueError(f"{label} has a 'tag' that is not an object")
    verdict = tag.get("verdict")
    if verdict not in TAG_VERDICTS:
        raise ValueError(f"{label} has an unknown tag verdict {verdict!r} (use {', '.join(TAG_VERDICTS)})")
    for k in ("who", "why"):
        if not isinstance(tag.get(k, ""), str):
            raise ValueError(f"{label} has a tag whose '{k}' is not a string")
    if verdict != "needs-lena" and not tag.get("who", "").strip():
        raise ValueError(f"{label} has a '{verdict}' tag with no 'who'")


def check_goals(goals) -> None:
    """Validate the optional top-level `goals` object (the output of parse_goals.py)."""
    if not isinstance(goals, dict):
        raise ValueError("'goals' is not an object")
    for k in ("quarter", "status", "status_note"):
        if not isinstance(goals.get(k, ""), str):
            raise ValueError(f"goals '{k}' is not a string")
    if not goals.get("quarter", "").strip():
        raise ValueError("goals is missing 'quarter'")
    for k in ("goals", "not_doing"):
        if not isinstance(goals.get(k, []), list):
            raise ValueError(f"goals '{k}' is not a list")
    for g in goals.get("goals", []):
        if not isinstance(g, dict) or not isinstance(g.get("title"), str) or not g["title"].strip():
            raise ValueError("a goal has no 'title'")
        if not isinstance(g.get("why", ""), str):
            raise ValueError(f"goal '{g['title']}' has a 'why' that is not a string")
        done = g.get("done_when", [])
        if not isinstance(done, list) or not all(isinstance(x, str) for x in done):
            raise ValueError(f"goal '{g['title']}' needs 'done_when' as a list of strings")
    if not all(isinstance(x, str) for x in goals.get("not_doing", [])):
        raise ValueError("goals 'not_doing' needs a list of strings")


def number_items(raw: dict) -> tuple[dict, dict]:
    """Validate, fill defaults and add a running `n` to every actionable item."""
    for k in ("date", "weekday_label", "focus"):
        if not str(raw.get(k, "")).strip():
            raise ValueError(f"brief is missing '{k}'")
    if raw.get("goals") is not None:
        check_goals(raw["goals"])
    brief = copy.deepcopy(raw)
    brief.setdefault("unavailable", [])
    brief.setdefault("urgent", [])
    in_progress = brief.get("in_progress")
    if in_progress is None:
        in_progress = brief["in_progress"] = []
    if not isinstance(in_progress, list):
        raise ValueError("'in_progress' is not a list")
    prs = brief.setdefault("prs", {})
    for k in ("review_requested", "ready", "awaiting"):
        prs.setdefault(k, [])
    actions = brief.setdefault("actions", {})
    actions.setdefault("yours", [])
    if actions.get("product"):
        raise ValueError("actions.product moved to 'waiting'")
    actions.pop("product", None)
    todos = brief.setdefault("todos", {})
    todos.setdefault("coming_up", [])
    brief.setdefault("testing", [])
    if brief.get("docs_drift") is None:
        brief["docs_drift"] = []
    waiting = brief.get("waiting")
    if waiting is None:
        waiting = brief["waiting"] = []
    if not isinstance(waiting, list):
        raise ValueError("'waiting' is not a list")
    ideas = brief.setdefault("ideas", {})
    for k, _ in IDEA_BUCKETS:
        ideas.setdefault(k, [])
    for k in ("meetings", "projects", "partners"):
        brief.setdefault(k, [])
    brief.setdefault("team_sync_notes", "")
    for p in brief["projects"]:
        if p.get("waiting_on"):
            raise ValueError(f"project '{p.get('name', '?')}' has 'waiting_on', which moved to 'waiting'")
        p.pop("waiting_on", None)

    numbers: dict[str, dict] = {}
    n = 0

    def todo_groups(groups: list) -> None:
        nonlocal n
        for g in groups:
            for item in g.get("items", []):
                if not item.get("id"):
                    raise ValueError(f"to-do '{item.get('title', '?')}' has no 'id'")
                check_tag(item, f"to-do '{item.get('title', '?')}'")
                n += 1
                item["n"] = n
                numbers[str(n)] = {"kind": "notion", "id": item["id"]}

    def action_list(items: list) -> None:
        nonlocal n
        for a in items:
            if not a.get("key"):
                raise ValueError(f"action '{a.get('text', '?')}' has no 'key'")
            check_tag(a, f"action '{a.get('text', '?')}'")
            n += 1
            a["n"] = n
            numbers[str(n)] = {"kind": "fathom", "key": a["key"]}

    def waiting_list(items: list) -> None:
        nonlocal n
        for i, w in enumerate(items, 1):
            if not isinstance(w, dict):
                raise ValueError(f"waiting item {i} is not an object")
            label = f"waiting item '{w.get('text', '?')}'"
            if not isinstance(w.get("text"), str) or not w["text"].strip():
                raise ValueError(f"waiting item {i} has no 'text'")
            kind = w.get("kind")
            if kind == "notion":
                if not w.get("id"):
                    raise ValueError(f"{label} has no 'id'")
                ref = {"kind": "notion", "id": w["id"], "waiting": True}
            elif kind == "fathom":
                if not w.get("key"):
                    raise ValueError(f"{label} has no 'key'")
                ref = {"kind": "fathom", "key": w["key"], "waiting": True}
            else:
                raise ValueError(f"{label} has an unknown kind {kind!r} (use notion or fathom)")
            for k in ("who", "url", "project"):
                if w.get(k) is None:
                    w[k] = ""
                if not isinstance(w[k], str):
                    raise ValueError(f"{label} has a '{k}' that is not a string")
            if not _is_date(w.get("since")):
                raise ValueError(f"{label} needs 'since' as YYYY-MM-DD")
            days = w.get("days")
            if isinstance(days, bool) or not isinstance(days, int) or days < 0:
                raise ValueError(f"{label} needs 'days' as an integer of 0 or more")
            if not isinstance(w.get("chase"), bool):
                raise ValueError(f"{label} needs 'chase' as true or false")
            if w.setdefault("chase_reason", None) is not None and not isinstance(w["chase_reason"], str):
                raise ValueError(f"{label} has a 'chase_reason' that is not a string or null")
            if w.setdefault("chased_on", None) is not None and not _is_date(w["chased_on"]):
                raise ValueError(f"{label} needs 'chased_on' as YYYY-MM-DD or null")
            n += 1
            w["n"] = n
            numbers[str(n)] = ref

    def testing_list(items: list) -> None:
        nonlocal n
        for t in items:
            ref = f"{t.get('repo', '?')}#{t.get('number', '?')}"
            for k in ("repo", "number", "url", "title"):
                if not t.get(k):
                    raise ValueError(f"testing item '{ref}' has no '{k}'")
            steps = t.get("steps")
            if not isinstance(steps, list) or not steps or not all(isinstance(x, str) and x.strip() for x in steps):
                raise ValueError(f"testing item '{ref}' needs 'steps' as a non-empty list of strings")
            n += 1
            t["n"] = n
            numbers[str(n)] = {"kind": "test", "key": f"{t['repo']}#{t['number']}"}

    def in_progress_list(items: list) -> None:
        nonlocal n
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ValueError(f"in_progress item {i} is not an object")
            kind = item.get("kind")
            if kind == "notion":
                label = f"in_progress to-do '{item.get('title', '?')}'"
                if not item.get("id"):
                    raise ValueError(f"{label} has no 'id'")
                ref = {"kind": "notion", "id": item["id"]}
            elif kind == "fathom":
                label = f"in_progress action '{item.get('text', '?')}'"
                if not item.get("key"):
                    raise ValueError(f"{label} has no 'key'")
                ref = {"kind": "fathom", "key": item["key"]}
            else:
                raise ValueError(f"in_progress item {i} has an unknown kind {kind!r} (use notion or fathom)")
            check_tag(item, label)
            n += 1
            item["n"] = n
            numbers[str(n)] = ref

    def draft_item(d: dict) -> None:
        """A hand-listed doc draft: no path, change or pr. Needs title, branch, doc.url, first_seen and age_days."""
        label = f"docs_drift draft '{d.get('title', '?')}'"
        for k in ("title", "branch"):
            if not isinstance(d.get(k), str) or not d[k].strip():
                raise ValueError(f"{label} needs a non-empty '{k}'")
        if not isinstance(d.get("doc"), dict) or not d["doc"].get("url"):
            raise ValueError(f"{label} needs 'doc.url'")
        if d.get("waiting_on") is not None and not isinstance(d["waiting_on"], str):
            raise ValueError(f"{label} needs 'waiting_on' as a string or null")
        if not _is_date(d.get("first_seen")):
            raise ValueError(f"{label} needs 'first_seen' as YYYY-MM-DD")
        age = d.get("age_days")
        if isinstance(age, bool) or not isinstance(age, int) or age < 0:
            raise ValueError(f"{label} needs 'age_days' as an integer, 0 or more")

    def docs_drift_list(items) -> None:
        """Validate only: drift items are never numbered and never enter the number map."""
        if not isinstance(items, list):
            raise ValueError("'docs_drift' is not a list")
        for i, d in enumerate(items, 1):
            if not isinstance(d, dict):
                raise ValueError(f"docs_drift item {i} is not an object")
            if d.get("status") == "draft":
                draft_item(d)
                continue
            label = f"docs_drift item '{d.get('path', '?')}'"
            for k in ("path", "change", "pr", "doc", "live_url", "status", "live_checked", "first_seen", "age_days"):
                if k not in d:
                    raise ValueError(f"{label} has no '{k}'")
            if not isinstance(d["path"], str) or not d["path"].strip():
                raise ValueError(f"{label} has an empty 'path'")
            if d["change"] not in DRIFT_CHANGES:
                raise ValueError(f"{label} has an unknown change {d['change']!r} (use removed or added)")
            if d["status"] not in DRIFT_STATUSES:
                raise ValueError(f"{label} has an unknown status {d['status']!r} (use stale, upload_pending or draft)")
            if not isinstance(d["live_checked"], bool):
                raise ValueError(f"{label} needs 'live_checked' as true or false")
            for obj, keys in (("pr", ("repo", "number", "url", "merged")), ("doc", ("file", "line", "url"))):
                if not isinstance(d[obj], dict):
                    raise ValueError(f"{label} needs '{obj}' as an object")
                for k in keys:
                    if k not in d[obj]:
                        raise ValueError(f"{label} has no '{obj}.{k}'")
            for k in ("repo", "url"):
                if not d["pr"][k]:
                    raise ValueError(f"{label} has an empty 'pr.{k}'")
            if not d["pr"]["number"]:
                raise ValueError(f"{label} has an empty 'pr.number'")
            if not _is_date(d["pr"]["merged"]):
                raise ValueError(f"{label} needs 'pr.merged' as YYYY-MM-DD")
            for k in ("file", "url"):
                if not d["doc"][k]:
                    raise ValueError(f"{label} has an empty 'doc.{k}'")
            line = d["doc"]["line"]
            if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
                raise ValueError(f"{label} needs 'doc.line' as a positive integer or null")
            if d["live_checked"] and not d["live_url"]:
                raise ValueError(f"{label} has no 'live_url'")
            if not _is_date(d["first_seen"]):
                raise ValueError(f"{label} needs 'first_seen' as YYYY-MM-DD")
            if isinstance(d["age_days"], bool) or not isinstance(d["age_days"], int) or d["age_days"] < 0:
                raise ValueError(f"{label} needs 'age_days' as an integer, 0 or more")

    in_progress_list(brief["in_progress"])
    todo_groups(brief["urgent"])
    todo_groups(todos["coming_up"])
    action_list(actions["yours"])
    waiting_list(brief["waiting"])
    testing_list(brief["testing"])
    docs_drift_list(brief["docs_drift"])
    for k, _ in IDEA_BUCKETS:
        todo_groups(ideas[k])
    return brief, numbers


def _is_date(value) -> bool:
    """True for a YYYY-MM-DD string that is a real date."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _short_date(value: str) -> str:
    """'2026-10-27' -> '27 Oct' (no leading zero on the day)."""
    y, m, d = value.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]}"


def _age_text(days: int) -> str:
    if days == 0:
        return "since today"
    return "waiting 1 day" if days == 1 else f"waiting {days} days"


def _drift_age(days: int) -> str:
    if days == 0:
        return "today"
    return "1 day" if days == 1 else f"{days} days"


def _drift_line(d: dict) -> str:
    if d["status"] == "draft":
        waiting = f", waiting on {d['waiting_on']}" if d.get("waiting_on") else ""
        return f"- Draft ready: [{d['title']}]({d['doc']['url']}) on `{d['branch']}`{waiting} ({_drift_age(d['age_days'])})"
    pr, doc = d["pr"], d["doc"]
    base = doc["file"].rsplit("/", 1)[-1]
    pr_link = f"[{pr['repo']}#{pr['number']}]({pr['url']})"
    when = _short_date(pr["merged"])
    live = d["live_checked"]
    plain = f"[{base}]({doc['url']})"
    located = f"[{base}:{doc['line']}]({doc['url']})" if doc.get("line") else plain
    live_link = f"[live page]({d['live_url']})"
    head = f"- `{d['path']}` was {d['change']} in {pr_link} ({when})"
    if d["change"] == "removed" and d["status"] == "stale":
        text = head + (f" but {located} and the {live_link} still show it." if live
                       else f" but {located} still shows it.")
    elif d["change"] == "removed":
        text = head + f". Fixed in {plain}, upload to ReadMe pending"
        text += f": the {live_link} still shows it." if live else "."
    elif d["status"] == "stale":
        text = head + f" and isn't in {plain} yet."
    else:
        text = head + f". It's in {plain}, upload to ReadMe pending."
    age = _drift_age(d["age_days"])
    text += f" {age.capitalize()}." if age == "today" else f" {age}."
    return text if live else text + " (live page not checked)"


def _waiting_for(brief: dict, project_name: str) -> list[dict]:
    return [w for w in brief["waiting"] if w.get("project") == project_name]


def _waiting_line(w: dict) -> str:
    chase = w["chase"]
    text = f"[{w['text']}]({w['url']})" if w.get("url") else w["text"]
    who = f" ({w['who']})" if w.get("who") else ""
    age = _age_text(w["days"])
    out = f"{w['n']}. {'⚡ ' if chase else ''}{text}{who} - {age}"
    if chase and w.get("chase_reason") and w["chase_reason"] != age:
        out += f"; {w['chase_reason']}"
    if w.get("chased_on"):
        out += f"; chased {_short_date(w['chased_on'])}"
    return out


def _tag_suffix(item: dict) -> str:
    tag = item.get("tag")
    if not tag:
        return ""
    verdict = tag["verdict"]
    who = f": {tag['who'].strip()}" if verdict != "needs-lena" else ""
    return f" [{TAG_LABELS[verdict]}{who}]"


def _tag_why(item: dict) -> list[str]:
    """The why line under a tagged item, indented to sit inside the numbered item."""
    tag = item.get("tag")
    if not tag or not tag.get("why", "").strip():
        return []
    return [" " * len(f"{item['n']}. ") + f"*{tag['why'].strip()}*"]


def _todo_line(item: dict, show_tags: bool = True) -> list[str]:
    due = f" ({item['due']})" if item.get("due") else ""
    cats = f"  [{', '.join(item.get('categories', []))}]" if show_tags and item.get("categories") else ""
    note = f" ({item['note']})" if item.get("note") else ""
    return [f"{item['n']}. {item['title']}{due}{cats}{note}{_tag_suffix(item)}"] + _tag_why(item)


def _todo_groups_md(groups: list, show_tags: bool = True) -> list[str]:
    out: list[str] = []
    for g in groups:
        if g.get("parent"):
            out += [f"*{g['parent']}:*", ""]
        for i in g.get("items", []):
            out += _todo_line(i, show_tags)
        out.append("")
    return out


def _pr_line(pr: dict) -> str:
    poke = "⚡ " if pr.get("poke") else ""
    note = f" - {pr['note']}" if pr.get("note") else ""
    return f"- {poke}[#{pr['number']}]({pr['url']}) {pr['title']} ({pr['repo']}){note}"


def _action_line(a: dict) -> list[str]:
    head = f"{a['n']}. [{a['text']}]({a['url']}) (from \"{a['meeting']}\", {a['date']}){_tag_suffix(a)}"
    return [head] + _tag_why(a)


def _testing_md(t: dict) -> list[str]:
    where = f"{t['repo']}, {t['project']}" if t.get("project") else t["repo"]
    head = f"{t['n']}. [#{t['number']}]({t['url']}) {t['title']} ({where})"
    if t.get("merged"):
        head += f" - merged {t['merged']}"
    if t.get("live"):
        head += f", live: {t['live']}" if t.get("merged") else f" - live: {t['live']}"
    out = [head] + [f"   - {s}" for s in t["steps"]]
    if t.get("inferred"):
        out.append("   - (steps inferred from the diff)")
    return out


def _count(groups: list) -> int:
    return sum(len(g.get("items", [])) for g in groups)


def _goals_md(goals: dict | None) -> list[str]:
    """The goals strip. Bullets, not a numbered list, so it never clashes with the running item numbers."""
    if not goals or not goals.get("goals"):
        return []
    L = [f"## {goals['quarter']} goals", ""]
    if goals.get("status", "") != "agreed":
        L += ["_Draft_", ""]
    for g in goals["goals"]:
        L += [f"- **{g['title']}**"]
        if g.get("why", "").strip():
            L += [f"  - Why: {g['why']}"]
        if g.get("done_when"):
            L += ["  - Done when:"] + [f"    - {x}" for x in g["done_when"]]
    L += [""]
    return L


def to_markdown(brief: dict, shared: bool = False) -> str:
    """Markdown archive. `shared` drops External meeting prep (research on named external people)."""
    L: list[str] = [f"# Morning brief - {brief['weekday_label']}", "",
                    f"> **Today's focus:** {brief['focus']}", ""]
    L += _goals_md(brief.get("goals"))
    for u in brief["unavailable"]:
        L += [f"_{u}_", ""]

    L += ["## To do", ""]
    if brief["in_progress"]:
        L += ["**In progress**", ""]
        for i in brief["in_progress"]:
            L += _action_line(i) if i["kind"] == "fathom" else _todo_line(i)
        L += [""]
    if brief["urgent"]:
        L += ["**Urgent today**", ""] + _todo_groups_md(brief["urgent"])
    coming = brief["todos"]["coming_up"]
    if _count(coming):
        L += [f"**Coming up** - {_count(coming)}", ""] + _todo_groups_md(coming)
    acts = brief["actions"]
    L += ["**Your actions**", ""]
    if acts["yours"]:
        L += [x for a in acts["yours"] for x in _action_line(a)] + [""]
    else:
        L += ["Nothing carrying over on your own actions. Clean slate.", ""]
    if brief["waiting"]:
        L += ["**Waiting for others**", ""] + [_waiting_line(w) for w in brief["waiting"]] + [""]

    if brief["docs_drift"]:
        L += ["## Docs behind code", ""] + [_drift_line(d) for d in brief["docs_drift"]]
        L += ["", "Fix with /ekko-api-docs, then upload to ReadMe.", ""]

    if brief["meetings"] and not shared:
        L += ["## External meeting prep", ""]
        for m in brief["meetings"]:
            L += [f"**{m['time']} - {m['title']}**", f"- Company: {m.get('company', '')}", "- Participants:"]
            L += [f"  - {p['name']} - {p['role']}" for p in m.get("participants", [])]
            L += [f"- {x}" for x in m.get("notes", [])] + [""]

    prs = brief["prs"]
    L += ["## PRs needing you", ""]
    if prs["review_requested"]:
        L += [f"**Review requested of you** ({len(prs['review_requested'])}):", ""]
        L += [_pr_line(p) for p in prs["review_requested"]] + [""]
    if prs["ready"] or prs["awaiting"]:
        L += ["**Yours to chase**", ""]
        if prs["ready"]:
            L += [f"Ready to merge ({len(prs['ready'])}):", ""] + [_pr_line(p) for p in prs["ready"]] + [""]
        if prs["awaiting"]:
            L += [f"Awaiting review ({len(prs['awaiting'])}):", ""] + [_pr_line(p) for p in prs["awaiting"]] + [""]
    if not any(prs.values()):
        L += ["Nothing waiting on you. Nice.", ""]

    if brief["testing"]:
        L += ["## Testing", ""]
        for t in brief["testing"]:
            L += _testing_md(t)
        L += [""]

    if any(_count(brief["ideas"][k]) for k, _ in IDEA_BUCKETS):
        L += ["## Ideas bank", ""]
        for key, label in IDEA_BUCKETS:
            groups = brief["ideas"][key]
            if _count(groups):
                L += [f"**{label}** - {_count(groups)}", ""] + _todo_groups_md(groups, show_tags=False)

    L += ["## Engineering progress", ""]
    for p in brief["projects"]:
        head = f"**{p['name']}** - {p['owner']}, {p['status']}"
        if p.get("next"):
            head += f", next: {p['next']}"
        if p.get("target"):
            head += f", target {p['target']}"
        L += [head, "", p.get("summary", ""), ""]
        waiting = _waiting_for(brief, p["name"])
        if waiting:
            L += [f"Waiting for others: {len(waiting)} (in To do)", ""]
        if p.get("stale_note"):
            L += [p["stale_note"], ""]
        if p.get("sync_note"):
            L += [p["sync_note"], ""]
        gh = p.get("github", {})
        L += [f"GitHub: {gh.get('line', '')}"]
        if gh.get("open"):
            L += ["- Open PRs:"]
            L += [f"  - [#{x['number']}]({x['url']}) {x['title']} ({x['repo']}) - {x['state']}, updated {x['updated']}"
                  for x in gh["open"]]
        L += [""]
    if brief["team_sync_notes"]:
        L += [f"Team sync notes: {brief['team_sync_notes']}", ""]
    if brief["partners"]:
        L += ["**Partners - next actions**", ""]
        for x in brief["partners"]:
            status = f", {x['status']}" if x.get("status") and x["status"] != "active" else ""
            target = f", target {x['target']}" if x.get("target") else ""
            L += [f"- **{x['name']}** ({x['owner']}{status}): {x['next']}{target}"]
        L += [""]
    return "\n".join(L).rstrip() + "\n"


def season_for(date_str: str) -> str:
    """Season for a YYYY-MM-DD date: Mar-May spring, Jun-Aug summer, Sep-Nov autumn, Dec-Feb winter."""
    month = int(str(date_str).split("-")[1])
    if not 1 <= month <= 12:
        raise ValueError(f"bad month in date {date_str!r}")
    return ("winter", "spring", "summer", "autumn")[(month % 12) // 3]


def pick_background(path: str | None, date_str: str) -> Path | None:
    """The background image to use, or None. A file is used as is; a folder gives <season>.<ext>."""
    if not path:
        return None
    p = Path(path).expanduser()
    if p.is_file():
        return p if p.suffix.lower() in BG_EXTS else None
    if p.is_dir():
        try:
            season = season_for(date_str)
        except (ValueError, IndexError):
            return None
        for ext in BG_EXTS:
            candidate = p / f"{season}{ext}"
            if candidate.is_file():
                return candidate
    return None


def background_data_uri(image: Path) -> str:
    """The image as a data: URI. Warns on stderr above BG_WARN_BYTES."""
    raw = image.read_bytes()
    if len(raw) > BG_WARN_BYTES:
        print(f"warning: background {image} is {len(raw) // 1024}KB; run scripts/prep_background.sh "
              f"to shrink it (the page embeds it)", file=sys.stderr)
    mime = BG_EXTS[image.suffix.lower()]
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def join_triage(brief: dict, triage: dict | None) -> dict:
    """A copy of the brief with the triage joined onto its Testing items, for the page only.

    The data is copied as is and never followed: the page shows it with
    textContent and links only through safeUrl()."""
    out = copy.deepcopy(brief)
    ok = (isinstance(triage, dict) and triage.get("status") == "ok" and triage.get("valid_for") == brief.get("date")
          and isinstance(triage.get("prs"), dict))
    if not out.get("testing"):
        return out
    if not ok:
        status = str(triage.get("status") or "unavailable") if isinstance(triage, dict) else "unavailable"
        out["triage"] = {"status": "stale" if status == "ok" else status}
        return out
    withheld = set(triage.get("withheld") or [])
    trial = triage.get("trial") if isinstance(triage.get("trial"), dict) else None
    notes = triage.get("group_notes")
    if not (isinstance(notes, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in notes.items())):
        notes = {}
    out["triage"] = {"status": "ok", "run_id": triage.get("run_id"), "trial": trial, "group_notes": notes,
                     "withheld": sorted(withheld)}
    for t in out["testing"]:
        key = f"{t['repo']}#{t['number']}"
        pr = triage["prs"].get(key)
        if isinstance(pr, dict):
            t["triage"] = pr
        elif key in withheld:
            t["triage_note"] = "Triage withheld: it held something that should not be there"
        else:
            t["triage_note"] = "No triage today"
    return out


def load_triage(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {"status": "unavailable"}
    return data if isinstance(data, dict) else {"status": "unavailable"}


def to_html(brief: dict, background: Path | None = None) -> str:
    data = json.dumps(brief, ensure_ascii=False).replace("<", "\\u003c")
    bg = json.dumps(background_data_uri(background)).replace("<", "\\u003c") if background else "null"
    return TEMPLATE.read_text().replace("/*__BG__*/null", bg).replace("/*__BRIEF_JSON__*/null", data)


def counts(brief: dict) -> dict:
    urgent_items = [i for g in brief["urgent"] for i in g.get("items", [])]
    return {
        "in_progress": len(brief["in_progress"]),
        "urgent": len(urgent_items),
        "overdue": sum(1 for i in urgent_items if str(i.get("due", "")).startswith("overdue")),
        "prs_review": len(brief["prs"]["review_requested"]),
        "prs_ready": len(brief["prs"]["ready"]),
        "prs_awaiting": len(brief["prs"]["awaiting"]),
        "coming_up": _count(brief["todos"]["coming_up"]),
        "actions": len(brief["actions"]["yours"]),
        "waiting": len(brief["waiting"]),
        "waiting_chase": sum(1 for w in brief["waiting"] if w["chase"]),
        "testing": len(brief["testing"]),
        "docs_drift": len(brief["docs_drift"]),
        "ideas": sum(_count(brief["ideas"][k]) for k, _ in IDEA_BUCKETS),
        "meetings": len(brief["meetings"]),
        "max_number": max([0] + [i["n"] for i in brief["in_progress"]]
                          + [i["n"] for g in brief["urgent"] for i in g.get("items", [])]
                          + [a["n"] for a in brief["actions"]["yours"]]
                          + [w["n"] for w in brief["waiting"]]
                          + [i["n"] for g in brief["todos"]["coming_up"] for i in g.get("items", [])]
                          + [t["n"] for t in brief["testing"]]
                          + [i["n"] for k, _ in IDEA_BUCKETS for g in brief["ideas"][k] for i in g.get("items", [])]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("--md")
    ap.add_argument("--shared-md")
    ap.add_argument("--html")
    ap.add_argument("--map")
    ap.add_argument("--background")
    ap.add_argument("--triage")
    args = ap.parse_args()
    try:
        brief, numbers = number_items(json.loads(Path(args.brief).read_text()))
    except (ValueError, json.JSONDecodeError) as e:
        print(f"invalid brief: {e}", file=sys.stderr)
        sys.exit(1)
    if args.md:
        Path(args.md).expanduser().write_text(to_markdown(brief))
    if args.shared_md:
        Path(args.shared_md).expanduser().write_text(to_markdown(brief, shared=True))
    if args.html:
        page = join_triage(brief, load_triage(args.triage)) if args.triage else brief
        Path(args.html).expanduser().write_text(to_html(page, pick_background(args.background, brief["date"])))
    if args.map:
        Path(args.map).expanduser().write_text(json.dumps({"date": brief["date"], "numbers": numbers}, indent=2))
    print(json.dumps(counts(brief)))


if __name__ == "__main__":
    main()
