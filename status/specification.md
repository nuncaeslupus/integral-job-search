# Specification: Candidate-centred integral job search

**Date**: 2026-08-15
**Ticket / PR**: branch `claude/ai-job-search-review-rtt6y4`
**Author**: nuncaeslupus

---

## 1. Problem statement

Job search tooling matches hard skills against stated requirements and stops there. But a
person is not a skill list and an employer is not a requirements list: how social the office
is, how many meetings a week, how much autonomy, whether "remote" means remote, whether the
schedule survives a school run, and how the employer *writes* — all of it decides whether a
candidate will still want the job in eighteen months. Existing tools, `ai-job-search`
included, treat profiling, search, ranking, CV tailoring and interview prep as separate
concerns with separate vocabularies, so the candidate's non-skill dimensions never survive
the trip from questionnaire to ranked list. The candidate ends up evaluating fit manually,
one ad at a time, and learns nothing from what happens next. We will build an integral,
candidate-side system in which a **single dimension model is the shared vocabulary** across
every stage — the questions asked, the evidence extracted from an ad, the ranking, the CV
emphasis, the interview prep and the outcome analysis — so that adding a dimension once
propagates everywhere, and so that "everything works toward the same goal" is enforced by
construction rather than by discipline.

Scope for v1 is a **thin vertical slice** that touches every layer for one candidate, one
market and one source. Later phases (application, outcome learning, recommendations,
automation) extend a working spine rather than being separate projects.

**Success criteria (measurable)** — scoped to the v1 thin vertical. Deferred phases carry
their own gates.

- [ ] `question_dimension_coverage == 1.0` — every question in the bank maps to ≥1 dimension ID
- [ ] `dimension_extractor_coverage >= 0.90` — fraction of dimensions with ≥1 extractor rule and ≥1 gold example
- [ ] `extraction_macro_f1 >= 0.75` — against the hand-labelled corpus, macro-averaged across dimensions
- [ ] `extraction_negation_recall >= 0.80` — on the corpus subset labelled as negated ("no on-call", "not open-plan")
- [ ] `rank_spearman >= 0.60` — Spearman correlation between system ranking and the candidate's own blind manual ranking of 20 held-out ads
- [ ] `explained_fraction == 1.0` — every ranked offer cites ≥1 verbatim evidence span per contributing dimension
- [ ] `dedup_precision >= 0.95` — on a seeded set of known cross-posted duplicates
- [ ] `ontology_hit_rate >= 0.85` — fraction of extracted concepts mapping to a known dimension; this doubles as the **staleness signal** (a sustained drop means the market moved and the model needs new questions)
- [ ] `corpus_size >= 100` — hand-labelled ads (≈60 ES, ≈25 EN, ≈15 CA)
- [ ] `story_bank_size >= 12` — distinct episodes captured at onboarding (projects, failures, decisions, definitions of success)
- [ ] `story_dimension_linkage == 1.0` — every episode links to ≥1 dimension ID, so the bank is queryable rather than a pile of prose
- **`story_failure_fraction` — reported, not gated.** The v1 draft floored this
  at `>= 0.33`: at least a third of episodes about something that went wrong,
  because success stories are rehearsed and reveal less. That floor is
  **superseded** — `status/spec-v2-steps.md` step 3's revised History protocol
  takes a failure episode when the candidate offers one rather than digging
  for one to satisfy a quota, and a floor requires exactly that digging; the
  two cannot both hold. What survives the concern behind the floor: once a
  bank holds four or more episodes it should contain both kinds, and
  `story_failure_fraction` is computed and shown alongside the bank so a
  monotone one is visible, but nothing in this system passes or fails against
  it. (D-3.)
- [ ] `reaction_elicitation_items >= 15` — real ads or ad excerpts reacted to, compared or sorted during onboarding
- [ ] `elicitation_eval_overlap == 0` — zero overlap between the ads used to elicit preferences and the 20 held-out ads scored for `rank_spearman`. Without this the ranking gate measures memorisation rather than fit, and would pass while the system is worthless
- [ ] **Profile recognisability** (non-numeric): given their own generated profile plus two
      perturbed variants, unlabelled, the candidate identifies their own. Judged by a single
      blind trial per candidate; failure means the profiler is producing generic output.
- [ ] **No autonomous outward action** (non-numeric): audited by inspection — no code path
      submits an application, sends an email, or contacts an employer without explicit
      per-item human approval.
