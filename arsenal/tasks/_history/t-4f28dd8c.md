---
id: t-4f28dd8c
title: "T239: a lesson learned inside one candidate's session has no route into the process every candidate gets"
label: "T239: candidate lessons reach process"
priority: 5
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

The owner's note: 'we have been doing work in my profile. But I don't know if all that has been added to the repo process … everything we have learned here should be used for everyone if it is generalizable.'

Today a correction a candidate makes (how a gap is worded, what a letter must not say, a screening rule) lands in that candidate's `profile/evidence.jsonl` and nowhere else; whether it becomes a task depends on the session remembering to offer it. The session-end pass in `test-mode` covers `[[…]]` notes only, and only in test sessions.

Give it a route: at the end of a candidate session, the corrections recorded during it are listed and each is either seeded as a task or recorded as candidate-specific, with the decision kept. Nothing personal leaves the profile — the task carries the rule, never the candidate's words about themselves.


## Acceptance gate

```bash
uv run pytest tests/test_lesson_triage.py -q
```
