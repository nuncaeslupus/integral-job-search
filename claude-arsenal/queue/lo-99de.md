# T39: Scoring triggers — step boundary, explicit request, batch threshold N

## Acceptance gate

```gate
unscheduled_scoring_runs == 0
evidence: status/evidence/T39.json
key: unscheduled_scoring_runs
```

```bash
uv run --extra dev pytest tests/test_scoring_triggers.py -q
uv run --extra dev python -m jobsearch.scoring status/evidence/T39.json
```

## What this is

Traits update continuously, but the cost of inference cannot be paid on every
message. Capture is cheap and always on (T28); scoring is expensive and runs at
exactly three triggers:

1. a **step boundary** — any step ending recomputes what its evidence touched;
2. an **explicit request** — "what do you know about me now?";
3. a **batch threshold** — N new trait-bearing evidence rows since the last run.
   N is set in the Traits step specification.

Each derived file records `scored_at` and the `profile_revision` it was computed
from, so freshness is visible rather than assumed.

## The rule that matters

**Deferring scoring costs freshness and nothing else.** Because the profile is
a pure function of the log, the log is never behind and no evidence is ever lost
to a scoring run that did not happen. A test that proves this is worth more than
the trigger logic itself.

## Tests

Write these RED before any production code:

`test_scoring_does_not_run_per_message` in `tests/test_scoring_triggers.py` —
a conversation of many turns below the batch threshold triggers no scoring run;
`test_deferred_scoring_loses_no_evidence` — scoring after N deferred turns
yields the same result as scoring at every turn;
`test_each_derived_file_records_scored_at_and_revision`.

## Location

Service: **RUNTIME** · Size: S · Depends: T37

Design: `status/plan.md` (RUNTIME) · Spec: `status/spec-v2-process.md` §4.2
