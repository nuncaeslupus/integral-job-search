---
id: t-cb7f9c44
title: "T344: An offer reaches the candidate's decision with no brief on the real employer or whether it is still open"
priority: 5
requires: [human:gate]
---

Promoted from the candidate sessions of 2026-09-06..2026-10-16: a practice the assistant ran by hand (scratch scripts or profile conventions) that any candidate needs.

Two recurring failures, both met again on 2026-10-16: an aggregator re-posting an advert under its own name (the employer had to be inferred from the advert's wording), and a posting closed at the source while still shown by aggregators.

Before an offer is put to the candidate for a decision, produce a short brief: the real employer (resolved through the advert's apply link or wording), its own job board's copy of the posting and whether it is still live there, what the employer does and its sector checked against the candidate's exclusions, published pay or the source of an estimate, and whether it hires in the candidate's country.

Suggested gate: `offers_presented_for_decision_without_an_employer_brief == 0`.

## Acceptance gate

<!-- Write a real check below, then DELETE the `requires: [human:gate]` line. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