- [ ] **No undisclosed story reuse** (non-numeric): audited by inspection — no story-bank
      episode reaches a document destined for an employer without per-use approval.
      Recounting a failure to the tool is not consent to send it to a company.
- [ ] `undocumented_methods == 0` — every technique that scores, weights or ranks, and every
      formula producing a number the candidate sees, has an entry in `docs/METHODS.md` naming
      the method, its source and its limits. Checkable by walking the computation sites
      against the register.

## 2. Systems & Impact

**Phases** — the table below labels deferred components by phase. Phases are a delivery
sequence, not a component list: several systems in one phase, and some systems (the
elicitation engine) are built in an early phase and reused by later ones.

| Phase | Name | Contents |
|---|---|---|
| 0 | Foundations | Dimension model, labelled corpus, multi-user schema decision, research |
| 1 | Candidate | Elicitation engine, dimension layer, story bank, feedback log |
| 2 | Supply | Source connectors, normalize, dedup, expiry |
| 3 | Understanding | Extraction funnel, writing-style features, enrichment |
| 4 | Matching | Pareto ranking, facet lists, explanations |
| 5 | Loop | Feedback → profile revision; calibration against revealed preference |
| 6 | Automation | Scheduled incremental search, new-offer detection |
| 7 | Application | Pre-draft gap-fill, CV + cover letter generation, outcome tracking, email sensor |
| 8 | Guidance | Interview rehearsal, recommendations (courses, preparation, situational advice) |

**Phases 0-5 are the v1 thin vertical.** Phases 6-8 are deferred and appear in the table
below marked as such.

Greenfield: nearly everything is new. "Needs changes" therefore reads as "in v1 scope".

| System | Type | Role | Needs changes? | Impact | Severity |
|--------|------|------|----------------|--------|----------|
| `dimensions/` — dimension model | Primary | The spine. Per dimension: ID, definition, elicitation question(s), extraction cues per language, hard-filter vs soft-preference, polarity | Yes (v1) | Every other component is a projection of this. Changing a dimension ID is a breaking change everywhere | High |
| `corpus/` — labelled ad corpus | Shared resource | Ground truth for extraction and ranking gates, **and** stimulus pool for reaction elicitation | Yes (v1) | Without it no quantitative gate can run. Pacing item for the whole project. Serving three consumers raises its value and makes the labelling effort easier to justify | High |
| `docs/METHODS.md` | Shared resource | Register of every technique, instrument and formula, with sources, limits and known evidence gaps | Yes (v1) | A tool that scores a person on psychological dimensions and cannot say why should not be trusted. Also the defence against silently adopting a method because it sounded plausible | High |
| Elicitation engine | Primary | One engine, three consumers: onboarding interview, pre-draft gap-filling, real-interview rehearsal. Generates questions from the dimension model, accepts free text, extracts both dimension values (with uncertainty) and episodes | Yes (v1) | Candidate-facing; poor questions produce a generic profile and everything downstream degrades. Splitting this into separate "profiler" and "interview simulator" would duplicate the hardest component | High |
| Reaction elicitation | Primary | Second elicitation modality: present real ads and ad excerpts (perks blocks, requirement blocks, how the employer phrases an ask) and capture free-text reaction, comparison and sorting. Draws stimuli from the corpus | Yes (v1) | People introspect badly in the abstract and react well to concrete text. Also surfaces ontology gaps, because reactions arrive in the wild vocabulary the extractor must handle. Supplies day-one preference data the system otherwise lacks until outcomes exist | High |
| Profile store — dimension layer | Primary / shared | Per-candidate dimension values as a **derived view** over an append-only evidence log | Yes (v1) | Holds sensitive psychological and personal data. Schema must be multi-user from day one | High |
| Profile store — story bank | Primary / shared | Verbatim episodes (projects, failures, decisions, definitions of success) tagged to dimension IDs, with a per-use disclosure flag | Yes (v1) | Dimension scores can rank a job but cannot write a sentence; the story bank is what makes a cover letter specific rather than fluent-generic. Most sensitive artefact in the system | High |
| Feedback log | Primary | Append-only record of "I don't like this because…" and every other preference signal | Yes (v1) | Source of truth for profile evolution; enables recompute and audit | High |
| Source connectors | Primary | Per-portal fetch → normalised offer schema. One connector in v1, plus manual-paste | Yes (v1) | ToS and anti-bot exposure lives here and nowhere else | Medium |
| Normalizer + dedup | Primary | Cross-source identity resolution, expiry detection | Yes (v1) | Duplicates poison every ranked list | Medium |
| Extractor (funnel) | Primary | Cheap lexical prefilter → LLM structured extraction on survivors, with evidence spans | Yes (v1) | Dominant recurring cost; accuracy sets the ceiling for ranking | High |
| Enrichment | Primary | Signals not in the ad: employer site, review sites, writing-style features of the ad itself | Partial (v1: writing-style only) | Where the project is genuinely differentiated; also where it can drift into astrology without corpus calibration | Medium |
| Ranker | Primary | Pareto frontier over dimensions + named facet lists; forced-pairwise-derived weights | Yes (v1) | The user-visible product | High |
| Explanation layer | Primary | Per-offer justification citing evidence spans | Yes (v1) | Non-negotiable: an unexplained rank is unusable and unfalsifiable | High |
| Pre-draft gap-fill | Dependent | Before drafting for a specific job: diff the posting's demands against story-bank coverage, elicit only the gaps, often nothing | No (Phase 7) | Deferred, but its dependency is in v1 — it is the elicitation engine pointed at one job. Keeps per-application effort proportional to what is genuinely missing | — |
| Application generator (CV/letter) | Dependent | Tailored documents driven by the same dimensions, written from approved story-bank episodes | No (Phase 7) | Deferred | — |
| Interview rehearsal | Dependent | Company research, likely questions, mock runs against the story bank | No (Phase 8) | Deferred. Thin layer over the v1 elicitation engine rather than a new subsystem | — |
| Outcome tracker + email sensor | Dependent | Read-only mail scan → application state; pattern analysis across applications | No (Phase 7) | Deferred. Needs volume before it yields signal | — |
| Recommendations | Dependent | Courses, preparation, situational advice | No (Phase 8) | Deferred. Highest harm potential of any subsystem | — |
| Scheduler | Infrastructure | Daily incremental search | No (Phase 6) | Deferred | — |
| `claude-arsenal` | Infrastructure | Queue, gates, workers | No | Consumed as-is at pinned `v0.23.1` | Low |
| LLM API | External | Extraction, profiling, explanation | No | Per-ad cost × daily cadence × sources is the main running cost; the funnel exists to bound it | Medium |
| Job portals | External | Supply | No | ToS, rate limits, blocking. Mitigated by low volume, robots.txt respect, manual-paste fallback | Medium |
| Mail provider | External | Outcome signal | No (Phase 7) | Deferred. Read-only, narrow query scope, propose-never-write | — |

