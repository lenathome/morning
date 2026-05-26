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
| 3 | Engineering progress per initiative | `initiatives.md` + GitHub PRs + Linear |
| 4 | Awaiting my input | GitHub (review requests, mentions) |
| 5 | Strategic-slot fit | Calendar + to-dos |
| 6 | One-sentence focus | Synthesis across all sections |

Output: printed to terminal, saved as `~/morning/briefs/YYYY-MM-DD.md`.

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
    ├── fetch_linear.sh                             # curls the Linear GraphQL API
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
| Linear issues | Linear GraphQL API via `curl` | API key in `~/.config/morning/linear-token` (chmod 600) |
| Web research (external meetings) | WebSearch / WebFetch | Built into Claude Code |

### `initiatives.md` schema

One file. Each initiative is an H2 heading followed by a fenced `yaml` block of structured fields and a free-text body for human-only context. The free-text body is the part a PR can never tell me — current blockers, scope nuance, what I'm worried about.

```markdown
## Carbon factors v3

```yaml
owner: manny
status: in-progress
linear_project: ENG-123
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
- `linear_project` (optional): Linear project or team key to query
- `github.repos` (optional): list of repos to scan
- `github.pr_keywords` (optional): keywords to match in PR titles
- `target_date` (optional): ISO date

If neither `linear_project` nor `github` is set, the initiative shows in the brief with status only — no auto-pulled signal.

### Brief generation flow

When `/morning` is invoked:

1. Load `~/morning/config.yaml` (Notion DB ID, ekko email domain, Linear token path, brief output dir).
2. Load `~/morning/initiatives.md`. Parse the YAML block from each `## ` section.
3. **In parallel** (one tool round, several calls):
   - Notion MCP query against to-do DB, filtered to incomplete items
   - `scripts/fetch_calendar.sh` for today's events
   - `scripts/fetch_github.sh` for each initiative + reviewer-requested + mentions
   - `scripts/fetch_linear.sh` for each initiative with `linear_project`
4. Classify calendar events as internal vs external (any attendee with non-`ekko.earth` domain → external).
5. For each external meeting (sequentially, can be slow): WebSearch the company by domain, WebSearch each named attendee for current role.
6. Run `scripts/compute_gaps.py` over the calendar to find free gaps ≥45 min. Match each gap to one or two strategic to-dos (no deadline this week).
7. Synthesise the one-sentence focus.
8. Render the brief using the voice guide.
9. Print to terminal. Write to `~/morning/briefs/YYYY-MM-DD.md`.

### Brief output shape

A markdown file with this rough structure:

```markdown
# Morning brief — Tuesday 26 May 2026

> **Today's focus:** [one sentence]

## To-dos
**Urgent / due today** — 2
- [item with deadline]
- ...

**This week** — 5
- ...

**Strategic (no deadline)** — 3
- ...

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
- Last activity: yesterday
- 3 PRs merged in last 7 days, 2 open
- Status: blocked on Nature Positive validation rules
- Open PRs: [list with links]

**[other initiatives...]**

## Awaiting my input
- PR #234 in ekko-api — reviewer requested 2 days ago
- Issue #45 in ekko-web-mono — @lena-thome mentioned this morning

## Strategic-slot fit
You have **14:00–15:30 free**. From your strategic list, the best fit is **"Draft Q3 OKRs first pass"** — it's been on your list for 9 days, needs deep focus, and fits a 90-min slot.
```

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
- The repo at `~/github/morning/` only ships templates and skill code.

## Open questions for implementation plan

1. **Notion DB shape.** Which Notion DB ID? Required properties (due date, priority, category, tags)? If the current DB doesn't have these properties, do we adjust it, or filter post-hoc?
2. **Linear API access.** Personal API token or read-only org token? Where is the token coming from today?
3. **`gcalcli` install + OAuth setup.** Needs a one-time browser flow. Confirm the Google Workspace tenant allows OAuth for this client.
4. **Skill registration.** Does this register under `~/.claude/skills/morning/` directly, get symlinked from the repo, or get published through `skill-forge` for the team?
5. **External-meeting cutoff.** What if a meeting has 10+ attendees? Cap research at the first N named attendees, or skip if it looks like a large group call?
6. **Voice guide drift.** When the global `CLAUDE.md` voice section changes, how does the skill's local copy stay in sync? Periodic manual diff, or a make target?

These get answered in the implementation plan, not here.

## Non-goals (worth naming explicitly)

- Not a to-do manager. The tool reads Notion; it does not create or check off items.
- Not a roadmap tool. Figjam stays the visual artefact; `initiatives.md` is the machine-readable mirror.
- Not a daemon or always-on service. It runs when invoked and exits.
- Not a substitute for standup. It supplements human conversation, not replaces it.
