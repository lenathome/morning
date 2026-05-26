# Morning Tool MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/morning` Claude Code skill that produces a daily morning brief covering to-dos (from a new 7-property Notion DB), calendar with external meeting prep, engineering progress per initiative (enriched with Fathom standup notes), GitHub items awaiting input, yesterday's meetings, open action items with interactive tick-off, To Do page triage with interactive add-to-DB or skip-forever, strategic-slot fit, and a one-sentence focus.

**Architecture:** A Claude Code skill (markdown orchestrator at `skill/SKILL.md`) calls a small set of deterministic helper scripts in parallel for data fetch (calendar, GitHub, initiatives parsing, gap computation) and state management (action-item acknowledgment, triage state). The skill uses Notion MCP for to-dos AND for creating triaged items in the new DB, Fathom MCP for meeting summaries and action items, and Claude's WebSearch / WebFetch for external meeting research. Claude synthesises the brief in the user's voice, saves it to `~/morning/briefs/YYYY-MM-DD.md`, then runs three sequential interactive prompts: action-item tick-off, triage Stage 1 (list & select), triage Stage 2 (per-item Q&A). All state stored in `~/morning/state/`. Local-only — no daemon, no database.

**Tech Stack:** Bash, Python 3, `gh` CLI, `gcalcli`, Notion MCP, Fathom MCP, Claude Code WebSearch / WebFetch.

**Spec:** [docs/specs/2026-05-26-morning-tool-design.md](../specs/2026-05-26-morning-tool-design.md)

**Testing approach:** Per the spec — no unit tests for v1. Each task ends with a smoke verification step (run it, inspect output). Add tests in v2 if helpers stabilise.

---

## Prerequisites (manual, before Task 1)

These cannot be automated and must be done by the user before the first task. The executor should confirm each is in place before starting.

| # | Prerequisite | How to verify |
|---|---|---|
| 1 | `gh` CLI authenticated to GitHub | `gh auth status` returns "Logged in to github.com as lenathome" |
| 2 | Notion MCP configured in Claude Code | `notion-search` tool works in a Claude Code session |
| 3 | Fathom MCP configured in Claude Code | `list_meetings` tool works in a Claude Code session |
| 4 | `gcalcli` installed and OAuth'd | `gcalcli list` shows the calendars |
| 5 | Python 3.10+ available | `python3 --version` returns 3.10 or higher |
| 6 | `pyyaml` installed | `python3 -c "import yaml"` succeeds — install via `python3 -m pip install --user pyyaml` if missing |

Note: the Notion **Tasks database** is *not* a prerequisite — it's created in Task 3, Step 3 via the Notion MCP. The existing "To Do" page stays untouched.

If any prerequisite is missing, install commands:

```bash
brew install gcalcli
gcalcli init                                    # browser OAuth flow
python3 -m pip install --user pyyaml
```

---

## File structure after this plan

```
~/github/morning/
├── .gitignore                                  # exists
├── README.md                                   # exists
├── config.example.yaml                         # NEW (Task 3)
├── initiatives.example.md                      # NEW (Task 4)
├── docs/
│   ├── specs/2026-05-26-morning-tool-design.md # exists
│   └── plans/2026-05-26-morning-tool-mvp.md    # this file
├── skill/
│   └── SKILL.md                                # NEW (Tasks 9, 10)
└── scripts/
    ├── fetch_calendar.py                       # NEW (Task 5)
    ├── fetch_github.sh                         # NEW (Task 6)
    ├── parse_initiatives.py                    # NEW (Task 7)
    ├── compute_gaps.py                         # NEW (Task 8)
    ├── ack_action.py                           # NEW (Task 11)
    └── triage_state.py                         # NEW (Task 12)
```

Per-machine state lives outside the repo:

```
~/morning/
├── config.yaml                                 # gitignored — copy of config.example.yaml with real values
├── initiatives.md                              # live initiatives index, user-maintained
├── briefs/
│   └── 2026-05-26.md                           # daily output
└── state/
    ├── acknowledged-actions.json               # Fathom action-item hashes that have been ticked off
    └── triaged-items.json                      # To Do page bullets added-to-DB or skipped-forever
```

---

## Task 1: Create feature branch and scaffold directories

**Files:**
- Create: `~/github/morning/scripts/.gitkeep`
- Create: `~/github/morning/skill/.gitkeep`

- [ ] **Step 1: Create feature branch**

```bash
cd ~/github/morning
git checkout -b feat/mvp-implementation
```

- [ ] **Step 2: Create directory structure**

```bash
cd ~/github/morning
mkdir -p scripts skill
touch scripts/.gitkeep skill/.gitkeep
```

- [ ] **Step 3: Verify structure**

```bash
cd ~/github/morning
find . -type d -not -path './.git*' | sort
```

Expected output:
```
.
./docs
./docs/plans
./docs/specs
./scripts
./skill
```

- [ ] **Step 4: Commit**

```bash
cd ~/github/morning
git add scripts/.gitkeep skill/.gitkeep
git commit -m "Scaffold scripts and skill directories"
```

---

## Task 2: Create per-machine state directory

**Files:** None in repo. Creates user state directory outside the repo.

- [ ] **Step 1: Create ~/morning/ structure**

```bash
mkdir -p ~/morning/briefs ~/morning/state
```

- [ ] **Step 2: Verify**

```bash
ls -la ~/morning
```

Expected: directory exists with `briefs/` and `state/` inside.

- [ ] **Step 3: No commit** — this is local state, not in the repo.

---

## Task 3: Create config.example.yaml

**Files:**
- Create: `~/github/morning/config.example.yaml`

- [ ] **Step 1: Write the example config**

Write file at `~/github/morning/config.example.yaml`:

```yaml
# ~/morning/config.yaml template.
# Copy this file to ~/morning/config.yaml and fill in real values.
# The real config.yaml is gitignored.

notion:
  # 32-character hex ID for the Notion database holding tasks.
  # This DB is created in Task 3 Step 3 (via Notion MCP) — the ID is captured
  # there and substituted into the live ~/morning/config.yaml.
  # See the spec: the existing "To Do" page is unstructured notes; this is a
  # new database for actionable tasks only.
  todo_database_id: "REPLACE_WITH_NOTION_DB_ID"

  # URL of the existing "To Do" page that the morning tool scans for triage.
  # This page stays untouched — it's Lena's strategic dumping ground.
  todo_page_url: "https://www.notion.so/ekko-earth/To-Do-77903060bd6d473eba1011e191acefbb"

  # Cap on untriaged items shown in the daily triage section.
  triage_cap: 20

  # Property names on the new Notion Tasks DB. These match the schema created
  # in Task 3 Step 3. Edit ONLY if you rename properties in Notion.
  property_names:
    title: "Name"
    due_date: "Due"
    status: "Status"
    category: "Category"
    type: "Type"
    client: "Client"
    area: "Area"

  # The category value that promotes a task into the "Strategic" bucket.
  # All other category values are treated as Operational/Other for bucketing.
  strategic_category: "Strategic"

calendar:
  # Any attendee whose email does NOT end with this domain is treated as external.
  ekko_email_domain: "@ekko.earth"
  # For external meetings: research all named attendees, with a soft cap so
  # large group meetings don't blow up runtime. Meetings rarely exceed 10.
  external_meeting_attendee_cap: 10
  # Path used by gcalcli for OAuth credentials. Default usually fine.
  gcalcli_oauth_path: "~/.gcalcli_oauth"

github:
  # Repos to scan for "awaiting your input" (review requests, mentions).
  # Per-initiative repos come from initiatives.md, not here.
  ekko_repos:
    - ekko-home
    - ekko-edge-api
    - ekko-api
    - ekko-admin
    - ekko-web-mono
    - skill-forge
    - sdk-test-client

fathom:
  enabled: true
  # How many days back to scan for meetings and open action items.
  lookback_days: 7
  # Title regex used to detect engineering standups. Lena has exactly one
  # standup, titled "Stand up" (or "Standup"), at 09:30 Tue-Fri. Full-title
  # match so we don't accidentally catch other meetings with "stand up" in
  # the description.
  standup_title_regex: "(?i)^stand[\\s-]?up$"
  # Your name as it would appear as an action-item owner in Fathom summaries.
  user_name: "Lena"

output:
  briefs_dir: "~/morning/briefs"

paths:
  initiatives_file: "~/morning/initiatives.md"
```

