---
id: t-d1a0cd63
title: "T104: Every open task PR goes stale on D12 the moment any other task PR merges"
priority: 5
issue: 288
status: merged
---

Imported from issue #288

Measured across #283, #284, #285, #286 and #287.

## Acceptance gate

```gate
board_sensitive_record_keys == 0
evidence: status/evidence/D12.json
key: board_sensitive_record_keys
```

```bash
uv run --extra dev pytest tests/test_task_gate.py tests/test_naming.py tests/test_plan_v2.py -q
uv run python -m integral.task_gate
uv run python -m integral.naming
uv run python -m integral.plan_v2
```

The `bash` block regenerates the three evidence files; the `gate` block asserts
the number in D12's committed record. `board_sensitive_record_keys` counts the keys of D12's
**committed record** that change when the board's gate census changes by one —
which is what another task PR merging does to every open PR's merge ref. Zero
is the property; `record_keys_compared` is the denominator that says the
comparison happened at all.

## What happened

`status/evidence/D12.json` committed a census of gate blocks across
`arsenal/tasks/` **and** `arsenal/tasks/_history/`. A task PR converts its
placeholder gate into a real one, so the moment any task PR merged, main's D12
gained a row and **every other open PR's committed D12 was correct for its own
branch and stale for its merge commit**:

```text
 status/evidence/D12.json | 4 ++--
evidence: committed evidence does not match what the code measures now
```

on a PR whose author changed nothing and whose own `make host-gate` was green.
Quadratic in open PRs, and each forced refresh restarted the review bot. It
happened again while this task was being worked: #291 merged and moved
`D12.json` by ten lines under this branch.

## The axis is not the archive — measured, not reasoned

`task_gate.measure` reads `tasks/` and `_history/` as **one board**, so
`open_task_pr.sh` moving a file between them changes nothing. A sweep of all
83 evidence modules across a simulated archive confirms it tree-wide: with one
live task file moved into `_history/` and every module regenerated, **no
committed evidence value moved at all**. That is why T100's
`archive_sensitive_evidence_keys` read zero for D12 throughout and never saw
this — not because its scan was too narrow, but because it measures a
different perturbation. Widening it to cover `D12.json` would add a check that
is true by construction and catches nothing.

The perturbation that matters is *the board gaining a gate block*, which is
what a merge does. On that axis three keys move — `evidence_gates_read`,
`gates_declaring_status_key`, and the 126-row `readings` array — and
`unrecordable_task_gates` and `unrecordable`, the two that carry D-12's
finding, do not.

## The fix

T100's move, on the axis that moves here. `record()` commits the finding
exactly and replaces the census: `evidence_gates_read_at_least` and
`gates_declaring_status_key_at_least`, the floors `_main` asserts the live
counts against, and no `readings` array — that is `--check` output, read by
nothing and regenerable on demand. The floors are not decorative: below either
one, `_main` exits **1**, because zero unrecordable gates over an empty board is
not a measurement.

`measure_board_sensitivity` is the proof rather than the assertion. It
withholds one recordable gate — the same census change a merge causes — and
compares the two records key by key, so a `record()` that satisfied
"unchanged" by committing nothing would be caught by `record_keys_compared`.

## Two more instances, same family

- `status/evidence/T100.json` committed `archived_for_the_comparison`, which is
  the sorted-first **live** task file — so T100's own record went stale the
  moment that task merged. It is now reported and not committed.
- `status/evidence/S8.json` committed `plan_rows` and `queue_tasks` as exact
  counts. They move whenever a task is seeded, which lands rows on both sides
  at once; it forced a regeneration on every open PR twice today. Both are
  denominators guarding `plan_queue_task_drift == 0` against an empty plan, so
  both become `MINIMUM_PLAN_ROWS`, checked live in `main`.

## Tests

`test_the_committed_record_survives_another_task_pr_merging` — the regression:
one more gate lands on the board, the raw measurement moves by one, and the
committed record does not. Shown failing before the fix, on exactly
`['evidence_gates_read', 'readings']`.
`test_archiving_a_task_file_changes_nothing_either` pins the axis that was
already clean, `test_a_census_committed_as_an_exact_value_is_reported_sensitive`
shows the gate failing when a census key is put back, and
`test_the_sensitivity_reading_is_unmeasured_with_no_gate_to_withhold` keeps a
zero over nothing compared from reading as a pass.

## Second-reader audit (#297) — five accepted findings, all fixed here

The first version of this fix replaced an enforceable census with a floor
nothing enforced. Held pending the five below, each now a committed fixture
rather than an answered comment.

