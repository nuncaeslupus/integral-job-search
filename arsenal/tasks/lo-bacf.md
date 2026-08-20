---
id: lo-bacf
title: "T10: Preference weights: forced pairwise choices → part-worths → salary-equivalent scale"
priority: 5
deps: [lo-b422]
workspace: PROFILE
tags: [m3]
---

## Acceptance gate

```gate
weight_salary_equivalent_roundtrip_error <= 0.01
evidence: status/evidence/T10.json
key: weight_salary_equivalent_roundtrip_error
```

```bash
echo "no gate command defined for T10 — replace this line with the command that writes status/evidence/T10.json" >&2; exit 1
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T10.json`; the `gate` block asserts the
number in it against the threshold. Without the first, a stale or hand-written
evidence file passes unchallenged; without the second, a command that exits 0
counts as a gate whatever it measured.

The default command fails on purpose. A task whose measurement is undefined has
not passed its gate — it has not been measured. Replace it as part of the work.

## Tests

Write these RED before any production code:

`test_partworth_to_salary_equivalent_roundtrips` in `tests/test_weights.py` — converting a dimension to €/month and back recovers the part-worth within 1%

## Location

Service: **PROFILE** · Size: M

Design: `status/plan.md` (T10) · Spec: `status/specification.md` §5 contracts · Methods: `docs/METHODS.md`
