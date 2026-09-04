# Dimension model v0 (T3)

One file per dimension, `dimensions/<id>.yaml`, conforming to
`status/specification.md` §5.1 and validated by `integral.dimensions`. This is
the spine: the questions the elicitation engine asks, the cues extraction reads
from an ad, the axes the ranker compares on, and later the CV and interview work
are all projections of these files. Changing an `id` is a breaking change
everywhere; adding a file is additive.

41 dimensions — 37 ad-side and 4 candidate traits. v0 was 23, within the plan's
20–25 range; `talking_clients` was the 23rd, coined by the labeller mid-read
rather than designed up front, which is the labelling page's `+ new dimension`
path working as intended.

**Twelve were added by T57**, for the only honest reason there is: the corpus
broadened past remote programming to six job families and `ontology_hit_rate` read
**0.6143** — 648 of the 1,680 concepts the adverts stated had nowhere in the model
to go. Re-reading the v0 model as generously as its own definitions allow reaches
0.6875, so widening was the only route to the 0.85 gate that did not involve
dropping what the readers could not name. The twelve cover what a care, trades,
retail or teaching advert says and a programming advert does not —
`formal_credential`, `local_language_demand`, `commute_burden`,
`contracted_hours`, `physical_demand`, `work_eligibility`, `role_breadth`,
`domain_knowledge`, `tool_specificity`, `hiring_process_burden`, `variable_pay` —
plus `ai_in_the_work`, which is the market moving rather than the corpus widening.
The measurement now reads **0.9071**, with no language below 0.87.

| id | kind | polarity | group | rungs (what you actually click) |
|----|------|----------|-------|--------------------------------|
| `ai_in_the_work` | soft | unipolar | `skills` | Not mentioned · Tools available or encouraged · The work is AI work |
| `ambition` | soft | bipolar | `growth` | Content with the work they hold · Not yet elicited · Reaches for the next step |
| `career_progression` | soft | unipolar | `growth` | No path named · Growth mentioned, undefined · A named path |
| `collaboration_mode` | soft | bipolar | `people` | Alone · Not stated · Both · In a team |
| `commute_burden` | hard | unipolar | `requirements` | No condition stated · Local residence expected · Own vehicle or licence required |
| `company_stage` | soft | bipolar | `growth` | Early-stage startup · Mid-size or unstated · Large and established |
| `compensation_transparency` | soft | unipolar | `terms` | Silent on pay · Described, never quantified · A figure or a band |
| `contract_stability` | hard | unipolar | `dealbreakers` | Freelance / self-employed · Fixed-term · Open-ended |
| `contracted_hours` | hard | unipolar | `dealbreakers` | Not stated · Very short part time · Part time · Full time |
| `creativity` | soft | bipolar | `the_work` | Works from the proven pattern · Not yet elicited · Invents an approach |
| `domain_knowledge` | soft | unipolar | `skills` | Not stated · A sector named · Domain expertise required |
| `english_demand` | hard | unipolar | `requirements` | Not required · Intermediate · The job runs in English |
| `formal_credential` | hard | unipolar | `requirements` | None stated · Desirable · Required |
| `hiring_process_burden` | soft | unipolar | `terms` | Nothing stated · A described process · An artefact or test required |
| `inclusion_commitment` | soft | unipolar | `people` | Silent · Boilerplate · Concrete commitment |
| `leadership` | soft | unipolar | `people` | Nobody to lead · Leads work, not people · A small team · A big team, or several |
| `learning_orientation` | soft | bipolar | `growth` | Learns what the job requires · Not yet elicited · Studies the field unprompted |
| `learning_support` | soft | unipolar | `growth` | Nothing · Mentioned, nothing named · Paid and specific |
| `local_language_demand` | hard | unipolar | `requirements` | Not required · Conversational · Certified or native level |
| `mentoring_culture` | soft | unipolar | `people` | Sink or swim · Mentioned · Deliberate |
| `mission_alignment` | soft | unipolar | `growth` | Not stated · Purpose stated |
| `on_call_load` | soft | unipolar | `terms` | None · Occasional · Rotation or incident duty |
| `physical_demand` | soft | unipolar | `requirements` | None stated · Some handling or standing · Heavy or hazardous |
| `process_formality` | soft | bipolar | `the_work` | Lightweight · Not stated · Agile ceremony · Heavy formal process |
| `product_vs_services` | soft | bipolar | `the_work` | Consultancy or staffing · Not stated · The employer's own product |
| `remote_arrangement` | hard | unipolar | `dealbreakers` | On-site · Hybrid · Fully remote |
| `role_breadth` | soft | bipolar | `the_work` | One specialism · Not stated · Several jobs in one post |
| `schedule_flexibility` | soft | unipolar | `terms` | Fixed timetable · Some give · Shaped around the person |
| `seniority_expectation` | hard | unipolar | `dealbreakers` | Junior · Mid-level · Senior |
| `social_intensity` | soft | bipolar | `people` | Solitary and focused · Not stated · Group-heavy |
| `spare_time_engagement` | soft | bipolar | `growth` | The day ends when it ends · Not yet elicited · The craft follows them home |
| `stack_modernity` | soft | bipolar | `the_work` | Legacy estate · Not stated · Current and active |
| `talking_clients` | soft | unipolar | `the_work` | None · A little · Some relationship · Job is about that |
| `team_autonomy` | soft | bipolar | `people` | Decisions arrive made · Not stated · The team decides |
| `technical_depth` | soft | bipolar | `the_work` | Operating what exists · Not stated · Engineering hard problems |
| `tool_specificity` | soft | unipolar | `skills` | No tool named · A broad list · A named stack required |
| `travel_requirement` | hard | unipolar | `dealbreakers` | None stated · Occasional · Regular travel or relocation |
| `variable_pay` | soft | unipolar | `terms` | None named · A bonus or premium · Equity or profit sharing |
| `wellbeing_benefits` | soft | unipolar | `terms` | None named · One perk · Real provision |
| `work_eligibility` | hard | unipolar | `requirements` | No restriction stated · A region or timezone band · A permit or country required |
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

