---
id: t-b4fafa85
title: "T212: The send/ folder one candidate used for final documents is not part of the step-11 workflow"
priority: 10
tags: [test-mode]
status: merged
---

Seeded by T188 from a test-mode note (session ba7a3a96, step-11-application, note 4).

> Add this send/ folder to our workflow for other sessions, for everyone.

That session collected the exact files to send (final CV and letter) into one send/ directory per offer. Make it the step-11 output for every candidate, and tie it to T46's send boundary: what is in send/ is what was approved.


## Acceptance gate

```bash
uv run --extra dev --extra collect pytest tests/test_send_folder.py -q
```
