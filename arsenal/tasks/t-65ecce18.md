---
id: t-65ecce18
title: "D-15: stop offering to end the session at every step boundary"
priority: 10
---

Captured during a test session at step `constraints` (ledger `test-2026-08-20-a`).

> Don't ask to let the session so soon, just ask if you see it is taking too much time.

Every step skill's Boundary example ends with "Carry on, or leave it here?" — so a candidate who
answers four steps is asked four times whether they want to stop. Offer the exit when the session is
actually long, not as the standard close of every step.

Addressed in: the Boundary sections of all thirteen step skills.


## Acceptance gate

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# e.g. bash tests/surface_probe_test.sh
false  # fail until a real check replaces this
```
