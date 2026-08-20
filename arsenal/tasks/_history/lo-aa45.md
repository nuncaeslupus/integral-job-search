---
id: lo-aa45
title: "S2: Specification v2 — one spec per step, filling the step template"
priority: 90
deps: [lo-6928, lo-d865]
workspace: ONTOLOGY
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/17
---

## Acceptance gate

```gate
step_specs_complete_fraction == 1.0
evidence: status/evidence/S2.json
key: step_specs_complete_fraction
```

```bash
uv run python -m jobsearch.step_specs status/evidence/S2.json
uv run --extra dev pytest tests/test_step_specs.py -q
```

## What this is

One specification per step, each filling the template in
`status/spec-v2-brief.md` §4: purpose, preconditions, inputs, protocol, stop
rule, outputs, gate, resume, re-run, privacy.

Reviewable as HTML, one document per step or one document with a section per
step — S1 decides which.

**The gate is a fraction, not a count, on purpose.** The step count is whatever
S1 settles — 12 is a proposal, and S1 may merge Intake with Constraints or fold
Traits into History. A hard-coded threshold would either block this task when
the count came out lower, or pass while a step went unwritten when it came out
higher. `step_specs_complete_fraction` = specs filling every template field ÷
the step count S1 recorded, and it must reach 1.0.

The divisor comes from S1's machine-readable step list, never from counting the
files that happen to exist — dividing by what was written makes any amount of
work look complete.

## The two fields most likely to be skipped

- **Stop rule.** Every step is a short, directed conversation with an end. A
  step with no cap runs until the candidate gives up, which is the failure mode
  the owner explicitly asked to avoid.
- **Re-run.** "The user updated their CV" and "the user left their job" both
  re-enter at an earlier step. Each output must say what a second pass
  preserves and what it replaces, or re-running will silently destroy work.

## Tests

`test_every_step_spec_fills_the_template` — a step whose specification omits a
template field is not counted; `test_every_step_has_a_stop_rule` — the one
field that cannot be defaulted.

## Location

Service: **ONTOLOGY** · Size: L · Depends: S1

Source: `status/spec-v2-brief.md`