- [ ] **Step 2: Verify file**

```bash
cat ~/github/morning/config.example.yaml | head -20
```

Expected: shows the first 20 lines starting with the comment header.

- [ ] **Step 3: Create the Notion Tasks database**

Use the Notion MCP `notion-create-database` tool to create a new database. The parent location will be confirmed with the user before this step runs — default is as a sub-page of the existing "To Do" page at `https://www.notion.so/ekko-earth/To-Do-77903060bd6d473eba1011e191acefbb`.

Database schema (per the design decision — 7 properties):

| Property | Type | Notes |
|---|---|---|
| `Name` | title | Default title property — the task itself |
| `Due` | date | Optional. Drives Urgent / This-week bucketing. |
| `Status` | select | Options: `Not started`, `In progress`, `Done`. The morning tool filters out `Done`. |
| `Category` | multi-select | Seeded: `Strategic`, `Operational`. Extendable in Notion. Items tagged `Strategic` go into the Strategic bucket regardless of date. Drives bucketing logic. |
| `Type` | select | Options: `Action`, `Idea`, `Feature`. Shown as a tag. `Idea` and `Feature` get extra weight in strategic-slot fit. |
| `Client` | checkbox | When true, the item is pinned at the top of its bucket and gets a `⚡` indicator. Always-priority signal. |
| `Area` | multi-select | Seeded: `Strategy`, `Product`, `Clients`, `Public docs`, `AI`. Extendable. Topic grouping only — no logic effect. |

Parent location: by default, create as a sub-page of the existing "To Do" page (see `notion.todo_page_url` in config). Override if the user nominates a different parent.

After creating, capture the database ID (32-char hex). The MCP response includes it.

- [ ] **Step 4: Copy template to ~/morning/ and substitute the real DB ID**

```bash
cp ~/github/morning/config.example.yaml ~/morning/config.yaml
# Then edit ~/morning/config.yaml and replace REPLACE_WITH_NOTION_DB_ID with the
# database ID from Step 3.
```

The executor should also remind the user to:
- Add their first few tasks to the new DB (so the smoke run in Task 14 has something to show), or rely on the triage flow during the smoke run.
- Optionally bookmark the new DB in Notion for fast access.

- [ ] **Step 5: Commit (template only — never commit the live config)**

```bash
cd ~/github/morning
git add config.example.yaml
git commit -m "Add config.example.yaml template"
```

---

## Task 4: Create initiatives.example.md

**Files:**
- Create: `~/github/morning/initiatives.example.md`

- [ ] **Step 1: Write the template**

Write file at `~/github/morning/initiatives.example.md`:

````markdown
# Initiatives

This file is the source of truth for active engineering initiatives. The morning tool reads it, then layers GitHub PR data on top of the status you write below.

Update it during your weekly planning time. Each initiative is an H2 heading with a YAML block of structured fields followed by free-text status.

If neither `linear_team` nor `github` is set, the initiative appears in the brief with status only — no auto-pulled signal.

---

## Carbon factors v3

```yaml
owner: manny
status: in-progress
# linear_team: ENG  # add when we re-introduce Linear in v2
github:
  repos: [ekko-api, ekko-edge-api]
  pr_keywords: [carbon-factor, cf-v3]
target_date: 2026-06-30
```

Replacing v2 endpoints with the new factor model. Currently blocked on validation rules from Nature Positive. Manny also handling the docs.ekko.earth migration plan.

## Checkout SDK v2

```yaml
owner: etienne
status: in-review
github:
  repos: [ekko-sdk-mono, sdk-test-client]
  pr_keywords: [sdk-v2]
target_date: 2026-07-15
```

New embedded checkout flow. Major PR open for review since Monday — needs my sign-off on the merchant-config schema.

## ekko Hub admin redesign

```yaml
owner: design
status: not-started
target_date: 2026-08-31
```

Awaiting design exploration before engineering scope. No code yet — included so it appears in the brief at status only.
````

- [ ] **Step 2: Copy to ~/morning/ for local use**

```bash
cp ~/github/morning/initiatives.example.md ~/morning/initiatives.md
```

The executor should ask the user to edit `~/morning/initiatives.md` to reflect her actual initiatives before doing end-to-end runs.

- [ ] **Step 3: Commit**

```bash
cd ~/github/morning
git add initiatives.example.md
git commit -m "Add initiatives.example.md template"
```

---

## Task 5: Create fetch_calendar.py

**Files:**
- Create: `~/github/morning/scripts/fetch_calendar.py`

Fetches today's calendar events via `gcalcli`, classifies each as internal vs external (based on attendee domains), and emits JSON. Pure Python so we avoid bash/heredoc gymnastics around subprocess output parsing.

- [ ] **Step 1: Write the script**

Write file at `~/github/morning/scripts/fetch_calendar.py`:

```python
#!/usr/bin/env python3
"""fetch_calendar.py — emit today's calendar events as JSON.

Usage:
    python3 fetch_calendar.py <ekko_email_domain>
    e.g. python3 fetch_calendar.py @ekko.earth

Output (stdout): JSON array of events. Each event has:
    {
        "time_start": "YYYY-MM-DD HH:MM",
        "time_end":   "YYYY-MM-DD HH:MM",
        "title": str,
        "attendees": [{"email": str, "name": str}],
        "is_external": bool,
        "conference_link": str,
    }

Exit codes:
    0 = success (may print "[]" if no events today)
    1 = gcalcli not installed
    2 = bad args
"""

from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: fetch_calendar.py <ekko_email_domain>", file=sys.stderr)
        sys.exit(2)
    ekko_domain = sys.argv[1]

    if shutil.which("gcalcli") is None:
        print("gcalcli not found in PATH", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # --tsv format with email + conference + length details.
    # Layout per gcalcli docs (subject to version drift):
    #   start_date  start_time  end_date  end_time  length  title  conference  emails
    result = subprocess.run(
        [
            "gcalcli", "agenda", today, tomorrow,
            "--details=email",
            "--details=length",
            "--details=conference",
            "--tsv",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Don't fail the brief — emit empty array so the section just says "no events".
        print("[]")
        return

    events = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 6:
            continue

        start_date = fields[0]
        start_time = fields[1] if len(fields) > 1 else ""
        end_date = fields[2] if len(fields) > 2 else ""
        end_time = fields[3] if len(fields) > 3 else ""
        title = fields[5] if len(fields) > 5 else "(no title)"
        conference = fields[6] if len(fields) > 6 else ""
        emails_field = fields[7] if len(fields) > 7 else ""

        attendees = []
        for raw_email in emails_field.split(","):
            e = raw_email.strip()
            if not e:
                continue
            m = re.match(r"^(.*?)\s*<(.+?)>$", e)
            if m:
                attendees.append({"name": m.group(1).strip(), "email": m.group(2).strip()})
            elif "@" in e:
                attendees.append({"name": "", "email": e})

        is_external = any(
            a["email"] and not a["email"].endswith(ekko_domain)
            for a in attendees
        )

        events.append({
            "time_start": f"{start_date} {start_time}".strip(),
            "time_end":   f"{end_date} {end_time}".strip(),
            "title": title,
            "attendees": attendees,
            "is_external": is_external,
            "conference_link": conference,
        })

    print(json.dumps(events, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/github/morning/scripts/fetch_calendar.py
```