**Risk of inaction**: the candidate keeps evaluating fit by hand at roughly one ad per five
minutes, applies to poorly-fitting roles, and — critically — never accumulates the outcome
data that would tell them which of their assumptions about themselves are wrong.

**Scope boundary (deliberate)**: this is a **candidate-side** tool. The same scoring
machinery pointed at candidates on an employer's behalf is a regulated activity under the
EU AI Act's employment provisions. Nothing in the architecture prevents that inversion, so
it is recorded here as an explicit non-goal.

## 3. Options

Three approaches, ordered by how much is built before anything runs. They differ less in
what they can eventually do than in what they foreclose: A is fastest to a tailored CV but
fixes the vocabulary fragmentation in place, B builds the shared vocabulary first and defers
features, C commits now to decisions that need evidence we do not yet have. Read each
option's **Tradeoffs** as the real decision content; effort is the least interesting column.

### Option A: Extend `ai-job-search` in place (Conservative)

- **Description**: Fork the existing project and add soft-dimension vocabulary to its skill
  files (`04-job-evaluation.md`, `search-queries.md`). Reuse its portal CLIs, LaTeX
  pipeline, PDF verification and interview prep as-is.
- **Scope**: A handful of Markdown files in a fork; no new codebase.
- **Effort**: Small
- **Tradeoffs**: Fastest path to *something*, and its PDF/ATS verification loop is genuinely
  good work we would otherwise rebuild. But it inherits every structural problem: framework
  and personal data share file paths (so upstream merges conflict by construction), the
  profile *is* the root `CLAUDE.md` (so two candidates need two repos), the tracker is a CSV
  that conflicts on every concurrent write, and — decisively — each stage keeps its own
  vocabulary, which is the exact failure this project exists to fix. Ranking stays a single
  linear list.
