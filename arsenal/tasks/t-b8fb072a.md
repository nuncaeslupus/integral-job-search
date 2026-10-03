---
id: t-b8fb072a
title: "T249: Asking an explicit question and recording the answer is left to the session instead of required by every step"
label: "T249: ask then record"
priority: 5
---

Filed from a candidate session (test-mode 453a5c19). The owner's act-now note: fix everything said in the session.

## What happened

The candidate said the offers shown were too senior and used tools he did not know. Two explicit questions (level; which named tools he had used, and whether he had set up infrastructure) produced answers that changed what was shown, and they were recorded as evidence. The owner's note: this is what moves the profile on, and it must be enforced across the whole process.

## What is missing

- Every step skill states the rule: a vague reaction is answered with an explicit, narrow question, and the answer is written to `profile/evidence.jsonl` with the question it answers before the step continues.
- A gate over the step skills that counts those lacking the rule.


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
