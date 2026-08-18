# D-8: captured evidence cannot say which offer a reason was about

## What the spec requires

T28's own brief (`claude-arsenal/queue/lo-62f9.md`, and `status/plan.md` Scope
extension §4) asks continuous capture to record provenance as **"which surface,
when, in response to what"** — the last clause being what lets a later reader
weigh a throwaway remark differently from a considered interview answer.

## What the code does

`EvidenceRow` (T6) carries `step`, `source` and `recorded_at`. There is no field
for the *subject* a capture was in response to. So `capture_offer_decision_reason`
records that a rejection reason was given at the feedback step from an offer
reaction — but not **which offer**. Two rejections of two different jobs are
indistinguishable in the log.

"Which surface" and "when" are satisfied. "In response to what" is not, for any
capture whose subject is a specific artefact rather than a question.

## Why it matters beyond tidiness

- **T21 (the feedback loop) depends on it.** Its gate is
  `feedback_traceability == 1.0` — rejection reason → evidence → rebuild →
  changed ranking. A reason that cannot name its offer cannot close that loop.
- **A reason is only interpretable against its subject.** "Too far from home"
  says nothing without the posting it was about, so the row keeps the words and
  loses the meaning.

## Fix location

`EvidenceRow` is T6's schema and deliberately narrow, so this is a schema
decision, not a patch. Options to weigh:

1. **An optional `about` field** (`{"kind": "offer", "id": "..."}`) — general
   enough to serve reactions (T17) and the interview log (S6) too.
2. **Reuse `dimensions` with a namespaced id** — no schema change, but overloads
   a field that means "which dimension this bears on" and would corrupt
   `story_dimension_linkage` and `trait_evidence_sufficiency`, both of which
   count that field. Cheap and wrong; recorded so it is not re-proposed.
3. **A companion file keyed by row id** — the shape S5 used for lifecycle state
   when `Offer` could not carry it (`offers/lifecycle/<id>.json`). Avoids
   touching the append-only log at the cost of a second thing to keep in step.

Prefer (1) if the append-only log can take an optional field without breaking
`profile_rebuild_deterministic`; check that before choosing.

## Acceptance gate

A captured reason names the artefact it was about, and a reader can recover it
from the log alone.

```bash
uv run --extra dev pytest tests/test_profile_capture.py -q
uv run python -m jobsearch.profile_capture --write-evidence
```

```gate
captures_without_a_subject == 0
evidence: status/evidence/D8.json
key: captures_without_a_subject
```

The metric counts captures whose subject is a specific artefact and which record
no way to identify it. A capture in response to a *question* has its subject in
the bank entry already and is not counted — conflating the two would make the
gate unsatisfiable rather than meaningful.

## Tests

`test_two_rejections_of_different_offers_are_distinguishable_in_the_log` — the
failure this exists for, and the one that is invisible while only one offer has
ever been rejected;
`test_a_captured_reason_survives_rebuild_with_its_subject` — provenance that
does not survive T6's rebuild is not provenance;
`test_an_answer_to_a_question_needs_no_subject_field` — the exclusion above,
asserted so the gate cannot be satisfied by demanding a subject everywhere.

## Location

Service: **PROFILE** · Size: M · Depends: T28, T6

`src/jobsearch/profile_capture.py`, `src/jobsearch/profile.py` (schema),
`status/specification.md` §5.7. Blocks T21 (`feedback_traceability`).

Found by the T28 worker and reported rather than fixed, since it needs a schema
decision T28's brief explicitly put out of scope.
