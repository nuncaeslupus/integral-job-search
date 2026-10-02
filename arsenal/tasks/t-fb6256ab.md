---
id: t-fb6256ab
title: "T230: 68 stored offers cannot be loaded (salary.period is 'YEAR', 'MONTH', 'hourly'), and one of them aborts any loop over the store"
label: "T230: 68 stored offers cannot"
priority: 10
---

Filed from a candidate session (test-mode 658fcce2).

Measured 2026-10-02: 68 of 2,908 files in one candidate's `offers/` raise `OfferError` in `load_offer`, every one on `salary.period` (`hourly` 15, `MONTH` 11, `YEAR`, ...), which the schema limits to `year|month|week|day|hour`. Something writes offers without going through the model. Find that writer, normalise the period where it is read from the board, repair the stored records, and make list-wide readers report an unreadable record instead of raising in the middle of a ranking.


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
