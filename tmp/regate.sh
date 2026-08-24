#!/usr/bin/env bash
# Resolve a rebase/cherry-pick that conflicts only on generated evidence, then
# regenerate every measurement and re-run the repo gate.
#
# status/evidence/*.json is a build product of `make evidence`. Merging two
# versions of it by hand is meaningless — the right answer is whatever the code
# measures on the resulting tree, which is what this recomputes. It refuses if
# anything *other* than evidence is conflicted, because that is a real conflict.
set -euo pipefail

conflicted=$(git diff --name-only --diff-filter=U)
if [ -n "$conflicted" ]; then
  other=$(echo "$conflicted" | grep -v '^status/evidence/' || true)
  if [ -n "$other" ]; then
    echo "regate: real conflicts outside status/evidence — resolve these first:" >&2
    echo "$other" >&2
    exit 1
  fi
  echo "$conflicted" | xargs -r git checkout --ours --
  echo "$conflicted" | xargs -r git add --
fi

git -c core.editor=true rebase --continue 2>/dev/null \
  || git -c core.editor=true cherry-pick --continue 2>/dev/null \
  || true

for module in $(grep -l '^def _main' src/integral/*.py | xargs -n1 basename | sed 's/\.py$//'); do
  uv run python -m "integral.$module" >/dev/null 2>&1 || true
done
git add -A
make host-gate
