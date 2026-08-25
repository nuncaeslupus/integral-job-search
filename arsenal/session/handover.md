# Session handover — 2026-08-25, two rounds labelled and a merged task reopened

`main` clean and green, **no open PRs**. Seven PRs merged (#194–#200). Board: 107
tasks — **open 6**, claimed 0, merged 98, done 1, cancelled 2. Nothing flagged.

claude-arsenal is at **v2.4.21**; `check_update.sh` reports current.

## The numbers

| gate | threshold | now | was this morning |
|---|---|---|---|
| `extraction_macro_f1` | ≥ 0.75 | **0.4943** over 11 dimensions, n=161 | `null` |
| `prefilter_suppressed_positives` | == 0 | **2 / 209** | 0 / 40 |
| `extraction_negation_recall` | ≥ 0.80 | 6/9 hits, `unmeasured` | 2/9, `unmeasured` |
| `ontology_hit_rate` | ≥ 0.85 | 0.6168 (untouched) | 0.6168 |

**0.5539 → 0.4943 is not a regression.** The macro went from five dimensions to
eleven and n from 52 to 161; the six that entered are where the extractor is worst.
`seniority_expectation` 0.3077 → 0.6061 and `remote_arrangement` 0.5714 → 0.6957 on
doubled n; `compensation_transparency` 0.8235 → 0.6452, which is what a ten-label
estimate does when it meets twenty. `team_autonomy` is **0.0000 over 10 labels**
(0 tp, 0 fp, 10 fn) and `product_vs_services` 0.1667 — those two are the next thing
to look at, and they are cue-coverage failures, not scoring failures.

## T15 is reopened, and this is the important thing to understand

`lo-25b1` is out of `_history/`, `status: open`, issue **#52 reopened**.
`prefilter_suppressed_positives == 0` no longer holds and `verify_gates.py` says so
— 99 terminal tasks now, not 100.

**Do not close it by tuning cues.** Both suppressions are adverts carrying evidence
at *both poles* of a bipolar dimension where the cue set has vocabulary for one:

* `manfred-8360/process_formality` — "se huye de los *sprints* infinitos… Funcionan
  con **Kanban**". Person -0.6, cues +0.5.
* `tecnoempleo-5daa18bff2393309c941/stack_modernity` — Kubernetes and cloud **and**
  "Experiencia sólida en JBoss / JBoss EAP". Person -0.7, cues +0.53.

One structural cause was found and fixed: `process_formality` was bipolar with a
declared -0.6 rung and **zero negative-pole cues in any language**. Provable from
the cue set alone. Cues written from the rung's own `tell` were added, and they do
**not** resolve `manfred-8360` — it phrases its rejection with a verb `_NEGATORS`
does not carry. Extending the negator list to match one advert, or picking
legacy-stack vocabulary by reading an evaluation-split miss, is D-2's failure in a
new costume. **`== 0` was set when four adverts were labelled; at thirty-three it
is a rate with no denominator. That threshold needs a decision, not a patch.**

The regression signal did not go away. `_main` prints suppressions and exits 0 so
`make evidence` is not blocked repo-wide, and `test_prefilter` names the exact two —
a **third** suppression fails the suite.

## `mission_alignment` is narrowed — the owner's finding, and it was right

Its definition read "how much the stated purpose matters **to the candidate**",
which describes a weight, not an advert. The `-0.7` "a sector to refuse" rung was
the same error in the levels: an advert states a *sector*; whether that is a draw or
a refusal is the candidate's. `sanidad → +0.7` and `sector defensa → -0.7` put one
person's ethics in the extractor.

Now **unipolar, two rungs** — "not stated" / "purpose stated". Refusal belongs to
the candidate's weights and step 2's knockouts. Eleven suggestion marks proposing
the dead rung were dropped rather than converted.

**This is a template, not a one-off.** Any dimension whose definition says "matters
to the candidate" is suspect. `ambition`, `creativity`, `learning_orientation` and
`spare_time_engagement` are already `side: candidate_trait`; `mission_alignment` was
the only `matched` one carrying a candidate judgement, but the check is worth
repeating when T57 adds dimensions.

## Labelling: two rounds done, the tooling generalised

* **Round 1** — 11 adverts, 5 dimensions, 76 labels.
* **Round 2** — 18 adverts, 6 dimensions, 127 labels.
* 231 labels in the store, 206 on the evaluation split, 33 adverts labelled.

`make labelling-round ROUND=NN DIMENSIONS=a,b,c` builds the page;
`tools/labelling_round.py --dimensions below-floor` reports what labelling cannot
fix. **Round 3 would be 30 adverts for 6 more dimensions**, and eight cannot be
floored at all: `on_call_load` (short 7), `social_intensity` (7), `company_stage`
(5), `mission_alignment` (5), `inclusion_commitment` (4), `mentoring_culture` (4),
`career_progression` (3), `technical_depth` (1).

**The import refuses same-dimension marks with different values, and it was right
to.** T57's read pass proposes two marks for one dimension and both quotes are
true — "Modalidad híbrida (60 de teletrabajo)" *and* "Centro de trabajo Barcelona".
A `Label` holds one value with several spans. Round 2 was merged strongest-value,
all spans kept, on the owner's instruction. Expect this again; consider making the
page reconcile it rather than the importer refuse it.

## The 141 collected adverts, still parked

`tools/collect_ads.py --target-es 140 --target-en 60 --target-ca 110 --target-family 30`
takes the raw corpus 208 → 349. **Deliberately not merged**: `blind_control` is
derived from ad ids with `count = ceil(len(slice) * share)`, so growing the corpus
recomputes the cohort, invalidates the declared one, and `validate_suggestions`
then refuses to build any page. Every new advert also needs T57's read pass before
it is cheap to label. Re-run the command to reproduce it.

Those eight unfloorable dimensions, and T59's tenth negated label, are the whole
case for landing it.

## Upstream — all five findings fixed

`claude-arsenal#237` and `#239` (four findings) shipped as v2.4.17–v2.4.21 (#238,
#240, #241, #242, #243) and this repo is on v2.4.21.

**`claude-arsenal#244` is open** with two gaps in those fixes, both verified:
`check_update.sh`'s skew probe uses `find … | head -1` — unsorted and unanchored, so
another skill matching first makes the guard fail **open** and silently, the exact
property #237 was filed about; and `open_task_pr.sh`'s `git rev-parse … || pwd`
means that outside a repository the gates run against arbitrary files. Neither bites
this repo's layout today.

## Next session

1. **`team_autonomy` 0.0000 and `product_vs_services` 0.1667** are the loudest
   signals in the evidence file. Diagnose from the **cue set and the elicitation
   split** — not from evaluation misses.
2. **T15's threshold needs the owner's decision** — rate, or accept and name.
3. **T57 closes by adding dimensions**: credentials (83 unmapped concepts), pay
   structure (54), place/mobility (41), working-time shape (37).
4. **T20 and T69 need the owner in person.** `tools/blind_ranking_page.py` for T20;
   T69 needs the exhaustion signal watched on a live cycle.
5. Round 3 (30 adverts) whenever there is an evening for it.
