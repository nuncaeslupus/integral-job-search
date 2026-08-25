---
id: t-cd8dcc16
title: "T85: The evidence run reaches every module that writes evidence"
priority: 10
deps: []
workspace: SOLO
tags: [v3]
---

# T85: The evidence run reaches every module that writes evidence

## Acceptance gate

```gate
gate_modules_outside_the_evidence_run == 0
evidence: status/evidence/T85.json
```

```bash
uv run --extra dev pytest tests/test_repo_gate.py -q
make evidence
```

The `bash` block regenerates `status/evidence/T85.json`; the `gate` block asserts the
number in it.

## Why

**Run this task first.** `make evidence` builds its module list with `grep -l '^def _main' src/integral/*.py` — 74 modules. Three define `main`, not `_main`, and are therefore never regenerated and never drift-checked:

- `plan_v2.py` — plan ↔ queue membership drift
- `process_spec.py`
- `step_specs.py`

Measured 2026-08-25: committed `status/evidence/S8.json` read `plan_rows: 81` against **107** measured, while `make evidence` exited 0 printing 'no drift'.

`plan_v2` is the guard that catches a plan row with no queue task. The fifteen tasks of this increment were seeded with it inert — the drift check was run by hand instead (0 across 124 rows) — and it must be live before anything else in the increment relies on it.

This is the cleanest instance of the class `status/spec-v3-silent-success.md` is about: the gate reported success over a check it never ran. It was found while validating that specification.

## What it must not become

**Fix the selection, not the three modules.** Renaming `main` → `_main` three times satisfies today's symptom and rebuilds the trap for the next module that defines `main`. The evidence run must *discover* every module that writes evidence, and a module that writes evidence but is not reached is the failure the check reports.

`integral.repo_gate` already asserts that every target `CLAUDE.md` names is real and is reached (D-22). This is the same assertion one level down, and belongs beside it.

## Tests — write these RED first

`test_every_module_writing_evidence_is_reached_by_the_evidence_run` in `tests/test_repo_gate.py`.

`test_a_module_that_writes_evidence_and_is_missed_fails_the_check` — the RED test: it must fail today, naming `plan_v2`, `process_spec` and `step_specs`.

`test_the_selection_does_not_depend_on_a_private_name_convention`.

## Location

Service: **SOLO** · Size: S

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T85) ·
Methods: `docs/METHODS.md`
