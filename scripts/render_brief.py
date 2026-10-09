#!/usr/bin/env python3
"""render_brief.py - turn the brief JSON into markdown, HTML and a number map.

Usage:
    python3 render_brief.py <brief.json> [--md OUT.md] [--shared-md OUT.md] [--html OUT.html] [--map OUT.json]
                           [--background PATH_OR_DIR]

The model writes the brief's content once as JSON (contract in
docs/plans/2026-10-01-brief-html-page.md). This script owns the numbering, so
the markdown archive, the page and the Step 7 tick-off map always agree.

--shared-md writes the same markdown as --md without the "External meeting
prep" section, which holds research on named external people and must not go
to a shared repo.

--background takes an image file, or a folder holding spring/summer/autumn/winter
.jpg/.jpeg/.webp/.png (the season comes from the brief's date). The image is
embedded in the HTML as a data: URI; a missing file means no background.

stdout: one JSON line of counts, e.g. {"urgent": 8, "overdue": 5, ...}, which
the skill prints as the chat header.

Exit codes: 0 ok, 1 invalid brief JSON, 2 bad args.
"""

from __future__ import annotations
import argparse
import base64
import copy
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "brief_template.html"
IDEA_BUCKETS = (("strategic", "Strategic"), ("other", "Operational"))
TAG_VERDICTS = ("needs-lena", "split", "handoff")
TAG_LABELS = {"needs-lena": "needs-Lena", "split": "split", "handoff": "handoff"}
BG_EXTS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".png": "image/png"}
BG_WARN_BYTES = 600 * 1024
ALPHA_NOTE = "Owner tags are alpha: a first guess at who could own each to-do, not yet reviewed."


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
    prs = brief.setdefault("prs", {})
    for k in ("review_requested", "ready", "awaiting"):
        prs.setdefault(k, [])
    actions = brief.setdefault("actions", {})
    actions.setdefault("yours", [])
    actions.setdefault("product", [])
    todos = brief.setdefault("todos", {})
    todos.setdefault("coming_up", [])
    brief.setdefault("testing", [])
    ideas = brief.setdefault("ideas", {})
    for k, _ in IDEA_BUCKETS:
        ideas.setdefault(k, [])
    for k in ("meetings", "projects", "partners"):
        brief.setdefault(k, [])
    brief.setdefault("team_sync_notes", "")
    for p in brief["projects"]:
        waiting = p.setdefault("waiting_on", [])
        name = p.get("name", "?")
        if not isinstance(waiting, list):
            raise ValueError(f"project '{name}' needs 'waiting_on' as a list")
        for w in waiting:
            if not isinstance(w, dict) or not isinstance(w.get("text"), str) or not w["text"].strip():
                raise ValueError(f"project '{name}' has a waiting_on entry without 'text'")
            if not isinstance(w.get("who", ""), str):
                raise ValueError(f"project '{name}' has a waiting_on entry whose 'who' is not a string")

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

    todo_groups(brief["urgent"])
    todo_groups(todos["coming_up"])
    action_list(actions["yours"])
    action_list(actions["product"])
    testing_list(brief["testing"])
    for k, _ in IDEA_BUCKETS:
        todo_groups(ideas[k])
    return brief, numbers


def has_tags(brief: dict) -> bool:
    """True when any to-do-like item in the brief carries a tag."""
    groups = brief["urgent"] + brief["todos"]["coming_up"] + [g for k, _ in IDEA_BUCKETS for g in brief["ideas"][k]]
    items = [i for g in groups for i in g.get("items", [])] + brief["actions"]["yours"] + brief["actions"]["product"]
    return any(i.get("tag") for i in items)


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
        note = goals.get("status_note", "").strip()
        L += [f"_Draft: {note}_" if note else "_Draft_", ""]
    for g in goals["goals"]:
        L += [f"- **{g['title']}**"]
        if g.get("why", "").strip():
            L += [f"  - Why: {g['why']}"]
        if g.get("done_when"):
            L += ["  - Done when:"] + [f"    - {x}" for x in g["done_when"]]
    L += [""]
    if goals.get("not_doing"):
        L += ["Not doing: " + "; ".join(x.rstrip(".") for x in goals["not_doing"]), ""]
    return L


def to_markdown(brief: dict, shared: bool = False) -> str:
    """Markdown archive. `shared` drops External meeting prep (research on named external people)."""
    L: list[str] = [f"# Morning brief - {brief['weekday_label']}", "",
                    f"> **Today's focus:** {brief['focus']}", ""]
    L += _goals_md(brief.get("goals"))
    for u in brief["unavailable"]:
        L += [f"_{u}_", ""]

    L += ["## To do", ""]
    if has_tags(brief):
        L += [f"_{ALPHA_NOTE}_", ""]
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
    if acts["product"]:
        L += ["**Product actions**", ""] + [x for a in acts["product"] for x in _action_line(a)] + [""]

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
        waiting = p.get("waiting_on", [])
        if waiting:
            L += [f"Waiting on others ({len(waiting)}):", ""]
            L += [f"- {w['text']} ({w['who']})" if w.get("who") else f"- {w['text']}" for w in waiting] + [""]
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


def to_html(brief: dict, background: Path | None = None) -> str:
    if has_tags(brief):
        brief = {**brief, "alpha_note": ALPHA_NOTE}
    data = json.dumps(brief, ensure_ascii=False).replace("<", "\\u003c")
    bg = json.dumps(background_data_uri(background)).replace("<", "\\u003c") if background else "null"
    return TEMPLATE.read_text().replace("/*__BG__*/null", bg).replace("/*__BRIEF_JSON__*/null", data)


def counts(brief: dict) -> dict:
    urgent_items = [i for g in brief["urgent"] for i in g.get("items", [])]
    return {
        "urgent": len(urgent_items),
        "overdue": sum(1 for i in urgent_items if str(i.get("due", "")).startswith("overdue")),
        "prs_review": len(brief["prs"]["review_requested"]),
        "prs_ready": len(brief["prs"]["ready"]),
        "prs_awaiting": len(brief["prs"]["awaiting"]),
        "coming_up": _count(brief["todos"]["coming_up"]),
        "actions": len(brief["actions"]["yours"]),
        "testing": len(brief["testing"]),
        "ideas": sum(_count(brief["ideas"][k]) for k, _ in IDEA_BUCKETS),
        "meetings": len(brief["meetings"]),
        "max_number": max([0] + [i["n"] for g in brief["urgent"] for i in g.get("items", [])]
                          + [a["n"] for a in brief["actions"]["yours"] + brief["actions"]["product"]]
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
        Path(args.html).expanduser().write_text(to_html(brief, pick_background(args.background, brief["date"])))
    if args.map:
        Path(args.map).expanduser().write_text(json.dumps({"date": brief["date"], "numbers": numbers}, indent=2))
    print(json.dumps(counts(brief)))


if __name__ == "__main__":
    main()
