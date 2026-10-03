---
id: t-98d9aad7
title: "T250: Adverts the candidate has already been shown or applied to are presented again as new"
label: "T250: no re-showing adverts"
priority: 5
---

Filed from a candidate session (test-mode 453a5c19). The owner's act-now note: fix everything said in the session.

## What happened

A round presented eight adverts as new. The candidate had already seen or applied to at least three of the employers (haddock, Cala, Valeria HR); an application confirmation for one sat in the same mailbox. Deduplication compares against stored offers by URL and text hash, so the same vacancy from another board, or one applied to outside the tool, comes back as new.

## What is missing

- Before presenting, each offer is compared by employer and title similarity against every offer previously shown, shortlisted, applied to or rejected, across boards.
- What was shown is recorded as shown, so a later round can tell.
- Matches are withheld and counted in the round's summary.


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
