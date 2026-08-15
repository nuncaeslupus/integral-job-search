# Dimension model v0 (T3)

One file per dimension, `dimensions/<id>.yaml`, conforming to
`status/specification.md` §5.1 and validated by `jobsearch.dimensions`. This is
the spine: the questions the elicitation engine asks, the cues extraction reads
from an ad, the axes the ranker compares on, and later the CV and interview work
are all projections of these files. Changing an `id` is a breaking change
everywhere; adding a file is additive.

22 dimensions, within the plan's 20–25 range for v0.

| id | kind | polarity | what it is about |
|----|------|----------|------------------|
| `career_progression` | soft | unipolar | a named path upward, or an unspecified future |
| `company_stage` | soft | bipolar | early-stage startup ↔ large established organisation |
| `compensation_transparency` | soft | unipolar | does the ad state what it pays |
| `contract_stability` | hard | unipolar | open-ended employment ↔ fixed-term or freelance |
| `english_demand` | hard | unipolar | how much working English the role requires |
| `inclusion_commitment` | soft | unipolar | concrete equality/disability commitments vs silence |
| `learning_support` | soft | unipolar | paid training, certifications, and time to use them |
| `mentoring_culture` | soft | unipolar | people brought on deliberately, or sink-or-swim |
| `mission_alignment` | soft | bipolar | purpose worth having ↔ sectors the candidate refuses |
| `on_call_load` | soft | unipolar | out-of-hours availability the role carries |
| `process_formality` | soft | bipolar | prescribed ceremony ↔ lightweight coordination |
| `product_vs_services` | soft | bipolar | own product ↔ consultancy / staff augmentation |
| `remote_arrangement` | hard | unipolar | fully remote ↔ hybrid quotas ↔ on-site |
| `schedule_flexibility` | soft | unipolar | how far the working day bends around the person |
| `seniority_expectation` | hard | unipolar | experience the ad requires |
| `social_intensity` | soft | bipolar | unstructured group interaction ↔ solitary focused work |
| `stack_modernity` | soft | bipolar | current, actively developed tech ↔ legacy estate |
| `team_autonomy` | soft | bipolar | the team decides ↔ decisions arrive already made |
| `technical_depth` | soft | bipolar | engineering hard problems ↔ operating what exists |
| `travel_requirement` | hard | unipolar | travel or relocation the role requires |
| `wellbeing_benefits` | soft | unipolar | health cover, mental-health support, leave |
| `work_intensity` | soft | bipolar | sustained delivery pressure ↔ deliberate pace |

`kind: hard` dimensions veto rather than trade off, so they are all `unipolar`:
a bipolar filter has no defensible cut-off. Direction on them is expressed by
the candidate's threshold, not by the sign of the score.

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
