---
id: t-0b0a29ea
title: "T187: step-07-sourcing: synonym-expand and parallel-search the web-search fallback before filtering"
priority: 5
tags: [step-07-sourcing]
---

Candidate note (Ivan, 2026-09-16, step `sourcing`): when this step falls back to a
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

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
# e.g. bash tests/surface_probe_test.sh
false
```
