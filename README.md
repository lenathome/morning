# morning

A personal Claude Code skill that produces a daily morning brief - to-dos, external meeting prep, engineering progress per project, GitHub items awaiting input, your open PRs, open action items and deep-work blocks, plus a one-sentence focus for the day.

This is **my own tool**, not an ekko team tool. The pattern is partly inspired by [Ryan's morning tool](https://github.com/ryanharmuth-ekko/crazy-experiments/tree/main/morning) (built for dispatching engineering work) and the Anthropic morning brief pattern, but tailored to the Head of Product job.

## Status

Running since 2026-05-26. Phase 1 of the product OS (2026-09) moved project context out of `initiatives.md` and into `~/product-os/projects/*.md`. Design history: [docs/specs/2026-05-26-morning-tool-design.md](docs/specs/2026-05-26-morning-tool-design.md); the product OS design lives in `~/docs/specs/2026-09-03-product-os-design.md`.

## Repo layout

```
~/github/morning/        # this repo - skill code, scripts, spec, templates
~/morning/               # local machine state - config, daily briefs, ack state
~/product-os/            # curated context repo - projects/*.md is read by the brief
```

## Tests

```
python3 -m unittest discover -s tests -v
```
