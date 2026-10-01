#!/usr/bin/env python3
"""render_brief.py - turn the brief JSON into markdown, HTML and a number map.

Usage:
    python3 render_brief.py <brief.json> [--md OUT.md] [--html OUT.html] [--map OUT.json]

The model writes the brief's content once as JSON (contract in
docs/plans/2026-10-01-brief-html-page.md). This script owns the numbering, so
the markdown archive, the page and the Step 7 tick-off map always agree.

stdout: one JSON line of counts, e.g. {"urgent": 8, "overdue": 5, ...}, which
the skill prints as the chat header.

Exit codes: 0 ok, 1 invalid brief JSON, 2 bad args.
"""

from __future__ import annotations
import argparse
import copy
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "brief_template.html"
TODO_BUCKETS = (("this_week", "This week"), ("strategic", "Strategic"), ("later", "Later"))


def number_items(raw: dict) -> tuple[dict, dict]:
    """Validate, fill defaults and add a running `n` to every actionable item."""
    for k in ("date", "weekday_label", "focus"):
        if not str(raw.get(k, "")).strip():
            raise ValueError(f"brief is missing '{k}'")
    brief = copy.deepcopy(raw)
    brief.setdefault("unavailable", [])
    brief.setdefault("urgent", [])
    prs = brief.setdefault("prs", {})
    for k in ("review_requested", "ready", "awaiting"):
        prs.setdefault(k, [])
    actions = brief.setdefault("actions", {})
    actions.setdefault("yours", [])
    actions.setdefault("product", [])
    todos = brief.setdefault("todos", {})
    for k, _ in TODO_BUCKETS:
        todos.setdefault(k, [])
    for k in ("meetings", "projects", "partners"):
        brief.setdefault(k, [])
    brief.setdefault("team_sync_notes", "")

    numbers: dict[str, dict] = {}
    n = 0

    def todo_groups(groups: list) -> None:
        nonlocal n
        for g in groups:
            for item in g.get("items", []):
                if not item.get("id"):
                    raise ValueError(f"to-do '{item.get('title', '?')}' has no 'id'")
                n += 1
                item["n"] = n
                numbers[str(n)] = {"kind": "notion", "id": item["id"]}

    def action_list(items: list) -> None:
        nonlocal n
        for a in items:
            if not a.get("key"):
                raise ValueError(f"action '{a.get('text', '?')}' has no 'key'")
            n += 1
            a["n"] = n
            numbers[str(n)] = {"kind": "fathom", "key": a["key"]}

    todo_groups(brief["urgent"])
    action_list(actions["yours"])
    action_list(actions["product"])
    for k, _ in TODO_BUCKETS:
        todo_groups(todos[k])
    return brief, numbers


def _todo_line(item: dict) -> str:
    due = f" ({item['due']})" if item.get("due") else ""
    cats = f"  [{', '.join(item.get('categories', []))}]" if item.get("categories") else ""
    note = f" ({item['note']})" if item.get("note") else ""
    return f"{item['n']}. {item['title']}{due}{cats}{note}"


def _todo_groups_md(groups: list) -> list[str]:
    out: list[str] = []
    for g in groups:
        if g.get("parent"):
            out += [f"*{g['parent']}:*", ""]
        out += [_todo_line(i) for i in g.get("items", [])]
        out.append("")
    return out


def _pr_line(pr: dict) -> str:
    poke = "⚡ " if pr.get("poke") else ""
    note = f" - {pr['note']}" if pr.get("note") else ""
    return f"- {poke}[#{pr['number']}]({pr['url']}) {pr['title']} ({pr['repo']}){note}"


def _action_line(a: dict) -> str:
    return f"{a['n']}. [{a['text']}]({a['url']}) (from \"{a['meeting']}\", {a['date']})"


def _count(groups: list) -> int:
    return sum(len(g.get("items", [])) for g in groups)


def to_markdown(brief: dict) -> str:
    L: list[str] = [f"# Morning brief - {brief['weekday_label']}", "",
                    f"> **Today's focus:** {brief['focus']}", ""]
    for u in brief["unavailable"]:
        L += [f"_{u}_", ""]

    if brief["urgent"]:
        L += ["## Urgent today", ""] + _todo_groups_md(brief["urgent"])

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

    acts = brief["actions"]
    L += ["## Open action items", "", "**Your actions**", ""]
    if acts["yours"]:
        L += [_action_line(a) for a in acts["yours"]] + [""]
    else:
        L += ["Nothing carrying over on your own actions. Clean slate.", ""]
    if acts["product"]:
        L += ["**Product actions**", ""] + [_action_line(a) for a in acts["product"]] + [""]

    L += ["## To-dos", ""]
    for key, label in TODO_BUCKETS:
        groups = brief["todos"][key]
        if _count(groups):
            L += [f"**{label}** - {_count(groups)}", ""] + _todo_groups_md(groups)

    if brief["meetings"]:
        L += ["## External meeting prep", ""]
        for m in brief["meetings"]:
            L += [f"**{m['time']} - {m['title']}**", f"- Company: {m.get('company', '')}", "- Participants:"]
            L += [f"  - {p['name']} - {p['role']}" for p in m.get("participants", [])]
            L += [f"- {x}" for x in m.get("notes", [])] + [""]

    L += ["## Engineering progress", ""]
    for p in brief["projects"]:
        head = f"**{p['name']}** - {p['owner']}, {p['status']}"
        if p.get("next"):
            head += f", next: {p['next']}"
        if p.get("target"):
            head += f", target {p['target']}"
        L += [head, "", p.get("summary", ""), ""]
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


def to_html(brief: dict) -> str:
    data = json.dumps(brief, ensure_ascii=False).replace("<", "\\u003c")
    return TEMPLATE.read_text().replace("/*__BRIEF_JSON__*/null", data)


def counts(brief: dict) -> dict:
    urgent_items = [i for g in brief["urgent"] for i in g.get("items", [])]
    return {
        "urgent": len(urgent_items),
        "overdue": sum(1 for i in urgent_items if str(i.get("due", "")).startswith("overdue")),
        "prs_review": len(brief["prs"]["review_requested"]),
        "prs_ready": len(brief["prs"]["ready"]),
        "prs_awaiting": len(brief["prs"]["awaiting"]),
        "actions": len(brief["actions"]["yours"]),
        "meetings": len(brief["meetings"]),
        "max_number": max([0] + [i["n"] for g in brief["urgent"] for i in g.get("items", [])]
                          + [a["n"] for a in brief["actions"]["yours"] + brief["actions"]["product"]]
                          + [i["n"] for k, _ in TODO_BUCKETS for g in brief["todos"][k] for i in g.get("items", [])]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("brief")
    ap.add_argument("--md")
    ap.add_argument("--html")
    ap.add_argument("--map")
    args = ap.parse_args()
    try:
        brief, numbers = number_items(json.loads(Path(args.brief).read_text()))
    except (ValueError, json.JSONDecodeError) as e:
        print(f"invalid brief: {e}", file=sys.stderr)
        sys.exit(1)
    if args.md:
        Path(args.md).expanduser().write_text(to_markdown(brief))
    if args.html:
        Path(args.html).expanduser().write_text(to_html(brief))
    if args.map:
        Path(args.map).expanduser().write_text(json.dumps({"date": brief["date"], "numbers": numbers}, indent=2))
    print(json.dumps(counts(brief)))


if __name__ == "__main__":
    main()
