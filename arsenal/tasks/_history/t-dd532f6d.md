---
id: t-dd532f6d
title: "T242: The ranker returns hash order when a priced dimension is unknown everywhere"
label: "T242: rank order, not hash"
priority: 5
status: merged
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

```bash
uv run --extra dev --extra collect pytest tests/test_rank_order_readings.py tests/test_rank.py tests/test_pay_dominance.py -q
uv run python -m integral.rank
python3 -c "import json,sys; m=json.load(open('status/evidence/T242.json')); sys.exit(0 if m['fraction_ordered_by_id']==0 and m['offers']>=12 and m['offers_with_a_total']==0 and m['violation_detected_when_planted']==1 and m['mixed_offers_with_a_total']>0 and m['mixed_fraction_ordered_by_id']==0 else 1)"
```
