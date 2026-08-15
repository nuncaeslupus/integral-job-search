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

**Caveat on gold provenance.** The v0 gold examples were selected by searching
the corpus for text each dimension's own cues match, then recording the
surrounding excerpt. That makes them real, but not independent: they demonstrate
that a cue fires on genuine market language, and they do **not** constitute
evidence that extraction generalises to phrasings the cues do not already
anticipate. T5's hand labels are the independent set, and `extraction_macro_f1`
(T15) must be measured against those, never against this gold.

## Working on the model

```bash
uv run python -m jobsearch.dimensions status/evidence/T2.json     # schema violations (T2)
uv run python -m jobsearch.dimensions --coverage status/evidence/T3.json  # extractor coverage (T3)
uv run --extra dev pytest tests/test_dimension_model.py tests/test_dimension_content.py -q
```

`dimension_extractor_coverage` is the fraction of dimensions carrying both ≥1
extractor rule and ≥1 gold example; the T3 gate requires ≥ 0.90.
