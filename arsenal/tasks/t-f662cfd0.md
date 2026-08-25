---
id: t-f662cfd0
title: "T84: Step 11's two drafting rules — relevance-weighted cutting and the backtrack test"
priority: 10
deps: []
workspace: PROFILE
tags: [v3]
---

# T84: Step 11's two drafting rules — relevance-weighted cutting and the backtrack test

## Acceptance gate

```gate
step_skills_without_the_drafting_rules == 0
evidence: status/evidence/T84.json
```

```bash
uv run --extra dev pytest tests/test_step_skills.py -q
uv run --extra dev python -m integral.step_skills
```

The `bash` block regenerates `status/evidence/T84.json`; the `gate` block asserts the
number in it.

## Why

Two rules, in prose, in `.claude/skills/step-11-application/SKILL.md`. Same shape as D-13, D-14 and D-15: a rule the protocol must state, pinned by a test over the skill file.

**Relevance-weighted cutting.** Score each line by (a) relevance to *this* posting, (b) uniqueness in the document, (c) **narrative load** — does the cover letter depend on it? If cutting the line would force a letter paragraph to be rewritten, it is load-bearing. Cut lowest total first, **ignoring section boundaries**. Step 11 already promises to say what was left out; this is the method for choosing, which it currently lacks.

**The interview backtrack test.** Could the candidate comfortably explain this line in an interview without backtracking? If they would have to say 'well, what I actually meant was…', it has gone too far. Tiers: OK / Flag it / Never. We already enforce traceability — every claim traces to a store entry — but traceability is not defensibility: a true fact can still be framed past what its owner can hold up under questioning.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

Prose only. No new module, no scoring code — the judgement belongs in the conversation, and a numeric line-scorer would be a worse version of what the model already does while reading the advert.

**Do not add an exit offer to the Boundary section** — D-15 removed those deliberately.

## Tests — write these RED first

`test_step_eleven_states_the_relevance_weighted_cut_rule` in `tests/test_step_skills.py`.

`test_step_eleven_states_the_interview_backtrack_test`.

`test_the_cut_rule_names_narrative_load` — the third factor is the one most likely to be dropped in a paraphrase.

## Location

Service: **PROFILE** · Size: S

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T84) ·
Methods: `docs/METHODS.md`
