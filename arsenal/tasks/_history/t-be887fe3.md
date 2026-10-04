---
id: t-be887fe3
title: "T235: every foorilla offer is stored with no company and no location"
label: "T235: foorilla company and location"
priority: 10
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

Measured 2026-10-02 on one candidate's store: **527 of 527** foorilla offers have an empty `company` and an empty `location.raw`. Screening by employer (a consultancy exclusion, a ruled-out employer — T228) and by reach cannot work on any of them, and a card for one has no employer to show.

Read both from the board (list row or advert page), or, if the board does not publish them, say so in `connector.yaml` and have the run report the board's offers as unplaceable rather than storing them as ordinary offers.


## Acceptance gate

```bash
UV_PYTHON=3.12 uv run --extra dev pytest tests/test_employer_published.py -q -k "foorilla"
```
`arsenal-task: t-be887fe3`
