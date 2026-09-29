---
id: t-8a4dd4ee
title: "T213: Ending a test-mode session does not require triaging its notes, so 58 accumulated unseen"
priority: 5
tags: [test-mode]
---

Seeded by T188 on the owner's decision (2026-09-29): ending a test session must enforce the triage.

T188 found 58 notes across 7 ledgers, none ever seeded, because the end-of-session pass (query_notes.py, then seed or discard each note) was left to memory. The session end should refuse to close while a ledger holds a note with no recorded seed or discard decision, and record each decision in the ledger so the next query shows it.


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
