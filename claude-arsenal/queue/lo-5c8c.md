# T11: Normalised offer schema + manual-paste connector

## Acceptance gate

```gate
offer_schema_violations == 0
evidence: status/evidence/T11.json
key: offer_schema_violations
```

Write the measured value to `status/evidence/T11.json` as `{"offer_schema_violations": <number>}`, commit it, then record the row in the plan's Evidence log with the command that produced it.

An evidence gate asserts the number against the threshold, so it cannot pass
vacuously — a missing evidence file is a hard failure, not a skip. It also runs
no build tooling, which matters for tasks that run before the scaffold exists.

## Tests

Write these RED before any production code:

`test_pasted_text_produces_valid_offer` in `tests/test_connect_manual.py` — a pasted ad yields a schema-valid offer with verbatim `text`

## Location

Service: **SUPPLY** · Size: M

Design: `status/plan.md` (T11) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
