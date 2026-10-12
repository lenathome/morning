# Brief as a tabbed page - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the morning brief each day as one private, tabbed HTML page at a fixed claude.ai artifact URL. The chat gets a short header and the link in place of the full brief.

**Architecture:** The model stops writing markdown by hand. In Step 4 it writes the brief's content once as `~/morning/briefs/<date>.json`. A deterministic script, `scripts/render_brief.py`, numbers every actionable line and writes three things from that file: the markdown archive (same layout as today), the HTML page (a fixed template with the JSON embedded, rendered in the browser) and a number map in `~/morning/state/` that Step 7 reads when Lena replies with numbers. The model then publishes the HTML to the artifact URL stored in config. If publishing fails, it falls back to printing the markdown in full.

**Tech Stack:** Python 3 stdlib only (matches the other scripts), `unittest`, one self-contained HTML file with inline CSS and vanilla JS. No build step.

**Decisions taken (1 Oct 2026, Lena):**
- The chat gets a link, not the full brief. A short header stays inline so the brief still reads at a glance on a phone notification.
- The page is a claude.ai artifact (private by default), not a local file: one pinned URL, works on her phone too.
- Calendar: some non-ekko attendees are personal contacts, not external meetings (first case: a catch-up with an old colleague). Config gets an allowlist.

