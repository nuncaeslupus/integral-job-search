---
id: t-37ea22aa
title: "T229: A skill the candidate lacks cannot be ruled out by requirement: text matching cannot tell required from mentioned"
label: "T229: A skill the candidate"
priority: 5
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

"Nunca he usado Go, así que fuera." A text exclusion on `golang` matches 128 stored adverts, many of which list it as one option among several (one employer alone: 32); 299 more say bare `Go`, which no word match can separate from the verb. So the statement was stored as evidence and applied by hand. Read required-versus-optional skills in extraction (step 8) and let a ruled-out skill hold only adverts that require it.


## Acceptance gate

```bash
uv run pytest tests/test_skill_requirement.py -q
```
