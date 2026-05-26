# Morning tool — MVP design

**Date:** 2026-05-26
**Owner:** Lena Thome
**Status:** Approved scope, pending implementation plan

## Background

Each morning I need to walk into the day knowing three things: what's on my to-do list (and which items are urgent vs strategic gap-fillers), how engineering is progressing against each initiative, and what's on my calendar — particularly for any external meetings where I need prep. Today I do this manually across Notion, Figjam, Linear, GitHub PRs and Google Calendar. It works, but engineering tracking in particular isn't reliable.

Two reference tools shaped this design:

- **Ryan's morning tool** (a Go daemon + tmux dispatching Claude Code sessions) is built for an engineer who needs to fan out work to agents. I don't need that — I'm not dispatching engineering work, I'm reading signal.
- **Anthropic's morning brief pattern** (a scheduled remote agent that delivers a personalised digest) is closer to what I need, but I want local iteration first.

## Problem and opportunity

The tool should give me a daily brief that lets me start the day with a clear picture, fitting strategic work into longer gaps and prepping me for external meetings without context-switching across five apps.

The opportunity is broader than automation. Engineering tracking is the weakest part of my current routine. By requiring a small `initiatives.md` index to drive the brief, the tool nudges me into a weekly discipline of keeping that index current — and that discipline, not the brief itself, is the durable value.

## Proposal

Build a Claude Code skill `/morning` that:

1. Reads a local `initiatives.md` and a config file.
2. Pulls signal from Notion, Google Calendar, GitHub and Linear in parallel.
3. For external meetings, researches the company and named participants via web search.
4. Computes free calendar gaps and suggests strategic to-dos that fit.
5. Synthesises a one-sentence focus for the day.
6. Prints the brief to the terminal and saves a dated copy to `~/morning/briefs/`.

## Scope

### In scope (v1)

| # | Section | Source |
|---|---|---|
| 1 | To-do summary | Notion DB |
| 2 | Calendar (list + external meeting prep) | Google Calendar |
| 3 | Engineering progress per initiative | `initiatives.md` + GitHub PRs only + Fathom standup summaries |
| 4 | Awaiting my input | GitHub (review requests, mentions) |
| 5 | Strategic-slot fit | Calendar + to-dos |
| 6 | One-sentence focus | Synthesis across all sections |
| 7 | Yesterday's meetings + open action items (with tick-off) | Fathom MCP |

Output: printed to terminal, saved as `~/morning/briefs/YYYY-MM-DD.md`. Tick-off interaction happens after rendering.

### Out of scope (v1)

- Yesterday's slippage diff against prior briefs (defer until persistence pattern proves itself)
- Slack mentions / DM triage (separate integration surface)
- Automatic classification of unmatched PRs into initiatives
- Notion comments / mentions
- Docs / translations queue
- Meeting prep depth for internal meetings (prior decisions, last meeting notes)
- Initiative drift early-warning ("no activity >5 days" flag) — can be inferred from raw output; revisit in v2
- Tests (manual smoke run is the test; revisit when helpers stabilise)

## Architecture

### Form factor

