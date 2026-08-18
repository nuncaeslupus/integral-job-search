# Session handover — 2026-08-18 (T29 session)

## State

**T29 is done and merged. The last owner-gated decision in M4 is settled.**

| PR | what landed |
|----|-------------|
| #33 | T29 — the distribution decision, and a real gate to replace its placeholder |
| #34 | the name settled as `integral-job-search`, T55 seeded for the rename |

`lo-2293` is recorded `done` against #33 — `release.sh` re-ran the gate as a
hard precondition, so it is measured rather than asserted. Both PRs are merged;
`reconcile_merged.sh` has not run (no `gh` in the cloud session), so the row
still reads `done` rather than the terminal `merged`. Flip it from a laptop.

## The decision, in one paragraph

The tool is installed by **cloning**. A clone already carries both halves — the
thirteen step skills under `.claude/skills/` and the checkpoint code in `src/` —
so the only missing piece is installed dependencies, and the tool installs those
itself on first run. The structural rule everything rests on: **candidate state
lives outside the clone**, resolved from `$INTEGRAL_HOME` by a resolver that
*refuses* any path inside a git work tree. That makes "candidate data never
reaches a repository" a property of the code rather than a `.gitignore` line,
and it keeps a plugin, a wheel or a UI a delivery change later rather than a
migration. Job-site connectors get their own repository and enter as a
dependency. Full record: `docs/distribution.md`.

## Newly claimable — four unblocked tasks where there were none

The queue was empty of cloud-doable work at the last handover. It is not now:

| task | id | note |
|------|-----|------|
| T51 | `lo-4b79` | `$INTEGRAL_HOME` resolver — **do this first**, every other M4 task is cheaper after it |
| T52 | `lo-b2de` | first-run bootstrap; blocked on T51 |
| T53 | `lo-803e` | connector contract pack; builds on the merged T32 format |
| T54 | `lo-892b` | connector exchange, with consent; blocked on T53 |
| T55 | `lo-9f72` | the rename — wide, mechanical, best landed before T51–T54 build on the old name |

## Still the owner's, and still blocking nothing

Whether the sources repository is public from the start, and whether this
repository is public. Neither gates any task above.

## What this session was actually about

**A gate that counts survivors is not a gate.** T29's own gate block was a
placeholder that `exit 1`s, so the task could never have been recorded `done` —
and the first real version I wrote had the deeper form of the same bug: it
filtered malformed entries away and compared nothing against a declared total,
so deleting the twelfth step or the fourth question would have left a clean
sheet. Review (Qodo) caught all three variants. Both sides now declare their own
length — `step_count` in the JSON, a `shape-questions` marker in the Markdown —
and the register's numbering is checked as well as counted.

Two smaller lessons:

1. **A resolution must be made, not mentioned.** The marker regex matched
   `**Decided`/`**Blocked` anywhere in an item's prose, so a sentence describing
   a blocker resolved the question it described. Anchored to line start, and a
   bare `**Blocked:**` with no reason no longer counts.
2. **`ruff format .` reformats ~40 files this repo has committed unformatted.**
   CI only runs `ruff check`, so it is invisible until someone runs
   `make format` and produces an enormous unrelated diff. Not fixed — worth its
   own housekeeping change.

## Upstream

Commented on `claude-arsenal#144` in support of its fix (2) — moving
host-owned state (`queue/`, `session/`, `project/`) out of the bundle prefix —
with this repo's own `profiles/` move as the supporting case, and offered to
prototype it. #142, #143, #145, #146, #147 remain open and untouched.

The owner has said they dislike the queue-coordination *branch* specifically.
Worth noting for a future upstream issue: that branch exists because a shared
remote ref is git's only cross-session channel, so a push race becomes the lock.
Where coordination is single-machine, a local lockfile buys the same guarantee
with none of the ceremony — but that is a separate argument from #144's, and
moving host state out does **not** remove the branch.

## Next action

Start T51 (`lo-4b79`), or T55 (`lo-9f72`) first if you would rather not build
the resolver twice under two names. Both are cloud-doable.
