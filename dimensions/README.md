# Dimension model v0 (T3)

One file per dimension, `dimensions/<id>.yaml`, conforming to
`status/specification.md` §5.1 and validated by `jobsearch.dimensions`. This is
the spine: the questions the elicitation engine asks, the cues extraction reads
from an ad, the axes the ranker compares on, and later the CV and interview work
are all projections of these files. Changing an `id` is a breaking change
everywhere; adding a file is additive.

22 dimensions, within the plan's 20–25 range for v0.

| id | kind | polarity | group | rungs (what you actually click) |
|----|------|----------|-------|--------------------------------|
| `career_progression` | soft | unipolar | `growth` | No path named · Growth mentioned, undefined · A named path |
| `company_stage` | soft | bipolar | `growth` | Early-stage startup · Mid-size or unstated · Large and established |
| `compensation_transparency` | soft | unipolar | `terms` | Silent on pay · Described, never quantified · A figure or a band |
| `contract_stability` | hard | unipolar | `dealbreakers` | Freelance / self-employed · Fixed-term · Open-ended |
| `english_demand` | hard | unipolar | `dealbreakers` | Not required · Intermediate · The job runs in English |
| `inclusion_commitment` | soft | unipolar | `people` | Silent · Boilerplate · Concrete commitment |
| `learning_support` | soft | unipolar | `growth` | Nothing · Mentioned, nothing named · Paid and specific |
| `mentoring_culture` | soft | unipolar | `people` | Sink or swim · Mentioned · Deliberate |
| `mission_alignment` | soft | bipolar | `growth` | A sector to refuse · Not stated · Purpose stated |
| `on_call_load` | soft | unipolar | `terms` | None · Occasional · Rotation or incident duty |
| `process_formality` | soft | bipolar | `the_work` | Lightweight · Not stated · Agile ceremony · Heavy formal process |
| `product_vs_services` | soft | bipolar | `the_work` | Consultancy or staffing · Not stated · The employer's own product |
| `remote_arrangement` | hard | unipolar | `dealbreakers` | On-site · Hybrid · Fully remote |
| `schedule_flexibility` | soft | unipolar | `terms` | Fixed timetable · Some give · Shaped around the person |
| `seniority_expectation` | hard | unipolar | `dealbreakers` | Junior · Mid-level · Senior |
| `social_intensity` | soft | bipolar | `people` | Solitary and focused · Not stated · Group-heavy |
| `stack_modernity` | soft | bipolar | `the_work` | Legacy estate · Not stated · Current and active |
| `team_autonomy` | soft | bipolar | `people` | Decisions arrive made · Not stated · The team decides |
| `technical_depth` | soft | bipolar | `the_work` | Operating what exists · Not stated · Engineering hard problems |
| `travel_requirement` | hard | unipolar | `dealbreakers` | None stated · Occasional · Regular travel or relocation |
| `wellbeing_benefits` | soft | unipolar | `terms` | None named · One perk · Real provision |
| `work_intensity` | soft | bipolar | `the_work` | Deliberate pace · Not stated · Sustained pressure |

## Levels — the rungs a human labels in

Nobody can answer "is this ad 0.6 or 0.7 on mentoring". Every dimension therefore
declares the two-to-five **named** positions its scale really has (`levels`),
each with the value it stands for and a `tell` naming what that rung looks like
in ad wording. The labelling page shows the names; the float is a storage detail
the labeller never sees.

The same list is the class set `extraction_macro_f1` (T15) is computed over.
Macro-F1 is defined over classes and a continuous score has none — so an
extracted float is snapped to the nearest rung (`Dimension.snap`) before it is
compared with a human label. Declaring the classes in the model, rather than
binning at measurement time, is what keeps the binning rule reviewable instead
of being a choice made where it could flatter the result.

Hence the asymmetry the loader enforces:

- a **gold** value must equal a declared rung — gold is a human judgement about
  a real ad, so it has to be sayable in the vocabulary a human labels in;
- a **cue** value need only lie inside the scale — it is the extractor's
  continuous estimate and is snapped when scored. What it must not do is point
  past either end, where snapping would silently clamp it into a rung it never
  meant.

That second rule caught four cues on first run (`company_stage` 0.7,
`english_demand` 1.0, `mission_alignment` 0.7, `travel_requirement` 0.9) each
reaching past the top rung the v0 model implied. The cues were right and the
ceilings were too low, so the rungs moved up and six gold entries snapped onto
them. Four further gold values (`stack_modernity` 0.4, `work_intensity` 0.6,
`learning_support` 0.7, `mission_alignment` 0.7) sat between rungs and were
snapped to the nearest. Every `span` is byte-identical — only `value` moved —
so `verify_gold` and `unmatched_gold` are unaffected.

**These gold values remain cue-derived (D-2).** Snapping them onto rungs makes
them expressible; it does not make them independent. `extraction_macro_f1` must
still be measured against T5's hand labels, never against this gold.

## Groups — how the labelling picker is ordered

