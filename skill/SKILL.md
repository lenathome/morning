---
name: morning
description: Produce the daily morning brief - project updates to apply first, then a To do section (urgent, coming up, action items), external meeting prep, PRs needing you, recently merged PRs to test by hand, an ideas bank of undated to-dos, engineering progress per project and a one-sentence focus. Run at the start of each working day.
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
- Bullet points for practical content (PR lists, attendee lists). Flowing prose for the focus sentence.
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
- Engineering progress: per-project one-liner BEFORE the PR list. The one-liner is the *narrative*, the PR list is the *evidence*.
- External meeting prep: factual. Don't speculate about meeting outcomes or strategy.

## Configuration

Load `~/morning/config.yaml`. All paths in this skill resolve relative to that config. If the config is missing, stop and tell the user to copy `config.example.yaml` to `~/morning/config.yaml` and fill in values.

## Step 0: Project updates first

Before fetching anything for the brief, deal with the project updates queued by the session-sweep skill.

1. Run `python3 ~/github/morning/scripts/proposals.py list`. It returns the pending proposals, each with `id, slug, kind, section, field, text, value, source, session_title, session_date, created_at`.
2. If the command fails, print `Project updates unavailable: <reason>` and continue to Step 1.
3. If there are no pending proposals, go straight to Step 1.
4. Otherwise print the sentence: `From yesterday's sessions. Reply with the numbers to apply, "all", or "none" to leave them for tomorrow.` Then a blank line, then a numbered list starting at 1, one line per proposal:

N. **<project name>** - <section or field>: <text or value> (from "<session_title>", <session_date>)

   `<project name>` is the `name` for the proposal's `slug` in the output of `python3 ~/github/morning/scripts/parse_projects.py "<paths.projects_dir from config>"` (if that fails, use the slug). `<section or field>` is `section` for an append and `field` for a frontmatter change; `<text or value>` is `text` or `value` to match. Order by project name, then `created_at`. The blank line after the sentence matters for the same CommonMark reason as in the brief: an ordered list can't interrupt a paragraph.
5. Then stop and wait for the reply. Map each number to its proposal `id`.
6. On the reply: run `python3 ~/github/morning/scripts/proposals.py accept <id1> <id2> ...` for the chosen ids (all of them for "all"). If the user explicitly names any to reject, run `python3 ~/github/morning/scripts/proposals.py reject <id1> <id2> ...` for those. Leave the rest pending, so they show again tomorrow. Confirm in one line: `Applied M project update(s).` (skip the line if M is 0). Then continue to Step 1, so the brief is built from the updated project files.

These numbers are separate from the brief's running sequence: the brief restarts at 1.

In an unattended run (scheduled, no user present) this step still prints the list and stops. Nothing is accepted or rejected until the user replies.

## Step 1: Fetch all data sources in parallel

Make these tool calls in a SINGLE message (parallel tool use):

1. **To-dos** — Notion MCP. Use `notion-search` with `data_source_url: collection://<todo_database_id from config's data source>` to list pages in the Tasks DB. Increase `page_size` to 25 (max) and `max_highlight_length: 0`. Then `notion-fetch` each page to read properties (Name, Due, Status, Category, Type, Client, Area, Parent, Subtasks). Filter out `Status: Done` and filter out `Type: Idea`. An Idea is not a to-do: parked ideas live in `~/product-os/backlog.md` and are reviewed at the cycle boundary, so surfacing them daily buries the actionable rows. Rows with no `Type` set are kept, because an unset Type is missing data rather than a decision. Keep `Parent` and `Subtasks` fields — they drive the parent/subtask rendering in the brief. If MCP unavailable, mark to-dos section as "Notion unavailable".

