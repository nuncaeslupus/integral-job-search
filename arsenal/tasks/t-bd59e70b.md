---
id: t-bd59e70b
title: "D-13: say what the tool is doing before a long silent setup"
priority: 10
---

Captured during a test session at step `intake` (ledger `test-2026-08-20-a`).

> You are doing a lot of things and the user is waiting. You should answer the user and tell him
> "Nice to meet you, XXX. Let me prepare the environment, it will take a moment" or similar. Then,
> you prepare the folders, run your scripts and finally answer something like "Thanks for waiting,
> XXX / Here's how this works..."

The candidate sees `Skill(step-02-constraints) Successfully loaded` and a run of Bash calls with no
narration. Two changes, both in the step skills rather than in code:

1. Acknowledge the person BEFORE profile creation, then do the setup, then continue.
2. Name what is happening in one short line when a step does visible work.

Addressed in: `step-00-identify`, and the shared protocol prose every step skill inherits.


## Acceptance gate

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# e.g. bash tests/surface_probe_test.sh
false  # fail until a real check replaces this
```