`group` sorts the 22 dimensions into five titled sections so the labeller can
find one without already knowing its name: `dealbreakers`, `terms`, `the_work`,
`people`, `growth`. It is purely presentational — nothing scores on it — and it
is declared in the model rather than in the page so a dimension added later
cannot appear in an unsorted "other" bucket. `dealbreakers` happens to be
exactly the `kind: hard` set today; that is v0 content, not a rule, so the two
fields stay independent.

`kind: hard` dimensions veto rather than trade off, so they are all `unipolar`:
a bipolar filter has no defensible cut-off. Direction on them is expressed by
the candidate's threshold, not by the sign of the score.

## Sides

Every dimension above is `side: matched` — the ad describes it, the candidate
has a preference about it, and ranking compares the two. Two other sides exist
so that things which are *not* that shape do not have to pretend:

| side | example | ad cues | how it is used |
|------|---------|---------|----------------|
| `matched` (default) | `social_intensity` | required | preference vs description |
| `candidate_fact` | languages spoken, location, salary floor | none of its own | filtered against the ad-side requirement named in `compares_against` |
| `candidate_trait` | creativity, ambition | **refused** | elicited in the interview; never extracted from an ad |

A cue on a trait asserts that an ad's wording evidences the *candidate's*
ambition — it evidences the employer's prose — so the loader rejects it rather
than warning. And `dimension_extractor_coverage` counts only ad-side
dimensions: asking "can this be extracted from an ad" of a trait scores the
model down for holding the thing the interview exists to elicit, which is
pressure on a future author to delete traits to keep a gate green.

`side` is not an escape hatch from writing cues. `side_coverage_violations`
(gate T23) counts every dimension whose side and content disagree:

- a `matched` dimension with no cues — the original defect the coverage gate
  exists to catch;
- a `candidate_fact` naming no comparison target, or one that does not resolve;
- a `candidate_fact` whose target is not `matched` — comparing a fact against
  another candidate-side dimension compares the candidate with themselves, so
  the filter reads as a constraint and behaves as a no-op;
- a `candidate_fact` carrying **its own** cues or gold — the ad-side evidence
  belongs to the requirement it compares against, and cues on both halves score
  the same ad wording twice;
- `compares_against` set anywhere but a `candidate_fact`, where it is a silent
  no-op.

## Cues and gold examples

Every dimension carries cues in all three corpus languages (es / en / ca) and at
least one **gold example**: a verbatim excerpt from a real ad in
`corpus/raw/ads.jsonl`, named by `ad_id`, with the value the dimension should
take on it. `verify_gold` asserts each span appears byte-for-byte in the ad it
cites, so the gold set cannot drift into paraphrase — the same rule the corpus
README applies to the ads themselves.

`unmatched_gold` additionally asserts that each gold span is matched by one of
its own dimension's cues. A gold example the extractor cannot reach still counts
towards `dimension_extractor_coverage` while proving the opposite of what that
metric claims — and it appears exactly when a cue is tightened without
revisiting the gold it was written from.

**Caveat on gold provenance.** The v0 gold examples were first selected by
searching the corpus for text each dimension's own cues match. That makes them
real, but not independent: they demonstrate that a cue fires on genuine market
language, and they do **not** constitute evidence that extraction generalises to
phrasings the cues do not already anticipate. T5's hand labels are the
independent set, and `extraction_macro_f1` (T15) must be measured against those,
never against this gold. Tracked as queue task D-2.

Review caught what that mechanical selection cost: seven dimensions had cues
matching a *word* without requiring it applied to the role or employer, and each
had inherited a gold example demonstrating the error. "Startup culture" at a
multinational founded in 1982 scored as early-stage; a staffing marketplace's
"product teams" scored as own-product; a required ISTQB certificate scored as
employer-funded learning; a mental-health institution's sector description scored
as an employee wellbeing benefit; "hand the on-call a summary" — something the
advertised product does — scored as on-call load on the candidate; "your main
mission will be" scored as employer mission; and a bare `anglès` matched any
mention of the word. Those cues now require role or employer attribution, and
every replacement gold span was read in its full ad before being committed.

## Where the model does not reach

`status/evidence/T3.json` records `language_slices_with_no_corpus_hit` — the
`<dimension>:<language>` pairs whose cues match no ad in the corpus. Eleven of
the 66 slices are silent, and most of them are the corpus telling the truth: the
Catalan slice carries no wellbeing benefits, no company-stage language and no
on-call language, because those 15 ads are public-sector and health IT roles
(see the T4b divergence note in `corpus/raw/README.md`). Inventing cue hits to
close those gaps would make the model look more covered than the market is. The
list is reported rather than failed so the gaps stay visible.

## Working on the model

```bash
uv run python -m jobsearch.dimensions status/evidence/T2.json     # schema violations (T2)
uv run python -m jobsearch.dimensions --coverage status/evidence/T3.json  # extractor coverage (T3)
uv run --extra dev pytest tests/test_dimension_model.py tests/test_dimension_content.py -q
```

`dimension_extractor_coverage` is the fraction of dimensions carrying both ≥1
extractor rule and ≥1 gold example; the T3 gate requires ≥ 0.90.
