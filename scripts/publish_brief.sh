#!/usr/bin/env bash
# publish_brief.sh - commit the shared brief markdown into a second repo and push it.
#
# Usage: publish_brief.sh <date YYYY-MM-DD> <shared-md path> <repo path>
#
# Copies the file to <repo>/briefs/<date>.md and <repo>/briefs/latest.md, commits
# only those two paths (unrelated edits in the repo are never swept in) and pushes
# HEAD to origin/main. Never rebases, merges or force-pushes.
#
# stdout: one final JSON line {"committed": bool, "pushed": bool, "reason": "..."}.
# Exit codes: 0 ok (including nothing to commit), 1 bad args or git error,
# 2 push skipped (unpushed commits outside briefs/), 3 push skipped (behind
# origin/main), 4 push failed.

set -u
export GIT_TERMINAL_PROMPT=0

if [ "$#" -ne 3 ]; then
  echo "usage: publish_brief.sh <date YYYY-MM-DD> <shared-md path> <repo path>" >&2
  exit 1
fi
date="$1"
src="$2"
repo="${3/#\~/$HOME}"

result() {
  # result <committed> <pushed> <reason>: the reasons are fixed strings, so no escaping is needed.
  printf '{"committed": %s, "pushed": %s, "reason": "%s"}\n' "$1" "$2" "$3"
}

if ! [[ "$date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "bad date: $date (want YYYY-MM-DD)" >&2
  result false false "bad date"
  exit 1
fi
if [ ! -f "$src" ]; then
  echo "shared markdown not found: $src" >&2
  result false false "shared markdown not found"
  exit 1
fi
if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
  echo "not a git repo: $repo" >&2
  result false false "not a git repo"
  exit 1
fi

mkdir -p "$repo/briefs" || { result false false "cannot create briefs/"; exit 1; }
cp "$src" "$repo/briefs/$date.md" && cp "$src" "$repo/briefs/latest.md" \
  || { result false false "copy failed"; exit 1; }

dated="briefs/$date.md"
latest="briefs/latest.md"

git -C "$repo" add -- "$dated" "$latest" || { result false false "git add failed"; exit 1; }

committed=false
if git -C "$repo" diff --cached --quiet -- "$dated" "$latest"; then
  echo "nothing changed in briefs/ - no commit"
else
  if ! git -C "$repo" commit -q -m "brief $date" -- "$dated" "$latest"; then
    result false false "git commit failed"
    exit 1
  fi
  committed=true
fi

# Push gate. Only commits that touch briefs/ alone may leave this machine.
if ! fetch_err=$(git -C "$repo" fetch -q origin 2>&1); then
  echo "$fetch_err" >&2
  result "$committed" false "fetch failed"
  exit 4
fi

outside=$(git -C "$repo" log origin/main..HEAD --name-only --pretty=format: | grep -v '^$' | grep -v '^briefs/' || true)
merges=$(git -C "$repo" rev-list --merges origin/main..HEAD)
if [ -n "$outside" ] || [ -n "$merges" ]; then
  echo "push skipped: unpushed commits outside briefs/"
  result "$committed" false "unpushed commits outside briefs/"
  exit 2
fi

behind=$(git -C "$repo" rev-list --count HEAD..origin/main)
if [ "$behind" != "0" ]; then
  echo "push skipped: behind origin/main"
  result "$committed" false "behind origin/main"
  exit 3
fi

ahead=$(git -C "$repo" rev-list --count origin/main..HEAD)
if [ "$ahead" = "0" ]; then
  echo "nothing to push"
  result "$committed" false "nothing to push"
  exit 0
fi

if ! push_err=$(git -C "$repo" push -q origin HEAD:main 2>&1); then
  echo "$push_err" >&2
  result "$committed" false "push failed"
  exit 4
fi

result "$committed" true "pushed"
