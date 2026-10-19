---
id: t-67eb3a9d
title: "Mailbox: pin the two read-binding leftovers from #845"
label: "mailbox read leftovers"
priority: 10
tags: [MAILBOX]
status: merged
---

Non-blocking leftovers from #845's reviews: deleting the reads file and editing `read_at` still passes confirm; a read refused for no yes leaves its id free. Decide per case: fix with a product test, or document why not. Policy E applies.

## Acceptance gate
```bash
uv run python -m pytest -n0 -q tests/test_mailbox_replies.py
```
