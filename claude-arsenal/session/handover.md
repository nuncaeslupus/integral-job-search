# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**PR #24 is merged** (`b53954f`). The board reads **37 merged, 32 open**, and
`make ci` is green across five jobs, 592 tests.

**The one thing that matters most is still not code: T5 has not run.** The
corpus has 100 ads and zero labels, and it is `[HUMAN]` — only the owner can do
it. Every remaining M2 task chains off it:

```
T14 ← T5
T15 ← T5, T14
T16 T17 T42 T18 ← T15        T19 ← T18        T44 ← T18, T19
```

The labelling aid is built and committed (`tools/labelling_page.py` generates a
self-contained `corpus/labelled/label.html`). There is no path to a ranked list
— the thing a candidate would actually look at — until the labelling happens.

## What landed in #24

S9 (claude-arsenal as a real subtree at `vendor/`), T7 (question bank generated
from the dimension model), T31 (reader notes rebound by a renumber), D-3 (a gate
the step protocol forbids), and D-4/D-7 via **T49**, a new task.

## The pattern this session kept hitting: green is not measured

Three of the four defects found were invisible to a passing check, and two of
them were found only by deliberately degrading the environment rather than by
reading code.

1. **`subtree_is_real()` accepted a hand-copied directory.** Its own test
   fixture — a plain `git init` plus one commit, no subtree anywhere — read as
   real. The trailer it needed (`git-subtree-dir:`) lives on the squash commit,
   whose tree is *unprefixed*, so it never appears in a path-filtered
   `git log -- <prefix>` walk at all.
2. **`compare()` only walked source → bundle**, so a file hand-added to
   `claude-arsenal/bin/` was invisible — the worst form of the exact failure the
   subtree conversion exists to remove.
3. **`make arsenal-upgrade` never reassembled the bundle it then verified**, so
   the documented upgrade path failed on any upstream change.
4. **CI's shallow checkout made two checks stop measuring rather than fail.**
   `actions/checkout` clones at depth 1. The subtree check reported "cannot
   tell" and skipped; T31's note check found only the tip commit, so all 28
   notes trivially resolved to today's title and reported `unchanged`. Neither
   turned a job red. Confirmed by cloning the repo `--depth 1` and reproducing
   both. Every job now checks out full history, pinned by a test.

**The lesson, which the previous handover already recorded in a different form:
a gate that passes vacuously is worse than one that fails, because nobody
investigates green.** Prefer degrading the environment (shallow clone, empty
directory, missing file) over re-reading the code.

## Decisions taken this session

1. **The Traits gate got a task, not an edit (T49).** `gate.task` names whoever
   *writes* the metric. T28 is measured on `profile_capture_coverage`, T27 on
   `interview_profile_coverage`; neither is `trait_evidence_sufficiency`, so no
   reassignment between them could make the register true. T49 scores trait
   evidence and carries the metric as its own gate.
2. **`story_failure_fraction` is reported, never gated on (D-3).** A `>= 0.33`
   floor cannot coexist with step 3's protocol, which takes a failure episode
   when offered rather than digging for one.
3. **Test mode's four open questions are answered** (payload `lo-5530.md`):
   simulated candidates allowed and marked as fiction; no mid-session
   retraction; notes shown at the end and seeded only once confirmed. Still
   open: the marker itself, recommendation `[[...]]` / `[[! ...]]` with meta
   parsing suspended during a paste.
4. **The skill listing budget is to be raised (S10), which is an upstream
   change.** `LISTING_BUDGET_CHARS = 8000` is a module constant with no CLI flag
   and no env override, so there is nothing to set here. **Do not patch it under
   `vendor/`** — the next subtree pull reverts it silently and
   `make verify-subtree` fails meanwhile. S11 now depends on S10.
5. **The Catalan corpus slice (D-1): option 1, accept and amend.** In flight at
   handover — check whether it landed.

## Filed upstream (nuncaeslupus/claude-arsenal)

- **#142 — the queue never reads GitHub issues.** Owner's request. A task row
  already carries an `issue` field and `queue_doctor.sh --closed-issues` flags
  closed ones, but nothing imports the other way, so a repo can report an empty
  board while carrying a backlog. Proposed a `queue_issues.sh` mirroring
  `queue_sync.sh`, and flagged the two things needing a decision: a label filter,
  and what happens about gates when the issue body is prose.
- **#143 — `LISTING_BUDGET_CHARS` is not configurable.** Blocks S10 and S11.
- **#144 — the bundle cannot be consumed as a subtree**, with the workaround
  this repo landed and what it costs.

## Review

Qodo raised 8 findings on #24 and reached **`🐞 Bugs (0)`**. Three were real,
all in this repo's own S9 code, all fixed with a test confirmed failing first.
Three were in vendored upstream code — declined, because a fix here is reverted
by the next pull, which is the failure the subtree removes. Two were repeat rule
violations already declined on #23 (a `size` field the queue schema does not
have; splitting the PR, which the one-branch constraint forbids).

## Waiting on the owner, not on work

- **T5** (label the corpus) and **T25** — `[HUMAN]`.
- **T12** — `[LAPTOP]`; needs a real browser.
- **S10** — needs upstream #143 to land first.
- **S11** — needs the marker decided, and S10.
- **T29** — product shape.

## Environment notes

- `gh` is unavailable; PRs go through the GitHub MCP tools, and `done` →
  `merged` flips through `claude-arsenal/scripts/update_task_row.py`.
- **The `PreToolUse` guard blocks its own commit messages** when they quote the
  paths it protects. Pass messages through a file (`git commit -F`).
- `update_task_row.py` rewrites every line it touches; restore the untouched
  ones verbatim or a status change reads as a 69-line diff.
- After a merge the remote branch is deleted, so `--force-with-lease` fails with
  "stale info" — push plainly.
- **Do not `git checkout <path>` to undo a scratch experiment** on a file you
  have edited but not committed — it reverts to the committed version and takes
  your work with it. Copy the file aside first.
- `make arsenal-upgrade REF=v0.x.y` pulls, reassembles and verifies in one step.
- Worker fan-out worked well: `isolation: worktree`, each worker copies a named
  disjoint file set back, orchestrator re-verifies and commits. Tell workers to
  `git fetch` and hard-reset to the branch tip first — several cut from a stale
  base.
- S9 and T7 sat `open` on the board after merging because nobody wrote the rows
  back. Check the ledger against the merged PR, not against memory.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks cannot be
released `done` from here.
