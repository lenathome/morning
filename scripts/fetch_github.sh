#!/usr/bin/env bash
# fetch_github.sh — fetch GitHub signal for the morning brief.
#
# Subcommands:
#   initiative <repo,repo> <keyword,keyword>   list recent PRs (last 7 days) matching repos + any keyword
#   reviewer-requested                          PRs where the current user is requested as reviewer
#   mentions                                    issues/PRs mentioning the current user updated in last 24h
#
# Output (stdout): JSON.
# Errors → stderr, non-zero exit.

set -euo pipefail

GH_USER=$(gh api user --jq .login 2>/dev/null || echo "")
if [[ -z "$GH_USER" ]]; then
  echo "gh not authenticated" >&2
  exit 1
fi

subcommand="${1:-}"
case "$subcommand" in

  initiative)
    repos="${2:-}"
    keywords="${3:-}"
    if [[ -z "$repos" ]]; then
      echo "usage: fetch_github.sh initiative <repo,repo> [keyword,keyword]" >&2
      exit 2
    fi

    # Scope to repos, last 7 days, any keyword in title.
    week_ago=$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d "7 days ago" +%Y-%m-%d)

    # Build --repo flags (gh accepts multiple). Assume ekko-enviroconomy org.
    repo_flags=()
    IFS=',' read -ra repo_arr <<< "$repos"
    for r in "${repo_arr[@]}"; do
      repo_flags+=(--repo "ekko-enviroconomy/${r// /}")
    done

    # Build the command as an array. Optional keyword qualifiers append as positional args.
    cmd=(gh search prs "${repo_flags[@]}" --updated ">=$week_ago" --json number,title,url,state,author,repository,updatedAt --limit 30)
    if [[ -n "$keywords" ]]; then
      IFS=',' read -ra kw_arr <<< "$keywords"
      for k in "${kw_arr[@]}"; do
        cmd+=("${k} in:title")
      done
    fi

    "${cmd[@]}" 2>/dev/null || echo "[]"
    ;;

  reviewer-requested)
    gh search prs --review-requested="@me" --state=open \
      --json number,title,url,repository,author,updatedAt --limit 30 \
      2>/dev/null || echo "[]"
    ;;

  mentions)
    day_ago=$(date -v-1d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "1 day ago" +%Y-%m-%dT%H:%M:%SZ)
    gh search issues --mentions="@me" --updated=">$day_ago" \
      --json number,title,url,repository,author,updatedAt --limit 30 \
      2>/dev/null || echo "[]"
    ;;

  *)
    echo "usage: fetch_github.sh {initiative <repos> [keywords] | reviewer-requested | mentions}" >&2
    exit 2
    ;;
esac
