# T11: Normalised offer schema + manual-paste connector

## Acceptance gate

```gate
offer_schema_violations == 0
evidence: status/evidence/T11.json
key: offer_schema_violations
```

```bash
echo "no gate command defined for T11 — replace this line with the command that writes status/evidence/T11.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T11.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_pasted_text_produces_valid_offer` in `tests/test_connect_manual.py` — a pasted ad yields a schema-valid offer with verbatim `text`

## Location

Service: **SUPPLY** · Size: M

Design: `status/plan.md` (T11) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
