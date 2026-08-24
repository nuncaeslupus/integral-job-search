---
id: t-c2c4dddb
title: "T20a: The calibration harness — blind presentation, recorded ordering, and rank_spearman"
priority: 5
deps: [lo-b422, lo-b313]
tags: [m3]
workspace: MATCH
status: merged
---

## Acceptance gate

```gate
blind_ranking_leaks == 0
evidence: status/evidence/T20a.json
key: blind_ranking_leaks
```

```bash
uv run python -m integral.calibration leaks status/evidence/T20a.json
```

The two blocks do different jobs and both are required. The `bash` block
regenerates `status/evidence/T20a.json`; the `gate` block asserts the number in
it against the threshold. Without the first, a stale or hand-written evidence
file passes unchallenged; without the second, a command that exits 0 counts as a
gate whatever it measured.

## What this is

T20 (`lo-c48f`) is `[HUMAN]`: the candidate ranks 20 held-out ads by hand, blind,
and `rank_spearman >= 0.60` says whether the system agrees. Everything around
that act is software, and none of it exists — T20's `bash` block is still the
placeholder that fails on purpose, `tests/test_calibration.py` has never been
written, and there is no Spearman anywhere in the tree.

Because T20 carries `requires: [surface:human]`, the selector excludes it, so no
agent would ever have built that software. The task as filed asked one person to
do a job that was 90% code. **This is the code half**; T20 keeps the judgement.

Build `src/integral/calibration.py`:

1. **Draw the 20.** From the **evaluation** split only — `harness.evaluation_offer_ids`
   already names it, and T9's `elicitation_eval_overlap == 0` is the reason: an ad
   used to elicit preferences and then scored is measuring memorisation. The draw
   is deterministic from the ad id, like `harness.split_rank`, not random per run.
2. **Present them blind.** See below — this is the gate.
3. **Record the ordering** the candidate gives, as a list of ad ids, in the
   **profile store** — `ProfileStore`, where the rest of their judgement already
   lives. Not in the repository. A permutation of 20 ads is a statement about the
   person, not about the ads: it is preference data of the same kind as T10's
   part-worths and T9's reactions, and neither of those is committed either.
   `integral.state_home` already owns where that lives and under what rules;
   this task adds no second answer.
4. **Validate both orderings before correlating.** Each must be an *exact
   permutation* of the same 20 ids — no duplicate, no omission, no id outside the
   drawn set, no id from the elicitation split. Refuse, with the offending ids
   named; never `zip` two lists of different length or index a rank map with a
   missing key, both of which compute a confident number over a silently
   truncated pair. State which id representation is canonical (`Offer.id`, as
   `compute_offer_id` produces it) so the two sides cannot disagree about what an
   id *is*.
5. **Compute `rank_spearman`** against the system's own ordering of the same 20,
   with tie handling stated. Write `status/evidence/T20.json` with
   `uv run python -m integral.calibration spearman status/evidence/T20.json` —
   the command that finally replaces T20's placeholder `bash` block. The
   evidence carries the scalar and nothing else: rho is a number about the
   system, the permutation behind it is a fact about the candidate.
6. Until an ordering is recorded, `rank_spearman` is **`null` with
   `rank_status: "unmeasured"`** — D-2's third outcome, as `extraction.measure`
   already does for `extraction_macro_f1`. Not a pass and not a fail. On a fresh
   clone with no state home that is what `make evidence` will always write, and
   it is the honest answer: the measurement has not been taken here.

Two evidence files, two subcommands, one module — the shape `integral.harness`
already uses for T4 (`gate`) and T5 (`labels`). `leaks` is this task's own gate
and needs no candidate; `spearman` is T20's and cannot run without one.

## The gate is about blindness, because that is what can rot silently

`blind_ranking_leaks` counts the ways the presentation tells the candidate what
the system already thinks. A leak does not make T20 fail — it makes T20 **pass
while measuring nothing**, which is the same failure D-2 named for cue-derived
gold and T9 named for a shared split. The candidate anchors on the order they
were shown, `rank_spearman` comes back high, and the number certifies the
suggestion rather than the judgement.

At least these count as a leak:

- the presentation order is a function of the system's ranking — it must be a
  deterministic shuffle keyed on the ad id, and `measure()` asserts the two
  orderings are uncorrelated on a fixture built to make them agree;
- any score, `contribution_eur_month`, salary-equivalent total, rank position,
  or explanation text reaches the page. The candidate reads the **advert**, and
  nothing else;
- the ordering already recorded is visible while ranking, which would turn a
  re-run into a confirmation of the first pass.

`measure()` must **plant each leak and watch the count rise**, the way
`presentation.measure` plants an unlabelled provisional page — a zero that has
never been anything else certifies nothing.

## Do not

**Do not have an agent produce the ordering.** The whole content of T20 is that
a person ranked these by hand. A fixture ordering exists to test the arithmetic
and must be visibly a fixture — never written to `status/evidence/T20.json`.

**Do not filter the draw by whether an ad carries labels.** Eligibility is
membership of the evaluation split and nothing else — `harness.evaluation_offer_ids`
is the whole test. `corpus/labelled/ads.jsonl` is the *store*: all 100 ads are in
it and all 100 carry a split, but only 4 carry labels today. Confusing the store's
name for "the ads that have labels" would draw the 20 from the labelling
campaign's leftovers, a sample of whatever happened to get annotated first. The
candidate reads the advert text, which every entry has.

## Tests

Write these RED before any production code:

`test_the_presentation_order_is_independent_of_the_system_ranking` in
`tests/test_calibration.py` — the gate's own property;
`test_no_score_or_explanation_reaches_the_blind_page`;
`test_spearman_matches_a_known_order` — including ties;
`test_rank_spearman_is_unmeasured_until_an_ordering_is_recorded`;
`test_the_twenty_are_drawn_from_the_evaluation_split_only`;
`test_a_malformed_ordering_is_refused` — a duplicate, a missing id, an unknown
id, and a shorter list are four separate cases and each must raise rather than
correlate.

## Consequence to expect

T20's `bash` block stops being the failing placeholder and becomes
`uv run python -m integral.calibration spearman status/evidence/T20.json`.
Update T20's file in the same PR that lands this, so the two do not disagree
about how T20 is measured.

Expect `status/evidence/T20.json` to read `null` / `"unmeasured"` on every
machine but the candidate's. `verify-gates` only demands a measurement of a task
that is *done*, and T20 is not done until they have ranked.

## Location

Service: **MATCH** · Size: M · Depends: T9 (`lo-b422`, merged), T19 (`lo-b313`, merged)

Design: `status/plan.md` (T20, T20a) · Spec: `status/specification.md` §5 ·
Sibling patterns: `integral.reaction_elicit` (split-disjointness and its probe),
`integral.extraction` (the `unmeasured` shape), `integral.presentation`
(planting the failure a page-shaped gate has to detect)
