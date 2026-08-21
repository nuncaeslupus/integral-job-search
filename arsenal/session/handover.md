# Session handover — 2026-08-21 (D-16, D-20 merged; D-22 merged-pending, PR #114)

## Board

- **D-21 (#91), D-16 (#92), D-20 (#94) all merged** — `7e1bf3f`, `429733c`,
  `f57340a`. Issues closed, task files archived on `main`, no lingering flags.
- **D-22 (`t-6f9328ab`, #95) is done and open in PR #114**, archived to
  `_history/` with `status: merged` and `Closes #95` in both the commit message
  and the PR body. It closes and unblocks by itself on merge.
- **Run the selector, do not trust this line.** A previous handover predicted
  D-17 next and the selector returned D-20. The queue is the truth.
- One pre-existing board flag, unchanged: mixed-priority-convention — 25 tasks
  on the size scale [10, 5, 1, 0] and 2 on other values [70, 60].

## What D-22 was

`CLAUDE.md` said five things must pass before a merge and nothing ran them. The
aggregate in fact already existed as `ci` — but named for the thing that cannot
run here (Actions has no runner minutes), and nothing checked that the docs' list
still matched it.

**`make host-gate`** is now the name, because that is the key `claude-arsenal`
points a worker at; `ci` depends on it rather than repeating the five. `gate` was
already taken by T1's lint-exit-code recorder, and reusing it would have made
"the payload gate ran" indistinguishable from "the repo gate ran" — which is the
confusion the task is about.

`required_gates_with_no_enforcement_point` (`src/integral/repo_gate.py`) reads the
`make` targets `CLAUDE.md` requires and asks two things of each: is it a real
target, and does `host-gate` reach it. **The second is the one that rots** —
somebody adds a sixth line to the docs and the target nobody wired up is the
target nobody runs. Reachability is transitive so `ci: host-gate` counts.

**The worker half is upstream's and still open** (`claude-arsenal#175`):
`open_task_pr.sh` re-runs the payload gate and never the repo gate, so a green
task PR can still break `make test`. Patching the vendored script here would be
reverted by the next subtree upgrade.

## Lessons worth keeping

**Prefer narrowing an existing field to adding one.** D-20's commute radius went
into `Location.commutable_regions` because `Location` already owned "on-site work
without moving" and `accepts_onsite_in_country` was that question asked as one
bool. Growing a field per sentence is how a pinned contract stops being one.

**When a check asks "does X exist", ask the loader, not the filesystem.** D-16's
first cut decided connector coverage from `meta.yaml` alone, so a directory of
plausible metadata suppressed the disclosure outright — D-16's own failure through
the back door of its own fix. It now calls `load_connector`.

**A vacuous zero is the recurring bug in this repo.** Every measurement here
records `-1` rather than `0` when it could not look: no packages, no probes, the
requirement deleted from the docs. Three tasks in a row needed it.

**Confirm RED before trusting a zero.** Each of D-16, D-20 and D-22 has a test
that reconstructs the pre-fix state and asserts the count goes positive.

**`make lint` does not check formatting** — no `ruff format --check`. Format only
the files you touched: `ruff format <paths>`, **never** `ruff format src tests`. I
did the repo-wide sweep twice in one session and reverted it twice (`fca469e`,
`b3fcc8f`).

**Do not push while a review bot is running.** Two CodeRabbit reviews aborted with
"head commit changed" because a docs commit landed mid-review. Let it finish.

**Check a plan row's path as well as its metric.** D-20's row named
`tests/test_candidate.py`, which does not exist; the row was corrected rather than
annotated.

## Left open (carried forward)

- **Nothing forces a human to run `make host-gate`.** The measurement keeps the
  list honest; a pre-push hook or upstream's call is what would make skipping it
  impossible. The remaining half of D-22. Not seeded.
- **Format drift is unenforced** — `make lint` has no `ruff format --check`. Not
  seeded.
- **A commute radius is a region list, not a distance.** "Within 50km" has nowhere
  to go; converting km to regions needs a gazetteer this repo lacks. Not seeded.
- **`connectors/` still holds no connector for a real board** — T12, not D-16.
- **`verify-gates` asserts a fenced gate block is *present*, never that the command
  inside resolves.** The general form of D-21 and T55. Still not seeded.
- **`claude-arsenal#175`** (worker never runs the host gate — D-22's other half),
  **`#182`** (false `rest`), **`#183`** (`check_update.sh` on a missing remote),
  **`#188`** (`outline.sh` parsing), **`#189`** (`context_budget.py` scores a
  missing `AGENTS.md` as 0 and passes). All open upstream.
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has existed
  since v0.33.0 (`gate: unmeasured`).
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***. Not
  seeded.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and say so out loud.
- **The GitHub repo has not been renamed.** Owner's to do.

## The gate, run locally (CI has no runner minutes)

Unchanged and re-diagnosed rather than assumed: jobs are created and completed
three seconds apart with `runner_id: 0` and an empty `runner_name` — no runner is
ever assigned, on `main` as much as any branch. Do not read a red CI here as a
signal about the code, and do not push fixes for it.

**One command now runs all five:**

```bash
make host-gate      # lint, test, evidence, verify-subtree, verify-gates
```

Green on this branch: lint clean over 107 source files, 1198 passed / 1 skipped,
no evidence drift, 34 subtree assets matching, 65 terminal tasks with 65 gates
asserted.

`status/evidence/T55.json`'s `files_scanned` moved 466 → 467. The scan counts
**tracked** files only: regenerate evidence *after* `git add`, or the count looks
like drift.

## Surface facts

Unchanged, all in `CLAUDE.md`: `--detect` prints a false `rest`, REST is dead here
(`403 GitHub access is not enabled for this session` — do not probe again),
`claim_task.sh` returns `manual POST` and `create_branch` on
`arsenal/claims/<id>` is the compare-and-swap (201 won, 422 lost),
`open_task_pr.sh` cannot be used, and merging goes through the MCP tool.

Two additions:

- **Editing `status/spec-v2-steps.md` requires `make reader-steps`.**
  `test_regenerating_the_reader_produces_no_diff` fails until
  `docs/spec-v2-steps/` is regenerated and committed, and the failure does not
  say that a spec edit caused it.
- **A merged PR deletes the branch.** `git push` then fails with "stale info" on
  a `--force-with-lease` against a remote-tracking ref that no longer exists.
  `git remote prune origin` and push normally.