2. **Calendar** — Bash: `python3 ~/github/morning/scripts/fetch_calendar.py "<ekko_email_domain>" "<primary_calendar>" "<calendar.internal_contacts comma-joined, or empty string>"` (values from config; second arg restricts gcalcli to your own calendar so shared calendars don't clutter the brief; third arg lists personal contacts who do not make a meeting external)

3. **Projects index** — Bash: `python3 ~/github/morning/scripts/parse_projects.py "<paths.projects_dir from config>"`. Returns a JSON array of live projects from `~/product-os/projects/*.md`, each with `slug, name, status, owner, repos, keywords, notion, next_milestone, target_date, last_reviewed, stale, body`. If the command exits non-zero, render the Engineering progress section as "Projects unavailable: <first line of stderr>" and continue.

4. **GitHub reviewer-requested** — Bash: `~/github/morning/scripts/fetch_github.sh reviewer-requested`

5. **GitHub mentions** — Bash: `~/github/morning/scripts/fetch_github.sh mentions`

6. **Fathom meetings** — Use the Fathom MCP tools:
   - First: `list_meetings` filtered to the last `fathom.lookback_days` days (default 7).
   - Then in parallel: `get_meeting_summary` for each meeting returned.
   - If the MCP is unavailable, mark the "Yesterday's meetings" and "Your actions" and "Product actions" lists as "Fathom unavailable" and continue.

7. **Acknowledged action items** — Read tool: `~/morning/state/acknowledged-actions.json`. If the file is missing, treat it as `[]`. Use Read, not `cat`, so an unattended run needs no Bash approval.

8. **Acknowledged PRs state** — Read tool: `~/morning/state/acknowledged-prs.json`. If the file is missing, treat it as `[]`.

9. **Your own open PRs** — Bash: `~/github/morning/scripts/fetch_github.sh authored`. Returns non-draft PRs you authored, enriched with `review_decision`, `reviewers_requested`, `latest_approvals`, `mergeable`. Used by "Yours to chase" in the PRs needing you section.

10. **Recently merged PRs** — Bash: `~/github/morning/scripts/fetch_merged.sh "<repos comma-joined>" 3`, where the repos are the union of every non-done project's `repos` and config `github.ekko_repos`. Returns merged PRs from the last 3 days, each with `repo, number, title, url, body, mergedAt, author, files` and `deploys` (the deploy, release and publish runs on the merge commit, with their jobs). Used by the Testing section. Also read `~/morning/state/acknowledged-tests.json` with the Read tool; if the file is missing, treat it as `[]`.


## Step 2: Per-project data fetch (parallel)

Once Step 1's projects parse completes, for EACH project whose `repos` list is non-empty and whose `status` is not `done`, dispatch in parallel:

- `~/github/morning/scripts/fetch_github.sh initiative "<repos comma-joined>" "<keywords comma-joined, or empty string>"`

If a project has no repos, no fetch - it appears in the brief with status only.

## Step 3: External meeting research

For each calendar event where `is_external: true`:

1. Extract unique external email domains from attendees.
2. WebSearch the company for each domain: query `"<domain>" company about`. Get one-line summary + any recent news (last 30 days).
3. For up to `external_meeting_attendee_cap` named attendees (skip ones with empty names), WebSearch `"<name>" "<company>" role` and infer their title.
4. Note: LinkedIn often blocks. Treat any inferred role as best-effort and prefix with "likely" in the output when confidence is low.

If a meeting has more than 10 attendees, treat it as a large event and skip per-attendee research — just include the company summary.

## Step 3a: Process Fathom meetings

Loop over the meetings returned in Step 1.6:

1. **Action item extraction.** Parse the summary for action items. Most Fathom summaries have a structured "Action items" block. For each action:
   - Compute the stable key: `sha1(meeting_id + lowercased_whitespace_normalised_text)[:16]`.
   - Classify into one of two buckets:
     - **Your actions** — owner equals `fathom.user_name` from config, OR owner is unspecified and the action text mentions `fathom.user_name`.
     - **Team actions** — actions owned by anyone in `fathom.team_action_owners` from config (case-insensitive substring match on the owner string, so "Etienne" matches "Etienne Smith"). These are the people whose work the user might absorb or needs to track (typically managers, peers in tight collaboration). Other owners are excluded entirely. If `team_action_owners` is empty or missing, no team actions are surfaced.
   - Filter out (from EITHER bucket) any action whose key is in the acknowledged-actions list from Step 1.7. Tick-off works the same way regardless of bucket.
   - Cap the team actions bucket at 20 items, ordered by meeting date descending then by position within the meeting. The user can manually look in Fathom for older ones.

2. **Team sync classification.** For each meeting:
   - If the title matches `fathom.team_sync_title_regex`, flag it as a team sync.
   - Capture the summary text for embedding into the engineering progress section. If the summary mentions specific projects (match against the names from the projects index), attach the summary to that project's block. Otherwise attach as a top-level "Team sync notes" line under engineering progress.
   - Action items from team syncs are still extracted in item 1 as normal.

3. **Recent meetings list.** For each non-team-sync meeting in the lookback window, prepare a single line. EXCLUDE any meeting that already contributed at least one item to the open action items list — that meeting's relevant context is already surfaced via the action's Fathom link, and listing it again is duplicative. Team syncs are also excluded here (they appear under engineering progress).

## Step 4: Render the brief

Write the brief's content as JSON to `<briefs_dir>/<YYYY-MM-DD>.json`, following the contract in `docs/plans/2026-10-01-brief-html-page.md` (section "The brief JSON contract"). That contract lives in this repo; the skill reads it from `~/github/morning/docs/plans/2026-10-01-brief-html-page.md`. Do not number anything: the renderer does. Put every list in final display order (standalone tasks first, then parent groups alphabetically). Apply the voice guide to every string you write. Then run:

`python3 ~/github/morning/scripts/render_brief.py <briefs_dir>/<date>.json --md <briefs_dir>/<date>.md --html <briefs_dir>/<date>.html --map ~/morning/state/brief-map-<date>.json`

It prints one JSON line of counts; keep it for Step 6. If it exits 1, fix the JSON it names and run it again.

The "Brief structure" section below still defines what goes in each list.

## Error handling

If any Step 1 sub-fetch fails:
- Show the section with the note "[Source] unavailable: <one-line reason>"
- Continue with the rest of the brief — never block on a single source.

If the entire orchestration fails before rendering, write a one-line error to `~/morning/briefs/<date>-ERROR.md` so the user can see what broke when they next check.

## Brief structure

The model writes the brief JSON (Step 4); `render_brief.py` produces the markdown archive and the page from it. Apply the voice guide at every step.

### Markdown archive layout (produced by render_brief.py)

```markdown
# Morning brief — <Weekday DD MMM YYYY>

> **Today's focus:** <one sentence, see Step 5 below>

## To do

**Urgent today**

Every to-do with `Due` ≤ today. Numbering starts at 1 here. See "To-do rules" below the template for bucket logic and parent/subtask rendering. If nothing is due, omit this sub-heading.

1. <standalone task> (due today)  [<categories>]

*<Parent name>:*

2. <subtask> (due today)  [<categories>]
3. <subtask> (overdue since <date>)  [<categories>]

**Coming up** - N

4. <standalone task> (due <date>)  [<categories>]

**Your actions**

5. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
6. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)

**Product actions**

7. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)

## External meeting prep

<see rules below>

## PRs needing you

**Review requested of you** (N):

- [#<num>](<pr_url>) <title> (<repo>) - opened by <author>, <days> days ago
- [#<num>](<issue_url>) <title> (<repo>) - mentions you

**Yours to chase**

Ready to merge (N):

- [#<num>](<pr_url>) <title> (<repo>)

Awaiting review (N):

- ⚡ [#<num>](<pr_url>) <title> (<repo>) - N reviewers, K days stale
- [#<num>](<pr_url>) <title> (<repo>) - N reviewers, K days stale, changes requested
- [#<num>](<pr_url>) <title> (<repo>) - opened today (no reviewers assigned)

(If both sub-lists are empty: "Nothing waiting on you. Nice.")

## Ideas bank

**Strategic** - N

8. <standalone task>  [<categories>]

*<Parent name 2>:*

9. <subtask>  [<categories>]

**Other** - N

10. <standalone task>  [<categories>]

## Engineering progress

<see rules below>
```

The sections below are the rules for each part of the template above.

### To do and Ideas bank

**Bucket logic** (each task lands in the first matching bucket):
1. **Urgent today** - has `Due` ≤ today. Renders under `**Urgent today**` in `## To do`.
2. **Coming up** - has `Due` after today, ordered by due date. Renders under `**Coming up**` in `## To do`.
3. **Ideas bank** - has no `Due` date. Renders under `## Ideas bank`, split into **Strategic** (`Category` contains `Strategic`) and **Other** (everything else).

Notion rows with `Type: Idea` are still dropped in Step 1; the Ideas bank here is undated to-dos, not parked ideas.

**Parent/subtask rendering.** The Tasks DB has a self-referencing `Parent` / `Subtasks` relation. Tasks split into three kinds:
- **Parent groupers** — `Subtasks` non-empty. These are containers, NOT actionable themselves. Do NOT render parent groupers as task lines. Use their Name as the heading for their child subtasks. If the query returns an empty `Subtasks` field on every row, that view doesn't populate it - infer parent groupers instead from the children's `Parent` relation: any page named by at least one other row's `Parent` field is a grouper, even though its own `Subtasks` field reads empty.
- **Subtasks** — `Parent` non-empty. Bucketed individually by their own Due/Category (see below), but never rendered under more than one heading.
- **Standalone tasks** — both `Parent` and `Subtasks` empty. Bucketed individually.

**Each parent group renders exactly once across Urgent today, Coming up and the Ideas bank together** - never split across buckets, never repeated:
1. Bucket every subtask individually, using the bucket logic above against its own Due/Category.
2. Place the group in the bucket of its most urgent subtask: the bucket of the subtask with the earliest `Due` date. If no subtask in the group has a `Due` date, the group goes to the Ideas bank: **Strategic** if any subtask's `Category` contains `Strategic`, otherwise **Other**. A group whose most urgent subtask is overdue or due today renders only under Urgent today, with all its subtasks.
3. Within that one bucket, render the group once, with its subtasks sorted by `Due` date (undated subtasks last). Each subtask line still shows its own due date.

Within each bucket (Urgent today, Coming up, Strategic, Other): standalone tasks first (flat, no indent, sorted by due date), then parent groups (alphabetically by parent name).

Every bucket heading line is followed by a blank line before its first list item, and a blank line separates one list (a run of standalone tasks, or a parent group's italic name line plus its subtasks) from the next. In CommonMark, an ordered list that doesn't start at 1 cannot interrupt a preceding paragraph, so a numbered line placed right after a heading or after a parent's italic name line - with no blank line between - merges into that line instead of rendering as a list. The same blank-line rule applies to the Your actions and Product actions headings.

A parent group renders as a standalone italic line, `*<Parent name>:*`, on its own with no leading bullet, followed by a blank line, then its numbered subtasks flush-left with no indent.

Each line shows the task title, its due date if any, and its categories as inline `[Tag1, Tag2]` after the title. Numbered lines have no checkbox.

**Numbering.** Every actionable line across the WHOLE brief shares one running number sequence, in page order: Urgent today (starting at 1), Coming up, Your actions, Product actions, Testing, then the Ideas bank (Strategic, then Other). Parent-name sub-headers are not actionable and do not consume a number; only standalone tasks, subtasks and action items do. PR lines are not numbered. The renderer assigns the numbers and writes the map to `~/morning/state/brief-map-<date>.json`; the model never numbers anything.

JSON mapping: Urgent today goes in `urgent`, Coming up in `todos.coming_up`, Strategic in `ideas.strategic`, Other in `ideas.other`.

If every to-do bucket is empty, render `## To do` with "Notion DB is empty. Add tasks at <DB url>". If a sub-heading's list is empty, omit it. If Notion is unavailable, render `## To do` with "Notion unavailable".

### PRs needing you

Filter the PRs from Step 1.4 and 1.5 against the acknowledged-PRs state from Step 1.8. A PR is hidden when its `updatedAt` is less than or equal to the recorded `last_seen_updated_at` (i.e. nothing has happened since the user parked it). Show the PR again when its `updatedAt` moves forward.

PR numbers MUST be wrapped as markdown links to the GitHub URL. PR lines are not numbered: they are parked by PR number in Step 7b.

**Review requested of you** (N): the reviewer-requested PRs from Step 1.4, then the issues / PRs mentioning you in the last 24h from Step 1.5. Review requests read `opened by <author>, <days> days ago`; mentions read `mentions you`. N counts both. Omit the sub-list if empty.

**Yours to chase**: PRs you've authored that are still open (drafts excluded), from Step 1.9. Two buckets, no reviewer names shown (always the same eng team).

Bucket logic:
- **Ready to merge** - `review_decision == "APPROVED"` OR (`latest_approvals` non-empty AND `mergeable == "MERGEABLE"`). The second clause catches the "3 of 4 approved, GitHub still says REVIEW_REQUIRED but the PR is mergeable" case.
- **Awaiting review** - everything else (REVIEW_REQUIRED, CHANGES_REQUESTED, no decision yet, etc).

Per-line annotations:
- Days stale = whole days since `updated_at`. If ≥5 days stale, prefix the line with `⚡` (call to poke).
- If `reviewers_requested` is empty, append ` (no reviewers assigned)` so Lena knows to add them.
- If `review_decision == "CHANGES_REQUESTED"`, append ` - changes requested`.

Omit a bucket or sub-list that is empty. If both sub-lists are empty, write "Nothing waiting on you. Nice."

### Your actions and Product actions

These render inside `## To do`, after Coming up. Numbering continues from the last Coming up item (or from Urgent today if Coming up is empty). Each `**Your actions**` / `**Product actions**` heading is followed by a blank line before its numbered list starts, for the same CommonMark reason.

**Your actions** - action items where you're the owner or named. The action text MUST be wrapped as a markdown link to the Fathom timestamp URL so you can jump into the recording at the exact moment the action was raised.

N. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
N+1. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
...

(If list is empty: write "Nothing carrying over on your own actions. Clean slate.")

**Product actions** - open actions from product-side colleagues (per `fathom.team_action_owners` config). These often land on the user as the only PM. No parenthetical preamble in the rendered brief; just the heading and the list.

N+1. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
N+2. [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
...

Numbering continues sequentially from the Your actions list. Testing then continues from the last action item, and the Ideas bank from the last Testing item. Owner names are NOT shown inline because all entries in this section share the same configured owner(s); putting the name on each line just adds noise. The tick-off prompt in Step 7 accepts any number from anywhere in the brief: Urgent today, Coming up, Your actions, Product actions, Testing or the Ideas bank alike.

(If this list is empty: skip the sub-section entirely.)

### Testing

Merged PRs Lena can try by hand. Write them into the `testing` key of the brief JSON, newest merge first.

- Keep only PRs from Step 1.10 whose key `<repo>#<number>` is not in the acknowledged-tests list and that change something visible or clickable. Drop CI, infra, refactor, test-only and docs PRs.
- `live` comes from the `deploys` the fetch returns for the merge commit, never from the merge itself. Name the environments whose deploy jobs succeeded (for example `dev, staging, prod`). If no deploy run succeeded, write `not deployed yet`; if a run is still going, say so.
- `steps` come from the PR body's test plan when it has one (`inferred: false`). Otherwise write them from the diff and the `files` list (`inferred: true`). Give 2 to 4 steps, each with the environment URL and any test data needed.
- Say plainly when something cannot be tested by hand, for example a change that only runs behind a feature flag or a backend job. Do not invent steps.
- `project` is the name of the project the PR belongs to (match on repo and keywords), or an empty string.
- If there are none, leave `testing` as `[]` and the section is omitted.

### External meeting prep

Only render this section when there's at least one external meeting today (events with `is_external: true`). DO NOT render a calendar listing of all events - the user can check her own calendar. The calendar data is still fetched in Step 1 and used in Step 3 (research), but it does NOT get listed in the brief.

Never repeat a numbered line here in full - each already has its own numbered line elsewhere in the brief. If any numbered item relates to this meeting (by company, client or topic), add one line pointing to it by number instead, e.g. "Your open Moka items are 3 to 8 and 29." Omit the line if nothing relates.

For each external meeting today:

**HH:MM — <Title>**
- Company: <name> — <one-line on what they do>. <Recent news if any>.
- Participants:
  - <Name> — <role at company>
  - ...
- (If recent news or anything notable, one line.)
- (If related numbered items exist, one line per the rule above.)

(If no external meetings: skip this section entirely.)

### Engineering progress

Projects whose slug starts with `client-` are commercial partners, not engineering initiatives. Skip them in the loop below entirely - they render together at the end of this section instead, under "Partners - next actions".

For each remaining project from the projects index with `status` other than `done`, ordered active first, then blocked, then waiting:

**<name>** - <owner>, <status>, next: <next_milestone if present>, target <target_date if present>

<one-liner: the first paragraph under `## Where it is` in the project body>

(If `stale` is true, append on its own line: `Not reviewed since <last_reviewed or "never">. Update ~/product-os/projects/<slug>.md.`)

Team sync notes (from <meeting title>, <date>): <one or two lines distilled from the Fathom summary - only if a matching team sync summary exists>.

**PR relevance.** A project's PR list only shows PRs that actually relate to that project:
- No `keywords` set on the project (even if it has `repos`) → skip the list and write: `GitHub: no keywords set, add some to ~/product-os/projects/<slug>.md.`
- Otherwise, a PR relates to a project when it matched that project's keyword search from Step 2. If the same PR matches more than one project's keywords (shared repo, overlapping terms), attribute it to the single best-matching project only - never list the same PR under two projects.
- Keywords set but nothing matched → write: `GitHub: no related PRs this week.`
- Otherwise, render:

GitHub: <N PRs merged in last 7 days, N open>
- Open PRs (PR numbers MUST be markdown links to the PR URL):
  - [#<num>](<pr_url>) <title> (<repo>) - <state>, updated <relative>
  - ...

The counts and list cover related PRs only - never the full, unfiltered set the repo-level fetch returned.

**Partners - next actions**

One bullet per `client-` project, in place of the full block above:

- **<name>** (<owner>[, <status> if not active]): <next_milestone>[, target <target_date>]

No "Where it is" paragraph, no team sync notes, no GitHub subsection, for these. (If there are no commercial partner projects, omit this heading entirely.)

### How to choose the one-sentence focus (Step 5)

Synthesise across:
- Items overdue or urgent in to-dos
- Projects marked `blocked` or `waiting` where you're the owner
- External meetings (if there's a major one, prep IS the focus)

Pick ONE thing. Write it as a single imperative sentence, ≤14 words. No softening. No prefix like "Your focus today is...". Just the focus.

Examples (good):
- "Ship the carbon factors merchant-config doc."
- "Get sign-off on the SDK v2 schema before the 11am with Acme."

Examples (bad):
- "Today, you might want to consider working on the OKRs." (hedged)
- "Focus on engineering progress." (vague)
- "Do the things from your to-do list." (useless)

## Step 6: Publish and present

1. Publish `<briefs_dir>/<date>.html` with the Artifact tool. If `output.artifact_url` is set: first `read` that URL (a publish to an artifact this conversation hasn't read is refused), then publish with `url` set to it, no `icon`. If it is empty: publish without `url`, with `icon: "calendar"` and `description: "Lena's daily morning brief"`, and tell Lena to paste the returned URL into `output.artifact_url` in `~/morning/config.yaml`.
2. Print only this in chat:
   - `**<weekday_label>** - <focus>`
   - one line of counters from the renderer: `Urgent N (M overdue) · PRs: R to review, K ready, A awaiting · Your actions N · Meetings N` (drop any part that is 0, except Urgent)
   - the artifact link
   - `Saved: <briefs_dir>/<date>.md`
3. If publishing fails for any reason, say so in one line and print the full markdown archive inline instead, verbatim. Lena must never end up with neither.

## Step 7: Action item tick-off

If the brief has any numbered lines (To do, Testing or Ideas bank):

1. Print exactly: `Already done any? (numbers comma-separated, blank to skip):`
2. Wait for the user's reply in the same conversation.
3. Parse the response: split on commas, strip whitespace, drop anything that isn't a positive integer or that exceeds `max_number` from the renderer's counts (also derivable as the largest key in the map).
4. For each valid number, look it up in `~/morning/state/brief-map-<date>.json` (`numbers[<n>]` gives `{kind: notion, id}`, `{kind: fathom, key}` or `{kind: test, key}`).
5. For a Notion to-do: update that page's `Status` property to `Done` via the Notion MCP.
6. For a Fathom action: run `python3 ~/github/morning/scripts/ack_action.py <key1> <key2> ...` (batch all such keys into one call).
7. For a Testing item (kind `test`): run `python3 ~/github/morning/scripts/ack_test.py <key1> <key2> ...` (batch all such keys into one call).
8. Confirm to the user: `Marked N item(s) done. They won't appear tomorrow.`

If the brief had no numbered lines, skip this step entirely.

Unattended runs (scheduled, no user present) never run this step. Step 0 still prints any pending project updates and stops; nothing is accepted or rejected until the user replies.

## Step 7b: PR park

If "Review requested of you" in PRs needing you surfaced any PRs (after the state filter):


1. Print exactly: `Park any of these PRs until they update? (PR numbers e.g. "182,5", blank to skip):`
2. Wait for the user's reply.
3. For each PR number, look up its URL and `updatedAt` from the data fetched in Step 1.4.
4. Run: `python3 ~/github/morning/scripts/ack_pr.py "<pr_url>" "<updated_at_iso>"`
5. Confirm: `Parked N PR(s). They'll resurface only if updated.`

If no PRs surfaced, skip this step entirely.

## Step 8: Final confirmation

Print one summary line like: `Done.`

No other follow-up questions. No "would you like me to..." offers. The page link is the deliverable.
