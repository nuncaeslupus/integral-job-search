---
id: t-e6f1dc24
title: "T76: The eligibility gate — refuse to score an offer the candidate is barred from"
priority: 1
deps: []
workspace: MATCH
tags: [v3, m5]
---

# T76: The eligibility gate — refuse to score an offer the candidate is barred from

## Acceptance gate

```gate
offers_ranked_despite_a_stated_disqualification == 0
evidence: status/evidence/T76.json
key: offers_ranked_despite_a_stated_disqualification
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_eligibility.py -q
uv run --extra dev python -m integral.eligibility
```

`src/integral/eligibility.py` must write `status/evidence/T76.json`. This is a new module, so it owns this record outright. **A gate must never name a file no module produces** — the file not existing yet is the honest state of an unstarted task; the file existing but empty of this metric is not.

The `bash` block regenerates it; the `gate` block asserts the number in it.

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

**A zero-violation count over an empty input set is not a pass.** The gate counts
violations, and nothing counted is also zero — so the evidence record must carry
`offers_ranked_despite_a_stated_disqualification_evaluated` (offers passed through the gate) and the gate is only meaningful while that count is
non-zero. This is the failure this whole increment is about, turned on its own gates:
a check that reports success over work it did not do. Assert the denominator.

## Tests — write these RED first

`test_a_stated_citizenship_requirement_excludes_the_offer` in `tests/test_eligibility.py`.

`test_silence_about_permits_is_not_a_disqualification` — an advert that says nothing has said nothing.

`test_a_company_wide_statement_is_not_role_level_permission`.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert `offers_ranked_despite_a_stated_disqualification_evaluated` is written and non-zero.

## Location

Service: **MATCH** · Size: L

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T76) ·
Methods: `docs/METHODS.md`

## A zero count must prove the mechanism ran — 2026-08-26

This gate asserts a **violation count of zero**, and an empty input set produces
zero too. As written it could pass without evaluating a single offer, verdict,
ranked result, document, keyword, application or technique — which is *precisely*
the failure class this increment exists to catch, reproduced inside its own
acceptance criteria.

The gate block therefore carries `status-key: gate_status`, and the producing
module must honour it:

* record **``offers_evaluated``** — how many inputs were actually evaluated — in the evidence
  file, beside the violation count;
* write **`gate_status: "unmeasured"`** whenever that count is `0`, and
  `"measured"` otherwise.

`gate_evidence.py` reads `status-key` before it reads the metric and exits **3** on
`unmeasured` — "the check ran, and what it found is that this cannot be scored
yet". Not a pass and not a fail, which is the honest third outcome for a run that
processed nothing. That is the same mechanism `lo-6f53` uses for
`extraction_macro_f1`, so this is existing machinery rather than a new rule.

**A second assertion in the gate block would not have worked**: line 1 of a `gate`
fence *is* the gate, one metric per block. Making the emptiness visible through the
status key is what makes the invariant executable rather than prose.
