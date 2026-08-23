---
id: lo-bd02
title: "T16: Negation handling in extraction"
priority: 5
deps: [lo-25b1]
workspace: MATCH
tags: [m2]
status: merged
issue: 56
---

## Acceptance gate

```gate
negation_scope_leaks == 0
evidence: status/evidence/T16.json
key: negation_scope_leaks
```

```bash
uv run --extra dev pytest tests/test_negation.py -q
uv run --extra dev python -m integral.extraction --negation
```

The `bash` block regenerates `status/evidence/T16.json`; the `gate` block
asserts the number in it.

## Why this gate and not `extraction_negation_recall`

Split on the owner's decision, 2026-08-23, exactly as **D-12 (`t-e1ca8374`,
#83)** split T15: the code half is checkable today, the accuracy number is not.

`extraction_negation_recall >= 0.80` is defined over "the corpus subset labelled
as negated". That subset is **two labels, both on one advert**
(`tecnoempleo-98201f7d82b073d32d45`), against a label floor of 10. A recall of
1.0 over n=2 is precisely the figure-computed-from-three-rows that **D-2
(`lo-77a6`)** exists to forbid, so this task does not compute it. The number,
its `status-key`, and its wait behind the corpus tasks are **T59 (`lo-4b17`)**.

Nor could this task borrow T15's trick of finding a second measurable property:
`prefilter_suppressed_positives` skips every negated label, because a denial on
a unipolar scale is class 0 and that counter only checks positives. Negation is
genuinely unmeasured here, and this file says so rather than dressing it up.

**Know what this gate is worth.** `negation_scope_leaks == 0` is a *regression*
gate — it holds by construction of `_negation_scope`, and it fails only if
somebody widens the scope rule back out. It does not show the negation is
accurate. `negation_window_only_count` in the same evidence file is the number
that shows the change did something: 2 matches that the raw character window
negates and the clause rule does not, and both were wrong before this task.

## Tests

`tests/test_negation.py`, written RED before the fix:

- `test_negated_cue_inverts_not_drops_score` — "no on-call" yields a negative
  score, not a missing one. Passed before the change; kept because it is the
  property the whole scope rule must not break.
- `test_negator_does_not_reach_past_a_full_stop` — `manfred-8392`, where "sin
  ambigüedades. **El inglés fluido" was read as a negated English requirement.
- `test_negator_does_not_reach_past_a_line_break` — `remotive-2091075`, where a
  `not` in one bullet inverted the next bullet across a blank line. Asserted on
  `_is_negated` rather than on a score, because `collaboration_mode` is bipolar
  and returns `None` for the unrelated reason that one match cannot settle it.
- `test_negator_still_reaches_across_a_comma` — `manfred-8389`, "Durante tus
  primeros 6 meses, no harás guardias". A comma is not a clause boundary, and
  the fix must not make it one.
- `test_no_negation_leaks_across_a_boundary_in_the_corpus` — the gate's own
  number, asserted from the suite as well as from the evidence file.

## Location

Service: **MATCH** · Size: M

Design: `status/plan.md` (T16) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
