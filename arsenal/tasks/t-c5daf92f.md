---
id: t-c5daf92f
title: "T220: A constraint row on a dimension outside the pinned ten is listed by `unrecorded` forever, and no honest record closes it"
priority: 5
deps: []
---

Found by the second reader of #598 (T218), finding F6 — fail-closed, design. A
`constraint` row whose dimension is outside T24's pinned ten (`dimensions=["commute"]`,
"No quiero desplazarme más de 30 minutos.") is not step 2's pinned write, so
`unrecorded_statements` lists it; it rules out no topic, so no honest
`record` covers it. `python -m integral.sourcing_exclusions unrecorded` then never
exits 0, while step 7's SKILL.md says both "re-run until exit 0" and "leave such a
row as it is" — two instructions that cannot both be followed.

## Rule

A per-row **acknowledgement**, recorded with the candidate's words, that closes one
row and nothing else:

- `python -m integral.sourcing_exclusions acknowledge --handle H --evidence <ev-id>
  --words "…"` appends `{evidence_id, words, text_sha256}` to
  `search/exclusion_acknowledgements.json`.
- **Refused** unless all hold, checked at write *and* re-checked at read (a stale or
  hand-edited file must not close anything):
  1. the id is a live row `unrecorded_statements` lists today;
  2. `words` is a non-empty verbatim substring of that row's text;
  3. the row carries at least one dimension tag, and **every** tag is outside
     `CONSTRAINT_FIELD_NAMES` and is not the facet of any recorded exclusion
     (`Exclusion.facet`) on this profile — so the bare topic list (no tags) and a
     topic row tagged with a pinned field (T218 round 3) stay listed;
  4. `text_sha256` matches the row's current text — a correction lapses it.
- `unrecorded` excludes acknowledged rows from its exit decision but **prints them to
  stderr** as `acknowledged: <id> "<words>"`, and the step 7 checkpoint reports them
  as `acknowledged_exclusion_statements`: closed, never silent.
- SKILL.md: replace "leave such a row as it is" with the `acknowledge` step, and say
  that a row naming any topic is recorded, never acknowledged.

Fixtures (second reader writes the adversarial half): the `commute` row closes and
`unrecorded` exits 0; each refusal (1)–(4) is pinned by a case that reverts it; an
acknowledgement on "defensa, apuestas" (untagged), on the round-3 pinned-tagged topic
row, and on a row tagged `sector` after `sector:banca` is recorded each exits non-zero
and the row stays listed.

## Acceptance gate

```bash
uv run pytest tests/test_exclusion_backfill.py
```
