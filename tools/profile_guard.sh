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
# `cd`-ing there runs `uv` against *that* project — which either errors out or
# runs a Python this package is not installed in. Either way the guard does not
# run, and the exit code the session sees is not this guard's answer: a 2 from
# uv's own resolution reads as a block and wedges every tool call, Read included.
cd "$(dirname "$0")/.." || exit 0

# No `--extra dev`: the guard needs `integral.identity`, which is the package
# itself. Asking for an extra only widens what resolution can fail on.
if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet python -m integral.identity --hook
fi
PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m integral.identity --hook
