---
id: t-67eb3a9d
title: "Mailbox: pin the two read-binding leftovers from #845"
label: "mailbox read leftovers"
priority: 10
tags: [MAILBOX]
---

Non-blocking leftovers from #845's reviews: deleting the reads file and editing `read_at` still passes confirm; a read refused for no yes leaves its id free. Decide per case: fix with a product test, or document why not. Policy E applies.

## Acceptance gate
```bash
uv run python -m pytest -n0 -q tests/test_mailbox_replies.py
```


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
