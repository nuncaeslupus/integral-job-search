---
id: t-bab04ce5
title: "T208: Step 3 never asks a developer for their GitHub or public projects"
priority: 10
tags: [test-mode]
status: merged
---

Seeded by T188 from a test-mode note (session b461d09a, step-03-history, note 4).

> Given I'm a developer, maybe you should have asked me about my GitHub or other projects, unless you will do it at a later step.

Public work is evidence the history step can read directly, and step 11 already links own projects when public (CV norms). Ask for it when the role family makes it relevant; no later step does.


## Acceptance gate

```bash
uv run --extra dev --extra collect pytest tests/test_step03_public_work.py -q
```
