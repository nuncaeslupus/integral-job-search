---
id: t-be887fe3
title: "T235: every foorilla offer is stored with no company and no location"
label: "T235: foorilla company and location"
priority: 10
---

Filed from a candidate session (test-mode 658fcce2).

Measured 2026-10-02 on one candidate's store: **527 of 527** foorilla offers have an empty `company` and an empty `location.raw`. Screening by employer (a consultancy exclusion, a ruled-out employer — T228) and by reach cannot work on any of them, and a card for one has no employer to show.

Read both from the board (list row or advert page), or, if the board does not publish them, say so in `connector.yaml` and have the run report the board's offers as unplaceable rather than storing them as ordinary offers.


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
