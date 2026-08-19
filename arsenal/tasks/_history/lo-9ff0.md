---
id: lo-9ff0
title: "S7: one skill per step, generated from the settled step specifications"
priority: 80
deps: [lo-d8d8, lo-485e, lo-4730]
workspace: ONTOLOGY
tags: [cross]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/23
---

## Acceptance gate

```gate
steps_with_a_skill_fraction == 1.0
evidence: status/evidence/S7.json
key: steps_with_a_skill_fraction
```

```bash
uv run --extra dev python3 -m jobsearch.step_skills
```

## What this is

One skill per step — thirteen — written with the `skill-creator` skill from
claude-arsenal, so each carries its step's protocol, stop rule, gate and
manner in the form Claude actually follows (owner, 2026-08-18).

**After S2r, never before.** A skill written against a specification that is
about to change gets rewritten thirteen times; that is the same argument that
put S1 before S2, and it held.

## Structured, and scripted where it can be

The owner's instruction: *use scripts for each of them when possible, to save
tokens and to make them computable.* The division is the one this repo already
runs on — prose for the manner, scripts for the numbers:

- **The skill** carries the protocol, the opening, the coverage, what is never
  asked, and how the step ends. Prose, because manner cannot be coded.
- **A script per step** carries the checkpoint: reading state, deciding whether
  coverage is met, writing the step's outputs and its gate evidence. Determinism
  and tokens both argue for it, and a number computed by a script is one nobody
  has to trust a model for.

A step whose skill embeds its checkpoint in prose has not been converted; it has
been transcribed.

## The gate

`steps_with_a_skill_fraction` = steps with a skill that names its gate metric and
its checkpoint script ÷ `step_count` from `spec-v2-steps.json`. The divisor is
the settled count, for the reason S2's gate documents at length.

## Do not

Re-decide anything in the step specifications. If writing a skill reveals that a
specification is wrong — and it will, at least once — that is a divergence: seed
it as a `D-N` task and fix the specification, rather than letting the skill and
the spec disagree quietly.

## Tests

`test_every_step_has_a_skill`; `test_every_skill_names_its_gate_metric`;
`test_every_skill_checkpoint_is_a_script_not_prose`;
`test_no_skill_contradicts_its_step_specification` — at minimum the stop rule and
the required/offered flag, which are the two a drifting skill gets wrong first.

## Location

Service: **ONTOLOGY** · Size: L · Depends: S2r

Source: `docs/spec-v2-steps/notes.json` (step 12, final note) · `status/spec-v2-steps.md`

---

## Scope change — v2 plan, 2026-08-18

**Sequencing, from the v2 plan.** S7 now depends on **T34 and T35**, not only on
S2r.

Each of the thirteen skills carries a checkpoint **script** that reads session
state, decides whether coverage is met, and writes the step's gate evidence.
None of that exists until T35 (session state) and T34 (the step graph runtime)
land. Written before them, the scripts have nothing to read and the skills
become exactly the prose transcription this payload already warns against.

The rest of the task is unchanged.