`group` sorts the dimensions into **seven** titled sections so the labeller can
find one without already knowing its name: `dealbreakers`, `requirements`,
`terms`, `the_work`, `people`, `skills`, `growth`. It is purely presentational —
nothing scores on it — and it is declared in the model rather than in the page so
a dimension added later cannot appear in an unsorted "other" bucket.

It said **five** until T57, listing the five that existed before `requirements`
and `skills` were added to keep every group under the eight-row no-scroll cap.
Prose about the model that no test reads drifts the moment the model changes, so
`test_the_readme_names_every_group_the_model_declares` now reads this paragraph
against `load_dimensions()`.

`dealbreakers` is **no longer** the `kind: hard` set: `commute_burden`,
`english_demand`, `formal_credential`, `local_language_demand`,
`seniority_expectation` and `work_eligibility` are `hard` and sit under
`requirements`. That the two ever coincided was v0 content rather than a rule,
which is why the fields stayed independent — and why the split cost nothing.

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

**Gold provenance is a field, not a caveat (D-2).** Every gold example carries
`derived_from: cue | human`, required by the schema with no default — a default
is a provenance decided by absence, and getting it wrong in the `human`
direction is the silent failure the field exists to prevent.

* `cue` — the span was found by searching the corpus for text this dimension's
  own cues already match. Real ad wording, and a fair demonstration that a cue
  fires on genuine market language. **Not** independent of the extractor:
  scoring extraction against it asks a regex to re-find the string it was
  written from, which passes near 1.0 and measures nothing.
* `human` — a person read the ad and decided the value. The only kind that can
  evidence generalisation.

`evaluation_gold(dimensions)` returns only the `human` half, per dimension, and
is the single function an extraction score may be computed over — so "score
only against human labels" is code rather than a rule someone has to remember.
It keeps a key for every dimension, including the ones whose list is empty: a
dimension that cannot be scored has to stay visible, or a macro-average over
the survivors reads as complete. `extraction_macro_f1` (T15, `lo-25b1`) is
computed over this and nothing else.

The committed state, measured on every `make evidence` run and recorded in
`status/evidence/T3.json`:

| | |
|---|---|
| `gold_by_provenance` | **69 cue, 0 human** |
| `evaluation_gold_count` | **0** |
| `dimensions_without_evaluation_gold` | **all 25 ad-side dimensions** |
| `cue_derived_gold_in_evaluation_split` | 0 — D-2's gate |

That first row is the finding, not a gap to be closed by relabelling: the whole
v0 gold set is cue-derived, so today **no dimension can be scored for
extraction at all**. The last row is the only one that can go wrong, and it
does so the moment `evaluation_gold`'s filter is relaxed — which is tempting
precisely because every list it returns is currently empty and that looks like
a bug.

One rule changes shape as a result. `unmatched_gold` applies to **cue-derived
gold only**. Requiring a span to be reachable by the very cues it tests is fair
of an example those cues selected and incoherent of a person's reading — a
human label matters most exactly where the cues miss it. Since `_main` treats
an `unmatched_gold` violation as a hard failure, the unscoped rule would have
turned the T3 gate red on the first human label the cues did not anticipate,
reading the most valuable evidence in the set as a defect.

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
uv run python -m integral.dimensions status/evidence/T2.json     # schema violations (T2)
uv run python -m integral.dimensions --coverage status/evidence/T3.json  # extractor coverage (T3)
uv run --extra dev pytest tests/test_dimension_model.py tests/test_dimension_content.py -q
```

`dimension_extractor_coverage` is the fraction of dimensions carrying both ≥1
extractor rule and ≥1 gold example; the T3 gate requires ≥ 0.90.
