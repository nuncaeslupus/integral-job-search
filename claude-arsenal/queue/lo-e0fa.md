# T6: Profile store: append-only `evidence.jsonl` + `rebuild` to byte-identical derived files; two-profile fixture

## Acceptance gate

```gate
profile_rebuild_deterministic == 1
evidence: status/evidence/T6.json
key: profile_rebuild_deterministic
```

```bash
echo "no gate command defined for T6 — replace this line with the command that writes status/evidence/T6.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T6.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_rebuild_twice_produces_identical_bytes` in `tests/test_profile_store.py` — two rebuilds from one log are byte-identical; `test_second_profile_does_not_leak_into_first` — writing profile B leaves A unchanged

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T6) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
