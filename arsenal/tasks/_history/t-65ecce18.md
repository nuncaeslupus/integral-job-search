---
id: t-65ecce18
title: "D-15: stop offering to end the session at every step boundary"
priority: 10
status: merged
---

Captured during a test session at step `constraints` (ledger `test-2026-08-20-a`).

> Don't ask to let the session so soon, just ask if you see it is taking too much time.

Every step skill's Boundary example ends with "Carry on, or leave it here?" — so a candidate who
answers four steps is asked four times whether they want to stop. Offer the exit when the session is
actually long, not as the standard close of every step.

Addressed in: the Boundary sections of all thirteen step skills.


## Acceptance gate

```gate
step_boundaries_offering_an_exit == 0
evidence: status/evidence/D-15.json
key: step_boundaries_offering_an_exit
```

```bash
uv run --extra dev pytest tests/test_step_skills.py -q
```

The number is measured over the step-skill library itself — the prose actually
put in front of the model — rather than over a restatement of the rule.

It counts a boundary as **offering an exit** on either of two limbs. The first
is the obvious one: the skill's fenced example, the text a model copies, offers
stopping as an alternative to carrying on. The second is the limb that makes the
gate bite, because rewriting four sentences satisfies the first forever: the
Boundary section carries no rule governing when the exit is named, so whether to
name it is left to improvisation from the example. That was the state of all
thirteen skills.

The two limbs read different halves of the section — limb 1 only the fenced
blocks, limb 2 only the prose. Without that split the rule sentence would trip
the check it satisfies, and no library could pass.

Verified by running the gate against the pre-fix library
(`--skills-dir` over a `git archive HEAD` copy): **13** offenders, four of them
on the regression limb and all thirteen on the silence limb. After the fix: 0.

## What the spec requires

`status/spec-v2-steps.md` has carried this as the fourth of its four
cross-cutting rules since the document was settled: **"Invite forward, do not
offer an exit. … Stopping is always allowed and never the default suggestion."**

## What the code does

Two documents diverged from that rule in opposite directions, and the live
session sat between them. The step spec's own per-step **Boundary** examples
contradicted it four times — steps 1, 4, 5 and 10 closed with *"or leave it
here?"*, *"Leave it there?"*, *"or pause?"* and *"or leave it?"* — while
`status/spec-v2-process.md` §3.2 positively **required** the offer ("A step ends
by naming what was gained, offering the next thing, and offering to stop").
Every step skill copied the examples verbatim and carried no rule at all. The
model was given four worked demonstrations of the behaviour and zero statements
of the rule against it, and behaved exactly as instructed.

## The fix

The step spec's rule now says *when* the exit is offered — only when the session
has actually run long, or the candidate sounds tired. Its four contradicting
examples invite forward instead. §3.2 of the process spec is reconciled to the
same rule rather than requiring its opposite. All thirteen step skills carry the
rule in their own Boundary section, where the model reads it.

`jobsearch.session_exit` measures it, as a module of its own for the reason D-14
records: `make evidence` runs each module once with no arguments, so a gate
reachable only behind a flag is a gate whose drift nothing notices. It reads the
requirement out of the step spec rather than restating it, and reports `-1` when
that rule is gone — a gate must stop reading as a pass when the policy it
enforces is withdrawn.

## Tests

`test_a_step_boundary_does_not_offer_to_end_the_session` — the gate over the
committed library. It asserts the count *and* that every boundary states the
rule and still says something out loud, so the zero cannot be earned by
boundaries that fell silent.

`test_the_four_boundaries_that_offered_an_exit_are_counted` — the regression
limb in the four pre-fix phrasings. `test_a_boundary_that_states_no_rule_is_counted`
— the silence limb, i.e. the state of all thirteen skills.
`test_stating_the_rule_is_not_read_as_offering_the_exit` — the prose/spoken
split, without which the fix would fail its own gate.
`test_deferring_an_artefact_is_not_offering_to_leave` — step 11's "Ready to
send, or sit on it?" is two ways forward, not an exit.
`test_a_bare_mention_of_stopping_does_not_state_the_rule` — D-14's review
finding, applied here before it could be found again.

`test_a_dropped_spec_rule_records_minus_one_never_a_clean_zero`,
`test_a_missing_spec_document_records_minus_one_never_zero`,
`test_a_boundaryless_library_records_minus_one_never_zero`,
`test_an_unloadable_step_list_records_minus_one_for_the_exit_gate`,
`test_a_boundary_that_says_nothing_out_loud_is_counted` — five routes by which
this measurement can stop happening, none of which may read as a clean pass.

## Location

`src/jobsearch/session_exit.py` (new), `.claude/skills/step-*/SKILL.md` (all
thirteen), `status/spec-v2-steps.md`, `status/spec-v2-process.md`,
`tests/test_step_skills.py`, `status/evidence/D-15.json`, `status/plan.md`
(the D-15 row).
