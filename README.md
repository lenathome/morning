# morning

A Claude Code skill, `/morning`, that produces a daily brief for a product manager, plus a companion skill, `/session-sweep`, that keeps the brief's project files current.

This is my own tool, not an ekko team tool. You are welcome to copy it, but it is built around my setup: a Notion tasks database, Fathom for meetings, a folder of project files and a handful of GitHub repos. The setup section below lists what you need to swap in.

## What it is

`/morning` reads from Notion, Google Calendar, GitHub, Fathom and a folder of project files, then publishes one page and prints a short header in chat. The brief contains, in this order:

- **Project updates.** Edits proposed by `/session-sweep` from the previous day's Claude Code sessions. They come first, so the rest of the brief is built from updated project files.
- **Today's focus.** One sentence.
- **To do.** Urgent today, coming up, your Fathom actions and product colleagues' actions and merged PRs to test by hand. Parent tasks in Notion group their subtasks.
- **External meeting prep.** A company summary and each attendee's likely role, for meetings with people outside the ekko domain. Personal recurring events are skipped.
- **PRs needing you.** Review requests and mentions, plus your own open PRs split into ready to merge and awaiting review, with a flag when one has gone stale.
- **Ideas bank.** To-dos with no due date, split into strategic and operational.
- **Engineering progress.** One line per project from its project file, the related PRs, notes from team syncs and next actions for each commercial partner.

Every actionable line has a number. You tick items off in chat by replying with the numbers and the next brief drops them.

Every to-do carries an owner tag (needs-Lena, split or handoff) saying who could own it. The tags are alpha: a first guess, not reviewed, and the page and the markdown say so. The `needs-Lena` tag is the name used by readers of the shared brief; for you it means product judgement, sign-off or a relationship only you hold.

`/session-sweep` runs before the brief. It reads every Claude Code session since its last run, writes a digest of each to `~/ai-log/YYYY-MM-DD.md` and queues proposed edits to the project files. It never edits a project file itself. You accept or reject the proposals when the brief opens.

## Why it was built

The design spec ([docs/specs/2026-05-26-morning-tool-design.md](docs/specs/2026-05-26-morning-tool-design.md)) starts from a daily routine. Each morning I needed to know three things: what is on my to-do list and what is urgent, how engineering is progressing against each initiative and what is on my calendar, particularly for external meetings that need prep. I was collecting that by hand across Notion, Figjam, Linear, GitHub PRs and Google Calendar. It worked, but engineering tracking in particular was not reliable.

Two reference tools shaped the design. Ryan's morning tool dispatches engineering work to agents, which is the wrong fit for someone who reads signal and does not dispatch work. The Anthropic morning brief pattern is closer, but I wanted to iterate locally first.

The spec also names the durable value: the brief needs a small index of projects to run, so it pushes me into keeping that index current each week. That index is now the `~/product-os/projects/*.md` folder. The brief marks a project as not reviewed when its `last_reviewed` date is stale and the sweep proposes updates from the previous day's sessions, so the files have a way to stay current.

The page came later ([docs/plans/2026-10-01-brief-html-page.md](docs/plans/2026-10-01-brief-html-page.md)). Chat now gets a short header and a link, so the brief reads at a glance in a phone notification and the page is a private claude.ai artifact at one fixed URL.

## How it was built

The tool is a Claude Code skill plus small Python and shell scripts. The skill is the orchestrator: `skill/SKILL.md` tells Claude which sources to read in parallel, how to write in my voice and what goes in each section. The scripts handle the parts that must give the same answer every time:

- `scripts/fetch_calendar.py` wraps `gcalcli`. It parses the human-readable agenda because the TSV output lists only one attendee per event. It marks events external or personal.
- `scripts/fetch_github.sh` and `scripts/fetch_merged.sh` wrap `gh` for review requests, mentions, your own PRs, project PRs and recently merged PRs with their deploy runs.
- `scripts/parse_projects.py` reads the project files.
- `scripts/render_brief.py` turns the brief into output (see below).
- `scripts/publish_brief.sh` commits the shared markdown copy to `briefs/` in the product-os repo and pushes it to origin/main.
- `scripts/extract_sessions.py` and `scripts/proposals.py` serve `/session-sweep`.
- `scripts/ack_*.py` record what you ticked off or parked, in `~/morning/state/`.

The brief is JSON. Claude writes it to `~/morning/briefs/<date>.json` and never numbers anything. `scripts/render_brief.py` validates it, numbers every actionable line and writes four files: a markdown archive, a shared markdown copy without the external meeting prep (`--shared-md`), an HTML page (`scripts/brief_template.html` with the JSON embedded, rendered in the browser) and a map from number to Notion page or Fathom action. The tick-off step reads that map, which is why numbers stay stable between the page and the chat.