**Out of scope (later phase):** tick-off buttons on the page. They need the artifact to hold state and write back to Notion and Fathom. Ticking off stays in chat, by number, as now.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/fetch_calendar.py` (modify) | Third optional arg: comma-joined emails that never count as external |
| `scripts/render_brief.py` (create) | Validate brief JSON, number items, write `.md`, `.html` and the number map |
| `scripts/brief_template.html` (create) | The page. Reads the embedded JSON and renders tabs. No data logic beyond display |
| `tests/test_fetch_calendar.py` (create) | External-marking tests |
| `tests/test_render_brief.py` (create) | Numbering, markdown, map and HTML-injection tests |
| `tests/fixtures/brief-sample.json` (create) | Small realistic brief used by the tests |
| `skill/SKILL.md` (modify) | Step 1 calendar call, Step 4 writes JSON and runs the renderer, Step 6 publishes and prints the link, Step 7 reads the map |
| `config.example.yaml` (modify) | `calendar.internal_contacts`, `output.artifact_url` |
| `README.md` (modify) | One short section on the page |

Outside the repo, done by the main model (config files, not code): `~/morning/config.yaml`, `~/.claude/scheduled-tasks/morning-brief/SKILL.md` and the memory note on printing the brief inline.

---

## The brief JSON contract

Written by the model in Step 4. `render_brief.py` adds the `n` field to every actionable item; the model never numbers anything.

```json
{
  "date": "2026-10-01",
  "weekday_label": "Thursday 01 Oct 2026",
  "focus": "Prep the \"match my footprint\" Checkout SDK translations before anything else.",
  "unavailable": ["Fathom unavailable: <reason>"],
  "urgent": [
    {"parent": null, "items": [
      {"id": "3ecf93807de4816c8cbff4d851e840e3", "title": "Prep translations ...", "due": "due today", "categories": ["Operational"], "note": "",
       "tag": {"verdict": "needs-lena", "who": "", "why": "Sets the copy rules and signs off."}}
    ]},
    {"parent": "Moka launch actions (Lena)", "items": [
      {"id": "3dbf...", "title": "Chase Simon ...", "due": "overdue since 17 Sep", "categories": ["Operational"], "note": "",
       "tag": {"verdict": "split", "who": "Maria", "why": "Maria drafts, you sign off."}}
    ]}
  ],
  "prs": {
    "review_requested": [{"number": 5, "url": "https://github.com/...", "title": "...", "repo": "decision-log", "note": "opened by kurtwarwick-ekko, 3 days ago"}],
    "ready": [{"number": 1291, "url": "...", "title": "...", "repo": "ekko-api", "note": "stacked on #1290", "poke": false}],
    "awaiting": [{"number": 325, "url": "...", "title": "...", "repo": "ekko-v3-infra", "note": "1 reviewer, 0 days stale", "poke": false}]
  },
  "actions": {
    "yours": [{"key": "d7302bff0bb978c1", "text": "Schedule 1:1 w/ Maria re: priorities", "url": "https://fathom.video/calls/843538837?timestamp=656.9999", "meeting": "P&E team sync", "date": "30 Sep"}],
    "product": []
  },
  "todos": {
    "coming_up": [{"parent": null, "items": []}]
  },
  "testing": [
    {"repo": "ekko-checkout", "number": 142, "url": "https://github.com/...", "title": "...", "project": "Checkout translation pipeline",
     "merged": "1 Oct", "live": "dev, staging, prod", "steps": ["Open the staging checkout in tr-TR", "..."], "inferred": false}
  ],
  "ideas": {
    "strategic": [],
    "other": []
  },
  "meetings": [
    {"time": "16:30", "title": "Catch up", "company": "...", "participants": [{"name": "...", "role": "..."}], "notes": ["Your open Moka items are 4 to 8."]}
  ],
  "projects": [
    {"name": "PPP localisation", "slug": "ppp-localisation", "owner": "Etienne", "status": "active",
     "next": "...", "target": "2026-10-02", "summary": "...", "stale_note": "", "sync_note": "",
     "waiting_on": [{"text": "...", "who": "Simon and Baran"}],
     "github": {"line": "0 PRs merged in last 7 days, 7 open",
                "open": [{"number": 1258, "url": "...", "title": "...", "repo": "ekko-api", "state": "open", "updated": "yesterday"}]}}
  ],
  "partners": [{"name": "Zip", "owner": "Jamie", "status": "active", "next": "...", "target": ""}],
  "team_sync_notes": "..."
}
```

Rules the renderer enforces (raises `ValueError` with a clear message, exit code 1):
- Top-level keys `date`, `weekday_label`, `focus` are present and non-empty.
- Every to-do item has `id`; every action has `key`.
- Optional `testing` lists merged PRs Lena can test by hand. Every item has `repo`, `number`, `url` and `title`, and `steps` is a non-empty list of strings. `live` is free text ("not deployed yet" is allowed); `inferred` is true when the steps were written from the diff rather than the PR's test plan.
- Optional `waiting_on` on each project lists tasks that wait on other people: `[{"text": "...", "who": "Simon and Baran"}]`. Each entry needs a non-empty `text`; `who` is a string and may be empty. Entries are not numbered, not in the number map and not tick-off-able. Defaults to `[]`.
- Optional `tag` on every to-do-like item (the items in `urgent`, `todos.coming_up`, `ideas.strategic` and `ideas.other`, plus every entry in `actions.yours` and `actions.product`) says who should own it: `{"verdict": "needs-lena" | "split" | "handoff", "who": "<first name, empty for needs-lena>", "why": "<one short sentence>"}`. `verdict` must be one of the three; `split` and `handoff` need a non-empty `who`; `who` and `why` are strings. A bad tag exits 1 and names the item. Items without a tag render as before. Testing items carry no tag. The brief prints no note about the tags.
- Optional top-level `goals` is the output of `scripts/parse_goals.py` copied verbatim: `{"quarter": "Q4 2026", "status": "draft" | "agreed", "status_note": "...", "goals": [{"title": "...", "why": "...", "done_when": ["..."]}], "not_doing": ["..."]}`. `quarter` is non-empty, every goal has a non-empty `title`, `why` is a string, `done_when` and `not_doing` are lists of strings; a bad shape exits 1 and names the problem. Goals are context: not numbered, not in the number map, not tick-off-able. When `status` is not `agreed` the strip carries a Draft marker and the `status_note`. The markdown (`--md` and `--shared-md`) gets a `## <quarter> goals` section right after the focus line, as bullets so it cannot clash with the running numbers; the page gets a collapsible Goals block under the header, above the pill row. Without `goals` the brief renders as before.
- Optional top-level `in_progress` lists things already started that need keeping on. Each item is either a Notion task, the same shape as an item inside an `urgent` group (`id, title, due, categories, note, tag`) plus `"kind": "notion"`, or a Fathom action, the same shape as an `actions.yours` entry (`key, text, url, meeting, date, tag`) plus `"kind": "fathom"`. A notion item needs `id`, a fathom item needs `key`, `kind` must be one of the two, and `tag` follows the tag rule above; a bad shape exits 1 and names the problem. Items are numbered first and mapped with their kind. Absent or empty means no section, and the brief renders as before. The markdown gets a `**In progress**` sub-heading before **Urgent today** under `## To do` (`--md` and `--shared-md`), with the same line format as the matching urgent task or action. On the page, the To do tab shows In progress beside the rest of To do from 1100px wide (to-do content on the left, 3fr; In progress pinned on the right, 2fr); below 1100px In progress is the first section of the To do panel. Without in-progress items the To do content takes the full width. The To do pill counts In progress at every width. The page header is full width (up to 1240px) and holds the date and title, the goals strip and the sticky pill row. Tabs, in order: To do, PRs, Testing, Ideas bank, Projects, Clients (the `partners` list, titled Partners - next actions). A tab with nothing in it gets no pill, except To do.
- Missing lists default to empty. Missing optional strings default to `""`.

