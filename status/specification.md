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
- [ ] **Profile recognisability** (non-numeric): given their own generated profile plus two
      perturbed variants, unlabelled, the candidate identifies their own. Judged by a single
      blind trial per candidate; failure means the profiler is producing generic output.
- [ ] **No autonomous outward action** (non-numeric): audited by inspection — no code path
      submits an application, sends an email, or contacts an employer without explicit
      per-item human approval.

## 2. Systems & Impact

Greenfield: nearly everything is new. "Needs changes" therefore reads as "in v1 scope".

| System | Type | Role | Needs changes? | Impact | Severity |
|--------|------|------|----------------|--------|----------|
| `dimensions/` — dimension model | Primary | The spine. Per dimension: ID, definition, elicitation question(s), extraction cues per language, hard-filter vs soft-preference, polarity | Yes (v1) | Every other component is a projection of this. Changing a dimension ID is a breaking change everywhere | High |
| `corpus/` — labelled ad corpus | Shared resource | Ground truth for every extraction and ranking gate | Yes (v1) | Without it no quantitative gate can run. Pacing item for the whole project | High |
| Profiler (adaptive interview) | Primary | Generates questions from the dimension model, accepts free text, extracts dimension values with uncertainty | Yes (v1) | Candidate-facing; poor questions produce a generic profile and everything downstream degrades | High |
| Profile store | Primary / shared | Per-candidate profile as a **derived view** over an append-only evidence log | Yes (v1) | Holds sensitive psychological and personal data. Schema must be multi-user from day one | High |
| Feedback log | Primary | Append-only record of "I don't like this because…" and every other preference signal | Yes (v1) | Source of truth for profile evolution; enables recompute and audit | High |
| Source connectors | Primary | Per-portal fetch → normalised offer schema. One connector in v1, plus manual-paste | Yes (v1) | ToS and anti-bot exposure lives here and nowhere else | Medium |
| Normalizer + dedup | Primary | Cross-source identity resolution, expiry detection | Yes (v1) | Duplicates poison every ranked list | Medium |
| Extractor (funnel) | Primary | Cheap lexical prefilter → LLM structured extraction on survivors, with evidence spans | Yes (v1) | Dominant recurring cost; accuracy sets the ceiling for ranking | High |
| Enrichment | Primary | Signals not in the ad: employer site, review sites, writing-style features of the ad itself | Partial (v1: writing-style only) | Where the project is genuinely differentiated; also where it can drift into astrology without corpus calibration | Medium |
| Ranker | Primary | Pareto frontier over dimensions + named facet lists; forced-pairwise-derived weights | Yes (v1) | The user-visible product | High |
| Explanation layer | Primary | Per-offer justification citing evidence spans | Yes (v1) | Non-negotiable: an unexplained rank is unusable and unfalsifiable | High |
| Application generator (CV/letter) | Dependent | Tailored documents driven by the same dimensions | No (Phase 7) | Deferred | — |
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

First implementation task under `ONTOLOGY`: dimension model v0 — 20-25 dimensions covering
hard skills, working environment, social intensity, autonomy, meeting load, remote
authenticity, schedule/caregiving compatibility, stability-vs-growth, learning demand, and
compensation — each with ID, definition, elicitation question, per-language cues (ES/EN/CA),
and hard-vs-soft classification.

**Candidate zero** (drives v1 dimension coverage): unemployed, seeking remote programming
roles, no current schedule constraints, ES/EN/CA. Second candidate (partner) is a schema
requirement in v1, not a v1 feature.

**Open questions**:
- [ ] **Research, blocking `ONTOLOGY`**: which elicitation techniques have real validity
      evidence for work-environment preference (behavioural/indirect questioning, forced
      pairwise trade-offs) — and what recruiters and ATS tooling actually reward in CVs in
      2026. The second must be sourced, not recalled; it moves fast and stale advice here is
      actively harmful. Feeds backwards into the dimension model.
- [ ] **Corpus labelling protocol**: who labels, against what rubric, and how
      inter-annotator agreement is checked with a single annotator (proposal: label a 20-ad
      subset twice, ≥2 weeks apart, report self-agreement).
- [ ] **Adaptive interview stopping rule**: fixed question budget, uncertainty threshold, or
      candidate-controlled. Affects whether profiling feels like a conversation or an
      interrogation.
- [ ] **Source connector for v1**: which single portal. Needs a market with real ES/CA
      remote programming volume and tolerable access rules.
- [ ] **Weight elicitation placement**: forced pairwise trade-offs inside the initial
      interview, or deferred until the candidate has seen real offers to compare?
- [ ] **Confirm**: applications are drafted and require explicit per-item approval; the
      system never submits autonomously. Specced this way pending confirmation.

---

> Sections 5–6 (contracts, risks) are appended by `design`.
