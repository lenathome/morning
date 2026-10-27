#!/usr/bin/env bash
# commit_curated.sh - commit named curated files in a repo and push them to origin/main.
#
# Usage: commit_curated.sh <repo> <message> <path> [<path> ...]
#
# Commits exactly the given paths (relative to <repo>) and pushes HEAD to origin/main.
# Used for project-file updates the user accepted and curated edits the user asked to
# commit. Anything else staged or modified in the repo is never swept in. Never resets,
# stashes, rebases, force-pushes or touches files outside the given paths.
#
# Refuses (exit 1, nothing committed) when: fewer than 3 args, <repo> is not a git repo,
# the current branch is not main, or a path is absolute, contains "..", is under briefs/
# (publish_brief.sh owns that), or neither exists in the repo nor is a tracked deletion.
#
# If origin/main is ahead and local has no unpushed commits, fast-forwards first. If local
# is both ahead and behind it does not merge: the commit stays local and the push is skipped.
#
# stdout: one final JSON line {"committed": bool, "pushed": bool, "reason": "..."}.
# Exit codes: 0 ok (including nothing to commit or push), 1 bad args or git error,
# 3 cannot catch up with origin/main (diverged, or fast-forward refused), 4 fetch or push failed.

set -u
export GIT_TERMINAL_PROMPT=0

result() {
  # result <committed> <pushed> <reason>: the reasons are fixed strings, so no escaping is needed.
  printf '{"committed": %s, "pushed": %s, "reason": "%s"}\n' "$1" "$2" "$3"
}

if [ "$#" -lt 3 ]; then
  echo "usage: commit_curated.sh <repo> <message> <path> [<path> ...]" >&2
  result false false "bad arguments"
  exit 1
fi
repo="${1/#\~/$HOME}"
message="$2"
shift 2
paths=("$@")

if [ -z "$message" ]; then
  echo "empty commit message" >&2
  result false false "empty message"
  exit 1
fi
if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
  echo "not a git repo: $repo" >&2
  result false false "not a git repo"
  exit 1
fi
branch=$(git -C "$repo" symbolic-ref --short -q HEAD || true)
if [ "$branch" != "main" ]; then
  echo "not on main (on '${branch:-detached HEAD}')" >&2
  result false false "not on main"
  exit 1
fi

for p in "${paths[@]}"; do
  norm="$p"
  while [[ "$norm" == ./* ]]; do norm="${norm#./}"; done
  case "$p" in
    /*) echo "absolute path refused: $p" >&2; result false false "absolute path"; exit 1 ;;
    *..*) echo "path with '..' refused: $p" >&2; result false false "path contains .."; exit 1 ;;
    *//*) echo "path with '//' refused: $p" >&2; result false false "malformed path"; exit 1 ;;
  esac
  case "$norm" in
    briefs|briefs/*) echo "briefs/ is published by publish_brief.sh: $p" >&2; result false false "path under briefs/"; exit 1 ;;
  esac
  if [ ! -e "$repo/$p" ] && ! git -C "$repo" ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then
    echo "path not found and not a tracked deletion: $p" >&2
    result false false "path not found"
    exit 1
  fi
done

# Catch up with origin before committing, so a plain fast-forward is still possible.
if ! fetch_err=$(git -C "$repo" fetch -q origin 2>&1); then
  echo "$fetch_err" >&2
  result false false "fetch failed"
  exit 4
fi

ahead=$(git -C "$repo" rev-list --count origin/main..HEAD 2>/dev/null) \
  || { result false false "no origin/main"; exit 1; }
behind=$(git -C "$repo" rev-list --count HEAD..origin/main)
diverged=false
if [ "$behind" != "0" ]; then
  if [ "$ahead" != "0" ]; then
    diverged=true
  elif ! merge_err=$(git -C "$repo" merge -q --ff-only origin/main 2>&1); then
    echo "$merge_err" >&2
    result false false "cannot fast-forward"
    exit 3
  fi
fi

git -C "$repo" add -- "${paths[@]}" || { result false false "git add failed"; exit 1; }

committed=false
if git -C "$repo" diff --cached --quiet -- "${paths[@]}"; then
  echo "nothing changed in the given paths - no commit"
else
  if ! git -C "$repo" commit -q -m "$message" -- "${paths[@]}"; then
    result false false "git commit failed"
    exit 1
  fi
  committed=true
fi

if [ "$diverged" = true ]; then
  echo "push skipped: diverged from origin/main"
  result "$committed" false "diverged from origin/main"
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