- [ ] **Step 3: Smoke test**

```bash
python3 ~/github/morning/scripts/fetch_calendar.py "@ekko.earth"
```

Expected output: a JSON array (possibly empty `[]` if no events today). Should not error. If gcalcli is not yet OAuth'd, it will prompt or fail — that's a prerequisite to fix.

- [ ] **Step 4: Commit**

```bash
cd ~/github/morning
git add scripts/fetch_calendar.py
git commit -m "Add calendar fetch script with internal/external classification"
```

---

## Task 6: Create fetch_github.sh

**Files:**
- Create: `~/github/morning/scripts/fetch_github.sh`

Fetches three things from GitHub via `gh`:
1. PRs matching an initiative's repos + keywords
2. PRs where the user is requested as reviewer
3. Issues where the user is mentioned in the last 24h

- [ ] **Step 1: Write the script**

Write file at `~/github/morning/scripts/fetch_github.sh`:

```bash
#!/usr/bin/env bash
# fetch_github.sh — fetch GitHub signal for the morning brief.
#
# Subcommands:
#   initiative <repo,repo> <keyword,keyword>   list recent PRs (last 7 days) matching repos + any keyword
#   reviewer-requested                          PRs where the current user is requested as reviewer
#   mentions                                    issues/PRs mentioning the current user updated in last 24h
#
# Output (stdout): JSON.
# Errors → stderr, non-zero exit.

set -euo pipefail

GH_USER=$(gh api user --jq .login 2>/dev/null || echo "")
if [[ -z "$GH_USER" ]]; then
  echo "gh not authenticated" >&2
  exit 1
fi

subcommand="${1:-}"
case "$subcommand" in

  initiative)
    repos="${2:-}"
    keywords="${3:-}"
    if [[ -z "$repos" ]]; then
      echo "usage: fetch_github.sh initiative <repo,repo> [keyword,keyword]" >&2
      exit 2
    fi

    # Build the gh search query: scope to repos, last 7 days, any keyword in title.
    week_ago=$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d "7 days ago" +%Y-%m-%d)

    # Convert comma-separated repos to "repo:owner/r1 repo:owner/r2 ..." (assume ekko-enviroconomy org).
    repo_filter=""
    IFS=',' read -ra repo_arr <<< "$repos"
    for r in "${repo_arr[@]}"; do
      repo_filter="$repo_filter repo:ekko-enviroconomy/${r// /}"
    done

    # If keywords given, OR them with the repo filter; if not, just repos.
    if [[ -n "$keywords" ]]; then
      kw_filter=""
      IFS=',' read -ra kw_arr <<< "$keywords"
      for k in "${kw_arr[@]}"; do
        kw_filter="$kw_filter $k in:title"
      done
      query="$repo_filter updated:>=$week_ago ($kw_filter)"
    else
      query="$repo_filter updated:>=$week_ago"
    fi

    gh search prs --json number,title,url,state,author,repository,updatedAt --limit 30 -- "$query" 2>/dev/null || echo "[]"
    ;;

  reviewer-requested)
    gh search prs --review-requested="@me" --state=open \
      --json number,title,url,repository,author,updatedAt --limit 30 \
      2>/dev/null || echo "[]"
    ;;

  mentions)
    day_ago=$(date -v-1d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "1 day ago" +%Y-%m-%dT%H:%M:%SZ)
    gh search issues --mentions="@me" --updated=">$day_ago" \
      --json number,title,url,repository,author,updatedAt --limit 30 \
      2>/dev/null || echo "[]"
    ;;

  *)
    echo "usage: fetch_github.sh {initiative <repos> [keywords] | reviewer-requested | mentions}" >&2
    exit 2
    ;;
esac
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/github/morning/scripts/fetch_github.sh
```

- [ ] **Step 3: Smoke test the three subcommands**

```bash
~/github/morning/scripts/fetch_github.sh reviewer-requested | head -50
~/github/morning/scripts/fetch_github.sh mentions | head -50
~/github/morning/scripts/fetch_github.sh initiative "ekko-api,ekko-edge-api" "carbon" | head -100
```

Expected: each emits a JSON array (possibly empty). No errors on stderr.

- [ ] **Step 4: Commit**

```bash
cd ~/github/morning
git add scripts/fetch_github.sh
git commit -m "Add GitHub fetch script for initiative PRs, review requests, and mentions"
```

---

## Task 7: Create parse_initiatives.py

**Files:**
- Create: `~/github/morning/scripts/parse_initiatives.py`

Parses `initiatives.md` into a JSON list. Each initiative is an H2 section with a YAML block and free-text body.

- [ ] **Step 1: Write the parser**

Write file at `~/github/morning/scripts/parse_initiatives.py`:

```python
#!/usr/bin/env python3
"""parse_initiatives.py — parse initiatives.md into JSON.

Usage:
    python3 parse_initiatives.py <path-to-initiatives.md>

Output (stdout): JSON array of initiatives, each:
    {
        "name": str,
        "yaml": {owner, status, linear_team?, github?, target_date?},
        "body": str   # free-text status, may be empty
    }

Exit codes:
    0 = success (even if zero initiatives — emits [])
    1 = file not found or unreadable
    2 = bad YAML in any initiative (the whole parse fails so the user fixes it)
"""

from __future__ import annotations
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: pyyaml not installed. Run: python3 -m pip install --user pyyaml", file=sys.stderr)
    sys.exit(1)


# H2 heading then anything until next H2 or EOF.
INITIATIVE_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# YAML block: ```yaml ... ```
YAML_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)


def parse(path: Path) -> list[dict]:
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        sys.exit(1)
    text = path.read_text(encoding="utf-8")

    # Find all H2 positions.
    matches = list(INITIATIVE_RE.finditer(text))
    if not matches:
        return []

    initiatives = []
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        # H1 sections (single #) are skipped — INITIATIVE_RE only matches "## " not "# ".
        # The H1 "# Initiatives" header at the top of the file is ignored by design.

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end]

        # Extract YAML block.
        yaml_match = YAML_RE.search(section)
        yaml_data: dict = {}
        body = section
        if yaml_match:
            try:
                yaml_data = yaml.safe_load(yaml_match.group(1)) or {}
            except yaml.YAMLError as e:
                print(f"error: bad YAML in initiative '{name}': {e}", file=sys.stderr)
                sys.exit(2)
            # Body is what remains after stripping the YAML fence.
            body = section[:yaml_match.start()] + section[yaml_match.end():]

        body = body.strip()
        initiatives.append({"name": name, "yaml": yaml_data, "body": body})

    return initiatives


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: parse_initiatives.py <path>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1]).expanduser()
    result = parse(path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/github/morning/scripts/parse_initiatives.py
```

- [ ] **Step 3: Smoke test against the example file**

```bash
python3 ~/github/morning/scripts/parse_initiatives.py ~/github/morning/initiatives.example.md
```

Expected output: JSON array with 3 entries (Carbon factors v3, Checkout SDK v2, ekko Hub admin redesign), each with `name`, `yaml`, and `body` fields. The third has only `owner`, `status`, `target_date` in its YAML (no GitHub block).

- [ ] **Step 4: Smoke test against the live initiatives file**

```bash
python3 ~/github/morning/scripts/parse_initiatives.py ~/morning/initiatives.md
```

Expected: parses without error. (Assumes the user has edited their live file by now — if not, executor should remind.)

- [ ] **Step 5: Commit**

```bash
cd ~/github/morning
git add scripts/parse_initiatives.py
git commit -m "Add initiatives.md parser"
```

---

## Task 8: Create compute_gaps.py

**Files:**
- Create: `~/github/morning/scripts/compute_gaps.py`

