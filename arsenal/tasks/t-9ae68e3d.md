---
id: t-9ae68e3d
title: "T246: Pay enters the ranking unconverted, and a stated band can be stored as none"
label: "T246: normalise pay for ranking"
priority: 10
---

Filed from a candidate session (test-mode 658fcce2). The owner's instruction for this round: the
project does a hard job to be able to sort offers, and anything that keeps it from sorting
correctly at this point is a design flaw.

## What happened

Among the eleven offers, one band was in USD while the candidate's weights are in EUR; it reached
`rank()` as a bare per-month number: `Candidate.salary_per_month` carries no currency, and
`require_pay_coherence` checks only a band's point against the band, skipping a band in another
currency. Nothing converts it and nothing refuses it. Another advert stated a USD band in its text and was stored with
`salary: null`, so it counted as unpaid. Six of eleven had no published pay and therefore no
basis for comparison at all.

## What is missing

- One conversion step into the weights' currency, dated, before any pay reaches the sort; refuse,
  rather than compare, when no rate is available.
- Extraction re-reads the advert text for a band when the source left `salary` empty.
- For an offer with no published pay, an estimate with its source and range (role, level, country),
  marked as an estimate — or the offer is ordered among the unpaid ones and said to be.


## Acceptance gate

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
# e.g. bash tests/surface_probe_test.sh
false
```
