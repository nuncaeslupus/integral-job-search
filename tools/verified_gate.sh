#!/usr/bin/env bash
# Run the repo gate against a PUSHED COMMIT, in a tree nothing else has touched.
#
# `make host-gate` in a session's own checkout answers a weaker question than CI
# did. It measures the working tree, which is not what a reviewer will merge:
# uncommitted edits, a file staged but not committed, a stale `.pyc` whose source
# was restored inside the same second (see CLAUDE.md, "A reverted mutation can
# leave the mutated bytecode running") — each of those can make a local run green
# over code that is not the code being shipped.
#
# So this resolves the ref to a 40-character SHA, checks that SHA out into a
# throwaway detached worktree, and runs the gate there. Nothing from the calling
# tree is reachable: not the index, not untracked files, not the bytecode cache.
#
# It runs `make host-gate` and nothing else, deliberately. A hand-listed set of
# targets here would be a second place for the gate to be defined and a second
# place for it to fall behind — which is D-22's whole subject. `integral.repo_gate`
# asserts that this file still delegates rather than enumerates.
#
#   bash tools/verified_gate.sh [ref]     # default: the current branch's upstream
#
# Exit 0 with a verdict block on stdout, ready to paste onto the pull request.
# Exit 1 if the gate fails; exit 2 if the ref cannot be resolved. One meaning per
# code: 2 always means NOTHING was measured, so a caller can tell a real failure
# from a bad argument. `make` itself exits 2 on a failing recipe; that is
# normalised to 1 at the end rather than passed through.
set -uo pipefail

ref="${1:-HEAD}"
repo_root="$(git rev-parse --show-toplevel)"

git -C "${repo_root}" fetch --quiet origin "${ref}" 2>/dev/null || true
sha="$(git -C "${repo_root}" rev-parse --verify --quiet "FETCH_HEAD^{commit}" 2>/dev/null \
  || git -C "${repo_root}" rev-parse --verify --quiet "${ref}^{commit}" 2>/dev/null)"
if [ -z "${sha}" ]; then
  echo "verified-gate: cannot resolve '${ref}' to a commit" >&2
  exit 2
fi

tree="$(mktemp -d -t verified-gate-XXXXXX)"
cleanup() { git -C "${repo_root}" worktree remove --force "${tree}" >/dev/null 2>&1 || true; }
trap cleanup EXIT

if ! git -C "${repo_root}" worktree add --detach "${tree}" "${sha}" >/dev/null 2>&1; then
  echo "verified-gate: could not check out ${sha}" >&2
  exit 2
fi

# Belt and braces. A fresh worktree carries no bytecode, but saying so here is
# what stops a future edit reusing an existing directory and reintroducing the
# staleness this script exists to rule out.
find "${tree}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

log="$(mktemp -t verified-gate-log-XXXXXX)"
( cd "${tree}" && make host-gate ) >"${log}" 2>&1
status=$?

echo '## Verified gate'
echo
echo "Run by \`tools/verified_gate.sh\` against a clean detached checkout of the"
echo "pushed commit — not a working tree. CI is unavailable; this is the substitute"
echo "\`CLAUDE.md\` names, and the SHA below is the one that was measured."
echo
echo "\`\`\`"
echo "commit    ${sha}"
echo "ref       ${ref}"
echo "measured  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "command   make host-gate   (delegated, never a listed subset)"
echo "verdict   $([ ${status} -eq 0 ] && echo PASS || echo FAIL)"
echo "\`\`\`"
echo
echo '```'
grep -E 'All checks passed|no issues found in|passed,|failed,|no drift|verify-gates:|Error [0-9]|FAILED' "${log}" | tail -8
echo '```'
if [ ${status} -ne 0 ]; then
  echo
  echo '<details><summary>failing output</summary>'
  echo
  echo '```'
  tail -40 "${log}"
  echo '```'
  echo
  echo '</details>'
fi
echo
echo "Merge only while the pull request head is still \`${sha}\`. A push after this"
echo "block was produced makes it evidence about a commit nobody is merging."
rm -f "${log}"

# Normalised, not passed through. `make` exits 2 when a recipe fails, and 2 is
# this script's "cannot resolve the ref" — so passing the status through made a
# failing gate indistinguishable from a bad ref, and a caller checking for 2
# would retry with a different ref instead of reading the failure. One meaning
# per code: 0 measured and passed, 1 measured and failed, 2 nothing measured.
[ ${status} -eq 0 ] && exit 0
exit 1
