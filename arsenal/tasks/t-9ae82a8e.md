---
id: t-9ae82a8e
title: "T225: partition holds back only an offer's own status, so a copy of a ruled-out or already-shown advert is presented again"
label: "T225: partition holds back only"
priority: 10
---

Filed from a candidate session (test-mode 658fcce2).

`presentation_log.partition` withholds an offer whose **own** record is `screened_out`/`rejected` or that matches an exclusion. It does not look for another stored record of the same advert (same canonical URL, or same employer and title), so a rule-out or a `present()` row on one copy does not hold the others. Independent of T224: copies already in a store stay there. In session 658fcce2 the filter had to be done by hand (15 held as already seen, 14 as repeats).


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
