#!/usr/bin/env bash
# PreToolUse hook (Bash matcher). Blocks `gh pr create` when the diff against
# its actual base branch exceeds the hard ceiling documented in CLAUDE.md's
# "Git workflow" section, so that limit can't be silently skipped under
# momentum.
#
# Reads the base from the command's own `--base <branch>` flag, defaulting to
# `main` only when it's absent (matching gh's own default). This matters for a
# stacked PR chain: a PR branched from another unmerged PR's branch has that
# branch's commits in its history too, so diffing against `main` would count
# the whole chain's lines against this one PR instead of just its own
# increment.
#
# The budget is read out of CLAUDE.md itself (not hardcoded here) so the hook
# and the doc can never drift apart. Escape hatch: prefix the command with
# SKIP_PR_SIZE_CHECK=1 when the diff genuinely fits after excluding
# generated/boilerplate content CLAUDE.md exempts (Alembic migrations,
# lockfiles, etc.) — deliberate and visible, not silent.
set -euo pipefail

input="$(cat)"
command="$(printf '%s' "$input" | jq -r '.tool_input.command // empty')"

# Anchored to the start of the command (or right after a shell separator like
# && / ; / |), not a bare substring match: a plain `*"gh pr create"*` glob
# also matches the phrase "gh pr create" sitting inside a quoted --title or
# --body string (e.g. a PR description that talks about this hook), which
# would fire on an unrelated command like `gh pr merge`.
if [[ ! "$command" =~ (^|[\;\&\|]+)[[:space:]]*gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$) ]]; then
  exit 0
fi

if [[ "$command" == *"SKIP_PR_SIZE_CHECK"* ]]; then
  exit 0
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$repo_root"

base_branch="main"
if [[ "$command" =~ --base[[:space:]]+([^[:space:]]+) ]]; then
  base_branch="${BASH_REMATCH[1]}"
fi

budget="$(grep -oE '[0-9]+ as a hard ceiling' CLAUDE.md 2>/dev/null | grep -oE '[0-9]+' | head -1)"
budget="${budget:-400}"

lines="$(git diff "${base_branch}...HEAD" --shortstat 2>/dev/null | grep -oE '[0-9]+ (insertion|deletion)s?' | grep -oE '[0-9]+' | awk '{s+=$1} END {print s+0}')"

if [ "$lines" -gt "$budget" ]; then
  reason="Diff against ${base_branch} is ${lines} lines, over CLAUDE.md's ${budget}-line hard ceiling (Git workflow section). Split into a PR chain (stacked branches), or re-run with SKIP_PR_SIZE_CHECK=1 prefixed if this genuinely fits after excluding generated/boilerplate content CLAUDE.md exempts."
  reason_json="$(printf '%s' "$reason" | jq -Rs .)"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' "$reason_json"
  exit 0
fi

exit 0
