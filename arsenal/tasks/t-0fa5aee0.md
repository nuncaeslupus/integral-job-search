---
id: t-0fa5aee0
title: "T188: Triage the 51 test-mode notes captured across past sessions that were never seeded"
priority: 10
tags: [test-mode]
---

Audit (2026-09-16): every historical `.test-mode/*.jsonl` ledger (5 sessions, 51
notes total) shows `captured == shown` — the ledger mechanism has never lost a note
it successfully parsed — but grepping `arsenal/tasks/` (live and `_history/`) for
the `Test-mode note` title pattern this skill's own seed command produces returns
zero matches. So the end-of-session triage step (test-mode skill: "print every note,
ask which to address, seed only what's confirmed") has apparently never been run to
completion in any past session — notes accumulate silently and are never surfaced
for a decision.

Action: read through the 5 historical ledgers, present each note to the owner, and
seed (or explicitly discard) each one — closing out the backlog once. Worth deciding
separately: should ending a test session enforce running triage before the session
is considered closed, rather than leaving it to be remembered each time?


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