Tag legend (the same wording lives in `skill/SKILL.md`): needs-Lena = product judgement, sign-off or a relationship only you hold; split = someone else does the legwork, you decide or sign off; handoff = someone else can own it end to end.

Markdown shows a tag as ` [needs-Lena]`, ` [split: Maria]` or ` [handoff: Kurt]` at the end of the item line, with the `why` on the next line as an indented italic line. The page shows it as a small pill with the `why` as a muted line under the item.

`render_brief.py --shared-md <path>` writes the same markdown as `--md` without the External meeting prep section, so the copy can go to a shared repo. Numbering is unchanged.

`render_brief.py --background <file or folder>` embeds a seasonal photo behind the page header. A file is used as is; a folder gives `<season>.<ext>` by the brief's `date` month (Mar-May spring, Jun-Aug summer, Sep-Nov autumn, Dec-Feb winter). The image goes into the HTML only, as a `data:` URI in a second JSON script tag (`bg-data`). A missing file or option means no photo, and a file over 600KB prints a warning to run `scripts/prep_background.sh`.

Bucket meaning: `urgent` is every to-do due today or overdue. `todos.coming_up` is every to-do due after today, ordered by due date. `ideas` holds every to-do with no due date: `ideas.strategic` when `Category` contains Strategic, `ideas.other` for the rest.

Numbering order, following the page: `in_progress` (in the order given), `urgent` (groups in the order given), `todos.coming_up`, `actions.yours`, `actions.product`, `testing`, `ideas.strategic`, `ideas.other`. A testing item's map entry is `{"kind": "test", "key": "<repo>#<number>"}`. The model is responsible for the order within each list (standalone first, then parent groups alphabetically), exactly as the current skill describes.

---

### Task 1: Calendar contacts that are never external

**Files:**
- Modify: `scripts/fetch_calendar.py`
- Test: `tests/test_fetch_calendar.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_calendar.py"
sys.path.insert(0, str(SCRIPT.parent))
import fetch_calendar  # noqa: E402


def ev(*emails):
    return {"title": "x", "attendees": [{"name": "", "email": e} for e in emails]}


class MarkExternalTest(unittest.TestCase):
    def test_outside_domain_is_external(self):
        events = [ev("you@ekko.earth", "alex.smith@agency.example.org")]
        fetch_calendar.mark_external(events, "@ekko.earth", [])
        self.assertTrue(events[0]["is_external"])

    def test_internal_contact_is_not_external(self):
        events = [ev("pat.jones@partner.example.com")]
        fetch_calendar.mark_external(events, "@ekko.earth", ["pat.jones@partner.example.com"])
        self.assertFalse(events[0]["is_external"])

    def test_contact_match_ignores_case_and_spaces(self):
        events = [ev("Pat.Jones@Partner.Example.com")]
        fetch_calendar.mark_external(events, "@ekko.earth", [" pat.jones@partner.example.com "])
        self.assertFalse(events[0]["is_external"])

    def test_contact_plus_real_external_is_still_external(self):
        events = [ev("pat.jones@partner.example.com", "robin.lee@agency.example.org")]
        fetch_calendar.mark_external(events, "@ekko.earth", ["pat.jones@partner.example.com"])
        self.assertTrue(events[0]["is_external"])

    def test_parse_contacts_arg(self):
        self.assertEqual(fetch_calendar.parse_contacts("a@x.com, B@y.com,,"), ["a@x.com", "b@y.com"])
        self.assertEqual(fetch_calendar.parse_contacts(""), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m unittest tests.test_fetch_calendar -v`
