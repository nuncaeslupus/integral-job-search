# T40: Decline ledger — non-insistence made mechanical

## Acceptance gate

```gate
repeat_asks_after_decline == 0
evidence: status/evidence/T40.json
key: repeat_asks_after_decline
```

```bash
echo "no gate command defined for T40 — replace this line with the command that writes status/evidence/T40.json" >&2; exit 1
```

## What this is

The non-insistence rule is the one that outranks every coverage target:

> A subject declined once is not raised again in that step; a subject declined
> twice is not raised again at all unless the candidate reopens it. It is better
> to find a worse job than to make someone feel bad about the questions.

Most of that rule is manner and cannot be coded. The part that can is the
ledger: which subjects were declined, in which step, how many times, and whether
the candidate has since reopened one. This task builds that ledger and makes
every asking surface consult it.

## The rule that matters

**This is the mechanical half of a rule whose other half is a review
question.** Do not let the ledger become an excuse to stop reading the step
specifications for tone. What it does guarantee is that the failure everyone
notices — being asked again about the thing they just refused — cannot happen
by accident.

A declined field records `declined`, which is distinct from `unknown`: the
candidate answered, and the answer was no.

## Tests

Write these RED before any production code:

`test_subject_declined_twice_is_never_asked_again` in
`tests/test_non_insistence.py`; `test_subject_declined_once_is_not_raised_again_in_that_step`;
`test_candidate_reopening_a_subject_clears_the_ledger` —
raising it themselves is permission, and nothing else is.

## Location

Service: **RUNTIME** · Size: S · Depends: T6

Design: `status/plan.md` (RUNTIME) · Spec: `status/spec-v2-process.md` §5.4