I built it with Claude Code. The spec and the implementation plans in `docs/plans` were written first and each plan is split into tasks for agents to execute one at a time. The scripts use the Python standard library only.

## Setup

### Prerequisites

- [Claude Code](https://claude.com/claude-code).
- Python 3.9 or later. The scripts use only the standard library, and the test suite passes on 3.9 and 3.14.
- [`gh`](https://cli.github.com/), authenticated (`gh auth status`).
- `jq`, which `fetch_merged.sh` uses.
- [`gcalcli`](https://github.com/insanum/gcalcli), with a one-time OAuth flow. Without it the calendar script returns an empty list and the brief has no meeting prep.
- Claude Code connectors for Notion (the tasks database) and Fathom (meetings and action items). Publishing the page uses the Artifact tool. Web research for meeting prep uses Claude Code's built-in search and fetch.
- A Notion tasks database with the properties `Name`, `Due`, `Status`, `Category`, `Type`, `Client`, `Area`, `Parent` and `Subtasks`. The skill treats `Status: Waiting` and `Status: Done` specially and drops `Type: Idea` rows. [`config.example.yaml`](config.example.yaml) holds the property names, so rename them there if yours differ.

### Install

The skill calls its scripts at `~/github/morning/scripts/...`, so clone to that path:

```
git clone https://github.com/lenathome/morning ~/github/morning
mkdir -p ~/morning/briefs ~/morning/state ~/ai-log ~/.claude/skills
ln -s ~/github/morning/skill ~/.claude/skills/morning
ln -s ~/github/morning/sweep ~/.claude/skills/session-sweep
cp ~/github/morning/config.example.yaml ~/morning/config.yaml
```

Then edit `~/morning/config.yaml`. The values to fill in:

- `notion.todo_database_id`: the ID of your tasks database.
- `calendar.ekko_email_domain`: attendees outside this domain count as external. Despite the name, put your own company's domain here.
- `calendar.primary_calendar`: your email, so `gcalcli` reads only your own calendar and not shared ones.
- `calendar.internal_contacts` and `calendar.personal_events`: friends or old colleagues who should not trigger meeting prep and recurring personal events.
- `github.ekko_repos`: the repos to scan for review requests and merged PRs. Per-project repos come from the project files.
- `fathom.user_name`: your name as it appears as an action owner in Fathom summaries. `fathom.team_action_owners` lists colleagues whose actions you want to track.
- `output.artifact_url`: leave empty on the first run. The skill prints the new URL and you paste it in, so every later brief goes to the same page.
- `paths.projects_dir`: where your project files live.
- `paths.product_os`: the product-os git repo. Step 6 publishes the shared brief to `briefs/` in it and pushes to origin/main.

`config.yaml` is gitignored.

### Project files

The brief expects a folder of markdown files, by default `~/product-os/projects/`, one per project. Each file starts with YAML frontmatter and has a `## Where it is` section whose first paragraph becomes the project's one-liner:

```
---
name: PPP localisation
status: active            # active | blocked | waiting | done
owner: Sam
repos: [ekko-api]         # GitHub repo names for PR signal
keywords: []              # optional PR title keywords
notion: https://...
next_milestone: one line
target_date: 2026-09-12
last_reviewed: 2026-09-01
---
## Where it is
...
```

[`scripts/parse_projects.py`](scripts/parse_projects.py) documents the full format and the output. It skips files whose names start with `_` and anything in subfolders such as `_archive/`. A project is stale when `last_reviewed` is missing or more than 14 days old. A project with `repos` but no `keywords` shows no PR list, because a repo-wide list would mix in unrelated work. Projects whose slug starts with `client-` render as commercial partners instead of engineering projects.

### Run it

In Claude Code, run `/session-sweep` and then `/morning`. The brief opens with any queued project updates and waits for your reply before it builds the rest.

### Schedule it

I run both as scheduled Claude Code tasks each weekday morning, the sweep first. Unattended runs still print the queued project updates and stop and they skip the tick-off prompts. Nothing is accepted, rejected or ticked off until you reply in a session.

### Tests

```
python3 -m unittest discover -s tests -v
```

## Layout

- `skill/` - the `/morning` skill (`SKILL.md`).
- `sweep/` - the `/session-sweep` skill (`SKILL.md`).
- `scripts/` - the Python and shell helpers, plus the HTML page template.
- `tests/` - unit tests and a sample brief in `tests/fixtures/`.
- `docs/specs/` - the original design spec.
- `docs/plans/` - the implementation plans, including the brief JSON contract that `skill/SKILL.md` points to.
- `config.example.yaml` - the template for `~/morning/config.yaml`.

Outside the repo, on your machine: `~/morning/` holds your config, the daily briefs and the tick-off state, `~/product-os/projects/` holds the project files and `~/ai-log/` holds the sweep's daily digests.
