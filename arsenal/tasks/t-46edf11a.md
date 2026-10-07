---
id: t-46edf11a
title: "T256: the dimension model does not cover the English corpus — 0.8423 against a 0.85 per-language floor"
priority: 5
requires: [human:gate]
---

Imported from issue #321

Filed from #320, against the measurement that PR now records.

## The measurement

Applying the independent audit of `concept_map.yaml` (#320, comment 5517619074 — 41 placements
wrong in the fail-open direction) moves `ontology_hit_rate_by_language` to:

| language | rate |
|---|---|
| ca | 0.8942 |
| es | 0.8803 |
| **en** | **0.8423** |

Aggregate is 0.8798, so T57's declared gate (`ontology_hit_rate >= 0.85`) survives the audit.
The **per-language** floor does not: nine of the audit's accepted findings fall on English
adverts, and English was already the weakest of the three at 0.8731 before them.

`status/evidence/T17.json` now carries `languages_below_gate: ["en"]` so the shortfall is a
value in the record rather than an absence from it, and
`test_the_per_language_shortfall_is_recorded_rather_than_averaged_away` pins it exactly — English
recovering fails that test as loudly as a second language falling under, so neither drifts.

## Why remapping cannot fix it

The 42 unmapped English occurrences are 39 distinct names, all but three of them singletons.
A second reader took the residue back to the 41 dimension `definition:` blocks and found exactly
one placement the definitions genuinely reach — `evaluation practice required` → `ai_in_the_work`,
on *"Strong evals practice: golden sets, LLM-as-judge, regression detection"*, which is applied in
#320 and moves English from 0.8385 to 0.8423.

Nothing else in the residue is reachable without stretching a definition, which is the fail-open
move the audit exists to stop. **English is short by 3 occurrences and there is no honest
remapping that closes it** — so this is a widening task, not a mapping one.

## The gap the audit named

Its structural finding is the place to start, and it is not English-specific:

> narrow technical specialisms (PKI, MBSE, navigation algorithms, platform engineering, quantum
> cryptography) have **no dimension at all** — `technical_depth` measures hardness,
> `tool_specificity` measures tools, `domain_knowledge` measures sectors, and none asks *which
> technical field*.

`domain_knowledge` had been absorbing them, which is why the gap was invisible: unmapping those
eleven occurrences is what put it back into the staleness signal.

The English residue additionally clusters around things no dimension asks:

- how performance is measured (`measured on named service metrics`, `measured on partner delivery KPIs`)
- what the intermediary takes (`platform takes no cut of your rate`, `payment reliability offered as the pitch`)
- openness as a working style (`open-source development in public`, `open-source rootedness claimed`,
  `stated volunteering and open-source commitment`)
- ambiguity tolerance as a stated filter (`ambiguity tolerance required`, 2 occurrences)

## Acceptance gate

```gate
ontology_hit_rate_worst_language >= 0.85
evidence: status/evidence/T17.json
key: ontology_hit_rate_worst_language
status-key: ontology_status
```

Read as: `languages_below_gate` is empty. The number must be reached by widening the model, never
by dropping the concepts a reader could not name — T57's task file says why, and the aggregate is
what the three languages can carry for each other.

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
