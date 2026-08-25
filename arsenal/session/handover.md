# Session handover — 2026-08-25, the day two gates stopped being null

`main` is clean and green. **Five PRs merged, no PRs open.** Board: 107 tasks —
open 5, claimed 0, merged 99, done 1, cancelled 2. Nothing flagged.

| PR | what |
|---|---|
| #194 | claude-arsenal v2.4.9 → v2.4.16, and the downgrade that caused it |
| #195 | T56's scorer: macro-F1 implemented, the placeholder `raise` disarmed |
| #196 | T59: `Cue.denies`, and corroboration asked of positives only — recall 2/9 → 6/9 |
| #197 | **T56 round 1: 76 labels, `extraction_macro_f1` measured for the first time** |
| #198 | round 2's cover, and a shortfall that separates "label more" from "collect more" |

## Where the numbers stand

| gate | threshold | now |
|---|---|---|
| `extraction_macro_f1` | ≥ 0.75 | **0.5539** — measured, failing |
| `extraction_negation_recall` | ≥ 0.80 | 6/9 hits, **still `unmeasured`** (floor is 10) |
| `ontology_hit_rate` | ≥ 0.85 | 0.6168, unchanged this session |
| `prefilter_suppressed_positives` | == 0 | 0 / 100 |

**0.5539 is a measured shortfall, not a failed round.** Per dimension:
`compensation_transparency` 0.8235, `contract_stability` 0.6667,
`remote_arrangement` 0.5714, `schedule_flexibility` 0.4000,
`seniority_expectation` 0.3077 (2 tp, 0 fp, **9 fn**). The last is the corpus
telling you what T57 already said in another voice: the model was built for
programming ads and does not read seniority in a hospitality or care advert.

## What round 1 proved about the method

The eleven adverts were a greedy cover computed from T57's marks, and the cover
held exactly — every one of the five reached ten with no shortfall. **That is the
reusable part.** `tools/labelling_round.py --dimensions <ids>` computes it for any
list, `--dimensions below-floor` for everything unscorable, and
`make labelling-round ROUND=NN DIMENSIONS=...` builds the page.

The corpus also found a real cue error on contact, which is the whole argument for
having one: nine adverts name both remote and on-site in one clause
(`presencial con 1 día de teletrabajo`, `teletrabajo y 2 presencial`,
`tant presencial com remot`) and the cue set called every one of them on-site.
Naming both poles **is** the hybrid statement; it is a cue in all three languages
now, and a general rule drops a cue match that lies wholly inside a longer one so
the specific reading is not averaged back down by the general one.

## Round 2 is built and needs no new adverts

`corpus/labelled/round-02.html` — **18 adverts, six dimensions, shortfall none**:
`talking_clients`, `english_demand`, `team_autonomy`, `product_vs_services`,
`travel_requirement`, `learning_support`. Every mark comes from T57's read pass;
nothing here waits on collection. Round 1's labels show as already-confirmed where
the adverts overlap.

## The corpus: 141 adverts collected, deliberately NOT merged

`tools/collect_ads.py --target-es 140 --target-en 60 --target-ca 110 --target-family 30`
ran this session and took the raw corpus 208 → **349** (evaluation 175, elicitation
174; ca 72/72, es 74/75, en 28/28). The result is **parked, not lost** — re-run the
same command to reproduce it.

**It was not merged, and the ordering matters.** `suggestions.blind_control` is
derived from ad ids with `count = ceil(len(slice) * share)`, so growing the corpus
**recomputes the cohort** and invalidates the declared one — `validate_suggestions`
then refuses to build any page at all. Every new advert also needs T57's read pass
before it is cheap to label. Landing it before round 2 would have broken the page
round 2 runs on.

So: **round 2 first, corpus second.** After round 2, land the 141 and run the read
pass over them.

### What the corpus is actually needed for

`--dimensions below-floor` says 44 adverts would floor 13 of the 20 remaining
dimensions from marks already on disk, and that **seven cannot be floored however
hard anyone labels**: `on_call_load` (short 7), `social_intensity` (7),
`company_stage` (5), `inclusion_commitment` (4), `mentoring_culture` (4),
`career_progression` (3), `technical_depth` (1). Those seven, and T59's tenth
negated label, are the entire case for collecting.

## T59 — 6/9, and why the last three are not this task's

Two mistakes were fixed, neither a corpus problem:

* **`Cue.denies`.** Three misses were *correct extractions* scored as failures.
  `value=0.0, negated=False` was already taken — it is what an advert stating its
  lowest rung means (`presencial` is rung 0 "On-site"). Ten of the sixteen
  zero-valued cues are denials and six are rung-0 statements, and one encoding
  carried both. The rule for telling them apart is mechanical: **a cue denies iff
  its pattern cannot match without a negator word.**
* **Corroboration is asked of positives, not denials.** One `sprint` establishes
  nothing; `sin sprints tradicionales` is not ambiguous that way. Measured before
  keeping it: 3 pairs out of 2,080, all true denials, suppression still 0.

The remaining three misses are vocabulary the cue set does not contain (`dailies`,
`reuniones innecesarias`) — T57's shortlist. And the gate stays `unmeasured`
regardless: 9 negated labels against a floor of 10, and round 1 added **zero**
(none of the 76 labels was negated).

## Upstream

`claude-arsenal#237` (the downgrade guard on the wrong side of the version
boundary) is **fixed** — v2.4.17 / #238 put the check in `check_update.sh`, which
is the side that can reach a stale host. **Update to v2.4.17 when convenient.**

`claude-arsenal#239` filed for four findings a review bot raised against the
vendored bundle. Two were verified against source: `open_task_pr.sh` resolves
`ARSENAL_HOME` relative to the caller's cwd while its `cd "$_repo_root"` calls are
subshell-only, so archiving from a subdirectory writes the wrong path; and
`handle_sync.py` lets an ambiguous loose key create two handles (deliberate per its
own comment, but this repo resolves issues **by title**, so the collision is live).

## Next session

1. **Round 2** — `corpus/labelled/round-02.html`, 18 adverts, needs the owner.
2. **Then land the 141 collected adverts** and run T57's read pass over them, in
   that order.
3. **T57 closes by adding dimensions, not by remapping** — 648 unmapped concepts;
   credentials (83), pay structure (54), place/mobility (41), working-time shape
   (37) is the shortlist, and `seniority_expectation`'s 9 false negatives are the
   same finding arriving from the other direction.
4. **T20 and T69 still need the owner in person.** `tools/blind_ranking_page.py`
   for T20; T69 needs the exhaustion signal watched on a live cycle.

Four open tasks carry no issue handle and are not claimable until one exists —
`lo-c48f` is T20 (#59 exists but the title no longer resolves), plus `t-192eaa52`,
`lo-3100`, `lo-9e41`. Worth a `handle_sync.py` pass.