Reads calendar JSON (from `fetch_calendar.sh`) and emits free-time gaps ≥ a minimum duration.

- [ ] **Step 1: Write the script**

Write file at `~/github/morning/scripts/compute_gaps.py`:

```python
#!/usr/bin/env python3
"""compute_gaps.py — find free-time gaps in today's calendar.

Usage:
    cat calendar.json | python3 compute_gaps.py [--min-minutes 45] [--day-start 09:00] [--day-end 18:00]

Input (stdin): JSON array of events (output of fetch_calendar.sh).
Output (stdout): JSON array of free gaps, each:
    {"start": "HH:MM", "end": "HH:MM", "minutes": int}

The day window defaults to 09:00–18:00 local time and counts gaps INSIDE that window only.
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timedelta


def parse_hhmm(s: str) -> datetime:
    """Parse 'HH:MM' against today's date."""
    today = datetime.now().replace(second=0, microsecond=0)
    h, m = s.split(":")
    return today.replace(hour=int(h), minute=int(m))


def parse_event_time(ts: str) -> datetime | None:
    """Parse the time_start/time_end fields from fetch_calendar.sh.

    Format is `YYYY-MM-DD HH:MM` typically. All-day events use just `YYYY-MM-DD`.
    Returns None for all-day events (they don't block free time).
    """
    ts = ts.strip()
    if not ts:
        return None
    # All-day: just a date, no time → skip.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts):
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-minutes", type=int, default=45)
    parser.add_argument("--day-start", type=str, default="09:00")
    parser.add_argument("--day-end", type=str, default="18:00")
    args = parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        print("[]")
        return
    events = json.loads(raw)

    day_start = parse_hhmm(args.day_start)
    day_end = parse_hhmm(args.day_end)

    # Build a list of (start, end) tuples for timed events that fall in the day window.
    intervals: list[tuple[datetime, datetime]] = []
    for e in events:
        s = parse_event_time(e.get("time_start", ""))
        en = parse_event_time(e.get("time_end", ""))
        if s is None or en is None:
            continue
        # Clip to day window.
        s = max(s, day_start)
        en = min(en, day_end)
        if en > s:
            intervals.append((s, en))

    # Sort and merge overlapping intervals.
    intervals.sort()
    merged: list[tuple[datetime, datetime]] = []
    for s, en in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], en))
        else:
            merged.append((s, en))

    # Compute gaps inside the day window.
    gaps = []
    cursor = day_start
    for s, en in merged:
        if s > cursor:
            mins = int((s - cursor).total_seconds() // 60)
            if mins >= args.min_minutes:
                gaps.append({"start": cursor.strftime("%H:%M"), "end": s.strftime("%H:%M"), "minutes": mins})
        cursor = max(cursor, en)
    if day_end > cursor:
        mins = int((day_end - cursor).total_seconds() // 60)
        if mins >= args.min_minutes:
            gaps.append({"start": cursor.strftime("%H:%M"), "end": day_end.strftime("%H:%M"), "minutes": mins})

    print(json.dumps(gaps, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/github/morning/scripts/compute_gaps.py
```

- [ ] **Step 3: Smoke test with fake input**

```bash
echo '[
  {"time_start":"'$(date +%Y-%m-%d)' 10:00","time_end":"'$(date +%Y-%m-%d)' 11:00","title":"x","attendees":[],"is_external":false,"conference_link":""},
  {"time_start":"'$(date +%Y-%m-%d)' 13:00","time_end":"'$(date +%Y-%m-%d)' 13:30","title":"y","attendees":[],"is_external":false,"conference_link":""}
]' | python3 ~/github/morning/scripts/compute_gaps.py --min-minutes 45
```

Expected output: JSON array showing at least one gap (11:00→13:00 = 120 mins) and another (13:30→18:00 = 270 mins). The 09:00→10:00 gap is only 60 mins so should also appear.

- [ ] **Step 4: Smoke test with empty input**

```bash
echo '[]' | python3 ~/github/morning/scripts/compute_gaps.py --min-minutes 45
```

Expected output: one big gap covering the whole day window (09:00→18:00, 540 minutes).

- [ ] **Step 5: Commit**

```bash
cd ~/github/morning
git add scripts/compute_gaps.py
git commit -m "Add free-time gap computation script"
```

---

## Task 9: Write SKILL.md — orchestrator (part 1, data flow)

**Files:**
- Create: `~/github/morning/skill/SKILL.md`

The SKILL.md is the main entry point invoked as `/morning`. It tells Claude exactly what to do, in what order, and which tools/scripts to call.

This task writes the first half: data fetching. Task 10 writes the rendering half.

- [ ] **Step 1: Write SKILL.md (data-flow section)**

Write file at `~/github/morning/skill/SKILL.md` with this initial content:

````markdown
---
name: morning
description: Produce the daily morning brief — to-dos, calendar, engineering progress, GitHub items awaiting input, strategic-slot fit, and one-sentence focus. Run at the start of each working day.
---

# /morning — daily brief skill

You are producing Lena's morning brief. Follow this skill exactly. The output must read like her own writing — see the Voice guide section below.

## Voice guide

This guide tells you (Claude) how to write the brief so it sounds like Lena writing for herself. Internal monologue style. Direct. Practical.

### Tone

- Warm, direct, conversational. Never corporate.
- Confident by default. State things plainly.
- Occasional dry humour in parenthetical asides.
- German cultural sensibility: unsentimental, practical.

### Structure

- Short sentences for impact. Longer ones for explanation. Vary naturally.
- Bullet points for practical content (PR lists, attendee lists). Flowing prose for the focus sentence and the strategic-slot suggestion.
- Rhetorical questions are fine sparingly: "So what's the move?"

### Confidence

