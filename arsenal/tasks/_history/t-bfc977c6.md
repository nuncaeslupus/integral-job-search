---
id: t-bfc977c6
title: "T221: T218's backfill loop still cannot close on a non-pinned constraint row, and the step-7 checkpoint has two unpinned error paths"
priority: 5
deps: [t-a4dc5d52]
status: merged
---



Filed from #598's second readers: round 3 (F6, issuecomment-5921154493) and round 4 (N1–N3, issuecomment-5921451249). None of them blocked T218. T218 merged as `2dbc21c`.

**F6 (fail-closed, design).** `sourcing_exclusions.unrecorded_statements` lists every free-text `constraint` row of steps `identify`/`constraints`. It skips only step 2's own pinned-field write (`_is_a_pinned_field_write`). A constraint row on a dimension outside T24's pinned ten is therefore listed forever, and no honest `record` covers it. Example: `dimensions=["commute"]`, text "No quiero desplazarme más de 30 minutos.", the shape of `integral.feedback`'s own fixture. On such a profile `unrecorded` never exits 0. Step 7's SKILL.md ("Backfill") says both "re-run until it exits 0" and "leave such a row as it is", which cannot both be followed. T218's task text requires the loop to be closable.

The remedy must close the loop without silencing a topic row. Weigh fail-open over fail-closed. One option is a per-row acknowledgement ("not a topic") kept under `search/`, written only with the evidence id and the candidate's words, which `unrecorded` honours. A listed-then-acknowledged topic is the candidate's call, never the session's.

**N1.** The step-7 checkpoint's `UnicodeDecodeError` catch (`.claude/skills/step-07-sourcing/scripts/run_checkpoint.py`) is reached by no test. Add a not-UTF-8 twin of `test_a_corrupt_evidence_log_makes_the_checkpoint_main_exit_2`.

**N2 (fail-closed).** The checkpoint does not catch `OSError`. With `search/exclusions.json` as a directory it gives a traceback and exit 1, while the `unrecorded` CLI exits 2, and SKILL.md says the two agree. Add `OSError` to the tuple and pin it.

**N3 (fail-open in theory; no writer produces it today).** `_is_a_pinned_field_write` accepts `{"quote": <non-str>, "value": {}}`, and reverting its `"quote" in payload` check survives the test file. Require a string quote and a non-empty value dict, or validate the value through `candidate.FIELD_MODELS`. Pin it.

Run tests with `UV_PYTHON=3.12`. CI uses 3.12, and on 3.13 `tests/test_connector_policy.py` fails on main as well.


**N1–N3 are done in #608**: the checkpoint catches `OSError`, both error paths are pinned, and the pinned-write predicate requires a `str` quote and a value `FIELD_MODELS` accepts for every tagged field. What is left here is F6.

## Acknowledgement rule (from #608, after its second reader)

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

## Owner decisions (2026-10-01)

- Topic-bearing dimensions, never acknowledgeable: `domain_knowledge`, `mission_alignment`,
  `product_vs_services`, `company_stage` (`sourcing_exclusions.TOPIC_DIMENSIONS`).
- A tag must be a `dimensions/*.yaml` id exactly, so the commute example is tagged
  `commute_burden`; a `commute`-tagged row stays listed.

## Acceptance gate

```bash
uv run pytest tests/test_exclusion_backfill.py
```
