#!/usr/bin/env bash
# PreToolUse guard — process specification §6.1.
#
# Refuses a tool call that would read or write under a profile belonging to
# somebody other than the candidate this session identified, and refuses any
# read under `profiles/` before anybody is identified at all. The rule itself
# lives in `integral.identity.guard_decision`, where it is unit-tested; this
# file only decides how to reach Python.
#
# Exit 0 lets the call through, exit 2 blocks it and shows stderr to the model.
# A hook that cannot start must not wedge the session, so anything unexpected
# here exits 0 — the store-side `ProfileLeak` is the enforcing half.
set -u
# Resolve the repo from this script's own location, never from
# CLAUDE_PROJECT_DIR: a session moved between repos keeps the old value, and
# `cd`-ing there runs `uv` against a project with no `dev` extra, whose exit 2
# reads as this guard blocking — wedging every tool call, Read included.
cd "$(dirname "$0")/.." || exit 0

if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --extra dev python -m integral.identity --hook
fi
PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m integral.identity --hook
