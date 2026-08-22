---
id: lo-5db0
title: "T17: `ontology_hit_rate` reporting and staleness signal"
priority: 10
deps: [lo-25b1]
workspace: MATCH
tags: [m2]
status: merged
issue: 55
---

## Acceptance gate

```gate
discarded_concepts == 0
evidence: status/evidence/T17.json
key: discarded_concepts
```

```bash
uv run --extra dev pytest tests/test_ontology_health.py -q
uv run --extra dev python -m integral.ontology_health
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T17.json`; the `gate` block asserts the number in
it against the threshold.

## Why the gate is not `ontology_hit_rate >= 0.85`

**Acceptance split 2026-08-22, following D-12 (`t-e1ca8374`, #83).** The
threshold half is **T57**; this task keeps the half that is measurable today.

`corpus/labelled/suggestions.json` is the only committed source of stated
concepts — 828 of them, over 84 real adverts. Every one was produced by a read
pass that was handed the dimension list and asked to fill it in, so its unmapped
count is 0 *by construction*. A reported hit rate of 1.0 would measure how the
pass was briefed, which is exactly the failure `status/specification.md` §6 names
for this metric: a gate that passes while measuring nothing. The other source,
candidate-side `extractions/<offer_id>.json`, lives under `INTEGRAL_HOME` and is
deliberately not read — a committed evidence file must not be a function of one
machine's candidate data.

So the rate records as D-2's third outcome — `ontology_hit_rate: null` beside
`ontology_status: "unmeasured"` — and what this task gates is the property the
metric exists to protect: **nothing is discarded on the way to the ratio.**
`concepts_read` is counted from the source's own entries and the buckets are
counted from the classifier, so a reader that filters out what it cannot name
makes the two disagree. 828 concepts is a denominator with teeth.

## Tests

`test_unmapped_concepts_are_counted_not_discarded` in
`tests/test_ontology_health.py` — a concept outside the model, and a concept the
reader found and could not name at all, both raise `unmapped` and lower the hit
rate. Plus
`test_a_source_that_cannot_report_unmapped_concepts_leaves_the_rate_unmeasured`,
which is the refusal above asserted rather than described.

## Location

Service: **MATCH** · Size: S

Design: `status/plan.md` (T17) · Spec: `status/specification.md` §5 contracts ·
Methods: `docs/METHODS.md`

Code: `src/integral/ontology_health.py`, evidence `status/evidence/T17.json`.
