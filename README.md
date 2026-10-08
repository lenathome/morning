# morning

A personal Claude Code skill that produces a daily morning brief - urgent to-dos, PRs needing you, open action items, to-dos, external meeting prep and engineering progress per project, plus a one-sentence focus for the day.

This is **my own tool**, not an ekko team tool. The pattern is partly inspired by [Ryan's morning tool](https://github.com/ryanharmuth-ekko/crazy-experiments/tree/main/morning) (built for dispatching engineering work) and the Anthropic morning brief pattern, but tailored to the Head of Product job.

## Status

Running since 2026-05-26. Phase 1 of the product OS (2026-09) moved project context out of `initiatives.md` and into `~/product-os/projects/*.md`. Design history: [docs/specs/2026-05-26-morning-tool-design.md](docs/specs/2026-05-26-morning-tool-design.md); the product OS design lives in `~/docs/specs/2026-09-03-product-os-design.md`.

## Repo layout

```
~/github/morning/        # this repo - skill code, scripts, spec, templates
~/morning/               # local machine state - config, daily briefs, ack state
~/product-os/            # curated context repo - projects/*.md is read by the brief
```

## The page

Step 4 writes the brief as JSON; `scripts/render_brief.py` numbers it and writes the markdown archive, a tabbed HTML page and the tick-off map. Step 6 publishes the page to the artifact URL in `output.artifact_url` and prints only the focus, counters and the link. Ticking off stays in chat, by number. Every to-do carries a tag (needs-Lena, split or handoff) saying who should own it. Step 6 also runs `scripts/publish_brief.sh`, which commits a shared markdown copy (without the external meeting prep) to `briefs/` in the product-os repo and pushes it to origin/main.

## session-sweep

A second skill, `sweep/SKILL.md`, runs unattended just before the brief (or when I say "sweep sessions"). It reads every Claude Code session since its last run, appends a digest of each to `~/ai-log/YYYY-MM-DD.md` and queues proposed updates to the project files in `~/product-os/projects/`. It never edits a project file. The brief opens with the queued proposals as a numbered list (Step 0). I reply with the numbers to apply, "all" or "none" before the brief is built.

State lives in `~/morning/state/`:

- `sweep-last-run.txt` - start time of the last successful sweep. The next run reads sessions since then.
- `project-proposals.json` - pending proposals. `project-proposals-log.json` keeps the resolved ones.

Install:

```
ln -s ~/github/morning/sweep ~/.claude/skills/session-sweep
```

## Tests

```
python3 -m unittest discover -s tests -v
```