- **D-1, blocking, fail-open.** Both floors exited **3**, and `Makefile`'s
  evidence loop maps 3 to `"unmeasured (recorded)"` and carries on. Since
  `record()` writes `evidence_gates_read_at_least: 100` unconditionally, a
  five-gate board committed a record claiming a hundred, produced *zero* drift,
  and `make host-gate` went fully green over a board where 126 of 131 gates
  were never read — where the exact value it replaced went red. **Now exit 1**,
  in `task_gate._main` and in `plan_v2.main`. Exit 1 over writing an
  `unmeasured` status into the record, for two reasons: a floor breach is a
  *finding* — the sweep ran, counted, and came back short — not the absence of
  a measurement that 3 means; and a record that flipped a status below the
  floor would make the committed file a function of the census again in that
  regime, which is the drift this task exists to remove. The artefact cannot
  distinguish a five-gate board from a healthy one — that is what a floor *is*
  — so the exit code has to, and it must be one the caller stops on.
- **D-2, blocking.** Nothing invoked `_main` or `main`, which is why D-1 sat
  behind a green suite. The audit's two board sizes are now fixtures on both
  modules: 5 gates and 92 gates, each asserting the exit code and the stderr,
  each with a passing control board above the floor so a failure cannot be the
  harness. Verified failing against the pre-fix exit code (5 failures, `3 == 1`).
- **D-3.** `test_a_census_committed_as_an_exact_value_is_reported_sensitive`
  said "the gate, shown failing" and never ran the gate: it hand-built two
  dicts one key apart and asserted that dict comparison compares dicts. It now
  monkeypatches `record` to re-emit `evidence_gates_read` and asserts
  `measure_board_sensitivity()` reports it.
- **D-4.** `record_keys_compared` was asserted as `>= len(record(measure()))` —
  `4 >= 4`, self-referential, and still green over a `record` that dropped a
  key. `MINIMUM_RECORD_KEYS_COMPARED = 4` is now a literal, checked in `_main`
  after the sensitivity status, with a fixture that drops
  `unrecordable_task_gates` from the record and exits 1 on three keys compared.
- **D-5.** `gates_declaring_status_key_at_least = 1` against a live 29 is not a
  denominator — it is D-12's *adoption* reading — and a floor of one permitted a
  96% collapse while adding nothing over the suite's existing `>= 1`. Raised to
  **20** — a round floor nine under the live twenty-nine — rather than restored
  as a reading: the exact count moves when a task declaring a `status-key`
  merges, which is the defect. Not a fraction of `MINIMUM_GATES_READ`: 100/132
  is 76% and 20/29 is 69%, and an earlier draft of this note claimed they
  matched. Fixture: 105 gates of which 3 declare one — a pass under the old
  floor.

Two more, recorded and deliberately not coded:

- **D-6.** `S8.json` and `D12.json` are now entirely static on a healthy repo,
  so the stale-census canary that found T85 — `S8` committing `plan_rows: 81`
  against 107 measured — is gone. `repo_gate.evidence_writing_modules` still
  guards what that canary guarded, so this is lost redundancy, not an open hole.
- **D-7.** Dropping `readings` loses the committed per-task index of which gate
  points at which evidence key: a gate repointed from `key: foo` to `key: bar`
  used to show as a diff hunk and now leaves no trace. Acceptable on its own,
  and acceptable here only because D-1 is fixed — with an unenforced floor *and*
  no index, "the board lost thirty gates" produced no artefact and no exit code
  anything respected.

## Review round 2 (#297) — two more, both fixed here

- **The floor record was written before the floor check.** D-1 fixed the exit
  code and left the ordering: `write_evidence` wrote `record(measured)` first,
  so a five-row plan overwrote `S8.json` with `plan_rows_at_least: 100` — a
  claim that the floor passed — and *then* `main` returned 1. A failing run
  left behind the artefact the next healthy run's `make evidence` diffs
  against, which is D-1's own finding surviving its own fix. `plan_v2` and
  `task_gate` both had it; both now read `floor_breaches(measured)` before
  writing anything and write nothing when it is non-empty. Fixtures:
  `test_a_sub_floor_run_leaves_an_existing_record_untouched` on each module —
  byte-identical, not merely still valid — plus `assert not target.exists()`
  on each of the three sub-floor cases that previously asserted the false
  claim was present.
- **A test that passed over a `None`.**
  `test_which_file_was_archived_is_reported_but_not_committed` asserted
  `"archived_for_the_comparison" in measured`, which holds when
  `measure_archive_sensitivity` reports `None` for it — so it proved a key and
  not a filename. D-3's shape, one file over. It now asserts a non-null
  `naming.first_task_file()` and compares the reported value against it.

## Location

`src/integral/task_gate.py` with `tests/test_task_gate.py` and
`status/evidence/D12.json`; `src/integral/naming.py` with `tests/test_naming.py`
and `status/evidence/T100.json`; `src/integral/plan_v2.py` with
`tests/test_plan_v2.py` and `status/evidence/S8.json`.
