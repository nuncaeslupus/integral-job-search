---
id: t-f05dfaa0
title: "T125: The repo has never been ruff-format clean, because make lint does not check it"
priority: 5
status: merged
---

Imported from issue #345

_(no issue body)_

## What landed

`ruff format .` once over the tree — **31 files**, 30 of them Python — and
`ruff format --check .` added to `make lint` so it cannot drift again.

## What "formatting only" actually means here, measured

`git diff --ignore-all-space` is **not** the proof: ruff re-wraps lines and moves
tokens between them, so it still reported 649 insertions. The claim worth making
is *semantic* equivalence, so every reformatted file was parsed before and after
and its AST compared:

| | files |
|---|---|
| AST-identical | **27** |
| docstring text changed | **3** |
| real code change | **0** |

The three are named rather than waved past, because each is a genuine change to a
string constant and "formatting only" is not literally true of them:

- `src/integral/audit_followup.py` — a usage line inside `_main`'s docstring
  re-indented from 8 spaces to 4.
- `tests/test_connector_policy.py`, `tests/test_gate_exit.py` — both open with a
  docstring whose first character is a quote, so the source read `""""The reader
  ran…`. Ruff inserted a separating space: `""" "The reader ran…`. That is an
  improvement — `""""` is ambiguous to a reader and very nearly ambiguous to a
  parser — but it does put one space into the docstring's value.

No docstring in the three is read by a gate; they are prose for humans.

## Why this mattered beyond tidiness

`make lint` was `ruff check` + `mypy` with **no** format check, so the tree had
never been format-clean and `make format` was a repo-wide rewrite rather than a
tidy-up of what you touched. Measured 2026-09-05 while working T124: `ruff format`
was reached for to fix an import-order complaint and swept a third of `src/` into
that task's diff — `src/integral/cue_audit.py` alone by 683 lines — which had to
be reverted file by file to keep the diff traceable.

That is the same reviewability problem #343 is about, pointed inward: a
contributor's one obvious tidy-up command was the one that destroyed their diff.

## Acceptance gate

```bash
set -euo pipefail
uv run ruff format --check .
grep -q 'ruff format --check' Makefile || {
  echo "make lint does not check formatting — it will drift again" >&2
  exit 1
}
echo "unformatted_files = 0 over $(uv run ruff format --check . | grep -oE '^[0-9]+') file(s) checked"
```
