# S10: the skill listing budget is structurally exceeded

Surfaced by S7, which added thirteen step skills. Flagged rather than resolved
because the choice is a project-level one, not S7's to make.

## The measurement

`skill-creator`'s `audit_library.py` caps the **sum of every skill's
`description`** at `LISTING_BUDGET_CHARS = 8000`. It is a global cap for a good
reason: every loaded skill's description sits in the model's context on every
turn of every session, so the budget is a running cost, not a lint preference.

Current state of `.claude/skills/`:

| set | skills | description chars |
|-----|--------|-------------------|
| pre-existing tooling | 19 | 7,011 |
| new `step-*` | 13 | 4,129 |
| **total** | **32** | **11,140** |

Over budget by 3,140 characters — and note the pre-existing nineteen already
consume 88% of the cap on their own. This is not S7 being wasteful: at 318
chars each the step descriptions are *tighter* than the existing average of
369. Thirteen more skills simply do not fit in a budget sized before they
existed.

Every individual skill validates clean (0 fail, 0 warn); only the library-wide
total is over.

## Why it cannot be trimmed away

To fit, the thirteen step descriptions would have to share ~989 characters — 76
each. A description has to carry what triggers the skill *and* what should not,
or the model loads the wrong one; 76 characters cannot do both for thirteen
skills that are deliberately adjacent (steps 8, 9 and 10 all concern the same
offers at different stages). Trimming to fit would trade a measurable overage
for an unmeasurable misrouting, which is the worse failure.

## The options, to be decided deliberately

1. **Raise the project's budget.** Honest if 32 skills is the intended size.
   The cap is upstream in `skill-creator`, so this means either a project-level
   override or an upstream change — see S9, which would make that a subtree
   pull rather than a vendored edit.
2. **Do not ship all thirteen as always-loaded skills.** The step skills are
   only reachable when a candidate's session is at that step, which the runtime
   already knows (`step_runtime.runnable`). A dispatcher skill that loads the
   one step in play would cost one description instead of thirteen — the
   largest saving available, and arguably the right shape regardless.
3. **Trim the pre-existing nineteen.** They hold 7,011 chars and were never
   audited against the cap. Not S7's to touch, and it does not fix the
   structural problem — it only buys room once.

Prefer (2) if the runtime can carry it: it is the only option that stays under
the cap as more steps are added, and the budget exists because the cost is
per-turn.

## Acceptance gate

`audit_library.py` reports no listing-budget finding, with every step reachable.

```bash
uv run --extra dev python3 -m jobsearch.step_skills
python3 .claude/skills/skill-creator/scripts/audit_library.py .claude/skills
```

```gate
skill_listing_budget_overage_chars == 0
evidence: status/evidence/S10.json
key: skill_listing_budget_overage_chars
```

## Tests

`test_the_library_is_within_its_listing_budget`;
`test_every_step_is_still_reachable_after_the_change` — whichever option is
taken, `steps_with_a_skill_fraction` must stay at 1.0, so the saving cannot
come from dropping a step.

## Location

`.claude/skills/`, `src/jobsearch/step_skills.py`, and — for option 1 — the
`skill-creator` budget constant (see S9)
