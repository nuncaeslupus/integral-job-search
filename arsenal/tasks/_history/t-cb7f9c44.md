---
id: t-cb7f9c44
title: "T344: An offer reaches the candidate's decision with no brief on the real employer or whether it is still open"
priority: 5
status: merged
---

Promoted from the candidate sessions of 2026-09-06..2026-10-16: a practice the assistant ran by hand (scratch scripts or profile conventions) that any candidate needs.

Two recurring failures, both met again on 2026-10-16: an aggregator re-posting an advert under its own name (the employer had to be inferred from the advert's wording), and a posting closed at the source while still shown by aggregators.

Before an offer is put to the candidate for a decision, produce a short brief: the real employer (resolved through the advert's apply link or wording), its own job board's copy of the posting and whether it is still live there, what the employer does and its sector checked against the candidate's exclusions, published pay or the source of an estimate, and whether it hires in the candidate's country.

Suggested gate: `offers_presented_for_decision_without_an_employer_brief == 0`.

## Acceptance gate

```bash
uv run pytest tests/test_employer_brief.py -q
```

Notes: "presented" is `search/presentations.jsonl` (`presentation_log.present`), joined on `offer_ids`; briefs live at `offers/briefs/<id>.json`. An offer with `live_at_source=false` counts as briefed only when its lifecycle status is `expired`; a brief is stale when an exclusion was stated after it was written.
