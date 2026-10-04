---
id: t-0b0a29ea
title: "T187: step-07-sourcing: synonym-expand and parallel-search the web-search fallback before filtering"
priority: 5
tags: [step-07-sourcing]
status: merged
---

Candidate note (2026-09-16, step `sourcing`): when this step falls back to a
general web search because no connector covers the candidate's market, it should
expand the search terms into synonyms itself (e.g. "AI engineer" / "LLM engineer" /
"prompt engineer" / "context engineer" / "agentic engineer"), run the resulting
queries in parallel, and union the results before applying the liveness/eligibility
filter — rather than running a single query and reporting on whatever it returns.

Observed live: doing this by hand across 6 parallel synonym queries surfaced
candidates a single-term search would have missed, but most turned out dead (410)
or geo-restricted to one country (US, Australia, Bulgaria/Greece-only). Whatever the
query-expansion mechanism, the liveness/eligibility filter and disclosure
requirements already in this skill still apply to the union, not just to one query's
results.


## Acceptance gate

```bash
uv run --extra dev pytest tests/test_sourcing_fallback_synonyms.py -q
```
