---
id: t-4cfbcbd1
title: "T77: Every disqualification carries the advert's own sentence"
priority: 10
deps: [t-e6f1dc24]
workspace: MATCH
tags: [v3, m5]
---

# T77: Every disqualification carries the advert's own sentence

## Acceptance gate

```gate
disqualification_verdicts_without_quoted_wording == 0
evidence: status/evidence/T77.json
key: disqualification_verdicts_without_quoted_wording
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_eligibility.py -q
uv run --extra dev python -m integral.eligibility
```

`src/integral/eligibility.py` must write `status/evidence/T77.json`. This is a new module, so it owns this record outright. **A gate must never name a file no module produces** — the file not existing yet is the honest state of an unstarted task; the file existing but empty of this metric is not.

The `bash` block regenerates it; the `gate` block asserts the number in it.

## Why

A veto with no quote is unfalsifiable — the same objection `status/specification.md` makes to an unexplained rank, and the reason `explained_fraction` exists. If the tool removes a job from someone's list, it must be able to show the sentence it removed it for.

The quote is a span of **the advert's own text**, on the same terms as `Candidate.spans`: nothing sourced outside the advert may appear here. `enrichment.py` already draws that line for explanations; this is the same line for refusals.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

**A verdict whose quote is not found in the advert text is a schema violation, not a warning.** Fail loudly — a fabricated justification for excluding someone's job is worse than no gate at all.

**A zero-violation count over an empty input set is not a pass.** The gate counts
violations, and nothing counted is also zero — so the evidence record must carry
`disqualification_verdicts_without_quoted_wording_evaluated` (verdicts emitted) and the gate is only meaningful while that count is
non-zero. This is the failure this whole increment is about, turned on its own gates:
a check that reports success over work it did not do. Assert the denominator.

## Tests — write these RED first

`test_every_fail_verdict_carries_the_adverts_own_sentence` in `tests/test_eligibility.py`.

`test_a_verdict_quote_is_a_span_of_the_advert_text` — the quote is found in the advert, byte for byte.

`test_a_flag_verdict_quotes_too` — FLAG is a claim about the advert as much as FAIL is.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert `disqualification_verdicts_without_quoted_wording_evaluated` is written and non-zero.

## Location

Service: **MATCH** · Size: S

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T77) ·
Methods: `docs/METHODS.md`

## A zero count must prove the mechanism ran — 2026-08-26

This gate asserts a **violation count of zero**, and an empty input set produces
zero too. As written it could pass without evaluating a single offer, verdict,
ranked result, document, keyword, application or technique — which is *precisely*
the failure class this increment exists to catch, reproduced inside its own
acceptance criteria.

The gate block therefore carries `status-key: gate_status`, and the producing
module must honour it:

* record **``disqualification_verdicts_evaluated``** — how many inputs were actually evaluated — in the evidence
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
