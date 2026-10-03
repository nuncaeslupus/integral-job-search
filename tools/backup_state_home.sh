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

# An inherited git environment can redirect every command below: GIT_DIR into some
# OTHER repository, GIT_CONFIG_PARAMETERS / GIT_CONFIG_COUNT into another push
# URL or a foreign hook. Git itself exports these to children, so they really
# arrive. The rule is closed, not a list: EVERY variable named GIT_* is dropped,
# and the author identity (the only one this script wants) is captured first.
author_name="${GIT_AUTHOR_NAME:-integral backup}"
author_email="${GIT_AUTHOR_EMAIL:-backup@localhost}"
for name in $(env | sed -n 's/^\(GIT_[A-Za-z0-9_]*\)=.*/\1/p'); do
  unset "$name"
done

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
# there would nest. This is a filesystem walk, not `git rev-parse`, because git's
# own discovery can be blinded (GIT_CEILING_DIRECTORIES, unsafe ownership) and a
# linked-worktree `.git` is a FILE. Any `.git` above DIR, of either kind, refuses.
p="$(dirname "$dir")"
while :; do
  if [ -e "$p/.git" ] || [ -L "$p/.git" ]; then
    echo "backup_state_home: $dir is inside the repository at $p; refusing" >&2
    exit 2
  fi
  [ "$p" = "/" ] && break
  p="$(dirname "$p")"
done
# `-d` follows a symlink, so the link test comes first: a `.git` that is a link
# (or a file) is somebody else's repository, never the state dir's own.
if [ -L "$dir/.git" ] || { [ -e "$dir/.git" ] && [ ! -d "$dir/.git" ]; }; then
  echo "backup_state_home: $dir/.git is not a real directory; refusing" >&2
  exit 2
fi

[ -d "$dir/.git" ] || git -C "$dir" init --quiet

git -C "$dir" add -A
if ! git -C "$dir" diff --cached --quiet; then
  git -C "$dir" \
    -c core.hooksPath=/dev/null \
    -c user.name="$author_name" \
    -c user.email="$author_email" \
    commit --quiet -m "backup $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "backup_state_home: committed in $dir"
else
  echo "backup_state_home: nothing new to commit in $dir"
fi

# Push to the URL named in the state repository's OWN config file, explicitly,
# so no other config layer's `remote.origin.*` can choose the destination.
cfg="$dir/.git/config"
target="$(git config --file "$cfg" --get remote.origin.pushurl 2>/dev/null ||
  git config --file "$cfg" --get remote.origin.url 2>/dev/null || true)"
if [ -n "$target" ]; then
  git -C "$dir" -c core.hooksPath=/dev/null push "$target" HEAD
else
  echo "backup_state_home: no 'origin' remote; add a PRIVATE one to keep this off-machine" >&2
fi
