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
