---
id: t-e6f1dc24
title: "T76: The eligibility gate — refuse to score an offer the candidate is barred from"
priority: 1
deps: []
workspace: MATCH
tags: [v3]
---

# T76: The eligibility gate — refuse to score an offer the candidate is barred from

## Acceptance gate

```gate
offers_ranked_despite_a_stated_disqualification == 0
evidence: status/evidence/T76.json
```

```bash
uv run --extra dev pytest tests/test_eligibility.py -q
uv run --extra dev python -m integral.eligibility
```

The `bash` block regenerates `status/evidence/T76.json`; the `gate` block asserts the
number in it.

## Why

Every hard constraint we hold filters on what the **candidate declared** (`stated_constraints.py`, `constraints_step.py`). Nothing filters on what the **advert demands**. So a ranked list can lead with a role requiring a work permit, a citizenship or a clearance the candidate does not have — which is what makes a beautifully-ranked list useless in the first reply.

Runs **before** the Pareto frontier, as a hard filter. Three verdicts:

- **FAIL** — a stated, role-level bar the candidate cannot meet. Excluded, not ranked.
- **FLAG** — stated but ambiguous, or the candidate's status is unclear. **Ranked, marked, and the human is the tiebreaker.**
- **PASS** — nothing stated.

Two rules govern what counts as stated: **silence is not permission**, and **a company-wide 'we welcome international applicants' is not role-level permission**.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

**Prefer FLAG over a silent PASS, and prefer FLAG over a confident FAIL.** A false FAIL is invisible — an excluded job is one the candidate never sees — so the default for anything short of an explicit, role-level, stated bar is FLAG.

**This gate is not accuracy-tested.** D-23 records that: there are no corpus labels for permit, citizenship, clearance or role-language requirements, so this task's gate measures the **mechanism over fixtures** only. Do not write a gate, a docstring or a skill sentence claiming it is accurate on real adverts.

Never read `weights.json` or any `dimensions/*` score here — see T78.

## Tests — write these RED first

`test_a_stated_citizenship_requirement_excludes_the_offer` in `tests/test_eligibility.py`.

`test_silence_about_permits_is_not_a_disqualification` — an advert that says nothing has said nothing.

`test_a_company_wide_statement_is_not_role_level_permission`.

## Location

Service: **MATCH** · Size: L

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T76) ·
Methods: `docs/METHODS.md`
