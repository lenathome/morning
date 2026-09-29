---
name: session-sweep
description: Runs before the morning brief (or when Lena says "sweep sessions"). Logs every Claude Code session since the last run into the daily digest in ~/ai-log/ and queues proposed project-file updates for the brief to show.
---

# session-sweep - unattended session log and project-update proposals

You are sweeping Lena's Claude Code sessions since the last run. This runs unattended, just before the morning brief. Follow this skill exactly. Nothing you write here is shown as prose to Lena: the digest is a factual record and the proposals are surfaced later by the brief.

## Unattended rules

- The only writes allowed: the digest files in `~/ai-log/`, the proposals queue (through `proposals.py`) and `~/morning/state/sweep-last-run.txt`.
- Never edit project files in `~/product-os/projects/`. Proposals only.
- Never accept or reject a proposal. That happens in the brief.
- Never ask a question. If something is ambiguous, skip it and count it as skipped.
- If the extractor fails, stop without updating the last-run file and say why in one line.

## Step 1: Work out the window

1. Read `~/morning/state/sweep-last-run.txt` with the Read tool. It holds one ISO 8601 timestamp. If the file is missing, use 48 hours ago.
2. Record this run's own start time now: `date -u +%Y-%m-%dT%H:%M:%SZ`. Keep it for Step 6. Do not use the time you finish.

## Step 2: Extract sessions

```
python3 ~/github/morning/scripts/extract_sessions.py --since "<last-run timestamp>" --exclude-session "$CLAUDE_CODE_SESSION_ID"
```

It prints a JSON array. Each session has: `session_id, cwd, git_branch, title, started_at, ended_at, scheduled_task` (name or null), `human_turns`, `messages` (each `{role, at, text}`).

If the command exits non-zero, stop. Do not touch the last-run file. Output one line: `Sweep failed: <first line of stderr>`.

## Step 3: Decide what to log

Skip a session when any of these hold:

- `scheduled_task` starts with `morning-brief` (this also covers `morning-brief-format-check`) or is `session-sweep`.
- It was one quick question with nothing written, decided or left open. Anything else gets an entry, including dead ends: a record of what did not work is worth keeping.
- It is already logged and nothing has happened since. Check with `grep -rl "<!-- session: <session_id>" ~/ai-log/`. If found, read that entry's time range. If the session has no messages after the entry's end time, write no digest entry for it, but still take it through Step 5 (the queue drops duplicate proposals). If it has, do not skip: append an `### Update - HH:MM` under the existing section (Step 4).

Count every skipped session for the final output.

## Step 4: Write the digest

One file per local calendar date of the session's `ended_at`: `~/ai-log/YYYY-MM-DD.md`. Create the directory if needed. If the file is missing, create it with the first line `# ai-log YYYY-MM-DD`. Never overwrite. Always append. Several sessions ending on the same date share one file, one section each.

Section format:

```markdown
## <short description of the session>
<!-- session: <session_id> · cwd: <cwd> · <HH:MM>-<HH:MM> -->

### What was built or changed
- ...

### Key decisions made
- <decision>: <why>

### Follow-ups identified
- ...
```

Times are local, from `started_at` and `ended_at`. Write `- None` under any empty subsection. Keep the structure.

For a session that already has a section (see Step 3), add this at the end of that section instead of a new one, and use the same three subsections beneath it with only the new material:

```markdown
### Update - HH:MM
```

Update the time range in the comment only if it is easy to do safely; otherwise leave it. The `<!-- session: <session_id>` prefix must stay intact so the next sweep finds it.

### Writing style

Factual record, not prose. Not Lena's voice: do not read the voice profile. 30 seconds to scan.

- Terse fragments, verb-first. 3 to 5 bullets under "What was built or changed".
- Exact figures wherever one exists: PR numbers with full URLs (`https://github.com/...`, never `owner/repo#123`), file counts, test results.
- Spaced hyphen ` - `, never an em dash.
- British spelling.
- No comma before "and", in lists or between clauses.
- "ekko" always lowercase, "ekko Hub" with a space.
- No emojis.
- The reason matters more than the decision.
- Log outcomes, not tool use.
- Every claim comes from the transcript. Infer nothing. If the transcript does not show it, leave it out.

## Step 5: Queue project-update proposals

1. Load the projects index: `python3 ~/github/morning/scripts/parse_projects.py ~/product-os/projects`. If it fails, skip this step, say so in the final output, and do not update the last-run file in Step 6, so the next run proposes for this window again. The digest entries already written stay, and Step 3's already-logged check stops them being written twice.
2. For each session not skipped in Step 3 (including already-logged ones sent here by the third rule), match it to projects by `repos` (the session's `cwd` or PR URLs in the transcript), `keywords` and project names. A session may match none.
3. For each match, propose only changes the session actually established:
   - A new decision or state change: `append` to section `Recent decisions`, text `YYYY-MM-DD: <fact>`.
   - A changed next step: `frontmatter`, field `next_milestone`, with the new value.
   - A new open question: `append` to section `Open questions`.
4. Before proposing, read the project file (`~/product-os/projects/<slug>.md`) and drop anything it already says. Sessions often edit project files directly.
5. At most 3 proposals per session per project.
6. Item shape:
   - `slug`, `kind` (`append` or `frontmatter`), `source`, `session_title`, `session_date`.
   - For `append`: `section` (heading text without `##`) and `text`.
   - For `frontmatter`: `field` and `value`.
   - `source` is `ai-log/YYYY-MM-DD.md, <section heading>`.
   - `text` follows the same style rules as the digest.
7. Pipe the whole batch to the queue in one call:

   ```
   python3 ~/github/morning/scripts/proposals.py add
   ```

   stdin is a JSON array. It prints `{"added": [...], "skipped": [...]}`. Skipped items are duplicates or invalid. Keep both counts for the output. If there is nothing to propose, skip the call.

## Step 6: Record the run

Only after Steps 4 and 5 succeeded, write the start time recorded in Step 1 to `~/morning/state/sweep-last-run.txt` (one line, the ISO timestamp, nothing else). If any earlier step failed, leave the file as it was so the next run covers the same window.

## Step 7: Output

Nothing but this:

- One line per session logged: `<digest path> - <section heading>`.
- `Proposals added: N` (add `, skipped: M` if any were skipped, with one short line each for the reason).
- `Sessions skipped: N`.

No other prose.
