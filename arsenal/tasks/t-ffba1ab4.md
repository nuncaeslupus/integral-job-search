---
id: t-ffba1ab4
title: "T211: Nothing shows the candidate where every application stands at a glance"
priority: 5
tags: [test-mode]
---

Seeded by T188 from a test-mode note (session ba7a3a96, step-11-application, note 3).

> A lo mejor deberíamos tener o poder generar un Excel o algo similar para saber en todo momento cómo están las cosas.

T82 defines the status vocabulary; nothing renders it. One table (offer, employer, status, date, next action, link), generated from the store, openable as a spreadsheet.


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
