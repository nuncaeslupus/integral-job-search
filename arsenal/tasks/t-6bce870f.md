---
id: t-6bce870f
title: "T107: The candidate-facing strings are English-only in a Spanish-facing product"
priority: 5
---

## Acceptance gate

```gate
candidate_facing_strings_without_a_translation == 0
evidence: status/evidence/T107.json
key: candidate_facing_strings_without_a_translation
```

Transcribed from `status/plan.md`'s row for this task, which declared this
metric before the task was imported. The name is the plan's, not a new one:
inventing a second name for a declared metric is a mistake this repository has
made four times, and `test_the_committed_plan_and_queue_agree` fails it.
Imported from issue #294

Found while drafting the candidate deliverables: a worker went to render a results page in Spanish and discovered the shipped labels are English, with no translation seam at all.

`presentation.PROVISIONAL_LABEL` is one hardcoded English string. It is not a fixture and not a test double — it is what the candidate reads.

## Why this is a defect rather than a gap

This project already has a standing requirement that **the supported languages behave identically**. ES/EN/CA parity is the bar; an English-only path is a *silent* feature, not a partial one, because nothing reports that the Spanish candidate got the English string. They just get it.

It is also the second instance of the same shape. `connector_health.BLOCK_PAGE_MARKERS` is English-only — "just a moment", "attention required", "checking your browser" — in a library that reads Spanish and Catalan boards. That one is already recorded in the handover as a known hole. Two instances is a pattern, and the pattern is: **strings that decide what a candidate sees, or whether a read succeeded, are written once in English and never given a second language.**

## Scope

Not "add i18n". The honest first step is to make the hole **measurable**, which is what this repo does with every other class of defect:

1. Find every candidate-facing literal that reaches a rendered page. `presentation.py` is the obvious surface; the step skills are the other.
2. Count them, and count how many have a Spanish rendering. That is the gate: `candidate_facing_strings_without_a_translation`, with a real `_evaluated` denominator and `gate_status`.
3. A zero over an empty scan is the failure mode to guard — the count of strings *found* must have a floor, the way `naming.MINIMUM_SCANNED` does for T55.

Whether the fix is a message catalogue or per-language constants is a design call for whoever takes it. Measuring first means the decision is made against a number instead of an impression.

## Note

`presentation.PROVISIONAL_LABEL` was rewritten in **#290 (T95)**, which is open at the time of filing. Whoever takes this should branch off main after #290 merges, or the string will move under them.

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
