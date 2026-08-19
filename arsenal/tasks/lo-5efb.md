---
id: lo-5efb
title: "S10: the skill listing budget is structurally exceeded by 13 step skills"
priority: 10
workspace: SOLO
tags: [infra]
requires: [surface:human]
---

Surfaced by S7, which added thirteen step skills. Flagged rather than resolved
because the choice is a project-level one, not S7's to make.

## Decision (owner, 2026-08-18): raise the budget — option 1

Chosen over the dispatcher (option 2), which this payload had preferred. The
reasoning stands recorded because it was overruled deliberately: a dispatcher is
the only option that stays under a fixed cap as steps are added, but it also
means the model cannot see what the other twelve steps are for, and the step
skills are deliberately adjacent — knowing that step 9 exists is part of
knowing step 8 is the wrong one to load.

**This is now blocked on an upstream change, not on work here.**
`LISTING_BUDGET_CHARS = 8000` is a module constant in
`vendor/claude-arsenal/plugins/skill-creator/skills/skill-creator/scripts/audit_library.py:50`,
referenced in nine places. `main()` exposes `--profile`, `--severity`, `--json`
and `--by-plugin`; none of them affect the budget, and no environment variable
is read. There is no project-level override to set.

Filed upstream as **`nuncaeslupus/claude-arsenal` issue #143**, asking for
`--listing-budget` plus an `ARSENAL_LISTING_BUDGET_CHARS` fallback, the
effective budget and its source printed in the output (a configurable threshold
whose value is invisible is one nobody can tell has been quietly raised to
whatever the library happened to measure), and the per-plugin breakdown kept
unconditional.

**Do not patch the constant in `vendor/`.** It is a subtree; the edit would be
reverted by the next `git subtree pull`, silently — which is the exact failure
S9 exists to remove, and `make verify-subtree` would fail on it in the
meantime. The sequence is: land the upstream change, `make arsenal-upgrade
REF=<tag>`, set this repository's budget, re-measure.

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

This payload preferred (2); the owner chose (1). See the decision at the top —
what (1) buys is that every step description stays visible, and what it costs is
that the cap has to be revisited each time the library grows.

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

`.claude/skills/`, `src/jobsearch/step_skills.py`, and — upstream, since
option 1 was chosen — the `skill-creator` budget constant
(`claude-arsenal` issue #143). Nothing under `vendor/` is edited here.
