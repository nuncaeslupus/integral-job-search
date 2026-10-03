#!/usr/bin/env bash
# Back up the candidate's state home ($INTEGRAL_HOME) as a private repository.
#
# Usage: bash tools/backup_state_home.sh [DIR]
#
# DIR defaults to $INTEGRAL_HOME, else whatever `integral.state_home.candidate_root`
# resolves (one resolver, so the per-OS defaults cannot drift from this script).
# It initialises DIR as a repository if needed, commits what is there, and pushes
# when a remote named `origin` is configured. It only ever ADDS commits: it never
# rewrites, deletes, or reformats a file inside DIR (profiles/ included), and it
# never touches any directory other than DIR.
#
# The remote must be PRIVATE — profiles hold a candidate's history. See
# docs/distribution.md §2. In an ephemeral cloud container this is necessary,
# not optional: state is lost when the container is reclaimed.
set -eu

dir="${1:-${INTEGRAL_HOME:-}}"
if [ -z "$dir" ]; then
  root="$(cd "$(dirname "$0")/.." && pwd)"
  dir="$(cd "$root" && uv run --quiet python -c \
    'from integral.state_home import candidate_root; print(candidate_root())')" || {
    echo "backup_state_home: cannot resolve the state home; pass DIR or set INTEGRAL_HOME" >&2
    exit 2
  }
fi

if [ ! -d "$dir" ]; then
  echo "backup_state_home: $dir does not exist; nothing to back up" >&2
  exit 2
fi
dir="$(cd "$dir" && pwd -P)"

# Refuse a directory that sits inside somebody else's repository: initialising
# there would nest, and `add` would be driven by the outer repository's rules.
outer="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$outer" ] && [ "$(cd "$outer" && pwd -P)" != "$dir" ]; then
  echo "backup_state_home: $dir is inside the repository at $outer; refusing" >&2
  exit 2
fi

[ -d "$dir/.git" ] || git -C "$dir" init --quiet

git -C "$dir" add -A
if ! git -C "$dir" diff --cached --quiet; then
  git -C "$dir" \
    -c user.name="${GIT_AUTHOR_NAME:-integral backup}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-backup@localhost}" \
    commit --quiet -m "backup $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "backup_state_home: committed in $dir"
else
  echo "backup_state_home: nothing new to commit in $dir"
fi

if git -C "$dir" remote get-url origin >/dev/null 2>&1; then
  git -C "$dir" push origin HEAD
else
  echo "backup_state_home: no 'origin' remote; add a PRIVATE one to keep this off-machine" >&2
fi
