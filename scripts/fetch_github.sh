#!/usr/bin/env bash
# fetch_github.sh — fetch GitHub signal for the morning brief.
#
# Subcommands:
#   initiative <repo,repo> <keyword,keyword>   list recent PRs (last 7 days) matching repos + any keyword (OR'd, one search per keyword, results merged)
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

    # Scope to repos, last 7 days, keywords OR'd (each keyword is its own
    # search — gh search prs joins multiple positional args into a single
    # AND'd query, so ANDing keywords together silently over-narrows results).
    week_ago=$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d "7 days ago" +%Y-%m-%d)

    # Build --repo flags (gh accepts multiple). Assume ekko-enviroconomy org.
    repo_flags=()
    IFS=',' read -ra repo_arr <<< "$repos"
    for r in "${repo_arr[@]}"; do
      repo_flags+=(--repo "ekko-enviroconomy/${r// /}")
    done

    base_fields="number,title,url,state,author,repository,updatedAt"

    if [[ -z "$keywords" ]]; then
      gh search prs "${repo_flags[@]}" --updated ">=$week_ago" --json "$base_fields" --limit 100 2>/dev/null || echo "[]"
    else
      # One search per keyword, quoted as a phrase so multi-word keywords
      # (e.g. "impact receipt") match as a phrase rather than as separate
      # AND'd terms. Merge and dedupe by URL.
      results=()
      IFS=',' read -ra kw_arr <<< "$keywords"
      for k in "${kw_arr[@]}"; do
        k="$(echo "$k" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [[ -z "$k" ]] && continue
        qualifier="\"${k}\" in:title"
        one=$(gh search prs "${repo_flags[@]}" --updated ">=$week_ago" --json "$base_fields" --limit 100 "$qualifier" 2>/dev/null || echo "[]")
        results+=("$one")
      done
      if [[ ${#results[@]} -eq 0 ]]; then
        echo "[]"
      else
        printf '%s\n' "${results[@]}" | jq -s 'add | unique_by(.url)'
      fi
    fi
    ;;

  reviewer-requested)
    # user-review-requested (not review-requested) so we only surface PRs
    # where Lena is named individually, not ones where a team she belongs to
    # (e.g. ekko-dev) is the requested reviewer.
    gh search prs "user-review-requested:@me" --state=open \
      --json number,title,url,repository,author,updatedAt --limit 30 \
      2>/dev/null || echo "[]"
    ;;

  mentions)
    day_ago=$(date -v-1d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "1 day ago" +%Y-%m-%dT%H:%M:%SZ)
    gh search issues --mentions="@me" --updated=">$day_ago" \
      --json number,title,url,repository,author,updatedAt --limit 30 \
      2>/dev/null || echo "[]"
    ;;

  authored)
    # List MY open PRs and enrich each with review state. Drafts are filtered
    # out (the user opted out of surfacing drafts in the brief).
    #
    # gh search prs doesn't expose reviewDecision/reviewRequests, so we fetch
    # the list via search and then one gh pr view per PR. Slow (~1s per PR)
    # but only runs once per /morning invocation.
    raw=$(gh search prs --author=@me --state=open \
      --json number,title,url,repository,createdAt,updatedAt,isDraft \
      --limit 30 2>/dev/null || echo "[]")

    echo "$raw" | jq -c '.[] | select(.isDraft == false)' | while read -r pr; do
      num=$(echo "$pr" | jq -r '.number')
      repo=$(echo "$pr" | jq -r '.repository.nameWithOwner')
      detail=$(gh pr view "$num" -R "$repo" \
        --json reviewDecision,reviewRequests,latestReviews,mergeable \
        2>/dev/null || echo "{}")

      jq -n --argjson pr "$pr" --argjson detail "$detail" '
        $pr + {
          review_decision: ($detail.reviewDecision // ""),
          reviewers_requested: [ ($detail.reviewRequests // [])[] | (.login // .name // "?") ],
          latest_approvals: [ ($detail.latestReviews // [])[] | select(.state == "APPROVED") | .author.login ],
          mergeable: ($detail.mergeable // "UNKNOWN")
        }
      '
    done | jq -s '.'
    ;;

  *)
    echo "usage: fetch_github.sh {initiative <repos> [keywords] | reviewer-requested | mentions | authored}" >&2
    exit 2
    ;;
esac
