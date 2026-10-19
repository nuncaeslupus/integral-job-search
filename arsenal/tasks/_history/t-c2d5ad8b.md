---
id: t-c2d5ad8b
title: "T305: Follow-ups from T235 (#708): foorilla location markers and truncated place lists"
priority: 5
status: merged
---

Imported from issue #710

Optional findings from the second reader on #708, not done there:

- O2: map foorilla's `[R]` / `[WH]` marker in `location.raw` to `location_remote` (needs a `first_text_node`-style `take` or a post-parse).
- O3: multi-place cards are cut by the board with "…"; check whether the advert page carries the full place list.
- T235 plan-row metric `foorilla_offers_without_location` is a label no evidence computes; consider naming the pinning test in the cell (as T236/T237 do).

## Acceptance gate

```bash
uv run python -m pytest -n0 -q tests/test_employer_published.py -k foorilla
uv run python -m pytest -n0 -q tests/test_connectors.py -k first_text_node
```
