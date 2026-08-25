---
id: t-4cfbcbd1
title: "T77: Every disqualification carries the advert's own sentence"
priority: 10
deps: [t-e6f1dc24]
workspace: MATCH
tags: [v3]
---

# T77: Every disqualification carries the advert's own sentence

## Acceptance gate

```gate
disqualification_verdicts_without_quoted_wording == 0
evidence: status/evidence/T77.json
```

```bash
uv run --extra dev pytest tests/test_eligibility.py -q
uv run --extra dev python -m integral.eligibility
```

The `bash` block regenerates `status/evidence/T77.json`; the `gate` block asserts the
number in it.

## Why

A veto with no quote is unfalsifiable — the same objection `status/specification.md` makes to an unexplained rank, and the reason `explained_fraction` exists. If the tool removes a job from someone's list, it must be able to show the sentence it removed it for.

The quote is a span of **the advert's own text**, on the same terms as `Candidate.spans`: nothing sourced outside the advert may appear here. `enrichment.py` already draws that line for explanations; this is the same line for refusals.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

**A verdict whose quote is not found in the advert text is a schema violation, not a warning.** Fail loudly — a fabricated justification for excluding someone's job is worse than no gate at all.

## Tests — write these RED first

`test_every_fail_verdict_carries_the_adverts_own_sentence` in `tests/test_eligibility.py`.

`test_a_verdict_quote_is_a_span_of_the_advert_text` — the quote is found in the advert, byte for byte.

`test_a_flag_verdict_quotes_too` — FLAG is a claim about the advert as much as FAIL is.

## Location

Service: **MATCH** · Size: S

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T77) ·
Methods: `docs/METHODS.md`
