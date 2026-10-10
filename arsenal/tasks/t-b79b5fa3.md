---
id: t-b79b5fa3
title: "T278: An offer with no salary is ordered by nothing at L2, even with every priced dimension settled"
priority: 5
requires: [human:gate]
---

Imported from issue #555

Measured on a live round, 2026-09-23, over 35 verified-live adverts from the new methods (T144 ATS boards, T194 talent.com).

Both of this candidate's priced dimensions (`mission_alignment`, `stack_modernity`) were settled on **all 35** — `still_unsettled: 0` after the rules stage plus the model stage. `rank()` still returned `level: L2` with `ordering = totals`, and `salary_equivalent_total` was computed for exactly **one** of the 35, because `Candidate.salary_per_month is None` for the other 34 — those adverts publish no pay.

The other 28 frontier entries therefore sort in **offer-id order**, which is arbitrary, and the ranking reads as an ordering to anyone who does not know that.

This is distinct from #548. #548 is about a conjoint pricing dimensions the adverts never state; here every priced dimension *is* stated and settled, and the ordering is still empty. The missing input is salary, and `salary_equivalent_total()` returns `None` the moment `salary_per_month` is.

What the candidate can actually be shown today is the conjoint value of the settled dimensions alone — `sum(weight[d] * score[d])`, in the ranking's numeraire — which separated those 35 into nine distinct groups from 863 to 0 €/month. That is a real partial order and the engine discards it.

Suggested shape: when no candidate carries a salary, order by the dimension value and say so in the ranking, rather than falling back to id order. The rule that a total needs a salary is right; silently degrading to id order is what is wrong.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
