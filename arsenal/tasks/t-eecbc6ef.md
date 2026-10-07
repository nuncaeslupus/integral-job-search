---
id: t-eecbc6ef
title: "T279: A 'not stated' score cannot cite evidence, so absence is recorded with a quote that means nothing"
priority: 5
requires: [human:gate]
---

Imported from issue #556

`DimensionScore.spans` is `list[EvidenceSpan] = Field(min_length=1)`, and `accept_model_scores` re-checks every quote against `ad.slice(start, end)`. That is right for a score derived from the text.

It is unsatisfiable for a **0.0 "not stated"** score, which is the value both scales define for *the advert says nothing either way* — `mission_alignment` 0.0 "not stated", `stack_modernity` 0.0 "not stated". Absence has no quote.

Measured on a live round, 2026-09-23: 29 of 35 adverts scored `mission_alignment = 0.0`, and every one of them had to be given a span. I cited the advert's opening 110 characters, which is evidence of nothing — it is a quote that passes the validator and supports no claim. Anything reading those spans back (an explanation, an audit, a second reader) is given text that does not argue for the score it is attached to.

Suggested shape: a 0.0 score records *why absence was concluded* — the fields read, or the whole-ad search that found no cue — rather than a span it cannot have. Either a separate provenance for it, or `min_length=1` relaxed exactly at value 0.0 with a required reason in its place. What must not stay is a validator satisfied by a quote chosen only to satisfy it.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
