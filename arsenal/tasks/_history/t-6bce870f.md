---
id: t-6bce870f
title: "T107: The candidate-facing strings are English-only in a Spanish-facing product"
priority: 5
status: merged
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

## What landed

`strings/catalogue.json` — every string the candidate reads on the ranked page,
in `en` (the source), `es` and `ca`. `src/integral/strings.py` reads it;
`presentation.py` looks strings up through `_t(key, language)` instead of
holding them as English literals, and `render()`, `card()` and every helper
below them take a `language`.

Three properties, and only two of them are claimed:

1. **Completeness** — 24 strings x 2 non-source languages = 48 evaluated, 0
   missing. Countable.
2. **Staleness** — each translation records `of`: the sha256 of the source text
   it was made from. Change the English and every translation of it stops
   matching, so *"when we change a report we update all the languages"* stops
   being a promise somebody has to keep and becomes a check that fails. A
   translation with **no** recorded provenance counts as stale, not fresh — an
   unstamped entry is exactly the state this replaces, and must not be able to
   opt out by omitting its stamp.
3. **Quality is not claimed anywhere.** No gate here says a translation is
   correct. Nothing can tell whether a contributed German pack is good German,
   so a pack records who made it and when, and that is the whole of the honest
   offer. This is the one place the repo's usual "measure it" answer does not
   apply, and saying so is better than a metric that implies otherwise.

**A missing or stale string falls back to the source and is named.** Silent
English is the defect this task exists to close; announced English is a partial
feature honestly reported. `presentation.untranslated(language)` returns exactly
which strings a language could not serve, so a session says so once rather than
the page apologising in every sentence. A stale translation falls back too —
text translated from English that has since changed is confidently wrong, which
is worse than visibly foreign.

The card column is **derived** from the label widths rather than typed as
spaces: `ubicación` is longer than `location`, and a hardcoded column renders
one of the two ragged. The pay period is rendered too — without it a Spanish
card reads `EUR/year`.

**Out of scope, named rather than silently left:** `enrichment.NOT_FROM_THE_ADVERT`
and `pay.NetEstimate.label()` are candidate-facing and still English-only, as is
`connector_health.BLOCK_PAGE_MARKERS` — whose English-only block-page detection
means a Spanish interstitial reads as a real empty result. The step skills' prose
is untouched. Each is the same shape as this task; none is in this diff.

## Acceptance gate

```bash
set -euo pipefail
uv run pytest tests/test_strings.py tests/test_presentation.py -q
uv run python -m integral.strings
uv run python tools/t107_gate.py
```
