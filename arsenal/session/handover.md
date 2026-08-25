# Session handover — 2026-08-24/25, iterative sourcing built end to end

A long worker session on the laptop. **The whole T60–T68 chain is merged**; the only
sourcing work left is T69, which is `[HUMAN]`. Nine PRs merged, two closed unmerged.
`main` is green: ruff, strict mypy over 161 files, full pytest, `evidence: no drift`,
`verify-gates: 100 terminal task(s); 100 gate(s) asserted`.

Board: 107 tasks — **open 5, claimed 0, merged 99**, done 1, cancelled 2.

## Start here — nothing left is machine-doable

All five open tasks need a human or a spend, and each was checked rather than assumed:

| Task | What it needs | Evidence today |
|---|---|---|
| **T69** | The exhaustion signal *watched on a real cycle* | `requires: [surface:human]` — a dep cannot express this. **Do not remove it.** |
| **T20** | A blind manual ranking of 20 held-out ads | `rank_spearman: unmeasured — no ordering recorded for the active candidate` |
| **T56 / T57 / T59** | One labelling round | T59 needs ≥10 negated labels; the corpus carries **2**. #163 records what the round costs — that spend is the owner's call. |

`task_select.py` offers T59 because its dep (T25, corpus broadening) merged. It is not
blocked by the graph; it is blocked by data. Its `status-key` makes it honest —
`gate_evidence.py` exits 3, "the check ran, and what it found is that this cannot be
scored yet".

## What merged

| PR | Task | Gate, measured |
|---|---|---|
| #180 | T61 — the §1 amendment across D-3's three documents | `spec_consistency_violations = 0` |
| #179 | T62 — exhaustion as a measurement | `exhaustion_triggers_without_a_reason = 0` |
| #184 | T63 — the `exhausted` trigger kind beside staleness | `stuck_cycles_without_a_proposal = 0` |
| #183 | T64 — symmetric scope proposals | `scope_proposals_offering_only_narrowing = 0` |
| #186 | T65 — consent, and a refusal is evidence | `narrowings_without_a_recorded_decision = 0` |
| #185 | T68 — the cycle improves or says why | `cycles_neither_improving_nor_proposing = 0` |
| #187 | T67 — standing scope re-surfaced on return | `standing_scope_decisions_not_resurfaced = 0` |
| #188 | T66 — the empty market: a time, never a relaxed constraint | `exhausted_searches_reported_as_a_scope_change = 0` |

Closed unmerged: **#178** (merge-policy, see below) and **#181** (a handover superseded
by this one).

## The merge policy was changed, then reverted, and #182 tracks it

The owner set `merge-policy = "after-ci-and-review"`. Runners had **not** returned —
every job still dies in 2–5s with `runner_id: 0` — and `github-automation.md` is explicit
that an unreported check leaves that policy unsatisfied for the length of the outage, so
it would have blocked every merge. On the owner's decision the change was closed unmerged
and **#182** carries the wording, ready for the day `gh run list` shows real durations.
`main` stays on `after-review`.

## Four things this session learned the hard way

**A CodeRabbit rate-limit is terminal, not a deferral.** Its comment says a review will be
available in N minutes; nothing re-triggers it when the window passes, and two PRs sat
reviewed-never for four hours. Under `after-review` that reads as an indefinite block.
**`@coderabbitai review` is the nudge** — post it and the review lands in a minute.

**`make evidence` compares the working tree against the INDEX, not HEAD.** Every worker
hit it. With new or changed evidence uncommitted it reports drift until
`git add status/evidence` — stage, do not commit; the uncommitted-edits workflow
`open_task_pr.sh` requires still holds.

**The T55 drift is conditional, not automatic.** CLAUDE.md describes a second commit after
`open_task_pr.sh`. Three tasks needed it and three did not: the archive is a *move*, so the
count only shifts when the task also adds files. Re-run the gate and look, rather than
committing a refresh reflexively.

**Two PRs landing the same evidence file both measure it without the other.** D12 and T55
end up one short after the second squash. Rebase the trailing branch and regenerate rather
than merging the stale number — `arsenal/config.toml`'s `host-gate` key exists for exactly
this, and the conflict is evidence-only, where the right content is neither side.

## Three review findings worth remembering, all real

**A frozen pydantic model still hands out a mutable list.** `Strict` sets `frozen=True`,
which blocks rebinding a field but not mutating the list inside it. On T64,
`alternatives.clear()` plus an append rebuilt exactly the all-narrowing proposal the gate
exists to make unconstructable — the invariant was enforced once, not always. Collection
fields carrying an invariant are now `tuple[X, ...]`. This was passed forward into every
later worker brief and no task after T64 repeated it.

**A sequence argument's order is a claim.** T68 read `pairwise(cycles)` without checking
adjacency, so `[3, 1]` inverted the comparison and the gate passed on a regression. Now
refused. Note what was *not* taken: sequences need not start at 1, because judging a later
window of one candidate's cycles is fair and only adjacency is load-bearing.

**A word blacklist over free prose is a net, never a proof.** Found by probing T66 rather
than by review: `HARD_CONSTRAINT_TERMS` was built from step 2's *field names*, so
`"pay floor"` was refused while `"try relaxing your remote requirement"` was accepted —
`employment_mode` in the words a candidate actually uses. The candidate-facing words are
added, `retry_options` is now a **closed set** (a whitelist cannot be out-phrased), and the
comment says plainly that the completeness is structural: the model has no field a scope
change fits.

## One upstream fix to pick up

`claude-arsenal` **v2.4.3** is fetched but **not merged**: `fix(core): init refreshes
forward only, and says so when it cannot` (#221). Step 0b's `init.py --silent` downgraded
this repo's bundle 2.4.2 → 2.4.0 while printing "Upgrading", reverting #162's placeholder-gate
fix that the whole T60–T69 chain depends on. Caught and reverted here before any work
touched it. Merge the tag when no workers are live — the subtree merge writes history into
the main working tree.