- **Compatibility**: Diverges from upstream immediately; community portal skills stay
  borrowable by hand.

### Option B: Dimension-model-first thin vertical (Recommended)

- **Description**: New codebase. Build the dimension model and labelled corpus first, then
  one end-to-end path through every layer: adaptive profiler → one source connector →
  extraction funnel → Pareto ranking with explanations → feedback log. One candidate, one
  market, three languages. Engine/data separation and multi-candidate schema from commit
  one. Later phases extend the spine.
- **Scope**: New repo layout — `dimensions/`, `corpus/`, `profiles/<handle>/`, `connectors/`,
  `extract/`, `rank/`, plus arsenal workspaces per subsystem.
- **Effort**: Medium-Large
- **Tradeoffs**: Slower to first output than A, and the corpus is real unglamorous labour
  before anything runs. In exchange every gate is mechanical from the start, the vocabulary
  cannot fragment, and multi-candidate and private-data separation cost nothing later
  because they were never wrong. Risk: the dimension model is designed once with imperfect
  information — mitigated by keeping v0 small (~20-25 dimensions) and treating the ontology
  hit-rate as a live signal that it needs extending.
- **Compatibility**: Greenfield. Can still borrow `ai-job-search`'s portal-CLI contract and
  PDF/ATS verification approach in Phase 7 rather than reinventing them.

### Option C: Full integral system, specced and built in dependency order (Thorough)

- **Description**: Spec all eight phases now, seed the whole DAG into the arsenal queue, and
  build in dependency order with parallel workers.
- **Scope**: Everything in the table above.
- **Effort**: Very Large
- **Tradeoffs**: The only option that delivers the complete vision as described, and the
  arsenal queue is genuinely built for this shape of work. But every phase past 5 depends on
  decisions best made with data from phases 1–5 — how good extraction actually gets, what
  the candidate's feedback reveals, what outcome data looks like in practice. Speccing them
  now means speccing them wrong. Highest risk of producing eight half-finished subsystems
  and no working tool.
- **Compatibility**: n/a

### Comparison

| | Option A | Option B | Option C |
|---|---|---|---|
| Effort | Small | Medium-Large | Very Large |
| Risk | Low build risk, high *design* risk — bakes in the vocabulary fragmentation | Medium | High — most likely to stall |
| Completeness | Partial; soft dimensions bolted onto a hard-skill spine | Spine complete, phases deferred | Full |
| Compatibility | Fork drift, per-candidate repos | Greenfield, multi-candidate native | Greenfield |
| Maintenance | Perpetual upstream merge cost | Single vocabulary; one place to extend | Large surface, thin coverage |
| Time to first real output | Days | 2-3 weeks | Months |

## 4. Recommendation

**Recommended option**: **Option B** — dimension-model-first thin vertical.
**Decided**: Option B, confirmed by the repository owner in spec review on 2026-08-15
(`status/reviews/spec-notes-2026-08-15.md`).

Option A is tempting for speed and would produce tailored CVs this week, but it cannot
express the thing that makes this project worth doing: one vocabulary carried end to end.
Bolting soft dimensions onto a tool whose profile is a single Markdown file, whose ranking
is a linear list, and whose tracker is a CSV means rebuilding within a month with the
awkward parts already load-bearing. Option C fails for the opposite reason — phases 6-8
depend on evidence that only phases 1-5 can produce.

Option B's real cost is the labelled corpus: ~100 ads annotated by hand before the first
quantitative gate can run. That is the pacing item and it should be started immediately and
in parallel, because everything measurable waits on it.

**Immediate next action**: run `design` on this specification to produce a `plan.md` per
subsystem under `claude-arsenal/project/`, each with a task DAG and a mechanical gate per
task. Proposed workspaces: `ONTOLOGY` (dimension model + corpus), `PROFILE` (adaptive
profiler + store + feedback log), `SUPPLY` (connectors, normalize, dedup), `MATCH`
(extraction funnel, ranking, explanations). `ONTOLOGY` blocks the other three.

`PROFILE` owns the elicitation engine, not a "profiler" — the same engine is later pointed at
a single job (pre-draft gap-fill) and at a scheduled interview (rehearsal). Building those as
separate subsystems would triplicate the hardest component in the project; building one and
reusing it is why Phases 7-8 are thin rather than large.

