---
id: t-4d5ec14c
title: "T111: T89: get_connectors_evaluated == 13 is an exact package count in committed evidence"
priority: 5
requires: [human:gate]
---

Imported from issue #300

Found by the second-reader audit of #295. Same family as T55/T100 and now T104 — a count of the day committed as though it were a measurement.

`status/evidence/T89.json` records `get_connectors_evaluated: 13` and `get_connectors_still_plain_gets: 13`, both being the number of committed GET packages on the day. Adding a sixteenth connector package drifts them and reddens `make evidence` on an unrelated PR.

## The repair

The measurement that matters is the **relation**: `get_connectors_still_plain_gets == get_connectors_evaluated`, i.e. no GET package changed shape. That relation is growth-invariant.

So the count becomes `get_connectors_evaluated_at_least`, asserting a floor the way `naming.MINIMUM_SCANNED` does, with the equality kept as the real check. T89 itself already uses a floor for the ledger scan and #295 added `MINIMUM_CREDENTIAL_CASES` — this is the one place in that module still committing an exact census.

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
