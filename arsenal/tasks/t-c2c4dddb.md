---
id: t-c2c4dddb
title: "T20a: The calibration harness — blind presentation, recorded ordering, and rank_spearman"
priority: 5
deps: [lo-b422, lo-b313]
tags: [m3]
workspace: MATCH
---

## Acceptance gate

```gate
blind_ranking_leaks == 0
evidence: status/evidence/T20a.json
key: blind_ranking_leaks
```

```bash
uv run python -m integral.calibration status/evidence/T20a.json
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
3. **Record the ordering** the candidate gives, as a list of ad ids, and commit it.
   The 20 ads are public corpus entries and an ordering of them carries nothing
   personal; committing it is what makes `rank_spearman` reproducible by
   `make evidence` on a fresh clone. The alternative — reading it out of the
   profile store — makes T20's number unrecomputable anywhere the candidate's
   state home does not exist, which is everywhere except their laptop.
4. **Compute `rank_spearman`** against the system's own ordering of the same 20,
   with tie handling stated. Write `status/evidence/T20.json` — this is the
   command that finally replaces T20's placeholder `bash` block.
5. Until an ordering is recorded, `rank_spearman` is **`null` with
   `rank_status: "unmeasured"`** — D-2's third outcome, as `extraction.measure`
   already does for `extraction_macro_f1`. Not a pass and not a fail.

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

**Do not draw the 20 from the labelled ads.** Only 4 of 100 are labelled, and
drawing from them would make the sample the labelling campaign's leftovers
rather than the evaluation split. The candidate reads the advert text, which
every corpus entry has.

## Tests

Write these RED before any production code:

`test_the_presentation_order_is_independent_of_the_system_ranking` in
`tests/test_calibration.py` — the gate's own property;
`test_no_score_or_explanation_reaches_the_blind_page`;
`test_spearman_matches_a_known_order` — including ties;
`test_rank_spearman_is_unmeasured_until_an_ordering_is_recorded`;
`test_the_twenty_are_drawn_from_the_evaluation_split_only`.

## Consequence to expect

T20's `bash` block stops being the failing placeholder and becomes
`uv run python -m integral.calibration --gate status/evidence/T20.json` (or
whatever this module settles on). Update T20's file in the same PR that lands
this, so the two do not disagree about how T20 is measured.

## Location

Service: **MATCH** · Size: M · Depends: T9 (`lo-b422`, merged), T19 (`lo-b313`, merged)

Design: `status/plan.md` (T20, T20a) · Spec: `status/specification.md` §5 ·
Sibling patterns: `integral.reaction_elicit` (split-disjointness and its probe),
`integral.extraction` (the `unmeasured` shape), `integral.presentation`
(planting the failure a page-shaped gate has to detect)
