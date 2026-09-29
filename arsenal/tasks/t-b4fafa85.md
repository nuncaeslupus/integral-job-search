---
id: t-b4fafa85
title: "T212: The send/ folder one candidate used for final documents is not part of the step-11 workflow"
priority: 10
tags: [test-mode]
---

Seeded by T188 from a test-mode note (session ba7a3a96, step-11-application, note 4).

> Add this send/ folder to our workflow for other sessions, for everyone.

That session collected the exact files to send (final CV and letter) into one send/ directory per offer. Make it the step-11 output for every candidate, and tie it to T46's send boundary: what is in send/ is what was approved.


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
