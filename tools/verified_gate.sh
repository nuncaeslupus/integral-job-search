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
# HOW THAT ASSERTION WORKS, because it changes what an edit here has to survive:
# `integral.verified_gate` no longer reads this file's text. Three rounds of
# regex properties were defeated — the last by putting all twelve patterns in one
# unused single-quoted string, and again in trailing `#` comments, both scoring
# `verified_gate_defects: 0` over a script that ran nothing. It now RUNS this
# script against throwaway git repositories and reads the verdict block, the exit
# status and the filesystem afterwards. So nothing you write here satisfies it;
# only what the script does when executed. Adding a comment cannot break it, and
# hard-coding a PASS cannot pass it.
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
# what the verdict block reports, so those two cannot disagree. The checker no
# longer takes that on trust from the assignment: its probe Makefile makes every
# target announce itself, and two contracts compare what the block SAYS ran with
# what the probe SAW run. Declaring one command and running another is caught
# from outside, which is where round 1's F1 mutation was invisible from inside.
gate_command="make host-gate"

ref="${1:-HEAD}"
repo_root="$(git rev-parse --show-toplevel)"

# Only a ref that is a PLAIN NAME is ever asked of the remote. Everything else
# is resolved locally, which is fail-CLOSED: the worst an over-strict rule does
# is label a genuinely pushed commit "local ref", while the failure it replaces
# was a green verdict about a commit the caller never named.
#
# The rule this replaces was `[ "${ref}" != "HEAD" ]`, a blacklist of one string,
# and a blacklist of one string is what `@` walked straight through. `@` is git's
# documented synonym for `HEAD`; `git fetch origin -- @` SUCCEEDS and sets
# FETCH_HEAD to origin's DEFAULT BRANCH, and FETCH_HEAD is preferred below. So on
# 316cd6c, standing on a branch whose gate genuinely failed, `verified_gate.sh @`
# printed origin/main's SHA and `PASS`, exit 0 — the same defect as #333's F2,
# reached by a different spelling. `HEAD~0`, `HEAD^0`, `@{u}`, `HEAD@{1}` and `""`
# are all the same shape.
#
# So: no leading `-`, and nothing outside `[A-Za-z0-9._/-]`, which excludes every
# ref *expression* character (`@ ~ ^ : { }`) and the empty string, and admits
# branch names, tags, `refs/…` and a bare SHA. The `--` before the ref stays as
# defence in depth (#333, F9) even though nothing option-shaped now reaches it.
case "${ref}" in
  "" | HEAD) fetchable="no" ;;
  -*) fetchable="no" ;;
  *[!A-Za-z0-9._/-]*) fetchable="no" ;;
  *) fetchable="yes" ;;
esac

sha=""
resolved_from="local ref"
if [ "${fetchable}" = "yes" ] && git -C "${repo_root}" fetch --quiet origin -- "${ref}" 2>/dev/null; then
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
# Declared before `cleanup` reads it: `set -u` makes an unset variable inside the
# trap an error, and an EXIT trap that errors is a cleanup that does not run.
log=""
# `worktree remove` alone leaves both the mktemp directory and the
# `.git/worktrees/` registration behind when it fails (#333, F10). The lines
# after it are what make the cleanup unconditional rather than best-effort — and
# the log joins them because the `rm -f` at the end of the happy path is not
# reached when the gate command is interrupted. `nothing_survives_the_run_pass_or_fail`
# runs the script with TMPDIR pointed at an empty directory of its own and fails
# on any surviving `verified-gate*` entry, which is the log as much as the tree.
cleanup() {
  git -C "${repo_root}" worktree remove --force "${tree}" >/dev/null 2>&1 || true
  rm -rf "${tree}" 2>/dev/null || true
  git -C "${repo_root}" worktree prune >/dev/null 2>&1 || true
  [ -n "${log}" ] && rm -f "${log}" 2>/dev/null
  return 0
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

log="$(mktemp -t verified-gate-log-XXXXXX)"  # removed by `cleanup`, on every path
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

# Normalised, not passed through. `make` exits 2 when a recipe fails, and 2 is
# this script's "cannot resolve the ref" — so passing the status through made a
# failing gate indistinguishable from a bad ref, and a caller checking for 2
# would retry with a different ref instead of reading the failure. One meaning
# per code: 0 measured and passed, 1 measured and failed, 2 nothing measured.
[ ${status} -eq 0 ] && exit 0
exit 1