First implementation task under `ONTOLOGY`: dimension model v0 — 20-25 dimensions covering
hard skills, working environment, social intensity, autonomy, meeting load, remote
authenticity, schedule/caregiving compatibility, stability-vs-growth, learning demand, and
compensation — each with ID, definition, elicitation question, per-language cues (ES/EN/CA),
and hard-vs-soft classification.

**Candidate zero** (drives v1 dimension coverage): unemployed, seeking remote programming
roles, no current schedule constraints, ES/EN/CA. Second candidate (partner) is a schema
requirement in v1, not a v1 feature.

**Open questions**:
- [x] **Research, blocking `ONTOLOGY`** — done 2026-08-15, written up in `docs/METHODS.md`.
      Headline: person–environment fit predicts satisfaction, commitment and staying
      (ρ ≈ .35–.51) but predicts performance only weakly, which sets the tool's objective;
      structured behavioural elicitation is the instrument to borrow, not its validity
      coefficient; discrete-choice trade-offs yield salary-equivalent weights, which is what
      makes explanations arguable; the ranked output is an automated realistic job preview,
      the mechanism with the best turnover evidence behind it. Type indicators are excluded
      with reasons. **The ATS/LLM-screening entry is the weak one** — commercial sources
      only, flagged for re-verification before Phase 7.
- [ ] **Corpus labelling protocol**: who labels, against what rubric, and how
      inter-annotator agreement is checked with a single annotator (proposal: label a 20-ad
      subset twice, ≥2 weeks apart, report self-agreement).
- [ ] **Adaptive interview stopping rule**: fixed question budget, uncertainty threshold, or
      candidate-controlled. Affects whether profiling feels like a conversation or an
      interrogation.
- [ ] **Story-bank saturation threshold**: how much coverage counts as "enough" before the
      pre-draft gap-fill asks nothing. Sets per-application effort, and therefore whether the
      tool is usable at twenty applications or only at three.
- [ ] **Source connector for v1**: which single portal. Needs a market with real ES/CA
      remote programming volume and tolerable access rules.
- [ ] **Weight elicitation placement**: reaction elicitation largely answers this — the
      candidate compares real ads rather than synthetic attribute bundles. Remaining
      question is whether any synthetic pairwise trade-offs are still needed to separate
      dimensions that real ads happen to correlate (e.g. salary and on-site, which co-vary
      in the market and so are hard to disentangle from reactions alone).
- [ ] **Reaction stimulus design**: whole ads, or excerpt blocks (perks / requirements /
      how the ask is phrased) shown side by side? Excerpts isolate a dimension but strip
      the context that makes a reaction honest. Probably both, at different stages.
- [ ] **Confirm**: applications are drafted and require explicit per-item approval; the
      system never submits autonomously. Specced this way pending confirmation.

---

> Sections 5–6 (contracts, risks) are appended by `design`.

## 5. Contracts

No HTTP surface: this is a local, single-machine tool. The contracts that matter are the
**file schemas** each component reads and writes, because those are what let subsystems be
built independently and what the vocabulary-coherence argument rests on.

All committed data files are UTF-8. Line-oriented stores are JSONL so appends are atomic and
diffs are readable.

### 5.1 Dimension model — `dimensions/*.yaml` (the spine)

One file per dimension. This is the contract every other component depends on; changing a
`id` is a breaking change across the whole system.

```yaml
id: social_intensity              # stable, snake_case, never reused after removal
kind: soft                        # soft (preference, weighted) | hard (filter, vetoes)
polarity: bipolar                 # bipolar (-1..1) | unipolar (0..1)
label:
  en: Social intensity
  es: Intensidad social
  ca: Intensitat social
definition: >
  How much of the working week is spent in unstructured group interaction —
  open-plan presence, socials, offsites — as opposed to solitary focused work.
elicitation:
  questions:                      # behavioural, not self-rating (METHODS §2.1)
    - id: si_q1
      text:
        en: Tell me about a working week you enjoyed. Who did you talk to, and how often?
        es: ...
        ca: ...
  reaction_probes:                # stimulus selectors for METHODS §2.4
    - excerpt_kind: perks
extraction:
  cues:
    en:
      - pattern: "(team\\s+)?offsites?"
        value: 0.6
        negatable: true           # "no offsites" flips sign, does not merely drop
    es:
      - pattern: "jornadas\\s+de\\s+equipo"
        value: 0.6
        negatable: true
methods_ref: METHODS.md#21-structured-behavioural-elicitation
```

