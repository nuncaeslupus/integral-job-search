---
id: t-fb06d2a2
title: "T210: A long candidate session never suggests compacting before the context fills"
priority: 10
tags: [test-mode]
---

Seeded by T188 from a test-mode note (session b461d09a, step-09-ranking, note 19).

> When context is growing, you could ask the user to compact it.

Suggest it at a step boundary, once, with what will be kept (state.json already makes resumption safe).


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
