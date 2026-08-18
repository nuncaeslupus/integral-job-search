# D-9: non-insistence is not honoured on intake's conversational write path

## What the spec requires

T40 (`src/jobsearch/decline.py`) makes non-insistence a property of the whole
profile, not of one step: a subject the candidate has declined, and has not
reopened, must not be written again. Every other free-text writer in this
codebase filters through `DeclineLedger` before it appends —
`elicit_extract.store_answer`, `constraints_step.resolve`, `interview`,
`question_bank`, `trait_sufficiency`.

## What the code does

`src/jobsearch/cv_store.py` contains no reference to `DeclineLedger` at all. It
is the only free-text writer in `src/jobsearch/` that does not:

```
$ grep -ln DeclineLedger src/jobsearch/*.py
constraints_step.py  decline.py  elicit_extract.py  freshness.py
interview.py  profile.py  profile_capture.py  question_bank.py
trait_sufficiency.py
$ grep -c DeclineLedger src/jobsearch/cv_store.py
0
```

`add_conversation_entry` and `set_conversation_scalar` call
`EvidenceLog.append` directly. So a candidate who declines to discuss, say,
salary history, and is then asked about it again while building the CV store by
conversation, has that answer recorded — the exact outcome T40 exists to
prevent. The decline is honoured everywhere except the one surface built for the
candidate who has no CV and is answering the most questions.

Found while wiring T50's intake driver, and reported rather than fixed there:
T50 was a size-S "wire a driver" task and this is a change to S4's own write
contract.

## Why this is not just a missing call

The fix is not only "add a filter". `EvidenceLog.append` is append-only with no
rollback, so the check has to happen *before* the write, and
`add_conversation_entry` already validates before appending (a Qodo finding
fixed in #28) — the decline check belongs alongside that validation, not after
it. Decide also whether a declined subject should raise, or return a result
reporting the refusal the way `ImportResult` reports an unavailable extractor.
Raising makes the caller handle it; reporting keeps the conversational surface
non-confrontational, which is closer to what non-insistence is for.

## Fix location

`src/jobsearch/cv_store.py` — `add_conversation_entry`, `set_conversation_scalar`
Reference implementations: `src/jobsearch/elicit_extract.py` (`_undeclined`),
`src/jobsearch/constraints_step.py`

## Acceptance gate

A declined subject is not written by the intake conversational path, measured
rather than asserted: the probe drives a real decline through `DeclineLedger`,
then calls the real `add_conversation_entry` for that subject, and counts the
rows it produced.

```bash
uv run python -m jobsearch.cv_store --write-evidence status/evidence/S4.json
uv run --extra dev pytest tests/test_cv_store.py tests/test_decline.py -q
```

```gate
intake_declined_subjects_written == 0
evidence: status/evidence/S4.json
key: intake_declined_subjects_written
```

The metric counts writes that should not have happened, so its floor is zero and
a regression moves it up. A coverage-style fraction would sit at 1.0 whether or
not the decline path was ever exercised — the failure this gate has to catch is
a write that occurs, not a percentage that slips.

## Tests

`test_a_declined_subject_is_not_written_by_the_conversational_path` in
`tests/test_cv_store.py` — decline a subject through the real `DeclineLedger`,
call `add_conversation_entry` for it, assert the evidence log gained no row;
`test_a_reopened_decline_lets_the_subject_be_recorded_again` — the other half,
so the fix cannot be "never write anything".

## Location

Service: **PROFILE** · Size: M · Depends: S4 (`lo-cb1c`, merged), T40
