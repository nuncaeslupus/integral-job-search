#!/usr/bin/env bash
# Run the repo gate against a PUSHED COMMIT, in a tree nothing else has touched.
#
# The aggregate target run in a session's own checkout answers a weaker question
# than CI did. It measures the working tree, which is not what a reviewer will
# merge: uncommitted edits, a file staged but not committed, a stale `.pyc` whose
# source was restored inside the same second (see CLAUDE.md, "A reverted mutation
# can leave the mutated bytecode running") — each of those can make a local run
# green over code that is not the code being shipped.
#
# So this resolves the ref to a 40-character SHA, checks that SHA out into a
# throwaway detached worktree, and runs the gate there. Nothing from the calling
# tree is reachable: not the index, not untracked files, not the bytecode cache.
#
# It runs the aggregate target and nothing else, deliberately. A hand-listed set
# of targets here would be a second place for the gate to be defined and a second
# place for it to fall behind — which is D-22's whole subject.
# `integral.verified_gate` asserts that this file still delegates rather than
# enumerates. (It is not `integral.repo_gate`, which is about the Makefile; this
# header claimed `repo_gate` until the second-reader report on #333, F6.)
#
#   bash tools/verified_gate.sh <branch-or-sha>
#   bash tools/verified_gate.sh                 # default: the local `HEAD` commit
#
# Exit 0 with a verdict block on stdout, ready to paste onto the pull request.
# Exit 1 if the gate fails; exit 2 if the ref cannot be resolved. One meaning per
# code: 2 always means NOTHING was measured, so a caller can tell a real failure
# from a bad argument. `make` itself exits 2 on a failing recipe; that is
# normalised to 1 at the end rather than passed through.
set -uo pipefail

# THE one place the gate command is written. `${gate_command}` is what runs and
# what the verdict block reports, so those two cannot disagree — and the checker
# anchors its "delegates to the aggregate target" property on this ASSIGNMENT,
# not on the string appearing somewhere in the file. Second-reader report on
# #333, F1: the pattern `make\s+host-gate` was satisfied by the header comments
# alone, so a script whose run line said `make lint` — and a script that ran no
# gate at all and hard-coded a PASS — both scored `verified_gate_defects == 0`,
# while the block still printed the aggregate's name as the command it ran.
gate_command="make host-gate"

ref="${1:-HEAD}"
repo_root="$(git rev-parse --show-toplevel)"

# `HEAD` is never asked of the remote. `git fetch origin HEAD` SUCCEEDS and sets
# FETCH_HEAD to origin's DEFAULT BRANCH, and FETCH_HEAD is preferred below — so
# the no-argument form used to measure `main` and print PASS while the branch the
# caller was standing on had a genuinely failing gate (#333, F2, measured). The
# guard also stops a FETCH_HEAD left by some earlier fetch being read as this
# run's answer, since a fetch that never runs truncates nothing.
#
# `--` before the ref: without it a ref beginning with `-` is parsed by
# `git fetch` as an option (#333, F9).
sha=""
resolved_from="local ref"
if [ "${ref}" != "HEAD" ] && git -C "${repo_root}" fetch --quiet origin -- "${ref}" 2>/dev/null; then
  sha="$(git -C "${repo_root}" rev-parse --verify --quiet "FETCH_HEAD^{commit}" 2>/dev/null || true)"
  [ -n "${sha}" ] && resolved_from="origin, fetched just now"
fi
if [ -z "${sha}" ]; then
  # No fetch, or a fetch that failed — offline, or a ref origin does not carry.
  # Falling back is right, but the block has to say so rather than go on claiming
  # "the pushed commit" for something that may be local only (#333, F2b).
  sha="$(git -C "${repo_root}" rev-parse --verify --quiet "${ref}^{commit}" 2>/dev/null || true)"
fi
if [ -z "${sha}" ]; then
  echo "verified-gate: cannot resolve '${ref}' to a commit" >&2
  exit 2
fi

# `refs/remotes/origin/HEAD` shortens to the bare word `origin`, which names no
# branch a reader could go and look at, so it is filtered out and a real branch
# reported instead.
on_origin="$(git -C "${repo_root}" for-each-ref --contains "${sha}" \
  --format='%(refname:short)' refs/remotes/origin 2>/dev/null \
  | grep -v '^origin$' | head -1 || true)"
if [ -n "${on_origin}" ]; then
  pushed="yes — reachable from ${on_origin}"
else
  pushed="NO — not reachable from any origin/* ref this clone knows"
fi

tree="$(mktemp -d -t verified-gate-XXXXXX)"
# `worktree remove` alone leaves both the mktemp directory and the
# `.git/worktrees/` registration behind when it fails (#333, F10). The two lines
# after it are what make the cleanup unconditional rather than best-effort.
cleanup() {
  git -C "${repo_root}" worktree remove --force "${tree}" >/dev/null 2>&1 || true
  rm -rf "${tree}" 2>/dev/null || true
  git -C "${repo_root}" worktree prune >/dev/null 2>&1 || true
}
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
( cd "${tree}" && ${gate_command} ) >"${log}" 2>&1
status=$?

echo '## Verified gate'
echo
echo "Run by \`tools/verified_gate.sh\` against a clean detached checkout of the"
echo "commit named below — not a working tree. CI is unavailable; this is the"
echo "substitute \`CLAUDE.md\` names, and that SHA is the one that was measured."
echo
echo "\`\`\`"
echo "commit    ${sha}"
echo "ref       ${ref}"
echo "resolved  ${resolved_from}"
echo "on origin ${pushed}"
echo "measured  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "command   ${gate_command}   (delegated, never a listed subset)"
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
