---
id: t-f662cfd0
title: "T84: Step 11's two drafting rules — relevance-weighted cutting and the backtrack test"
priority: 10
deps: []
workspace: PROFILE
tags: [v3, m5]
status: merged
---

# T84: Step 11's two drafting rules — relevance-weighted cutting and the backtrack test

## Acceptance gate

```gate
step_skills_without_the_drafting_rules == 0
evidence: status/evidence/T84.json
key: step_skills_without_the_drafting_rules
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_step_skills.py -q
uv run --extra dev python -m integral.step_skills
```

`src/integral/step_skills.py` must write `status/evidence/T84.json`. It already writes `status/evidence/S7.json` for another task — add this record beside it rather than replacing it, so both gates keep reading. **A gate must never name a file no module produces** — the file not existing yet is the honest state of an unstarted task; the file existing but empty of this metric is not.

The `bash` block regenerates it; the `gate` block asserts the number in it.

## Why

Two rules, in prose, in `.claude/skills/step-11-application/SKILL.md`. Same shape as D-13, D-14 and D-15: a rule the protocol must state, pinned by a test over the skill file.

**Relevance-weighted cutting.** Score each line by (a) relevance to *this* posting, (b) uniqueness in the document, (c) **narrative load** — does the cover letter depend on it? If cutting the line would force a letter paragraph to be rewritten, it is load-bearing. Cut lowest total first, **ignoring section boundaries**. Step 11 already promises to say what was left out; this is the method for choosing, which it currently lacks.

**The interview backtrack test.** Could the candidate comfortably explain this line in an interview without backtracking? If they would have to say 'well, what I actually meant was…', it has gone too far. Tiers: OK / Flag it / Never. We already enforce traceability — every claim traces to a store entry — but traceability is not defensibility: a true fact can still be framed past what its owner can hold up under questioning.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

Prose only. No new module, no scoring code — the judgement belongs in the conversation, and a numeric line-scorer would be a worse version of what the model already does while reading the advert.

**Do not add an exit offer to the Boundary section** — D-15 removed those deliberately.

**A zero-violation count over an empty input set is not a pass.** The gate counts
violations, and nothing counted is also zero — so the evidence record must carry
`step_skills_without_the_drafting_rules_evaluated` (step skills scanned) and the gate is only meaningful while that count is
non-zero. This is the failure this whole increment is about, turned on its own gates:
a check that reports success over work it did not do. Assert the denominator.

## Tests — write these RED first

`test_step_eleven_states_the_relevance_weighted_cut_rule` in `tests/test_step_skills.py`.

`test_step_eleven_states_the_interview_backtrack_test`.

`test_the_cut_rule_names_narrative_load` — the third factor is the one most likely to be dropped in a paraphrase.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert `step_skills_without_the_drafting_rules_evaluated` is written and non-zero.

## Location

Service: **PROFILE** · Size: S

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T84) ·
Methods: `docs/METHODS.md`

## A zero count must prove the mechanism ran — 2026-08-26

This gate asserts a **violation count of zero**, and an empty input set produces
zero too. As written it could pass without evaluating a single offer, verdict,
ranked result, document, keyword, application or technique — which is *precisely*
the failure class this increment exists to catch, reproduced inside its own
acceptance criteria.

The gate block therefore carries `status-key: gate_status`, and the producing
module must honour it:

* record **``step_skills_checked``** — how many inputs were actually evaluated — in the evidence
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
