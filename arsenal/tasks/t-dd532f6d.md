---
id: t-dd532f6d
title: "T242: The ranker returns hash order when a priced dimension is unknown everywhere"
label: "T242: rank order, not hash"
priority: 5
---

Filed from a candidate session (test-mode 658fcce2). The owner's instruction for this round: the
project does a hard job to be able to sort offers, and anything that keeps it from sorting
correctly at this point is a design flaw.

## What happened

The candidate asked for their eleven sent applications in order of what suits them. `rank()`
returned all eleven on the Pareto front, none dominated, and **no salary-equivalent total for any
of them**. Every offer carried both priced dimensions as unknown, so `_salary_equivalent` returned
`None` for all, and the sort fell through to its tie-break: `offer_id`, a sha256. The order handed
back was the order of the hashes.

The candidate's stored rankings show this is the normal case, not an edge: of the last three, one
of 35 offers had a total, and none of 12 and none of 81 did. Each was presented as a ranking.

## What is missing

- An order that exists when totals do not. Unknown must stay unknown (the module is right not to
  score it 0.0), but "no total" cannot mean "no order": order on the known part of the total, on
  pay, or on an interval over the unknowns — and say which.
- The tie-break must never be presented as a preference. When the ranker cannot order two offers,
  the output says they are tied and why, rather than listing them in hash order.
- A gate: over a realistic set where a priced dimension is unknown on every offer, the fraction of
  offers ordered by id rather than by any reading is 0 — or the result says it is unordered.
- A way to rank a named set of offers (for example the ones already applied to), not only the live
  batch.


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
