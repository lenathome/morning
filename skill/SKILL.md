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

2. **Calendar** — Bash: `python3 ~/github/morning/scripts/fetch_calendar.py "<ekko_email_domain>" "<primary_calendar>"` (both values from config; second arg restricts gcalcli to your own calendar so shared calendars don't clutter the brief)

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