`methods_ref` is **required** on every dimension and every computation site. It is what makes
the `undocumented_methods == 0` criterion mechanically checkable: walk every dimension file
and every scoring function, resolve each `methods_ref` anchor against `docs/METHODS.md`, and
fail on any that does not resolve. Documentation enforced by a link check, not by discipline.

### 5.2 Normalised offer — `offers/*.json`

Every connector emits this shape regardless of source. Connectors may not invent fields.

```json
{
  "id": "sha256:9f2c…",
  "source": "infojobs",
  "source_ref": "1234567",
  "url": "https://…",
  "fetched_at": "2026-08-15T14:00:00Z",
  "title": "Backend Engineer (Python)",
  "company": "Acme SL",
  "location": { "raw": "Barcelona", "country": "ES", "remote": "hybrid" },
  "salary": { "min": 45000, "max": 55000, "currency": "EUR", "period": "year", "stated": true },
  "language": "es",
  "text": "…verbatim full posting text, never a summary…",
  "expires_at": null,
  "duplicate_of": null
}
```

`text` is verbatim because extraction evidence spans are offsets into it, and a summary would
invalidate every span. `salary.stated` distinguishes absent from zero — a distinction the
whole "best salary" facet depends on in markets where ads routinely omit pay.

### 5.3 Extraction output — `extractions/<offer_id>.json`

```json
{
  "offer_id": "sha256:9f2c…",
  "extractor_version": "0.1.0",
  "dimension_scores": [
    {
      "dimension": "social_intensity",
      "value": 0.6,
      "confidence": 0.82,
      "evidence": [
        { "span": "team offsites every quarter", "start": 412, "end": 439, "negated": false }
      ]
    }
  ],
  "unmapped_concepts": ["4-day week", "equity refresh"]
}
```

`unmapped_concepts` is not diagnostic output — it is the numerator of `ontology_hit_rate`, and
therefore the staleness signal. An extractor that silently discards what it cannot classify
destroys the project's only automatic warning that the market has moved.

Every score carries `evidence`. A score with an empty evidence list is invalid, not weak: it
is the shape an unexplainable rank would take, and the schema forbids it.

### 5.4 Profile store — `profiles/<handle>/`

| File | Kind | Rule |
|---|---|---|
| `evidence.jsonl` | **Source of truth**, append-only | Every answer, reaction, and feedback event. Never edited, never reordered |
| `stories.jsonl` | Derived | Episodes with `disclosure: private \| approved_for:<offer_id>` |
| `profile.json` | Derived | Dimension values with uncertainty |
| `weights.json` | Derived | Part-worth utilities, salary-equivalent scale |

The derived files are regenerable: `rebuild` reads `evidence.jsonl` and reproduces all three
**byte-identically**. That is the mechanical form of "the profile is a derived view, never
mutated in place" — and it is what makes "why does it believe this about me?" answerable, by
pointing at the evidence rows that produced a value.

`disclosure` defaults to `private`. Promotion to `approved_for` requires an explicit
per-offer act by the candidate and is itself recorded in `evidence.jsonl`.

### 5.5 Ranking output — `rankings/<run_id>.json`

```json
{
  "run_id": "2026-08-15T14:00:00Z",
  "profile_rev": "sha256:ab12…",
  "pareto": ["sha256:9f2c…", "sha256:1d5e…"],
  "dominated": { "sha256:77aa…": "dominated_by:sha256:9f2c…" },
  "facets": {
    "best_salary_equivalent": ["sha256:9f2c…"],
    "quiet_environment": ["sha256:1d5e…"]
  },
  "explanations": {
    "sha256:9f2c…": {
      "salary_equivalent_delta_eur_month": 450,
      "drivers": [
        { "dimension": "social_intensity", "contribution_eur_month": 210,
          "evidence_span": "team offsites every quarter" }
      ]
    }
  }
}
```

`profile_rev` pins which profile revision produced the ranking, so a ranking can be
reproduced or invalidated when the profile changes.

### 5.6 Configuration

| Variable | Default | Purpose |
|---|---|---|
| `JOBSEARCH_PROFILE` | — | Active candidate handle. Required; no default, so a second candidate can never be written by accident |
| `JOBSEARCH_LLM_MODEL` | `claude-sonnet-5` | Extraction/elicitation model |
| `JOBSEARCH_EXTRACT_CONFIDENCE_FLOOR` | `0.35` | Evidence below this is dropped, not down-weighted |
| `JOBSEARCH_DATA_DIR` | `./data` | Root for offers, extractions, rankings |