- State things directly. No hedging out of habit.
- If you must hedge, use "I think" — and only when there is genuine uncertainty (e.g. you couldn't fetch a data source and are inferring).

### Anti-AI words — NEVER use

leverage, delve, it's worth noting, seamless, game-changer, empower, transformative, cutting-edge, robust, streamline, unlock, pivotal, in today's world, navigate (metaphorical), at the end of the day, move the needle, circle back, touch base, deep dive (as noun), exciting opportunity, innovative solution, going forward, quietly (as a modifier), gently (as a softener)

### Anti-AI structural patterns — AVOID

- Reframe construction: "That's not X. It's Y."
- Multiple rhetorical questions in one piece.
- Em dashes (—). Use a comma, colon, or full stop instead.
- Oxford comma (no comma before "and" or "or" in a list).

### Brief-specific style

- The one-sentence focus at the top should be ONE sentence. Imperative or declarative. No prefix like "Your focus today is...". Just the focus.
  - Good: "Ship the carbon factors merchant-config doc."
  - Bad: "Your focus today is to consider shipping the carbon factors doc."
- Strategic-slot suggestion: one short paragraph. State the time, the suggested item, and ONE sentence on why it fits.
- Engineering progress: per-initiative one-liner BEFORE the PR list. The one-liner is the *narrative*, the PR list is the *evidence*.
- External meeting prep: factual. Don't speculate about meeting outcomes or strategy.

## Configuration

Load `~/morning/config.yaml`. All paths in this skill resolve relative to that config. If the config is missing, stop and tell the user to copy `config.example.yaml` to `~/morning/config.yaml` and fill in values.

## Step 1: Fetch all data sources in parallel

Make these tool calls in a SINGLE message (parallel tool use):

1. **To-dos** — Notion MCP `notion-fetch` against the `todo_database_id` from config. Filter for incomplete items. If MCP unavailable, mark to-dos section as "Notion unavailable".

2. **Calendar** — Bash: `python3 ~/github/morning/scripts/fetch_calendar.py "<ekko_email_domain from config>"`

3. **Initiatives index** — Bash: `python3 ~/github/morning/scripts/parse_initiatives.py "<initiatives_file from config>"`

4. **GitHub reviewer-requested** — Bash: `~/github/morning/scripts/fetch_github.sh reviewer-requested`

5. **GitHub mentions** — Bash: `~/github/morning/scripts/fetch_github.sh mentions`

6. **Fathom meetings** — Use the Fathom MCP tools:
   - First: `list_meetings` filtered to the last `fathom.lookback_days` days (default 7).
   - Then in parallel: `get_meeting_summary` for each meeting returned.
   - If the MCP is unavailable, mark the "Yesterday's meetings" and "Open action items" sections as "Fathom unavailable" and continue.

7. **Acknowledged action items** — Bash: `cat ~/morning/state/acknowledged-actions.json 2>/dev/null || echo "[]"`

8. **Existing "To Do" page (for triage)** — Notion MCP `notion-fetch` against `notion.todo_page_url`. The page is large (~70KB); the response will contain all toggle sections and bullets. Extraction happens in Step 4b (see below).

9. **Triaged-items state** — Bash: `cat ~/morning/state/triaged-items.json 2>/dev/null || echo "[]"`

## Step 2: Per-initiative data fetch (parallel)

Once Step 1's initiatives parse completes, for EACH initiative that has a `github` block in its YAML, dispatch in parallel:

- `~/github/morning/scripts/fetch_github.sh initiative "<repos comma-joined>" "<keywords comma-joined>"`

If an initiative has no GitHub config, no fetch — it'll appear in the brief with status only.

## Step 3: Compute calendar gaps

Pipe the calendar output through gap computation:

```
echo '<calendar JSON from step 1>' | python3 ~/github/morning/scripts/compute_gaps.py --min-minutes 45
```

## Step 4: External meeting research

For each calendar event where `is_external: true`:

1. Extract unique external email domains from attendees.
2. WebSearch the company for each domain: query `"<domain>" company about`. Get one-line summary + any recent news (last 30 days).
3. For up to `external_meeting_attendee_cap` named attendees (skip ones with empty names), WebSearch `"<name>" "<company>" role` and infer their title.
4. Note: LinkedIn often blocks. Treat any inferred role as best-effort and prefix with "likely" in the output when confidence is low.

If a meeting has more than 10 attendees, treat it as a large event and skip per-attendee research — just include the company summary.

## Step 4a: Process Fathom meetings

Loop over the meetings returned in Step 1.6:

1. **Action item extraction.** Parse the summary for action items. Most Fathom summaries have a structured "Action items" block. For each action:
   - Compute the stable key: `sha1(meeting_id + lowercased_whitespace_normalised_text)[:16]`.
   - Include in the open-actions list if EITHER the action's owner equals `fathom.user_name` from config, OR the owner is unspecified and the action text mentions `fathom.user_name`.
   - Filter out any whose key appears in the acknowledged-actions list from Step 1.7.

2. **Standup classification.** For each meeting:
   - If the title matches `fathom.standup_title_regex`, flag it as a standup.
   - Capture the summary text for embedding into the engineering progress section. If the summary mentions specific initiatives (match against the names from the initiatives index), attach the summary to that initiative's block. Otherwise attach as a top-level "Standup notes" line under engineering progress.

3. **Yesterday's meetings list.** For each non-standup meeting in the lookback window, prepare a single line: `**<Title>** (<HH:MM>) — <one-line summary>`. Standups are not duplicated here — they appear under engineering progress.

## Step 4b: Extract untriaged To Do page bullets

From the To Do page fetched in Step 1.8:

1. **Extract bullets.** Read the markdown content. For each `<details>` toggle section, walk the top-level bullets (lines starting with `- ` or `* ` inside that section's body, ignoring lines beginning with `~~`/strikethrough and ignoring deeply nested rich content like email drafts). Each bullet's plain text becomes one candidate item.
2. **Compute hash for each.** `sha1(normalised_text)[:16]` where `normalised_text` = lowercase + collapse whitespace.
3. **Filter against state.** Drop any hash present in the triaged-items state from Step 1.9.
4. **Cap.** Keep at most `notion.triage_cap` items (default 20), preserving page order (oldest top-to-bottom).
5. **Hold the list.** Pair each surviving item with its hash and 1-indexed position. The list is used in the brief render (Step 5) and in Stage 1 of the interactive triage (Step 9 below).

## Step 5: Render the brief

Use the voice guide section above. The full brief structure is in the next section of this skill file (continued in part 2).

## Error handling

If any Step 1 sub-fetch fails:
- Show the section with the note "[Source] unavailable: <one-line reason>"
- Continue with the rest of the brief — never block on a single source.

If the entire orchestration fails before rendering, write a one-line error to `~/morning/briefs/<date>-ERROR.md` so the user can see what broke when they next check.
````

(Task 10 will append the rendering section.)

- [ ] **Step 2: Verify the file**

```bash
head -40 ~/github/morning/skill/SKILL.md
```

Expected: shows the frontmatter, the title, and Step 1.

- [ ] **Step 3: Commit**

```bash
cd ~/github/morning
git add skill/SKILL.md
git commit -m "Add SKILL.md with data-flow orchestration"
```

---

## Task 10: Append brief-rendering instructions to SKILL.md

**Files:**
- Modify: `~/github/morning/skill/SKILL.md` (append rendering section)

This task adds the rendering / output section. Keep it explicit so the brief shape is consistent every day.

- [ ] **Step 1: Append the rendering section**

Append this content to `~/github/morning/skill/SKILL.md`:

````markdown

## Brief structure

Produce the brief as a single markdown file. Apply the voice guide at every step.

### Template

```markdown
# Morning brief — <Weekday DD MMM YYYY>

> **Today's focus:** <one sentence, see Step 6 below>

## To-dos

Bucket logic (in priority order — each task lands in the first matching bucket):
1. **Urgent / due today** — has `Due` ≤ today.
2. **This week** — has `Due` in the rest of this calendar week.
3. **Strategic** — `Category` contains `Strategic` (regardless of date, unless already shown above).
4. **Later** — everything else (no date and not Strategic).

Each line shows the task title, its due date if any, and its categories as inline `[Tag1, Tag2]` after the title.

**Urgent / due today** — N
- <task title> (due today)  [<categories>]
- ...

**This week** — N
- <task title> (due <date>)  [<categories>]
- ...

**Strategic** — N
- <task title> (<due date if any>)  [<categories>]
- ...

**Later** — N
- <task title>  [<categories>]
- ...

If a bucket is empty, omit its sub-heading entirely. If ALL buckets are empty, write "Notion DB is empty. Add tasks at <DB url>".

## Calendar

- HH:MM — <Title> (<internal | external>)
- HH:MM–HH:MM — Free (NN min)
- ...

### External meeting prep

For each external meeting (skip section if none):

**HH:MM — <Title>**
- Company: <name> — <one-line on what they do>. <Recent news if any>.
- Participants:
  - <Name> — <role at company>
  - ...
- (If recent news or anything notable, one line.)

## Engineering progress

For each initiative from initiatives.md:

**<Name>** — <owner>, <status>, target <date if present>

<one-liner: your own free-text status from initiatives.md>

Standup notes (from <meeting title>, <date>): <one or two lines distilled from the Fathom summary — only if a matching standup summary exists>.

GitHub:
- <N PRs merged in last 7 days, N open>
- Open PRs:
  - #<num> <title> (<repo>) — <state>, updated <relative>
  - ...

(If no recent activity at all: write "No recent activity.")

## Awaiting your input

PRs requesting your review (N):
- #<num> <title> (<repo>) — opened by <author>, <days> days ago

Issues / PRs mentioning you in the last 24h (N):
- #<num> <title> (<repo>)

(If both lists are empty, write "Nothing waiting on you. Nice.")

## Yesterday's meetings

For each non-standup Fathom meeting in the lookback window:
- **<Title>** (<HH:MM>) — <one-line summary>

(If no meetings or Fathom unavailable: skip the section, or write "Fathom unavailable — <reason>".)

## Open action items

Numbered list, one per open action where you're the owner or named:

1. [ ] <action text> (from "<meeting title>", <date>)
2. [ ] <action text> (from "<meeting title>", <date>)
...

The numbers MUST be 1-indexed and sequential — they're used by the tick-off prompt. Pass the corresponding action keys to the tick-off step.

(If list is empty: write "Nothing carrying over. Clean slate.")

## From your To Do page — triage

(Section heading reads: "## From your To Do page — triage (N untriaged items, showing top K)" where N is total untriaged and K is what's surfaced after capping.)

Numbered list of the surviving items from Step 4b:

1. <bullet text>
2. <bullet text>
...

The numbers are 1-indexed and match the order in Step 9 (triage prompt).

(If no untriaged items: skip the section entirely.)

## Strategic-slot fit

<One short paragraph. State the largest free gap, the to-do best matched to it from the **Strategic bucket only** (items where `Category` contains `Strategic`), and ONE sentence on why it fits — e.g. "it needs deep focus and it's been parked for 9 days".>

(If no gap ≥45 min: "No deep-work window today. The strategic list will have to wait.")
(If no Strategic items at all: "Strategic bucket is empty. Add one in Notion and tag it `Strategic`.")
```

### How to choose the one-sentence focus (Step 6)

Synthesise across:
- Items overdue or urgent in to-dos
- Initiatives marked `blocked` or `in-review` where you're the owner
- External meetings (if there's a major one, prep IS the focus)
- The strategic-slot suggestion (if the day is genuinely open)

Pick ONE thing. Write it as a single imperative sentence, ≤14 words. No softening. No prefix like "Your focus today is...". Just the focus.

Examples (good):
- "Ship the carbon factors merchant-config doc."
- "Get sign-off on the SDK v2 schema before the 11am with Acme."
- "Use the 14:00 gap to draft Q3 OKRs first pass."

Examples (bad):
- "Today, you might want to consider working on the OKRs." (hedged)
- "Focus on engineering progress." (vague)
- "Do the things from your to-do list." (useless)

## Step 7: Save and present

1. Save the rendered brief to: `<briefs_dir from config>/<YYYY-MM-DD>.md`
2. Print the full brief to the conversation so the user sees it immediately.
3. End with the file path so she can re-open the brief later.

## Step 8: Action item tick-off

If the open action items list is non-empty:

1. Print exactly: `Already done any? (numbers comma-separated, blank to skip):`
2. Wait for the user's reply in the same conversation.
3. Parse the response: split on commas, strip whitespace, drop anything that isn't a positive integer or that exceeds the list length.
4. For each valid number, look up the corresponding action's stable key from the list you prepared in Step 4a.
5. Run: `python3 ~/github/morning/scripts/ack_action.py <key1> <key2> ...`
6. Confirm to the user: `Marked N item(s) done. They won't appear tomorrow.`

If the list was empty, skip this step entirely.

## Step 9: To Do page triage — Stage 1 (list & select)

If the untriaged list from Step 4b is non-empty:

1. Print exactly: `Numbers to add to DB? (e.g. "1,3-4"). "s <nums>" to skip-forever. Blank to leave for tomorrow:`
2. Wait for the user's reply.
3. Parse the response:
   - Tokens like `1`, `3-4`, `7` → list of integer indices to ADD
   - Token like `s 2,5,9` or `s2,5,9` → list of integer indices to SKIP-FOREVER
   - Mixed input allowed: `1,3 s 2,5`
   - Blank → no action; all items stay untriaged
4. For each SKIP-FOREVER index: look up its hash, then run `python3 ~/github/morning/scripts/triage_state.py skip <hash1> <hash2> ...`
5. Hold the list of ADD indices for Stage 2.

## Step 10: To Do page triage — Stage 2 (per-item Q&A)

For each index in the ADD list, in user-selected order:

1. Print:
   ```
   Item <N>: "<bullet text>"
   Details? (category, type, client, due, context — or "defaults"):
   ```
2. Wait for the user's reply.
3. Parse the free-text reply. Apply these rules in order:
   - If reply contains `defaults` or is blank → use `Type: Action`, `Category: ["Operational"]`, `Client: false`, no due date, no context.
   - Else, recognise tokens (case-insensitive, comma- or space-separated):
     - `strategic` → add `Strategic` to `Category` multi-select
     - `operational` → add `Operational` to `Category` multi-select (default if neither given)
     - `action` → `Type: Action` (default if not specified)
     - `idea` → `Type: Idea`
     - `feature` → `Type: Feature`
     - `client` or `+client` → `Client: true`
     - Specific client names like `megatix`, `acme` → `Client: true` AND if matching an Area option, add to `Area`
     - Date phrases (`fri`, `friday`, `next week`, `2026-06-15`, `mon`, `tomorrow`) → set `Due` using a robust date parser. If ambiguous, ask: "Due when? (specific date please)"
     - `context: <text>` or `+context: <text>` → save `<text>` as the page body content
4. If the parse is ambiguous in a way you can't infer (e.g. user types just "tag it nicely"), ask ONE clarifying question, then proceed.
5. Call Notion MCP `notion-create-pages` with:
   - parent = `notion.todo_database_id`
   - properties: Name = bullet text, plus parsed Category / Type / Client / Due / Area
   - body = context text if provided
6. Append the item's hash to triaged state: `python3 ~/github/morning/scripts/triage_state.py add <hash> <notion_page_url>`
7. Print: `✓ Added. [<Category>, <Type>]` (and any extras)

## Step 11: Final confirmation

Print one summary line like: `Done. Added N, skipped M, K left for tomorrow.`

No other follow-up questions. No "would you like me to..." offers. The brief is the deliverable.
````

- [ ] **Step 2: Verify the file is complete**

```bash
wc -l ~/github/morning/skill/SKILL.md
grep -c "^## " ~/github/morning/skill/SKILL.md
```

Expected: ~150-200 lines, and 6-8 top-level `## ` sections.

- [ ] **Step 3: Commit**

```bash
cd ~/github/morning
git add skill/SKILL.md
git commit -m "Add brief rendering template and focus-sentence guidance to SKILL.md"
```

---

## Task 11: Create ack_action.py — action item acknowledgment helper

**Files:**
- Create: `~/github/morning/scripts/ack_action.py`

Tiny helper that appends action-item keys to `~/morning/state/acknowledged-actions.json` so SKILL.md can stay declarative. The file is a plain JSON array of hash strings.

- [ ] **Step 1: Write the script**

Write file at `~/github/morning/scripts/ack_action.py`:

```python
#!/usr/bin/env python3
"""ack_action.py — mark Fathom action item(s) as done.

Usage:
    python3 ack_action.py <key1> [<key2> ...]

Each key is a stable hash computed by SKILL.md as:
    sha1(meeting_id + lowercased_whitespace_normalised_action_text)[:16]

The script appends new keys to ~/morning/state/acknowledged-actions.json
(a JSON array of strings) and writes it back. Existing keys are not
duplicated. The state file is created lazily if it doesn't exist.

Exit codes:
    0 = success (always, unless arg parsing fails)
    2 = no keys provided
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/acknowledged-actions.json"))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: ack_action.py <key> [<key> ...]", file=sys.stderr)
        sys.exit(2)

    new_keys = [k.strip() for k in sys.argv[1:] if k.strip()]
    if not new_keys:
        print("no valid keys provided", file=sys.stderr)
        sys.exit(2)

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if STATE_FILE.exists():
        try:
            existing = json.loads(STATE_FILE.read_text())
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            # Corrupt file — start fresh. Don't lose user's ack history silently in production;
            # for v1, this is acceptable since the file is local and re-tickable.
            existing = []
    else:
        existing = []

    seen = set(existing)
    added = []
    for k in new_keys:
        if k not in seen:
            existing.append(k)
            seen.add(k)
            added.append(k)

    STATE_FILE.write_text(json.dumps(existing, indent=2))
    print(f"acknowledged {len(added)} new action(s); total acked: {len(existing)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/github/morning/scripts/ack_action.py
```

- [ ] **Step 3: Smoke test — fresh file**

```bash
# Ensure clean state for the test.
rm -f ~/morning/state/acknowledged-actions.json

python3 ~/github/morning/scripts/ack_action.py abc123 def456
cat ~/morning/state/acknowledged-actions.json
```

Expected output:
- First command prints: `acknowledged 2 new action(s); total acked: 2`
- `cat` shows: `["abc123", "def456"]` (formatted)

- [ ] **Step 4: Smoke test — dedup**

```bash
python3 ~/github/morning/scripts/ack_action.py abc123 ghi789
cat ~/morning/state/acknowledged-actions.json
```

Expected output:
- Script prints: `acknowledged 1 new action(s); total acked: 3` (only `ghi789` is new; `abc123` is a duplicate)
- File now shows three entries: `["abc123", "def456", "ghi789"]`

- [ ] **Step 5: Smoke test — corrupt file recovery**

```bash
echo "not valid json" > ~/morning/state/acknowledged-actions.json
python3 ~/github/morning/scripts/ack_action.py recovery-key
cat ~/morning/state/acknowledged-actions.json
```

Expected: script does not crash, the file is rewritten as `["recovery-key"]`.

- [ ] **Step 6: Commit**

```bash
cd ~/github/morning
git add scripts/ack_action.py
git commit -m "Add ack_action.py helper for Fathom action-item tick-off"
```

---

## Task 12: Create triage_state.py — To Do page triage state helper

**Files:**
- Create: `~/github/morning/scripts/triage_state.py`

Manages `~/morning/state/triaged-items.json`. The file holds records of bullets that have been added to the DB or skipped-forever during morning triage, so they don't reappear.

- [ ] **Step 1: Write the script**

Write file at `~/github/morning/scripts/triage_state.py`:

```python
#!/usr/bin/env python3
"""triage_state.py — record To Do page triage decisions.

Usage:
    python3 triage_state.py skip <hash> [<hash> ...]
    python3 triage_state.py add <hash> <notion_page_url>

The state file at ~/morning/state/triaged-items.json is a JSON array of records:
    {"hash": "...", "action": "skipped-forever" | "added", "notion_url": "..." (optional), "ts": "..."}

Exit codes:
    0 = success
    2 = bad args
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


STATE_FILE = Path(os.path.expanduser("~/morning/state/triaged-items.json"))


def load() -> list[dict]:
    if not STATE_FILE.exists():
        return []
    try:
        data = json.loads(STATE_FILE.read_text())
        if not isinstance(data, list):
            return []
        return data
    except json.JSONDecodeError:
        return []


def save(records: list[dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(records, indent=2))


def main() -> None:
    if len(sys.argv) < 3:
        print("usage:\n  triage_state.py skip <hash> [<hash> ...]\n  triage_state.py add <hash> <notion_page_url>", file=sys.stderr)
        sys.exit(2)

    action = sys.argv[1]
    records = load()
    seen = {r["hash"] for r in records if "hash" in r}
    now = datetime.now(timezone.utc).isoformat()

    if action == "skip":
        new_hashes = [h.strip() for h in sys.argv[2:] if h.strip()]
        added = 0
        for h in new_hashes:
            if h not in seen:
                records.append({"hash": h, "action": "skipped-forever", "ts": now})
                seen.add(h)
                added += 1
        save(records)
        print(f"skip-forever: {added} new, {len(records)} total triaged")

    elif action == "add":
        if len(sys.argv) < 4:
            print("usage: triage_state.py add <hash> <notion_page_url>", file=sys.stderr)
            sys.exit(2)
        h = sys.argv[2].strip()
        url = sys.argv[3].strip()
        if h in seen:
            print(f"hash already triaged: {h}")
            return
        records.append({"hash": h, "action": "added", "notion_url": url, "ts": now})
        save(records)
        print(f"added: {h} -> {url}")

    else:
        print(f"unknown action: {action}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/github/morning/scripts/triage_state.py
```

- [ ] **Step 3: Smoke test — skip-forever**

```bash
rm -f ~/morning/state/triaged-items.json
python3 ~/github/morning/scripts/triage_state.py skip aaa111 bbb222
cat ~/morning/state/triaged-items.json
```

Expected output:
- Script prints: `skip-forever: 2 new, 2 total triaged`
- File contains two records with `action: skipped-forever`.

- [ ] **Step 4: Smoke test — add**

```bash
python3 ~/github/morning/scripts/triage_state.py add ccc333 https://www.notion.so/test-page-id
cat ~/morning/state/triaged-items.json
```

Expected: third record with `action: added`, `notion_url` populated.

- [ ] **Step 5: Smoke test — dedup**

```bash
python3 ~/github/morning/scripts/triage_state.py skip aaa111
```

Expected: `skip-forever: 0 new, 3 total triaged` (the existing hash is detected; no duplicate appended).

- [ ] **Step 6: Commit**

```bash
cd ~/github/morning
git add scripts/triage_state.py
git commit -m "Add triage_state.py helper for To Do page triage state"
```

---

## Task 13: Register skill with Claude Code

**Files:** No new files in repo. Creates a symlink in `~/.claude/skills/`.

The skill needs to be discoverable by Claude Code. For v1 we **symlink** only — no publishing to `skill-forge` until Lena has trialled the tool for a few weeks and confirmed it earns its keep.

- [ ] **Step 1: Create the symlink**

```bash
mkdir -p ~/.claude/skills
ln -sf ~/github/morning/skill ~/.claude/skills/morning
```

- [ ] **Step 2: Verify**

```bash
ls -la ~/.claude/skills/morning
cat ~/.claude/skills/morning/SKILL.md | head -10
```

Expected: symlink resolves, SKILL.md content is readable.

- [ ] **Step 3: Restart Claude Code or open a new session**

The skill is loaded at session start. Tell the user: "Open a new Claude Code session, then type `/morning` to invoke."

- [ ] **Step 4: No commit** — the symlink is a per-machine setup step, not in the repo. Do NOT copy or publish this skill into `skill-forge` or any team-shared location during v1.

---

## Task 14: End-to-end smoke run

**Files:** None.

This is the live test — run `/morning` for the first time and inspect the brief.

- [ ] **Step 1: Open a new Claude Code session in any working directory**

```bash
cd ~ && claude
```

- [ ] **Step 2: Run the skill**

In the new session, type: `/morning`

- [ ] **Step 3: Verify the brief**

Inspect the output. Confirm:

1. To-dos section appears (or shows "Notion unavailable" with a clear reason) and uses the new four-bucket layout (Urgent / This week / Strategic / Later) with category tags
2. Calendar section lists today's events
3. External meetings have a prep block (only if there are external meetings today)
4. Engineering progress shows initiatives from `~/morning/initiatives.md`
5. "Awaiting your input" section appears (may be empty)
6. **Yesterday's meetings** section lists Fathom meetings from the lookback window (or "Fathom unavailable")
7. **Open action items** section appears with numbered list (or "Nothing carrying over.")
8. **From your To Do page — triage** section appears with up to 20 untriaged bullets (or is skipped if no untriaged items)
9. For any initiative whose name appears in a recent standup summary, a "Standup notes:" line is embedded above its PR list
10. Strategic-slot suggestion appears (or notes no gap)
11. One-sentence focus is at the top
12. Brief is saved to `~/morning/briefs/<today>.md`

- [ ] **Step 4: Verify the action-item tick-off flow (if there were open actions)**

After the brief renders, the tool prompts for action numbers. Reply with one valid number (e.g. `1`). Confirm:

1. Script reports `acknowledged 1 new action(s); total acked: 1`
2. `cat ~/morning/state/acknowledged-actions.json` shows the hash
3. Re-run `/morning` and confirm that the acknowledged action no longer appears in the Open action items list

- [ ] **Step 5: Verify the triage flow — Stage 1 (skip-forever)**

After the action-item prompt, the tool moves to the triage prompt. Reply with `s 1` (skip-forever item 1). Confirm:

1. `triage_state.py skip <hash>` runs and reports `skip-forever: 1 new, 1 total triaged`
2. `cat ~/morning/state/triaged-items.json` shows one record with `action: skipped-forever`
3. Re-run `/morning` and confirm item 1 no longer appears in the triage list

- [ ] **Step 6: Verify the triage flow — Stage 2 (add to DB)**

Run `/morning` again. At the triage prompt, reply with one number (e.g. `1`). The tool moves to per-item Q&A. Reply with a one-liner like `strategic idea, context: testing the triage`. Confirm:

1. Tool prints `✓ Added. [Strategic, Idea]`
2. New row appears in your Notion Tasks DB with Name = bullet text, Category = Strategic, Type = Idea, body = "testing the triage"
3. `cat ~/morning/state/triaged-items.json` shows a second record with `action: added` and a `notion_url`
4. Re-run `/morning` and confirm the just-added item no longer appears in the triage list

- [ ] **Step 7: Verify the triage flow — defaults**

Run `/morning` again. At the triage prompt, reply with a different number. At the per-item prompt, reply `defaults`. Confirm:

1. Tool prints `✓ Added with defaults [Operational, Action]`
2. Notion DB has a new row with Type=Action, Category=Operational, no date, no client, no body

- [ ] **Step 8: Inspect the saved file**

```bash
cat ~/morning/briefs/$(date +%Y-%m-%d).md
```

Expected: same content as printed in the session (note: brief itself does NOT include the interactive Q&A — only the rendered sections).

- [ ] **Step 9: Note any issues**

If anything fails or the brief shape is wrong, document the issue and either:
- Fix it inline (small bugs)
- Add a follow-up task to the plan (larger issues)

- [ ] **Step 10: No commit** — this is a verification task.

---

## Task 15: Raise PR to merge feature branch

**Files:** None.

- [ ] **Step 1: Push the feature branch**

```bash
cd ~/github/morning
git fetch origin main
git rebase origin/main
git push -u origin feat/mvp-implementation
```

- [ ] **Step 2: Raise the PR**

```bash
gh pr create --title "MVP implementation: /morning skill with helpers and templates" --body "$(cat <<'EOF'
## Summary
- Implements the MVP /morning skill per the [design spec](docs/specs/2026-05-26-morning-tool-design.md).
- Eight brief sections: to-dos (Notion 7-property DB, four-bucket layout), calendar (with external meeting prep), engineering progress per initiative (enriched with Fathom standup notes), GitHub items awaiting input, yesterday's meetings + open action items (interactive tick-off), To Do page triage (interactive add-to-DB or skip-forever), strategic-slot fit, one-sentence focus.
- Helper scripts: calendar fetch, GitHub fetch, initiatives parser, gap computation, action-item ack, triage state.
- Skill orchestrator at `skill/SKILL.md` with embedded voice guide for consistent rendering.
- Notion Tasks DB created with 7-property schema during setup (Task 3 Step 3).

## Test plan
- [ ] Skill is registered (symlink in ~/.claude/skills/morning exists)
- [ ] /morning runs end-to-end and saves a brief to ~/morning/briefs/
- [ ] Notion Tasks DB exists with all 7 properties
- [ ] To-dos section uses four-bucket layout (Urgent / This week / Strategic / Later) with category tags
- [ ] At least one external meeting prep block has been verified manually
- [ ] At least one initiative shows GitHub PRs pulled from initiatives.md mapping
- [ ] Yesterday's meetings section pulls Fathom summaries
- [ ] Action tick-off prompt works: replying with a number acknowledges the action, and the item disappears on next run
- [ ] Triage prompt works: replying with `s <n>` skip-forevers an item; replying with a number plus details adds it to the Notion DB
- [ ] Smoke run on a second day to check the saved-brief folder grows correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Note the PR URL**

Return the PR URL to the user. They review and merge — do NOT merge without explicit instruction.

---

## Open questions to revisit after MVP

These are deliberately deferred from v1 but worth noting for v2 planning:

1. **Voice guide drift.** When the global `CLAUDE.md` voice section changes, the skill's local copy goes stale. Options: periodic manual diff, or a `make sync-voice` target that pulls the relevant section.
2. **gcalcli output format stability.** The TSV parsing in `fetch_calendar.py` is defensive but version-dependent. If gcalcli upstream changes the format, the parser breaks silently (empty array). Worth adding a sanity check.
3. **Notion DB schema discovery.** Currently the user hard-codes property names in config. A discovery step (read the DB schema first, map common variants) would make setup more robust.
4. **Skill installation as a Claude Code plugin** instead of a symlink. Plugins offer cleaner distribution but more ceremony — fine to defer.
5. **Yesterday's slippage.** With briefs now persisted to `~/morning/briefs/`, the data is there. Adding a "what was suggested yesterday but didn't get done" check is cheap when we want it.
6. **Linear (or replacement) integration.** Deferred from v1. When added back in v2, plan a single isolated fetch script so it can be swapped out cleanly later.
7. **Fathom action key drift.** Hashing on `(meeting_id, normalised_text)` is robust as long as Fathom doesn't regenerate summaries between runs. If users notice acknowledged items reappearing, revisit either Fathom-provided action IDs (if added to the MCP) or fuzzy matching.
8. **Standup regex tuning.** The default regex is a starting point. After the first week of real briefs, look at which meetings did/didn't match and adjust.
9. **Triage bullet extraction robustness.** Bullet detection is done by Claude reading the page markdown (no helper script). If the page structure changes substantially (e.g. heavy new nesting or non-bullet items), the extraction may need tuning. Revisit after a week of real triage.
10. **Triage hash stability.** If Lena edits a bullet's text on the To Do page (typo fix, rephrasing) after it's been triaged, the hash changes and the item could resurface. Acceptable for v1; consider fuzzy matching in v2.
11. **Per-item Q&A parsing.** The free-text parser in SKILL.md Step 10 is rule-based with LLM fallback. Hard cases (e.g. ambiguous category) trigger one clarifying question. Watch for cases that need more than one round and tighten the prompt if they're common.

---

## Plan self-review notes

- [x] Spec coverage: all 8 brief sections in the spec have implementation tasks (Tasks 3-12).
- [x] No placeholders — all code blocks contain full, working content.
- [x] Type consistency: script names, output JSON shapes, config keys are consistent across tasks (e.g. `todo_database_id` and `todo_page_url` are used in config + SKILL.md; `fathom.user_name` flows from config into SKILL.md action-item filtering; 7-property schema is identical in Task 3 schema table, config property_names, and SKILL.md triage step).
- [x] Fathom action key format documented in spec AND used identically in SKILL.md (Step 4a) and ack_action.py.
- [x] Triage item hash format documented in SKILL.md (Step 4b) AND used identically in triage_state.py.
- [x] Skipped: unit tests per the spec ("no tests for v1"). Verification at each task is a smoke run.
- [x] Prerequisites called out separately — installation steps user must do before Task 1.
- [x] Interactive steps (action tick-off, triage Stage 1, triage Stage 2) are explicitly documented as sequential post-brief prompts so the executor doesn't try to skip them.
