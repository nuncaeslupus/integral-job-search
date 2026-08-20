# Session handover — 2026-08-20 (D-21 merged-pending; PR #111)

## Board

- **D-21 (`t-20ca057d`, #91) is done and open in PR #111**, archived to
  `_history/` with `status: merged` and `Closes #91` in both the commit message
  and the PR body. It closes and unblocks by itself on merge.
- `task_select.py` next returns **`t-221adf32` (D-16, "sourcing has no real
  connector — say so, and offer to build one", priority 5)**. Unclaimed.
- One pre-existing board flag, unchanged: mixed-priority-convention — 27 tasks on
  the size scale [10, 5, 1, 0] and 2 on other values [70, 60].
- `query_status.py` also flags `t-20ca057d` as "archived as merged but #91 is
  still open". That is correct and temporary: it clears when #111 merges.

## What D-21 was, and what was decided

`run_checkpoint.py` printed `"gate_state": "not_implemented"` and exited **0** in
the same breath. A caller reading a status rather than parsing the JSON saw the
step pass. Seven of the thirteen steps were in that position.

D-21 offered two resolutions and **both were taken**, because they answer
different readers:

- **The exit code**, for a caller. `integral.step_gates.checkpoint_exit` is now
  the one place a checkpoint's exit code is decided, and it will not return 0 for
  a step whose gate is unbuilt. The code is **3**, not 1 — reusing 1 would have
  made "this step has no gate" indistinguishable from "this candidate has not
  finished the step", which is the ambiguity that hid the defect. `coverage_met`
  keeps its meaning (the artefacts *are* present); a new `certifiable` field,
  from which the exit code is derived, carries what 0 had been standing in for.
- **The prose**, for a person. Each of the seven skills whose gate is unbuilt now
  says so in its `## Checkpoint` section and is told to say it before presenting
  the step's output.

`steps_certified_on_an_unimplemented_gate == 0` is the gate — the metric name
`status/plan.md` had already settled for the D-21 row, found only when
`test_the_committed_plan_and_queue_agree` failed on a name invented here first.
**Read the plan row before naming a metric**; the plan also named the two tests
it wanted, and they are in `tests/test_step_gates.py` under those names.

## Two things worth knowing before touching this area

**The package may not load code from a path.**
`test_nothing_in_the_codebase_executes_a_contributed_parse_module` scans
`src/integral/*.py` on the AST and forbids `spec_from_file_location`,
`exec_module`, `exec`, `eval`, `compile`, `__import__`. The connector contract's
whole safety argument rests on it. The first draft of `step_certification.py`
probed by importing each checkpoint script and that test caught it — so the
package now *reads* (AST), and `tests/test_step_certification.py` does the
*running* (each script driven through its own `main` with `checkpoint()`
stubbed). Both halves were confirmed to fail against the pre-D-21 tail before
being trusted.

**A new module with `_main` is picked up by `make evidence` for free.** The
target derives its module list from `grep -l '^def _main' src/integral/*.py`, so
`step_certification` is regenerated and drift-checked every run. `step_gates`'s
`--owners` (D7) and `--traits` (D-4) evidence are *not* — they need flags the
no-arg entry point never passes, so those two files are only as fresh as the last
hand-run. That is a live hole, not a design.

## Left open (carried forward)

- **`verify-gates` asserts a fenced gate block is *present*, never that the
  command inside resolves.** The general form of D-21, and of the T55 defect
  before it. Still not seeded.
- **`claude-arsenal#182`** (false `rest`), **`#183`** (`check_update.sh` on a
  missing remote — still reports INERT here), **`#188`** (`outline.sh` parsing),
  **`#189`** (`context_budget.py` scores a missing `AGENTS.md` as 0 and passes).
  All still open upstream.
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has existed
  since v0.33.0 (`gate: unmeasured`).
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***, not
  only one being opened. Still not seeded.
- **D-22's host half is actionable**: a `make gate` target running all five, for
  `host-gate` to point at.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`** — and now say so out
  loud, at the top of their own checkpoint sections.
- **The GitHub repo has not been renamed.** Owner's to do; `README.md`'s clone
  URL stays aspirational until then.

## The gate, run locally (CI has no runner minutes)

Still true, and re-confirmed this session on PR #111: every job fails in 3–4
seconds with no logs at all (the Actions log endpoint 404s, because no runner is
ever assigned), on `main` as much as on any branch — `71cbe02` 4s, `6dc9c1a` 7s,
`745a155` 6s. Do not read a red CI here as a signal about the code.

All five run locally and pass on this branch:

```bash
make lint           # ruff + strict mypy — clean, 104 source files
make test           # 1172 passed, 1 skipped
make evidence       # no drift
make verify-subtree # 0 diverging, 34 assets compared
make verify-gates   # 62 terminal tasks, 62 gates asserted
```

`status/evidence/T55.json`'s `files_scanned` moved 462 → 464: two new files, and
the task file moving into the allowlisted archive. `old_name_references` is still
0.

## Surface facts

Unchanged, and all in `CLAUDE.md`: `--detect` prints a false `rest`, REST is dead
here (`403 GitHub access is not enabled for this session` — do not probe again),
`claim_task.sh` returns `manual POST` and `create_branch` on
`arsenal/claims/<id>` is the compare-and-swap (201 won, 422 lost),
`open_task_pr.sh` cannot be used, and merging goes through the MCP tool.

One addition: **`init.py --silent` writes to the tree.** It restored a
`<!-- /claude-arsenal: auto-managed -->` marker line in `CLAUDE.md` this session.
Harmless, and it will do it again — commit it rather than reverting it.