### 5.7 Migrations

| Store | Change | Reversible | Forward-compatible |
|---|---|---|---|
| `evidence.jsonl` | Append-only; new event types added as new `kind` values | Yes (truncate) | Yes — unknown `kind` is skipped by older readers |
| `dimensions/*.yaml` | Add file = additive. **Renaming an `id` is breaking** | No | No — requires an explicit id-migration map |
| Derived files | Regenerated wholesale by `rebuild` | n/a | n/a |

## 6. Risks & Validation

| Risk | Likelihood | Impact | Mitigation | Validation |
|------|-----------|--------|------------|------------|
| Corpus labelling stalls; every numeric gate blocks behind it | **High** | **High** | Start at T4/T5 in parallel with everything else; 100 ads is the floor, not the target. Label in sittings of 20. If it stalls, the honest response is to re-open the Option A/B decision, not to lower the gate | `corpus_size >= 100` before any extraction gate is trusted |
| Dimension model v0 is wrong — designed before seeing enough ads | High | Medium | Keep v0 small (20-25). `ontology_hit_rate` makes the wrongness visible rather than silent. Adding a dimension is additive and cheap; renaming is breaking and must be rare | `ontology_hit_rate >= 0.85`; review unmapped concepts each run |
| Extraction accuracy too low for ranking to mean anything | Medium | **High** | Funnel with a confidence floor; unknown ≠ neutral; negation handled explicitly since it inverts meaning on exactly the dimensions we care about | `extraction_macro_f1 >= 0.75`, `extraction_negation_recall >= 0.80` |
| Ranking gate passes by memorisation (elicitation ads reused for evaluation) | Medium | **High** | Disjoint split enforced as a gate, not a convention | `elicitation_eval_overlap == 0` |
| Wording features drift into astrology | Medium | Medium | No wording feature affects a rank until calibrated against the corpus; METHODS §2.6 states the evidence covers perception, not workplace reality | Per-feature corpus calibration before enabling |
| LLM extraction cost makes daily runs unaffordable | Medium | Medium | Lexical prefilter before LLM; extraction cached per `offer_id` + `extractor_version`; re-extraction only on version bump | Cost-per-run recorded in the evidence log |
| Portal blocks the connector or its ToS forbids access | Medium | Medium | One connector in v1 plus a manual-paste path that is always available. Low volume, robots.txt respected. Connector failure degrades to manual, never to a broken pipeline | Manual-paste path covered by tests independently of any live portal |
| **Cloud agent sessions cannot reach job boards at all** — confirmed 2026-08-15: the session egress policy returns 403 for `remoteok.com`, `weworkremotely.com`, `freehire.me`, `tecnoempleo.com`, `remotolist.com`. Ad collection and live-connector work are physically impossible from a cloud worker | **Certain** (observed) | Medium | Tag every task needing job-board egress `laptop` so a cloud worker never claims it (T4b, T12). Everything else in v1 — schema, model, harness, profile store, ranking — needs no egress and is unaffected. The manual-paste connector exists partly for this | Attempt from a cloud session returns 403 at the proxy; run these tasks on the laptop |
| **Synthetic ads used to unblock the corpus** | Medium | **Critical** | Every numeric gate is measured against the corpus, so a corpus of invented ads makes `extraction_macro_f1`, `rank_spearman` and `ontology_hit_rate` all pass while measuring nothing. Ads must be real, verbatim, and carry their source URL. If collection is blocked, the corpus waits — it is never filled in | Each corpus entry carries a resolvable `source_url` and fetch timestamp; entries without one are refused at load |
| Profile drifts incoherent as feedback accumulates | Medium | Medium | `evidence.jsonl` append-only; all derived state regenerable byte-identically; every value traceable to the rows that produced it | `profile_rebuild_deterministic == 1` |
| Sensitive personal data leaks into a commit or an employer's inbox | Low | **High** | `profiles/` gitignored by default; `disclosure` defaults to private; per-use approval required and itself logged | Inspection audit; secret-scan over `profiles/` in the queue doctor |
| Second candidate (partner) retrofit turns out expensive | Low | Medium | `profiles/<handle>/` from commit one; `JOBSEARCH_PROFILE` required with no default | Two-profile fixture exercised in tests from T6 onward |
