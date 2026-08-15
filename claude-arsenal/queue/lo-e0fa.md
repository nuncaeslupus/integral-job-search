# T6: Profile store: append-only `evidence.jsonl` + `rebuild` to byte-identical derived files; two-profile fixture

## Acceptance gate

```gate
profile_rebuild_deterministic == 1
evidence: status/evidence/T6.json
key: profile_rebuild_deterministic
```

Write the measured value to `status/evidence/T6.json` as `{"profile_rebuild_deterministic": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_rebuild_twice_produces_identical_bytes` in `tests/test_profile_store.py` — two rebuilds from one log are byte-identical; `test_second_profile_does_not_leak_into_first` — writing profile B leaves A unchanged

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T6) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
