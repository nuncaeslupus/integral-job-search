#!/usr/bin/env bash
# SessionStart hook — the tool installs its own dependencies (T52).
#
# `docs/distribution.md` §1: the install is `git clone`, `cd`, `claude`. A clone
# carries the skills and the code but not the installed dependencies, so this
# runs at session start, checks whether the environment is current, and syncs
# when it is not. Silent when there is nothing to do.
#
# The rule itself lives in `jobsearch.bootstrap`, which is stdlib-only for the
# obvious reason: it exists to prevent an ImportError, so it cannot need the
# packages it installs. This file only decides how to reach Python.
#
# It always exits 0. A hook that fails the session because a network was down
# would be worse than the ImportError it was avoiding, and the candidate has
# already been told in words.
set -u
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/..}" || exit 0
export INTEGRAL_ENTRY_POINT=session-start

# Deliberately NOT `uv run`: that would install the environment as a side
# effect of asking whether the environment exists, and the announcement the
# candidate is owed would never be made.
#
# stdout carries a machine-readable status line and is discarded; **stderr is
# deliberately not**, because that is where the candidate-facing announcement
# goes. Sending both to /dev/null made the install silent — and worse than
# silent: the marker was still written, so step 0 then saw a current
# environment and said nothing either, and a package manager had run on
# somebody's machine without them ever being told.
for python in python3 python; do
  if command -v "$python" >/dev/null 2>&1; then
    PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" "$python" -m jobsearch.bootstrap --ensure >/dev/null \
      || true
    exit 0
  fi
done
echo "integral-job-search: no python3 on PATH — install Python 3.12+ and start again." >&2
exit 0
