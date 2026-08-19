---
id: lo-d2b2
title: "T5: Label the collected ads against the dimension model; assign elicitation/evaluation split"
priority: 1
deps: [lo-2774, lo-e16f, lo-e497]
requires: [surface:human]
workspace: ONTOLOGY
tags: [human, m3]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/42
---

## Acceptance gate

```gate
corpus_size >= 100
evidence: status/evidence/T5.json
key: corpus_size
```

```bash
uv run python -m jobsearch.harness labels --evidence status/evidence/T5.json
uv run --extra dev pytest tests/test_corpus.py tests/test_corpus_raw.py -q
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T5.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

`corpus_size` counts *collected* ads, which is what T5 was always gated on —
the threshold predates the labelling campaign and did not move when the
campaign was retired. The rest of `T5.json` — `labels_by_dimension`,
`dimensions_without_labels`, `labels_by_split` — is what D-2 and T15 read to
decide whether `extraction_macro_f1` can be computed at all.

## Tests

Write these RED before any production code:

`test_corpus_meets_size_and_language_mix` in `tests/test_corpus_content.py` — corpus has ≥100 labelled ads and the language mix is within ±10% of target

## Location

Service: **ONTOLOGY** · Size: L

Design: `status/plan.md` (T5) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`

## Human-owned

Requires the candidate personally. Carries `requires: [surface:human]`, a
capability no surface declares, so the selector excludes it by default — the
`human` tag alone would not, since tags only filter when LOOP_TAGS is set.

---

## Scope change — owner decision, 2026-08-19

**The labelling campaign is retired.** The owner worked through part of the
pre-marked corpus, judged the read good enough, and decided the model should
read each advert and find the dimensions on its own rather than be taught by a
hand-labelled set:

> *"some other dimensions can be added, but the job you did is really good. So I
> don't think we need to do this annotation step. The LLM must read the text and
> find those dimensions alone. If, when working on a test session I can see some
> other dimensions to be added, we'll use that time to do that."*

So T5 no longer means "label 100 ads by hand". It means:

1. **The corpus's pre-marks stand as they are.** `corpus/labelled/suggestions.json`
   — 828 marks over 84 ads from one independent read — is the model's reading of
   the corpus. It is *not* promoted to labels: a proposal nobody confirmed is
   still a proposal, and `Label.source` has no member for one.
2. **Human labels accrue from use, not from a campaign.** Whatever the owner
   confirms, edits or writes — in the labelling page or, later, in a live
   session — is imported through `jobsearch.harness import` and is the corpus's
   only human-labelled content. Today that is 8 labels on one ad.
3. **The labelling page survives as a spot-check surface**, not a work queue.
   Nothing about it changes; only the expectation that it will be run to
   completion.

### What this costs, and where it lands

`extraction_macro_f1 >= 0.75` was specified "against the hand-labelled corpus".
With no campaign there is no such corpus, so the gate has no honest denominator
and cannot simply be pointed at the pre-marks — see **D-2** (`lo-77a6`), whose
scope change records the new risk and the n-floor that answers it. T5 does not
block on that; it stops being a supply task and D-2 owns the measurement.

### Do not

Promote `suggestions.json` to labels to make a gate pass. Every mark in it was
written by the same reader that will do the extracting, and a metric computed
over it measures the model agreeing with itself.
