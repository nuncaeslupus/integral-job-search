---
id: lo-27bb
title: "D-6: rebuild() flattens constraints.json back to stated-only, dropping declined/unknown"
priority: 10
deps: [lo-f55b]
workspace: SOLO
tags: [m2]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/23
---

## What the spec requires

Process spec §9 and T24: every field in `profile/constraints.json` resolves to
exactly one of `stated`, `declined` or `unknown`. `declined` and `unknown` are
distinct — `unknown` is a question nobody has asked, `declined` is one the
candidate has answered by refusing it, and the refusal is the only record that
the asking is finished (T40's non-insistence rule depends on it).

## What the code does

There are two independent writers of that one file.

- `jobsearch.constraints_step.resolve()` (T41) writes all three states.
- `jobsearch.profile._build_constraints()` (T6) writes **only** `state:
  "stated"` rows and leaves every other field **absent** — deliberately, by its
  own docstring, because "only T24 gets to name the difference".

`jobsearch.revision.refresh()` calls `rebuild()` on every upstream change. So
any refresh after a constraints step silently overwrites T41's output with the
stated-only sliver, dropping every `declined` and `unknown` entry. A field the
candidate explicitly refused reverts to indistinguishable-from-never-asked, and
the tool asks again — the exact PR #16-style collapse T41 exists to prevent,
reintroduced one layer up.

Nothing currently fails: no test drives `refresh()` after `resolve()`. The
first thing to write is that failing test.

## The fix location

`src/jobsearch/profile.py` — `_build_constraints` / `rebuild`. Two candidate
approaches, pick one deliberately:

1. Teach `_build_constraints` the trichotomy, so the rebuild is a faithful
   function of the log for this file as it is for the others. Needs the log to
   carry declines, which sit in `session/declines.jsonl` (T40), not the
   evidence log — so `rebuild` would take the ledger as an input.
2. Hold `constraints.json` out of the generic derived set, making T41 its sole
   writer, and record it as authored-by-a-step rather than derived. Cheaper,
   but it costs the "derived files are a pure function of the log" property
   that T6's determinism gate rests on.

Prefer (1) unless it forces the ledger into `rebuild`'s signature in a way that
breaks T6's determinism gate; say in the PR which was chosen and why.

## Acceptance gate

A refresh after a constraints step preserves every `declined` and `unknown`
field. T6's `profile_rebuild_deterministic` and T41's
`constraint_field_resolution` both still pass.

```gate
constraint_states_survive_rebuild == 1.0
evidence: status/evidence/D6.json
key: constraint_states_survive_rebuild
```

```bash
uv run pytest tests/test_profile_store.py tests/test_constraints_step.py tests/test_revision.py -q
uv run python -m jobsearch.profile --check
uv run python -m jobsearch.constraints_step --check
uv run python -m jobsearch.profile --constraint-survival status/evidence/D6.json
```

## Tests

`test_a_declined_field_survives_a_rebuild` and
`test_an_unknown_field_survives_a_rebuild` in `tests/test_revision.py` — both
must fail against current `main` before the fix.

## Location

`src/jobsearch/profile.py`, `src/jobsearch/revision.py`,
`tests/test_revision.py`
