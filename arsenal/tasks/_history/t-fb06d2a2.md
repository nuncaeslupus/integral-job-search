---
id: t-fb06d2a2
title: "T210: A long candidate session never suggests compacting before the context fills"
priority: 10
tags: [test-mode]
status: merged
---

Seeded by T188 from a test-mode note (session b461d09a, step-09-ranking, note 19).

> When context is growing, you could ask the user to compact it.

Suggest it at a step boundary, once, with what will be kept (state.json already makes resumption safe).


## Acceptance gate

```bash
uv run pytest tests/test_compaction_hint.py tests/test_step_skills.py tests/test_session_kind_rule.py -q
```
