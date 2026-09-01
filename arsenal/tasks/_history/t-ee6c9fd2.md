---
id: t-ee6c9fd2
title: "T95: What reaches the candidate in one turn: too few adverts, and our vocabulary"
priority: 10
tags: [PRESENTATION]
status: merged
---

Three observations about the candidate-facing surface, all from step 5.

**Batch size.** *"Four ads can be very few. I like that you don't give me long
lists, but maybe two or three chunks can help better."* The instinct against long
lists was right; the quantity was not. What the candidate asked for is the same
total delivered as a few digestible groups.

**Our vocabulary leaked.** *"'pasamos a convertir esto en pesos para el ranking'
is weird for the user when nothing about ranking or weights has been explained
before."* `weights.py` and `rank.py` are internal machinery. Either the term is
introduced before it is used, or it is not used.

Note `vocabulary_reach.py` does **not** cover this — it measures whether the
dimension model reaches a market, which is a different sense of the word. This
is register, and nothing checks it.

**Summaries are the right shape.** *"I like that you give me a summary of the
ads. Just make sure that all the important info is in there. A link could be
useful, but as a summary without link it makes the process easier and quicker."*
So: keep the summary, make the field set complete, treat the link as optional
rather than the payload.

## Acceptance gate

```gate
internal_terms_used_before_introduction == 0
evidence: status/evidence/T95.json
key: internal_terms_used_before_introduction
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_presentation_register.py -q
uv run --extra dev pytest tests/test_presentation.py -q
uv run --extra dev python -m integral.presentation
```

`tests/test_presentation.py` is in the block because T95 changes behaviour two
of its tests pinned: an unstated salary is now shown and marked rather than
suppressed to `unknown`, and the page chunks rather than truncates. Both were
updated in place with the reason, and running only the new file would hide a
regression in the old one.

- `test_a_batch_is_chunked_rather_than_truncated` — the cap is per chunk, not per
  turn.
- `test_an_internal_term_is_introduced_before_it_is_used` — over a named list
  including weights, part-worth, ranking, corpus, connector.
- `test_a_summary_carries_every_field_a_decision_needs`
- `test_a_summary_says_whether_a_salary_was_stated_or_estimated` — T92 lets an
  estimate exist provided it never reads as stated. A summary that prints one
  number honours the letter of that and breaks it here, at the only place the
  candidate actually looks.
- `test_an_estimated_salary_shows_its_basis_in_the_summary`
