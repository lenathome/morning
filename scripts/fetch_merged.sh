#!/usr/bin/env bash
# fetch_merged.sh — fetch recently merged PRs and their deploy runs, for the Testing tab.
#
# Usage:
#   fetch_merged.sh <repo,repo> [days]
#
# A repo without a slash is looked up in the ekko-enviroconomy org. days defaults to 3.
#
# Output (stdout): one JSON array, one element per merged PR:
#   [{repo, number, title, url, body, mergedAt, author, files (paths only),
#     deploys: [{workflow, status, conclusion, jobs: [{name, conclusion}]}]}]
# Deploys are the workflow runs on the merge commit whose name matches deploy|release|publish.
# A repo that fails prints one warning line to stderr and is skipped.

set -uo pipefail

repos="${1:-}"
days="${2:-3}"
if [[ -z "$repos" ]]; then
  echo "usage: fetch_merged.sh <repo,repo> [days]" >&2
  exit 2
fi

# macOS date first, GNU date as the fallback.
since=$(date -v-"${days}"d +%Y-%m-%d 2>/dev/null || date -d "${days} days ago" +%Y-%m-%d)

results=()
IFS=',' read -ra repo_arr <<< "$repos"
for r in "${repo_arr[@]}"; do
  r="${r// /}"
  [[ -z "$r" ]] && continue
  full="$r"
  [[ "$r" == */* ]] || full="ekko-enviroconomy/$r"

  if ! prs=$(gh pr list -R "$full" --state merged --search "merged:>=$since" --limit 30 \
      --json number,title,url,body,mergedAt,author,mergeCommit,files 2>/dev/null); then
    echo "warning: could not list merged PRs for $full, skipped" >&2
    continue
  fi

  while read -r pr; do
    oid=$(echo "$pr" | jq -r '.mergeCommit.oid // ""')
    deploys="[]"
    if [[ -n "$oid" ]]; then
      runs=$(gh run list -R "$full" --commit "$oid" --json workflowName,status,conclusion,databaseId 2>/dev/null || echo "[]")
      deploy_runs=$(echo "$runs" | jq -c '.[] | select(.workflowName | test("deploy|release|publish"; "i"))')
      while read -r run; do
        [[ -z "$run" ]] && continue
        id=$(echo "$run" | jq -r '.databaseId')
        jobs=$(gh run view "$id" -R "$full" --json jobs --jq '[.jobs[] | {name, conclusion}]' 2>/dev/null || echo "[]")
        deploys=$(jq -c --argjson run "$run" --argjson jobs "$jobs" \
          '. + [{workflow: $run.workflowName, status: $run.status, conclusion: $run.conclusion, jobs: $jobs}]' <<< "$deploys")
      done <<< "$deploy_runs"
    fi
    results+=("$(jq -c --arg repo "$r" --argjson deploys "$deploys" '{
      repo: $repo, number, title, url, body, mergedAt,
      author: (.author.login // ""),
      files: [(.files // [])[] | .path],
      deploys: $deploys
    }' <<< "$pr")")
  done < <(echo "$prs" | jq -c '.[]')
done

if [[ ${#results[@]} -eq 0 ]]; then
  echo "[]"
else
  printf '%s\n' "${results[@]}" | jq -s '.'
fi
