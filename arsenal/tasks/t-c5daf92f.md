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
  1. the id is a live row that the **raw** listing — `unrecorded_statements` before
     any acknowledgement is applied — returns today (checking against the filtered
     list would be circular at read time);
  2. `words` equals the row's whole text, whitespace-normalised — never a substring:
     a substring lets `--words "a"` through, and lets the non-topic half of a row
     ("30 minutos, y nada de banca") close the topic half;
  3. the row carries **exactly one** dimension tag, and it is an id from the closed
     vocabulary `dimensions/*.yaml` (`integral.dimensions.load_dimensions`), outside
     `CONSTRAINT_FIELD_NAMES`, and outside a named topic-bearing subset of that
     vocabulary (`domain_knowledge`, `mission_alignment`, … — the exact subset is an
     owner decision recorded in this file before implementation). Membership in a
     closed list, never "not a recorded exclusion's facet": on a pre-T203 profile
     nothing is recorded, so that clause would exclude nothing;
  4. `text_sha256` matches the row's current text — a correction lapses it.
- `unrecorded` excludes acknowledged rows from its exit decision but **prints them to
  stderr** as `acknowledged: <id> "<words>"`, and the step 7 checkpoint reports them
  as `acknowledged_exclusion_statements`: closed, never silent.
- SKILL.md: replace "leave such a row as it is" with the `acknowledge` step, and say
  that a row naming any topic is recorded, never acknowledged.

Measured, not asserted: an `EVIDENCE_SOURCES` record counts
`unclosable_unrecorded_rows` over constructed profiles (the `commute` row; a
step-2 write with a blank quote, which #608 already stops listing) and
`acknowledged_topic_rows` over the refusal cases below, both `== 0`, with a floor
on the states constructed.

Fixtures (second reader writes the adversarial half): the `commute` row closes and
`unrecorded` exits 0; each refusal (1)–(4) is pinned by a case that reverts it; an
acknowledgement on "defensa, apuestas" (untagged), on the round-3 pinned-tagged topic
row, on a `sector`-tagged row of a profile with **nothing** recorded, on a
`mission_alignment`-tagged row, on a two-tag row, and with `--words` a strict
substring ("30 minutos" of "30 minutos, y nada de banca") each exits non-zero and the
row stays listed.

Known ceiling: a single-tag non-topic row whose whole text also names a topic can
still be acknowledged by quoting all of it. The stderr line keeps that visible; no
free-text check can close it.

## Acceptance gate

```bash
uv run pytest tests/test_exclusion_backfill.py
make evidence
```
