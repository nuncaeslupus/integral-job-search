---
id: lo-2a7e
title: "T45: Per-advert generation \u2014 CV and letter from store entries only, versioned, with a claim manifest"
priority: 1
deps: [lo-25b1]
tags: [m4]
---

## Acceptance gate

```gate
cv_generation_traceability == 1.0
evidence: status/evidence/T45.json
key: cv_generation_traceability
```

```bash
echo "no gate command defined for T45 — replace this line with the command that writes status/evidence/T45.json" >&2; exit 1
```

## What this is

Select from `cv/master.json` against what the advert asks for, draft, and show
the candidate what was chosen **and what was left out** — the omissions are as
much a decision as the inclusions. Output goes to
`cv/generated/<offer_id>/v<N>/`: the CV, the letter, and a manifest naming the
store entry behind every claim.

Where the advert asks for something the candidate lacks, say so and offer the
options honestly: apply anyway and address the gap in the letter, or leave this
one. A gap named plainly costs less than a gap the reader discovers.

## The rule that matters

**Every claim traces to a store entry.** Anything less is the tool inventing
experience on a candidate's behalf, which is the single worst thing this project
could ship — the generated document is the candidate's word, and it is the one
artefact here that reaches a stranger.

**Mirror the advert's wording only over ground the candidate actually holds.**
Where the match is partial or absent, borrowing the phrase is a lie with good
vocabulary.

**A regeneration never overwrites**: it writes `v<N+1>` and preserves every
earlier version, because an earlier one may already be with an employer. Hard
cap three regeneration rounds per offer — past that, the useful move is to talk
about what is wrong.

## Tests

Write these RED before any production code:

`test_every_claim_traces_to_a_store_entry` in `tests/test_generate.py` — the
gate, measured over the manifest; `test_regeneration_writes_a_new_version` —
`v1` survives byte-identical after `v2` is written;
`test_advert_wording_is_mirrored_only_over_held_ground` — a required skill the
store does not hold never appears in the draft.

## Location

Service: **DOCUMENT** · Size: L · Depends: S4, T15, S5

Design: `status/plan.md` (DOCUMENT) · Spec: `status/spec-v2-steps.md` step 11
