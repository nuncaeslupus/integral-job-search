# S2r: fold the owner's twelve step-spec annotations into the step specifications

## Acceptance gate

```gate
step_specs_complete_fraction == 1.0
evidence: status/evidence/S2.json
key: step_specs_complete_fraction
```

```bash
uv run python -m jobsearch.step_specs status/evidence/S2.json
uv run --extra dev pytest tests/test_step_specs.py -q
```

## What this is

Twelve annotations on `status/spec-v2-steps.md`, saved at
`docs/spec-v2-steps/notes.json`. This folds them in. The step list, the
required/offered split and the twelve-field template are settled and unchanged;
what changes is what the fields say.

Decided alongside them (owner, 2026-08-18): connectors are **declarative files
in a public repo** (T32); **S2r precedes the per-step skills** (S7), for the
same reason S1 preceded S2 — a skill written against a spec about to change gets
rewritten thirteen times; net pay uses **repo rules where they exist and
generated rules where they do not**, marked as generated (T33).

## Three corrections, not preferences

1. **Intake's "never ask" list is wrong.** Date of birth, address and telephone
   are not asked at Intake because they do not improve a *search* — but a real
   CV needs them. **Application collects what the document it is producing
   actually requires**, when it requires it. Move the rule; do not delete it.
2. **The question caps are too high.** 40 in History and 25 in Intake read as an
   interrogation to someone who was promised a job. Bring them down, and invert
   the framing: not "want to stop?" but "carry on, or move to traits?" with the
   reason attached. The candidate should feel they are getting somewhere.
3. **History over-weights failure.** That came from `story_failure_fraction >=
   0.33` and coloured the whole step. Successes, and how someone reached them,
   evidence traits equally and are pleasanter to tell.

## The rest of the notes, by where they land

- **Cross-cutting**: the process should feel like a game, or at least be
  enjoyable — the prize is a job but the path must not be a chore. Say up front
  that it takes a while and why.
- **Step 0**: the chosen display name is the identifier unless taken, and need
  not be the name that appears on a CV.
- **Step 2**: candidates do not know their own constraints. Carry a prepared
  list of *usual suspects* — sectors, causes, countries, kinds of employer — and
  reach them conversationally, never as a checklist. Also: **pre-sourcing may
  begin here**, in the background, once country, field and reach are known, so
  Reactions has fresh ads rather than a cold fetch.
- **Step 4**: stale or irrelevant history is de-emphasised — a doctor's first
  job waiting tables is not evidence about the doctor they are now.
- **Step 6**: the forced choices must not be tedious. "200 euros or your
  afternoons" repeated twenty times is a survey, not a conversation.
- **Step 7**: prefer specialised boards and employers' own pages over
  generalist portals; the candidate's browser may be used where a site needs a
  login; dedup by **similarity**, not by hash alone.
- **Step 8**: define the extraction method. Script and keyword work first, the
  model only where it is genuinely needed. Normalised fields for every offer,
  and offer fields related to constraints and preferences at extraction time so
  ranking is comparison rather than computation.
- **Steps 9-10**: presentation is specified, not improvised. An offer is a card
  with its facts as bullets plus **one line of what actually matters about it**
  ("full remote, pay is good, but it is a gun factory"). Feedback may open a new
  search when the candidate discovers a kind of job they did not know existed.
- **Step 11**: use the advert's own words, with subtlety, only where what it
  asks for matches what the candidate has. State how sincere to be about gaps.
- **Step 12**: the mock interview is a **role-play with no chatting**, declared
  as such before it starts and left only when it ends. Dictation is worth
  offering. Preparation afterwards, not only before.

## The gate

Unchanged: `step_specs_complete_fraction == 1.0`. The twelve fields must still
all be answered for all thirteen steps after the revision — a note folded in by
deleting a field is not a revision, it is a regression, and the gate says so.

## Tests

The existing S2 suite, unchanged and re-run: `test_every_step_spec_fills_the_template`,
`test_every_step_has_a_stop_rule`,
`test_every_step_says_what_happens_when_the_candidate_declines`,
`test_the_divisor_is_the_settled_count_not_the_number_of_specs_written`. Add
`test_no_step_asks_for_a_field_it_does_not_need` if the Intake/Application split
can be expressed mechanically; if it cannot, say so rather than faking it.

## Location

Service: **ONTOLOGY** · Size: L · Depends: —

Source: `docs/spec-v2-steps/notes.json` · `status/spec-v2-steps.md`