Expected: FAIL, `AttributeError: module 'fetch_calendar' has no attribute 'mark_external'`

- [ ] **Step 3: Implement**

In `scripts/fetch_calendar.py`, add above `main()`:

```python
def parse_contacts(arg: str) -> list[str]:
    """Comma-joined emails -> lowercased list, blanks dropped."""
    return [e.strip().lower() for e in arg.split(",") if e.strip()]


def mark_external(events: list[dict], ekko_domain: str, internal_contacts: list[str]) -> None:
    """Set is_external: any attendee outside the domain who is not a known personal contact."""
    contacts = {c.strip().lower() for c in internal_contacts}
    for e in events:
        e["is_external"] = any(
            a["email"]
            and not a["email"].lower().endswith(ekko_domain.lower())
            and a["email"].lower() not in contacts
            for a in e["attendees"]
        )
```

In `main()`, read the third arg and replace the inline marking loop:

```python
    primary_calendar = sys.argv[2] if len(sys.argv) > 2 else None
    internal_contacts = parse_contacts(sys.argv[3]) if len(sys.argv) > 3 else []
```

```python
    events = parse_agenda(result.stdout, today_d.year)
    mark_external(events, ekko_domain, internal_contacts)
    print(json.dumps(events, indent=2))
```

Update the module docstring usage line to `python3 fetch_calendar.py <ekko_email_domain> [<primary_calendar>] [<internal_contacts comma-joined>]` and add one sentence: "Attendees in <internal_contacts> are personal contacts and never make a meeting external."

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_calendar.py tests/test_fetch_calendar.py
git commit -m "feat(calendar): personal contacts never make a meeting external"
```

---

### Task 2: Renderer - numbering, markdown and number map

**Files:**
- Create: `scripts/render_brief.py`
- Create: `tests/fixtures/brief-sample.json`
- Test: `tests/test_render_brief.py`

- [ ] **Step 1: Create the fixture**

`tests/fixtures/brief-sample.json`:

```json
{
  "date": "2026-10-01",
  "weekday_label": "Thursday 01 Oct 2026",
  "focus": "Ship the thing.",
  "unavailable": [],
  "urgent": [
    {"parent": null, "items": [
      {"id": "p1", "title": "Standalone urgent", "due": "due today", "categories": ["Operational"], "note": ""}
    ]},
    {"parent": "Moka launch actions (Lena)", "items": [
      {"id": "p2", "title": "Chase Simon", "due": "overdue since 17 Sep", "categories": ["Operational"], "note": ""}
    ]}
  ],
  "prs": {
    "review_requested": [],
    "ready": [{"number": 1291, "url": "https://github.com/ekko-enviroconomy/ekko-api/pull/1291", "title": "fix(funds): convert unit prices", "repo": "ekko-api", "note": "stacked on #1290", "poke": false}],
    "awaiting": [{"number": 325, "url": "https://github.com/ekko-enviroconomy/ekko-v3-infra/pull/325", "title": "DNS <records>", "repo": "ekko-v3-infra", "note": "1 reviewer, 6 days stale", "poke": true}]
  },
  "actions": {
    "yours": [{"key": "k1", "text": "Email Jamie", "url": "https://fathom.video/calls/1?timestamp=2", "meeting": "P&E team sync", "date": "25 Sep"}],
    "product": [{"key": "k2", "text": "Schedule officers' call", "url": "https://fathom.video/calls/3?timestamp=4", "meeting": "P&E team sync", "date": "30 Sep"}]
  },
  "todos": {
    "this_week": [{"parent": null, "items": [{"id": "p3", "title": "Revisit round-up", "due": "due 2 Oct", "categories": ["Operational"], "note": ""}]}],
    "strategic": [{"parent": null, "items": [{"id": "p4", "title": "Travel calculator", "due": "", "categories": ["Strategic"], "note": ""}]}],
    "later": [{"parent": "Public documentation", "items": [{"id": "p5", "title": "Link to methodology PDFs", "due": "", "categories": ["Operational"], "note": ""}]}]
  },
  "meetings": [{"time": "16:30", "title": "Partner call", "company": "Acme - payments", "participants": [{"name": "Jo Bloggs", "role": "likely Head of Product"}], "notes": []}],
  "projects": [{"name": "PPP localisation", "slug": "ppp-localisation", "owner": "Etienne", "status": "active", "next": "Flag on", "target": "2026-10-02", "summary": "Bilo is finishing the move.", "stale_note": "", "sync_note": "",
    "github": {"line": "0 PRs merged in last 7 days, 1 open", "open": [{"number": 1258, "url": "https://github.com/ekko-enviroconomy/ekko-api/pull/1258", "title": "feat(ppp): drop the gate", "repo": "ekko-api", "state": "open", "updated": "yesterday"}]}}],
  "partners": [{"name": "Zip", "owner": "Jamie", "status": "active", "next": "Get a live date", "target": ""}],
  "team_sync_notes": "SDK moves to one skeleton loader."
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_render_brief.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "render_brief.py"
FIXTURE = ROOT / "tests" / "fixtures" / "brief-sample.json"
sys.path.insert(0, str(SCRIPT.parent))
import render_brief  # noqa: E402


def load():
    return json.loads(FIXTURE.read_text())


class NumberingTest(unittest.TestCase):
    def test_running_sequence_across_sections(self):
        brief, numbers = render_brief.number_items(load())
        self.assertEqual(brief["urgent"][0]["items"][0]["n"], 1)
        self.assertEqual(brief["urgent"][1]["items"][0]["n"], 2)
        self.assertEqual(brief["actions"]["yours"][0]["n"], 3)
        self.assertEqual(brief["actions"]["product"][0]["n"], 4)
        self.assertEqual(brief["todos"]["this_week"][0]["items"][0]["n"], 5)
        self.assertEqual(brief["todos"]["strategic"][0]["items"][0]["n"], 6)
        self.assertEqual(brief["todos"]["later"][0]["items"][0]["n"], 7)

    def test_number_map(self):
        _, numbers = render_brief.number_items(load())
        self.assertEqual(numbers["1"], {"kind": "notion", "id": "p1"})
        self.assertEqual(numbers["3"], {"kind": "fathom", "key": "k1"})
        self.assertEqual(len(numbers), 7)

    def test_missing_lists_default_to_empty(self):
        _, numbers = render_brief.number_items({"date": "d", "weekday_label": "w", "focus": "f"})
        self.assertEqual(numbers, {})

    def test_missing_focus_is_rejected(self):
        with self.assertRaises(ValueError):
            render_brief.number_items({"date": "d", "weekday_label": "w", "focus": ""})

    def test_todo_without_id_is_rejected(self):
        b = load()
        del b["urgent"][0]["items"][0]["id"]
        with self.assertRaises(ValueError):
            render_brief.number_items(b)


class MarkdownTest(unittest.TestCase):
    def setUp(self):
        brief, _ = render_brief.number_items(load())
        self.md = render_brief.to_markdown(brief)

    def test_header_and_focus(self):
        self.assertTrue(self.md.startswith("# Morning brief - Thursday 01 Oct 2026\n"))
        self.assertIn("> **Today's focus:** Ship the thing.", self.md)

    def test_parent_group_has_blank_lines_around_italic_name(self):
        self.assertIn("\n*Moka launch actions (Lena):*\n\n2. Chase Simon (overdue since 17 Sep)  [Operational]\n", self.md)

    def test_pr_line_and_poke(self):
        self.assertIn("- [#1291](https://github.com/ekko-enviroconomy/ekko-api/pull/1291) fix(funds): convert unit prices (ekko-api) - stacked on #1290", self.md)
        self.assertIn("- ⚡ [#325](", self.md)

    def test_action_line(self):
        self.assertIn('3. [Email Jamie](https://fathom.video/calls/1?timestamp=2) (from "P&E team sync", 25 Sep)', self.md)

    def test_no_em_dash(self):
        self.assertNotIn("—", self.md)

    def test_empty_your_actions_says_clean_slate(self):
        b = load()
        b["actions"]["yours"] = []
        brief, _ = render_brief.number_items(b)
        self.assertIn("Nothing carrying over on your own actions. Clean slate.", render_brief.to_markdown(brief))


class HtmlTest(unittest.TestCase):
    def test_json_is_embedded_and_script_safe(self):
        brief, _ = render_brief.number_items(load())
        html = render_brief.to_html(brief)
        self.assertIn('id="brief-data"', html)
        self.assertNotIn("DNS <records>", html)          # raw < must not reach the page
        self.assertIn("DNS \\u003crecords>", html)
        self.assertIn("<title>Morning brief</title>", html)


class CliTest(unittest.TestCase):
    def test_writes_three_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = subprocess.run(
                [sys.executable, str(SCRIPT), str(FIXTURE),
                 "--md", str(d / "b.md"), "--html", str(d / "b.html"), "--map", str(d / "m.json")],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((d / "b.md").read_text().startswith("# Morning brief"))
            self.assertIn("brief-data", (d / "b.html").read_text())
            m = json.loads((d / "m.json").read_text())
            self.assertEqual(m["date"], "2026-10-01")
            self.assertEqual(m["numbers"]["7"], {"kind": "notion", "id": "p5"})
            self.assertIn('"urgent": 2', r.stdout)

    def test_bad_input_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text('{"date": "d"}')
            r = subprocess.run([sys.executable, str(SCRIPT), str(bad), "--md", str(Path(d) / "x.md")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("weekday_label", r.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run and confirm failure**

Run: `python3 -m unittest tests.test_render_brief -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'render_brief'`

- [ ] **Step 4: Implement `scripts/render_brief.py`**

```python
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
```

`to_html` needs the template file to exist, so create a minimal stub now (Task 3 replaces it):

`scripts/brief_template.html`:

```html
<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Morning brief</title></head>
<body><script id="brief-data" type="application/json">/*__BRIEF_JSON__*/null</script></body></html>
```

Note: the JSON goes inside `<script type="application/json">`, so `JSON.parse(el.textContent)` reads it back; `<` decodes to `<` there, which is why the escape is safe and lossless.

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/render_brief.py scripts/brief_template.html tests/test_render_brief.py tests/fixtures/brief-sample.json
git commit -m "feat(brief): render the brief from JSON with one numbering for md, page and tick-off"
```

---

### Task 3: The page

**Files:**
- Modify: `scripts/brief_template.html` (replace the stub)

Load the `artifact-design` skill before writing this file and follow its page contract. Fixed requirements:

- `<title>Morning brief</title>`. The data block stays exactly `<script id="brief-data" type="application/json">/*__BRIEF_JSON__*/null</script>`.
- Colour tokens on `:root`, redefined under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])` and under `:root[data-theme="dark"]`. `body` has an explicit background.
- No external scripts. Fonts only from Google Fonts, or the system stack.
- Works at 375px wide: 16px side gutter, no horizontal scroll, tabs scroll sideways inside their own bar if they don't fit.
- All text inserted with `textContent` or a tiny `el()` helper, never `innerHTML` with data (titles contain `<`, quotes, Turkish characters).
- No em dashes anywhere in fixed copy.

Layout:

1. **Header**: date, the focus sentence large, then a row of counter chips: `Urgent N` (with `N overdue` in the warning colour when > 0), `PRs to chase N`, `Your actions N`, `Meetings N`. Chips are buttons that switch to the matching tab. Any `unavailable` lines show as a muted banner under the counters.
2. **Tabs** (buttons with `role="tab"`, `aria-selected`; the selected tab is remembered in `localStorage` inside try/catch, default `Today`):
   - **Today**: Urgent today (numbered rows, parent groups as a small caps label), Your actions (numbered, text links to Fathom, meeting + date muted), External meeting prep cards.
   - **PRs**: Review requested, Ready to merge, Awaiting review. One card per PR: `#number` + title as the link, repo as a tag, note muted, `⚡` badge when `poke`.
   - **To-dos**: This week, Strategic, Later with counts, then Product actions. Same row style as Today.
   - **Projects**: a filter row (All / Active / Blocked / Waiting). One card per project: name, status pill (active green, blocked red, waiting amber), owner, `next`, target date. Clicking the card expands `summary`, the `waiting_on` list, `stale_note`, `sync_note` and the open PR list (`<details>` is fine). Team sync notes as a card at the top. Partners as a compact table at the bottom.
3. Every numbered row shows its number in a fixed-width column so Lena can read numbers back into chat.
4. Empty sections are hidden. An entirely empty tab shows one muted line ("Nothing here today.").

- [ ] **Step 1: Write the template** following the above.

- [ ] **Step 2: Render the fixture and check it in the browser**

Run: `python3 scripts/render_brief.py tests/fixtures/brief-sample.json --html /tmp/brief-check.html`
Open `/tmp/brief-check.html` in the preview browser. Check: all four tabs render, counters switch tabs, the `<records>` title shows literally, number column aligns, dark mode (`resize_window colorScheme: dark`) and mobile preset (375px) with no horizontal scroll. Fix and repeat.

- [ ] **Step 3: Run the tests**

Run: `python3 -m unittest discover -s tests -v`
Expected: all pass (`HtmlTest` still finds `brief-data` and the `<title>`).

- [ ] **Step 4: Commit**

```bash
git add scripts/brief_template.html
git commit -m "feat(brief): tabbed page with counters, projects behind their own tab"
```

---

### Task 4: Skill and config wiring

**Files:**
- Modify: `skill/SKILL.md`
- Modify: `config.example.yaml`
- Modify: `README.md`

- [ ] **Step 1: `config.example.yaml`**

Under `calendar:` add:

```yaml
  # Personal contacts outside the ekko domain (old colleagues, friends). A
  # meeting with only these people plus ekko colleagues is not external, so it
  # gets no company research and no prep block.
  internal_contacts: []
```

Under `output:` add:

```yaml
  # claude.ai artifact the brief page is published to every morning. Leave
  # empty for the first run; the skill prints the new URL to paste here.
  artifact_url: ""
```

- [ ] **Step 2: `skill/SKILL.md` Step 1.2** - change the calendar call to pass the contacts:

`python3 ~/github/morning/scripts/fetch_calendar.py "<ekko_email_domain>" "<primary_calendar>" "<calendar.internal_contacts comma-joined, or empty string>"`

- [ ] **Step 3: `skill/SKILL.md` Step 4** - replace "Use the voice guide... continued in part 2" with:

> Write the brief's content as JSON to `<briefs_dir>/<YYYY-MM-DD>.json`, following the contract in `docs/plans/2026-10-01-brief-html-page.md` (section "The brief JSON contract"). Do not number anything: the renderer does. Put every list in final display order (standalone tasks first, then parent groups alphabetically). Apply the voice guide to every string you write. Then run:
>
> `python3 ~/github/morning/scripts/render_brief.py <briefs_dir>/<date>.json --md <briefs_dir>/<date>.md --html <briefs_dir>/<date>.html --map ~/morning/state/brief-map-<date>.json`
>
> It prints one JSON line of counts; keep it for Step 6. If it exits 1, fix the JSON it names and run it again.

Keep the "Brief structure" section and its rules: they still define what goes in each list. Retitle the template block "Markdown archive layout (produced by render_brief.py)".

- [ ] **Step 4: `skill/SKILL.md` Step 6** - replace with:

> 1. Publish `<briefs_dir>/<date>.html` with the Artifact tool. If `output.artifact_url` is set: first `read` that URL (a publish to an artifact this conversation hasn't read is refused), then publish with `url` set to it, no `icon`. If it is empty: publish without `url`, with `icon: "calendar"` and `description: "Lena's daily morning brief"`, and tell Lena to paste the returned URL into `output.artifact_url` in `~/morning/config.yaml`.
> 2. Print only this in chat:
>    - `**<weekday_label>** - <focus>`
>    - one line of counters from the renderer: `Urgent N (M overdue) · PRs: R to review, K ready, A awaiting · Your actions N · Meetings N` (drop any part that is 0, except Urgent)
>    - the artifact link
>    - `Saved: <briefs_dir>/<date>.md`
> 3. If publishing fails for any reason, say so in one line and print the full markdown archive inline instead, verbatim. Lena must never end up with neither.

- [ ] **Step 5: `skill/SKILL.md` Step 7** - in item 4, replace "look it up in the running number→item map you built while rendering" with "look it up in `~/morning/state/brief-map-<date>.json` (`numbers[<n>]` gives `{kind: notion, id}` or `{kind: fathom, key}`); drop numbers above `max_number` from the renderer's counts".

- [ ] **Step 6: README** - add under the layout section:

```markdown
## The page

Step 4 writes the brief as JSON; `scripts/render_brief.py` numbers it and writes the markdown archive, a tabbed HTML page and the tick-off map. Step 6 publishes the page to the artifact URL in `output.artifact_url` and prints only the focus, counters and the link. Ticking off stays in chat, by number.
```

- [ ] **Step 7: Check the skill reads cleanly**

Read `skill/SKILL.md` top to bottom once. Every step refers to files and keys that exist after Tasks 1 to 3; no step still says "print the ENTIRE brief". Run `python3 -m unittest discover -s tests -v`; expected all pass.

- [ ] **Step 8: Commit**

```bash
git add skill/SKILL.md config.example.yaml README.md
git commit -m "feat(morning): publish the brief as a page and print a link"
```

---

### Task 5: Local config, scheduled prompt and memory (main model only)

Not in the repo, not delegated.

- [ ] `~/morning/config.yaml`: add `calendar.internal_contacts: ["pat.jones@partner.example.com"]` and `output.artifact_url: ""`.
- [ ] `~/.claude/scheduled-tasks/morning-brief/SKILL.md`: change "print the ENTIRE brief inline in the chat, never condensed and never replaced with a pointer to the file" to "publish the page and print the header, counters and link (Step 6); print the full brief inline only if publishing fails". Add to "Needed approval" guidance: list any Artifact call that prompted.
- [ ] Memory `feedback_brief_numbered_lists.md`: replace "always print the full brief inline" with the link decision (1 Oct 2026) and its reason. Update the `MEMORY.md` line.

---

### Task 6: End-to-end check and PR

- [ ] **Step 1:** Write today's real brief (2026-10-01) as JSON from the data already fetched this session and run the renderer into a scratch folder. Diff the generated markdown against `~/morning/briefs/2026-10-01.md`: section order, numbering 1 to 39 and the PR lines must match. Wording differences are fine.
- [ ] **Step 2:** Publish the HTML as the first artifact. Put the URL into `output.artifact_url`.
- [ ] **Step 3:** Check the published page in the browser: light, dark, 375px. Screenshot for Lena.
- [ ] **Step 4:** Rebase on `origin/main` (`git fetch origin main && git rebase origin/main`), run the full test suite, push `feature/brief-html` and open the PR with the `pr-description` skill.
- [ ] **Step 5:** After merge, the symlinked skill in `~/.claude/skills/morning` picks it up from `~/github/morning` main. Pull main there before the next 09:00 run.

---

## Risks

- **Unattended publish may prompt.** The Artifact publish at 09:00 runs with no one present. If it needs approval it will stall; the fallback prints the markdown, and the run lists the call under "Needed approval" so the allowlist can be fixed.
- **Contents on claude.ai.** The page holds client names, Fathom action text and PR titles. It is private to Lena's account by default and is never shared. Nothing new leaves ekko's existing tools apart from this page.
- **Model-written JSON can be malformed.** The renderer validates and names the bad field; the skill tells the model to fix and rerun.