A Claude Code skill at `~/github/morning/skill/SKILL.md` (loaded via `~/.claude/skills/` or registered through the user's plugin). Invoked as `/morning` from any Claude Code session.

The skill is the orchestrator. It instructs Claude how to:

- Read config and `initiatives.md`
- Call helper scripts where determinism matters
- Use Claude's native WebSearch / WebFetch for external meeting research
- Use the Notion MCP for to-dos
- Synthesise the brief in the user's voice (warm, direct, short sentences, no AI tics)
- Render and save the brief

### Repo layout

```
~/github/morning/
├── README.md
├── config.example.yaml
├── initiatives.example.md
├── docs/
│   └── specs/
│       └── 2026-05-26-morning-tool-design.md      # this doc
├── skill/
│   ├── SKILL.md                                    # main skill entry point
│   └── voice-guide.md                              # excerpted from CLAUDE.md, used for brief rendering
└── scripts/
    ├── fetch_calendar.sh                           # wraps gcalcli
    ├── fetch_github.sh                             # wraps `gh` for PRs / reviews / mentions
    └── compute_gaps.py                             # calendar → free-slot list
```

Per-machine config lives outside the repo:

```
~/morning/
├── config.yaml                                     # gitignored equivalent; real values
├── initiatives.md                                  # the live, edited file
└── briefs/
    └── 2026-05-26.md                               # output, dated
```

### Data sources

| Source | Access | Auth |
|---|---|---|
| Notion to-dos | Notion MCP (already configured) | MCP-managed |
| Google Calendar | `gcalcli` CLI | One-time OAuth, refresh token cached locally |
| GitHub PRs / mentions | `gh` CLI | Existing `gh` auth |
| Fathom meeting summaries + action items | Fathom MCP (already configured) | MCP-managed |
| Web research (external meetings) | WebSearch / WebFetch | Built into Claude Code |

### `initiatives.md` schema

One file. Each initiative is an H2 heading followed by a fenced `yaml` block of structured fields and a free-text body for human-only context. The free-text body is the part a PR can never tell me — current blockers, scope nuance, what I'm worried about.

```markdown
## Carbon factors v3

```yaml
owner: manny
status: in-progress
linear_team: ENG
github:
  repos: [ekko-api, ekko-edge-api]
  pr_keywords: [carbon-factor, cf-v3]
target_date: 2026-06-30
```

Replacing v2 endpoints with the new factor model. Currently blocked on validation rules from Nature Positive. Manny is also handling the docs.ekko.earth migration plan.
```

Fields:

- `owner` (required): primary engineer
- `status` (required): one of `not-started`, `in-progress`, `blocked`, `in-review`, `shipping`, `done`
- `linear_team` (optional): Linear team key (e.g. `ENG`) to query open issues for
- `github.repos` (optional): list of repos to scan
- `github.pr_keywords` (optional): keywords to match in PR titles
- `target_date` (optional): ISO date

If neither `linear_team` nor `github` is set, the initiative shows in the brief with status only — no auto-pulled signal.

### To Do page triage

Each morning the tool scans the existing "To Do" page in Notion and helps move actionable items into the new database. This is how the DB gets populated over time — no upfront migration.

**Detection.** The tool fetches the page, extracts top-level bullets (skipping strikethrough, deep nested rich notes, and section headers), and hashes each bullet's normalised text. Hashes already present in `~/morning/state/triaged-items.json` are filtered out.

**Capped surfacing.** Surface at most 20 untriaged items per morning, oldest-first by position on the page. The rest wait until tomorrow.

**Stage 1 — list & select.** The brief shows the numbered list. After the brief renders, the tool prompts:

> *Numbers to add to DB? (e.g. "1,3-4"). "s <nums>" to skip-forever. Blank to leave for tomorrow.*

The user replies. Blank → no action, items remain untriaged. `s <nums>` → those hashes are appended to `triaged-items.json` with `action: skipped-forever` so they don't reappear (this is how reminders and non-tasks get filtered out permanently). Numbers → proceed to Stage 2.

**Stage 2 — per-item Q&A.** For each selected number, in order:

> *Item N: "<text>"*
> *Details? (category, type, client, due, context — or "defaults"):*

The user replies with a free-text one-liner. Claude parses it into the structured properties:

- Recognises `strategic`, `operational` → `Category`
- Recognises `action`, `idea`, `feature` → `Type`
- Recognises `client`, `+client`, client names → sets `Client` true
- Recognises date phrases like `fri`, `friday`, `2026-06-15`, `next week` → `Due`
- Recognises `context: <text>` or `+context: <text>` → saved as the page body content
- Recognises `defaults` → uses `Type: Action`, `Category: Operational`, no due date, no client

If a parse is ambiguous, Claude asks ONE follow-up. Otherwise it just commits via `notion-create-pages` and records the hash with `action: added` in `triaged-items.json`.

**Reminders.** Items that look like reminders rather than tasks are handled by the user typing `s <num>` for those — they get permanently skipped without being added to the DB.

### Fathom — yesterday's meetings and action items

Pulls meetings from a lookback window (default: past 7 days, configurable in `config.yaml` under `fathom.lookback_days`) via the Fathom MCP. For each meeting in the window:

- Fetch the summary via `get_meeting_summary`.
- Extract action items. An action belongs to the brief if its owner is the user OR its owner is unspecified but the action text mentions the user by name.
- If the meeting title matches a standup/dev-sync regex (default: `(?i)standup|dev[\s-]?sync|engineering[\s-]?sync|eng[\s-]?weekly`) or its attendees overlap with the engineering team, the summary is **also** embedded inside the engineering progress section as a "Standup notes:" line for the relevant initiative(s) — this is the narrative context PRs alone can't give.

Open action items appear in their own brief section as a numbered list with checkboxes. Items previously acknowledged (see state) are filtered out before display.

**Tick-off flow:** after the brief renders, the tool prompts *"Already done any? (numbers comma-separated, blank to skip)"*. The user types one or more numbers; each maps to an action's stable key, which is appended to the acknowledged state file. The brief itself is not modified — the prompt is the only mutation surface.

**Stable action keys:** the Fathom MCP does not guarantee stable IDs per action item. The tool computes a key as `sha1(meeting_id + lowercased_whitespace_normalised_action_text)[:16]` — stable across runs as long as Fathom's summary text doesn't change, which is good enough for v1. If the summary regenerates and the text drifts, the user simply re-acknowledges once and it stays gone.

### Brief generation flow

When `/morning` is invoked:

1. Load `~/morning/config.yaml` (Notion DB ID, ekko email domain, brief output dir).
2. Load `~/morning/initiatives.md`. Parse the YAML block from each `## ` section.
3. **In parallel** (one tool round, several calls):
   - Notion MCP query against to-do DB, filtered to incomplete items
   - `scripts/fetch_calendar.sh` for today's events
   - `scripts/fetch_github.sh` for each initiative + reviewer-requested + mentions
   - Fathom MCP: `list_meetings` for the lookback window, then `get_meeting_summary` for each meeting → extract action items + standup summaries
4. Classify calendar events as internal vs external (any attendee with non-`ekko.earth` domain → external).
5. For each external meeting (sequentially, can be slow): WebSearch the company by domain, WebSearch each named attendee for current role.
6. Run `scripts/compute_gaps.py` over the calendar to find free gaps ≥45 min. Match each gap to one or two to-dos from the Strategic bucket (items where `Category` contains `Strategic`).
7. Load `~/morning/state/acknowledged-actions.json` and filter Fathom action items against it.
8. Synthesise the one-sentence focus.
9. Render the brief using the voice guide.
10. Print to terminal. Write to `~/morning/briefs/YYYY-MM-DD.md`.
11. **Interactive tick-off** — prompt for any action item numbers the user has already completed. Append hashes to `acknowledged-actions.json`.
12. **To Do page triage (Stage 1)** — prompt for numbers to add to DB / skip-forever. Record skip-forever items.
13. **To Do page triage (Stage 2)** — for each item to add, walk the per-item Q&A, parse the user's reply, create the Notion DB page via `notion-create-pages`, append the hash to `triaged-items.json` with `action: added`.
14. Confirm totals to the user (`Added N, skipped M, K left for tomorrow`) and exit.

### Brief output shape

A markdown file with this rough structure:

```markdown
# Morning brief — Tuesday 26 May 2026

> **Today's focus:** [one sentence]

## To-dos
**Urgent / due today** — 2
- [item with deadline]  [Operational]
- ...

**This week** — 5
- ...  [Operational]
- ...  [Operational, Client work]

**Strategic** — 3
- [item tagged Strategic, with or without date]  [Strategic]
- ...

**Later** — 4 (no date, not Strategic)
- ...  [Operational]

## Calendar
- 09:30 — Team standup (internal)
- 11:00 — [External meeting block, see below]
- 14:00–15:30 — Free
- 16:00 — 1:1 with Designer (internal)

### External meeting prep

**11:00 — Discovery call with Acme Climate**
- Company: [1-line summary, recent news if any]
- Participants:
  - Jane Doe — Head of Partnerships at Acme
  - John Smith — VP Engineering
- Suggested questions: [if I can infer any from context]

## Engineering progress
**Carbon factors v3** — Manny, in-progress, target 30 Jun
- Standup notes (from yesterday's dev sync): Manny finished the validation harness and is waiting on Nature Positive to confirm the new range bounds.
- Last activity: yesterday
- 3 PRs merged in last 7 days, 2 open
- Status: blocked on Nature Positive validation rules
- Open PRs: [list with links]

**[other initiatives...]**

## Awaiting my input
- PR #234 in ekko-api — reviewer requested 2 days ago
- Issue #45 in ekko-web-mono — @lena-thome mentioned this morning

## Yesterday's meetings
- **Manny 1:1** (15:00) — discussed carbon factors blockers, Q3 hiring plan
- **Acme Climate intro** (16:30) — partnership scope, next step is sending the SDK overview
- **Dev sync** (09:30) — covered above in engineering progress

## Open action items
1. [ ] Send Acme the SDK overview deck (from "Acme Climate intro", May 25)
2. [ ] Confirm Q3 hiring brief with Etienne (from "Manny 1:1", May 24)
3. [ ] Review the carbon factors validation PR (from "Dev sync", May 25)

## From your To Do page — triage (12 untriaged items, showing top 20)

1. user testing skill - questions to answer
2. product decision log from Fathom recordings
3. Set agents on competitor developer docs
4. create a to do list agent to add reminders
5. Ryan's morning digest - what does it do?
6. methodology on choosing carbon credits...
...

(Prompt after brief: "Numbers to add? '1,3-4'. 's <nums>' to skip-forever. Blank to defer.")

## Strategic-slot fit
You have **14:00–15:30 free**. From your strategic list, the best fit is **"Draft Q3 OKRs first pass"** — it's been on your list for 9 days, needs deep focus, and fits a 90-min slot.
```

After printing the brief, the tool asks: *"Already done any of the open action items? (numbers comma-separated, blank to skip)"*. The user types e.g. `1,3` and those items are appended to the acknowledged state file.

### Voice rendering

The brief must read like me writing for myself — warm, direct, short sentences, no AI tics. The skill includes a `voice-guide.md` derived from the relevant sections of my global `CLAUDE.md` so the rendering stays consistent even when the skill is run outside my main session.

### Error handling

- Each section is independent. If any source fails, the section says "[Source] unavailable — [reason]" and the rest of the brief proceeds.
- Helper scripts exit non-zero on failure with a short stderr message; the skill catches and substitutes the unavailability note.
- The brief is always saved to disk, even when partial.

### State

- No database. The `~/morning/briefs/` folder is the persistence layer for future slippage / trend features.
- `~/morning/config.yaml` for per-machine config.
- `~/morning/initiatives.md` for the live initiatives index.
- `~/morning/state/acknowledged-actions.json` — JSON array of hashes for Fathom action items the user has marked done. Created lazily on first tick-off; if the file is missing the tool treats the list as empty.
- `~/morning/state/triaged-items.json` — JSON array of `{hash, action, notion_url?}` records for To Do page bullets that have been added to the DB or skipped-forever. Created lazily.
- The repo at `~/github/morning/` only ships templates and skill code.

## Decisions and open questions

### Decisions made (2026-05-26 review)

1. **Notion source.** The existing "To Do" page is unstructured notes, not a task list. We'll create a new Notion database for actionable tasks and leave the old page as the strategic dumping ground.

   **Schema (7 properties):**
   - `Name` (title) — the task itself.
   - `Due` (date, optional) — drives Urgent / This-week bucketing.
   - `Status` (select: `Not started`, `In progress`, `Done`) — `Done` items are filtered out of the brief.
   - `Category` (multi-select: `Strategic`, `Operational`, extendable) — drives the Strategic bucket. A task is Strategic if and only if `Category` contains `Strategic`.
   - `Type` (single-select: `Action`, `Idea`, `Feature`) — kind of work. `Idea` and `Feature` get extra weight in strategic-slot fit because they need deep-thinking time.
   - `Client` (checkbox) — client-related items are pinned at the top of their bucket and marked with `⚡`.
   - `Area` (multi-select: `Strategy`, `Product`, `Clients`, `Public docs`, `AI`, extendable) — topic grouping for organisation. Shown as a tag, doesn't drive logic.

   **Population:** the DB starts empty. Tasks land in it via the daily To Do page triage step (see Triage section below). The morning tool reads only the new database; the existing "To Do" page stays untouched as the strategic dumping ground.
2. **Linear integration deferred to v2.** v1 ships GitHub-only signal per initiative. Linear (or whatever replaces it) gets added back when the rest of the brief has proven itself.
3. **Skill registration.** Symlink into `~/.claude/skills/morning/` for v1. **No publishing to `skill-forge`** until the tool has been trialled for a few weeks and confirmed useful.
4. **External-meeting cutoff.** Research **all** named attendees, with a soft cap of 10. Meetings rarely exceed this in practice.
5. **Standup detection.** Lena has exactly one standup, titled "Stand up" (or "Standup"), at 09:30 Tue–Fri. The regex tightens to `(?i)^stand[\s-]?up$` — full-title match so we don't accidentally catch other meetings.

### Still open (deferred to v2)

- **`gcalcli` install + OAuth setup.** Needs a one-time browser flow. Confirm the Google Workspace tenant allows OAuth for this client during prereqs.
- **Voice guide drift.** When the global `CLAUDE.md` voice section changes, how does the skill's local copy stay in sync? Periodic manual diff, or a make target.
- **Fathom action-item stable IDs.** Does the MCP expose a per-action stable ID, or only the raw summary text? Hashing on `(meeting_id, text)` is the v1 fallback.
- **Notion DB schema evolution.** If `Priority` or `Category` properties prove useful in practice, add them in v2 without breaking the v1 reader.

## Non-goals (worth naming explicitly)

- Not a to-do manager. The tool reads Notion; it does not create or check off items.
- Not a roadmap tool. Figjam stays the visual artefact; `initiatives.md` is the machine-readable mirror.
- Not a daemon or always-on service. It runs when invoked and exits.
- Not a substitute for standup. It supplements human conversation, not replaces it.
- Not a Fathom client. The tool reads Fathom summaries and action items; it never writes back to Fathom. Tick-off lives in local state only.
- The tool does NOT delete items from the existing "To Do" page during triage. Bullets marked skip-forever or added-to-DB just stop appearing in future briefs — they stay on the page until Lena removes them manually.
