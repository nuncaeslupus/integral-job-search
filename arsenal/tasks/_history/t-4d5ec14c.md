---
id: t-4d5ec14c
title: "T111: T89: get_connectors_evaluated == 13 is an exact package count in committed evidence"
priority: 5
status: merged
---

## Acceptance gate

```gate
growth_sensitive_evidence_keys == 0
evidence: status/evidence/T111.json
key: growth_sensitive_evidence_keys
```

Transcribed from `status/plan.md`'s row for this task, which declared this
metric before the task was imported. The name is the plan's, not a new one:
inventing a second name for a declared metric is a mistake this repository has
made four times, and `test_the_committed_plan_and_queue_agree` fails it.

Imported from issue #300

Found by the second-reader audit of #295. Same family as T55/T100 and now T104 — a count of the day committed as though it were a measurement.

`status/evidence/T89.json` records `get_connectors_evaluated: 13` and `get_connectors_still_plain_gets: 13`, both being the number of committed GET packages on the day. Adding a sixteenth connector package drifts them and reddens `make evidence` on an unrelated PR.

## The repair

The measurement that matters is the **relation**: `get_connectors_still_plain_gets == get_connectors_evaluated`, i.e. no GET package changed shape. That relation is growth-invariant.

So the count becomes `get_connectors_evaluated_at_least`, asserting a floor the way `naming.MINIMUM_SCANNED` does, with the equality kept as the real check. T89 itself already uses a floor for the ledger scan and #295 added `MINIMUM_CREDENTIAL_CASES` — this is the one place in that module still committing an exact census.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_connectors.py -q
uv run python -m integral.connector_transport
```

The `bash` block runs the module's suite and regenerates both evidence files;
the `gate` block above asserts the number in T111's committed record.
`growth_sensitive_evidence_keys` counts the keys of T89's **committed record**
that move when the connector library gains one more GET package — which is
what merging any connector PR does to every other branch — and
`evidence_keys_compared` is the denominator that says the comparison happened
at all.

## What was done

`record()` commits `get_connectors_evaluated_at_least` (the floor
`MINIMUM_GET_PACKAGES`, checked live in `measure`) and drops both censuses.
The equality the two counts carried is `get_packages_changed == []`, which
stays in the record and still fails when a GET package's request changes
shape. `measure_growth_sensitivity` runs the whole reading twice — over the
committed library and over that library plus one synthesised GET package — and
compares the two records key by key.

Five mutations, each shown red on the test named for it: `record` re-emitting
the census; the package floor back at `== 0`; the grown library never checked
for having actually grown; `MINIMUM_RECORD_KEYS_COMPARED` unenforced; and
`get_packages_changed` hard-coded empty.

## Noted, out of scope

`ledger_entries_scanned` (34) and `credential_key_cases_checked` (102) are
exact counts in the same record. They are invariant on *this* axis — a
connector package does not touch the ruled-out ledger or the credential-key
table — so T111's gate reads zero over them honestly; they move on their own
axes, which is a separate finding and a separate task.
