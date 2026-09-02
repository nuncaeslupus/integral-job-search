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
the number in D12's. `board_sensitive_record_keys` counts the keys of D12's
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

```
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
one, `_main` exits 3, because zero unrecordable gates over an empty board is
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

## Location

`src/integral/task_gate.py` with `tests/test_task_gate.py` and
`status/evidence/D12.json`; `src/integral/naming.py` with `tests/test_naming.py`
and `status/evidence/T100.json`; `src/integral/plan_v2.py` with
`tests/test_plan_v2.py` and `status/evidence/S8.json`.
