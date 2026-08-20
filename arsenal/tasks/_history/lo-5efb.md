---
id: lo-5efb
title: "S10: the skill listing budget is structurally exceeded by 13 step skills"
priority: 10
workspace: SOLO
tags: [infra]
status: merged
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

## Resolved (owner, 2026-08-20): the budget lives here, not upstream

**13,000 characters, set in `arsenal/config.toml`'s `listing-budget`.** The
decision was never the blocker; *where the raised number lives* was — and
arsenal already answers that. The key exists, is validated by
`arsenal_config.py`, and is documented there as the place "a consumer whose
budget differs can set it instead of being unable to pass the audit at all
(#143)". It is host-owned and never rewritten by an upgrade.

What upstream has not done yet is wire `audit_library.py` to read it. So
`jobsearch.skill_budget` reads the setting and measures against it, which makes
the raise real today without touching `vendor/`; when #143 lands, the auditor
reads the same key and the two agree without either moving. The budget is
**not** duplicated as a Python constant — two copies of a threshold are two
thresholds.

Three properties keep a raised threshold honest, because a cap fitted to the
measurement reports the same clean zero as a cap somebody chose:

1. **round and with headroom** — `check_declaration` refuses a budget that is
   not a whole multiple of 1,000 or that leaves under 400 spare chars, so
   "raise it to whatever we measure" fails mechanically;
2. **the source is recorded** — committed evidence carries
   `budget_source: "config"`; `--budget`/`JOBSEARCH_LISTING_BUDGET_CHARS` mark a
   reading `override`, and a missing settings file marks it `fallback` (at
   upstream's 8,000, never this repository's number, so an absent config cannot
   be mistaken for a present one). Only `config` can satisfy the gate;
3. **upstream's reading stays visible** — `overage_against_upstream_default`
   keeps "deliberately N chars above the 8,000 default" a fact anyone can read.

The per-skill cost formula is upstream's, mirrored, and
`test_the_measurement_agrees_with_the_upstream_audit` runs the real
`audit_library.py` and asserts the totals are equal — so a formula change
upstream fails a test here instead of leaving two numbers nobody compares.

Measured after the change: **12,138 chars across 33 skills**, 862 spare,
`steps_with_a_skill_fraction` still 1.0.

**Review finding folded in (Qodo, 2026-08-20): the three properties are inside
the gate key, not beside it.** `verify_gates` asserts the fenced
`skill_listing_budget_overage_chars == 0` and nothing else, so a bare
`total - budget` would have let an override — or a budget fitted to the
measurement — report a clean zero while every guarantee above went unchecked
outside the test suite. A library inside an unsoundly declared budget now
reports `-1`: not a pass, and not silent either. Second finding, same shape: an
`OSError` reading a `SKILL.md` used to cost nothing, which is a false zero
overage — the gate passing because it could not see its input. It raises.

### The original framing, kept because it was overruled deliberately

**This was blocked on an upstream change, not on work here.**
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
uv run --extra dev python3 -m jobsearch.step_skills --check
uv run --extra dev python3 -m jobsearch.skill_budget --check
uv run --extra dev pytest tests/test_skill_budget.py -q
```

The three properties are folded into the gate key rather than sitting beside
it: `verify_gates` asserts `skill_listing_budget_overage_chars == 0` and
nothing else, so a library inside an unsoundly declared budget — or one whose
budget came from an override or a fallback — reports `-1` rather than a clean
zero.

`audit_library.py` is **not** the gate command. It measures against upstream's
own 8,000-char constant, which this repository has deliberately risen above —
so it reports a finding by design, and a gate asserted on it could only pass by
undoing the decision. It is still run (by
`test_the_measurement_agrees_with_the_upstream_audit`) for the one thing it is
authoritative about: the total.

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

`src/jobsearch/skill_budget.py` (new), `tests/test_skill_budget.py` (new),
`arsenal/config.toml` (`listing-budget = 13000`), `status/evidence/S10.json`.
Nothing under `vendor/` is edited —
`test_nothing_under_vendor_was_patched_to_achieve_this` asserts the upstream
constant is still 8,000, because a subtree edit works perfectly until the next
`git subtree pull` reverts it, silently.
