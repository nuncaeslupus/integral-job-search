---
id: t-476dcbe2
title: "T248: Search terms never grow from the adverts a search finds"
label: "T248: terms from adverts"
priority: 5
status: merged
---

Filed from a candidate session (test-mode 453a5c19). The owner's act-now note: fix everything said in the session.

## What happened

Five titles the candidate would search for (applied AI engineer, developer platform, AI platform engineer, generative AI engineer, developer tools) were only found by reading adverts a board recommended. The aim's term list is written once and nothing proposes additions.

## What is missing

- After a sourcing round, titles recurring in found adverts and absent from the aim are proposed to the candidate, who accepts or declines each.
- Accepted terms are appended to `search/aim.json`; nothing is added without their yes.


## Acceptance gate

```bash
uv run pytest tests/test_term_proposals.py -q
```
