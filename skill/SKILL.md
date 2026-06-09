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

1. **To-dos** — Notion MCP. Use `notion-search` with `data_source_url: collection://<todo_database_id from config's data source>` to list pages in the Tasks DB. Increase `page_size` to 25 (max) and `max_highlight_length: 0`. Then `notion-fetch` each page to read properties (Name, Due, Status, Category, Type, Client, Area, Parent, Subtasks). Filter out `Status: Done`. Keep `Parent` and `Subtasks` fields — they drive the parent/subtask rendering in the brief. If MCP unavailable, mark to-dos section as "Notion unavailable".

2. **Calendar** — Bash: `python3 ~/github/morning/scripts/fetch_calendar.py "<ekko_email_domain>" "<primary_calendar>"` (both values from config; second arg restricts gcalcli to your own calendar so shared calendars don't clutter the brief)

3. **Initiatives index** — Bash: `python3 ~/github/morning/scripts/parse_initiatives.py "<initiatives_file from config>"`

4. **GitHub reviewer-requested** — Bash: `~/github/morning/scripts/fetch_github.sh reviewer-requested`

5. **GitHub mentions** — Bash: `~/github/morning/scripts/fetch_github.sh mentions`

6. **Fathom meetings** — Use the Fathom MCP tools:
   - First: `list_meetings` filtered to the last `fathom.lookback_days` days (default 7).
   - Then in parallel: `get_meeting_summary` for each meeting returned.
   - If the MCP is unavailable, mark the "Yesterday's meetings" and "Open action items" sections as "Fathom unavailable" and continue.

7. **Acknowledged action items** — Bash: `cat ~/morning/state/acknowledged-actions.json 2>/dev/null || echo "[]"`

8. **Acknowledged PRs state** — Bash: `cat ~/morning/state/acknowledged-prs.json 2>/dev/null || echo "[]"`

9. **Your own open PRs** — Bash: `~/github/morning/scripts/fetch_github.sh authored`. Returns non-draft PRs you authored, enriched with `review_decision`, `reviewers_requested`, `latest_approvals`, `mergeable`. Used by the "Your PRs" section.

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
   - Classify into one of two buckets:
     - **Your actions** — owner equals `fathom.user_name` from config, OR owner is unspecified and the action text mentions `fathom.user_name`.
     - **Team actions** — actions owned by anyone in `fathom.team_action_owners` from config (case-insensitive substring match on the owner string, so "Etienne" matches "Etienne Smith"). These are the people whose work the user might absorb or needs to track (typically managers, peers in tight collaboration). Other owners are excluded entirely. If `team_action_owners` is empty or missing, no team actions are surfaced.
   - Filter out (from EITHER bucket) any action whose key is in the acknowledged-actions list from Step 1.7. Tick-off works the same way regardless of bucket.
   - Cap the team actions bucket at 20 items, ordered by meeting date descending then by position within the meeting. The user can manually look in Fathom for older ones.

2. **Standup classification.** For each meeting:
   - If the title matches `fathom.standup_title_regex`, flag it as a standup.
   - Capture the summary text for embedding into the engineering progress section. If the summary mentions specific initiatives (match against the names from the initiatives index), attach the summary to that initiative's block. Otherwise attach as a top-level "Standup notes" line under engineering progress.

3. **Recent meetings list.** For each non-standup meeting in the lookback window, prepare a single line. EXCLUDE any meeting that already contributed at least one item to the open action items list — that meeting's relevant context is already surfaced via the action's Fathom link, and listing it again is duplicative. Standups are also excluded here (they appear under engineering progress).

## Step 5: Render the brief

Use the voice guide section above. The full brief structure is in the next section of this skill file (continued in part 2).

## Error handling

If any Step 1 sub-fetch fails:
- Show the section with the note "[Source] unavailable: <one-line reason>"
- Continue with the rest of the brief — never block on a single source.

If the entire orchestration fails before rendering, write a one-line error to `~/morning/briefs/<date>-ERROR.md` so the user can see what broke when they next check.

## Brief structure

Produce the brief as a single markdown file. Apply the voice guide at every step.

### Template

```markdown
# Morning brief — <Weekday DD MMM YYYY>

> **Today's focus:** <one sentence, see Step 6 below>

## To-dos

**Bucket logic** (in priority order, each task lands in the first matching bucket):
1. **Urgent / due today** — has `Due` ≤ today.
2. **This week** — has `Due` in the rest of this calendar week.
3. **Strategic** — `Category` contains `Strategic` (regardless of date, unless already shown above).
4. **Later** — everything else (no date and not Strategic).

**Parent/subtask rendering.** The Tasks DB has a self-referencing `Parent` / `Subtasks` relation. Tasks split into three kinds:
- **Parent groupers** — `Subtasks` non-empty. These are containers, NOT actionable themselves. Do NOT render parent groupers as task lines. Use their Name as the heading for their child subtasks.
- **Subtasks** — `Parent` non-empty. Bucketed individually by their own Due/Category.
- **Standalone tasks** — both `Parent` and `Subtasks` empty. Bucketed individually.

Within each bucket:
1. Group the bucket's subtasks by their Parent's Name.
2. For each parent group, render the parent name as an italic sub-header, then indent the subtasks under it.
3. Render standalone tasks as flat list items, no indent.
4. Sort: standalone tasks first, then parent groups alphabetically by parent name.

Each line shows the task title, its due date if any, and its categories as inline `[Tag1, Tag2]` after the title.

Example shape:

**Urgent / due today** — N
- <standalone task> (due today)  [<categories>]
- *<Parent name>:*
  - <subtask> (due today)  [<categories>]
  - <subtask> (due today)  [<categories>]

**This week** — N
- <standalone task> (due <date>)  [<categories>]
- *<Parent name>:*
  - <subtask> (due <date>)  [<categories>]

**Strategic** — N
- <standalone task> (<due date if any>)  [<categories>]
- *<Parent name>:*
  - <subtask> (<due date if any>)  [<categories>]

**Later** — N
- <standalone task>  [<categories>]
- *<Parent name>:*
  - <subtask>  [<categories>]

If a bucket is empty, omit its sub-heading entirely. If ALL buckets are empty, write "Notion DB is empty. Add tasks at <DB url>".

## External meeting prep

Only render this section when there's at least one external meeting today (events with `is_external: true`). DO NOT render a calendar listing of all events — the user can check her own calendar. The calendar data is still fetched in Step 1 and used in Step 4 (research), Step 3 (gap computation) and Strategic-slot fit (deep-work block detection), but it does NOT get listed in the brief.

For each external meeting today:

**HH:MM — <Title>**
- Company: <name> — <one-line on what they do>. <Recent news if any>.
- Participants:
  - <Name> — <role at company>
  - ...
- (If recent news or anything notable, one line.)

(If no external meetings: skip this section entirely.)

## Engineering progress

For each initiative from initiatives.md:

**<Name>** — <owner>, <status>, target <date if present>

<one-liner: your own free-text status from initiatives.md>

Standup notes (from <meeting title>, <date>): <one or two lines distilled from the Fathom summary — only if a matching standup summary exists>.

GitHub:
- <N PRs merged in last 7 days, N open>
- Open PRs (PR numbers MUST be markdown links to the PR URL):
  - [#<num>](<pr_url>) <title> (<repo>) — <state>, updated <relative>
  - ...

(If no recent activity at all: write "No recent activity.")

## Awaiting your input

Filter the PRs from Step 1.4 against the acknowledged-PRs state from Step 1.10. A PR is hidden when its `updatedAt` is less than or equal to the recorded `last_seen_updated_at` (i.e. nothing has happened since the user parked it). Show the PR again when its `updatedAt` moves forward.

PR numbers MUST be wrapped as markdown links to the GitHub URL.

PRs requesting your review (N):
- [#<num>](<pr_url>) <title> (<repo>) — opened by <author>, <days> days ago

Issues / PRs mentioning you in the last 24h (N):
- [#<num>](<issue_url>) <title> (<repo>)

(If both lists are empty, write "Nothing waiting on you. Nice.")

## Your PRs

PRs you've authored that are still open (drafts excluded). Two buckets, no reviewer names shown (always the same eng team).

**Bucket logic:**
- **Ready to merge** — `review_decision == "APPROVED"` OR (`latest_approvals` non-empty AND `mergeable == "MERGEABLE"`). The second clause catches the "3 of 4 approved, GitHub still says REVIEW_REQUIRED but the PR is mergeable" case.
- **Awaiting review** — everything else (REVIEW_REQUIRED, no decision yet, etc).

**Per-line annotations:**
- Days stale = whole days since `updated_at`. If ≥5 days stale, prefix the line with `⚡` (call to poke).
- If `reviewers_requested` is empty, append ` (no reviewers assigned)` so Lena knows to add them.

**Ready to merge (N):**
- [#<num>](<pr_url>) <title> (<repo>)

**Awaiting review (N):**
- ⚡ [#<num>](<pr_url>) <title> (<repo>) — N reviewers, K days stale
- [#<num>](<pr_url>) <title> (<repo>) — N reviewers, K days stale
- [#<num>](<pr_url>) <title> (<repo>) — opened today (no reviewers assigned)

(If both buckets empty, write "Nothing of yours in flight.")

## Open action items

**Your actions** — action items where you're the owner or named. Numbered list. The action text MUST be wrapped as a markdown link to the Fathom timestamp URL so you can jump into the recording at the exact moment the action was raised.

1. [ ] [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
2. [ ] [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
...

(If list is empty: write "Nothing carrying over on your own actions. Clean slate.")

**Product actions** — open actions from product-side colleagues (per `fathom.team_action_owners` config). These often land on the user as the only PM. No parenthetical preamble in the rendered brief; just the heading and the list.

N+1. [ ] [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
N+2. [ ] [<action text>](<fathom_timestamp_url>) (from "<meeting title>", <date>)
...

Numbering continues sequentially from the Your actions list. Owner names are NOT shown inline because all entries in this section share the same configured owner(s); putting the name on each line just adds noise. The tick-off prompt accepts any number across both lists.

(If this list is empty: skip the sub-section entirely.)

## Time blocked for deep work

Lena schedules her own deep-work blocks on the calendar. The point of this section is to surface those blocks (so she sees at a glance how much focus time she's already secured) and only suggest a free gap if it's worth flagging.

1. **Identify self-scheduled deep-work blocks.** From today's calendar, pick events where the only attendee is the user (or the event has no other attendees) AND the title is descriptive of a work block rather than a routine ceremony. Heuristics:
   - INCLUDE: titles like `OSTs`, `OST`, `Deep work`, `Focus`, any initiative name (matched against the initiatives index), product-y titles like `Optty flow`, `Nature Footprint: Tech Spec`.
   - EXCLUDE: `Stand up`, `Lunch`, `Catch up`, `1:1`, any title with another person's name, recurring ceremonies, breaks.
2. **List them in one short paragraph**, summing total time: e.g. *"You've blocked 3h45 for deep work: OSTs 10:00–12:00, Nature Footprint tech spec 14:30–15:30, plus the 30-min Optty flow at 11:30. The Nature Footprint slot is the highest-leverage of these (mid-June deadline)."*
3. **If gaps ≥45 min remain on top of those blocks**, mention them in one line: *"If you want more focus time, there's a 60-min open slot at 15:30."* If no gaps, skip.

(If no self-scheduled deep blocks AND no free gaps: "No deep-work window today, and you haven't scheduled any. Consider blocking time tomorrow.")
(If Notion Strategic bucket has items AND there's a free gap, append one sentence matching one strategic item to the gap — but keep the deep-blocks listing as the primary content of this section.)
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

## Step 8b: PR park

If "Awaiting your input" surfaced any PRs (after the state filter):

1. Print exactly: `Park any of these PRs until they update? (PR numbers e.g. "182,5", blank to skip):`
2. Wait for the user's reply.
3. For each PR number, look up its URL and `updatedAt` from the data fetched in Step 1.4.
4. Run: `python3 ~/github/morning/scripts/ack_pr.py "<pr_url>" "<updated_at_iso>"`
5. Confirm: `Parked N PR(s). They'll resurface only if updated.`

If no PRs surfaced, skip this step entirely.

## Step 9: Final confirmation

Print one summary line like: `Done.`

No other follow-up questions. No "would you like me to..." offers. The brief is the deliverable.
