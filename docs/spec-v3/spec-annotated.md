# Silent success — borrowed hardening — Specification (annotated edition)

> Generated 2026-08-25. This is the document with a **note slot** after every section. Read it in any Markdown app. To annotate, replace the `_(your notes…)_` placeholder under any section. When done, send the file back — notes are acted on.

---

# Spec V3 Silent Success

## Preamble & scope

> `specify` owns sections 1–4. `design` appends 5–6.
> A peer of `status/specification.md`, not a replacement: that document specifies the
> product, this one specifies a hardening increment against a failure class the
> divergence register has now named three times. Where the two touch — the Systems
> table, the phase boundaries — this document defers to it and says so.

**Date**: 2026-08-25
**Ticket / PR**: —
**Author**: nuncaeslupus (with Claude)

> **✎ Notes** · `SPEC · intro`
> _(your notes here — replace this line)_

## §1 Problem statement

This repository has a recurring failure mode, and the divergence register has now named it
three times without naming the *class*: **D-18** (seven adverts passed `offer_schema_violations`
and every one was dead — "schema validity is not liveness"), **D-19** (`extract()` settled 0 of
25 dimensions on seven construction adverts and step 8 reported success), and **D-21**
(`run_checkpoint.py` exited 0 for steps whose gate was `not_implemented`). In each case a layer
**reported success over work it did not actually perform**, the gate above it agreed, and the
defect was found by a human running the tool rather than by any check. The remaining instances
are concentrated in exactly the layers that touch the world outside this repository, and the
first live candidate session is imminent:

- `robots.py` delegates matching to `urllib.robotparser`, which **fails open** on a blank line
  inside a record — so `meta.yaml`'s `robots_txt: respected` is an assertion the code cannot
  currently support (measured, below).
- No check exists that a connector still *works*. `connector_coverage.py` asks whether a
  connector exists for a market; `liveness.py` asks whether one offer is alive. A restyled
  portal returns zero rows and is indistinguishable from a market with no vacancies.
- `liveness.read_response` compares `advert_url` to `final_url` (`liveness.py:120,148`) — URL
  identity, not page identity. A fragment-anchor URL fetches 200, renders an unrelated listing
  page, and is read as the advert.
- `dedup.py` picks a survivor among duplicates with no preference for the employer's own
  posting, and aggregators routinely strip the grade — the input to `seniority_expectation`.
- Nothing can refuse to rank an offer the candidate is **barred from taking**. Every hard
  constraint we hold (`stated_constraints.py`, `constraints_step.py`) filters on what the
  candidate declared; none filters on what the advert *demands* — work permit, citizenship,
  clearance, or a language level the candidate does not hold.
- The one artefact that reaches a stranger — the generated CV — is never checked for the
  literal text an applicant-tracking system must find in it.
- `applications/{offer_id}/` has no status vocabulary, so what happened to an application is
  not a thing the tool can state.
- **The evidence gate does not run three of its own checks.** `make evidence` builds its module
  list with `grep -l '^def _main' src/integral/*.py` — 74 modules. `plan_v2.py`,
  `process_spec.py` and `step_specs.py` define `main`, not `_main`, so they are never
  regenerated and never drift-checked. Measured 2026-08-25: committed
  `status/evidence/S8.json` reads `plan_rows: 81` while the module measures **107**, and
  `make evidence` still exits 0 printing "no drift". `plan_v2` is the check that catches a plan
  row with no queue task — the guard against exactly the bookkeeping error this increment's own
  fifteen-task seeding could make. Found while validating this specification, which makes it the
  cleanest instance of the class: the gate reported success over a check it never ran.

Most of the remedies below are adapted from **[`MadsLorentzen/ai-job-search`](https://github.com/MadsLorentzen/ai-job-search)** (MIT, © 2026 Mads Lorentzen),
whose matching layer we assessed and rejected in `status/specification.md` §3 Option A and still
reject — it scores on an unvalidated 30/25/15/30 rubric with no evidence spans, no confidence and
no corpus. Its *failure-handling* layer is the opposite: five weeks of one person hitting real
portals and writing down what broke. **This specification takes that layer and none of the
scoring layer.** Attribution is a deliverable, not a courtesy — see the success criteria.

**Success criteria (measurable)** — each seeds a task Gate in the plan:

- [ ] `robots_verdicts_misread == 0` — over a fixture table of `robots.txt` documents paired
      with their RFC 9309 verdict per (agent, path), every verdict matches. The table must
      include a blank line inside a record and an `Allow`/`Disallow` longest-match conflict,
      the two cases measured as failing today.
- [ ] `silent_connector_failures == 0` — a connector whose selectors no longer match its own
      recorded fixture is reported `broken` or `inconclusive`, never as a successful run that
      found nothing.
- [ ] `rate_limited_runs_reported_as_broken == 0` — a 429 or block page yields
      `inconclusive (rate-limited)`, never `broken`. (The converse of the line above; both
      directions must hold or the check becomes noise and gets ignored.)
- [ ] `offers_presented_from_a_page_that_is_not_the_advert == 0`
- [ ] `duplicate_groups_resolved_away_from_the_canonical_source == 0`
- [ ] `offers_ranked_despite_a_stated_disqualification == 0` — measured over hand-built
      fixtures, not the corpus. See §4 open question 1 and the D-12 precedent for why the
      accuracy half is a separate, blocked task.
- [ ] `disqualification_verdicts_without_quoted_wording == 0` — a refusal to rank always
      carries the advert's own sentence. A veto with no quote is unfalsifiable, which is the
      same objection §"Explanation layer" makes to an unexplained rank.
- [ ] `documents_missing_a_required_text_layer_field == 0` — every generated CV carries
      contact e-mail, telephone and every employment date as **literal text**, renderer-independent.
- [ ] `posting_keywords_left_unclassified == 0` — every keyword drawn from the posting is
      reported as exactly one of `covered` / `synonym-only` / `missing (have it)` /
      `missing (gap)`.
- [ ] `applications_with_a_noncanonical_status == 0`
- [ ] `gate_modules_outside_the_evidence_run == 0` — every module that writes gate evidence is
      reached by `make evidence`. Selection must not depend on a private-name convention that a
      module can silently fail to follow.
- [ ] `borrowed_techniques_without_attribution == 0` — every technique adopted here has an
      entry in `docs/METHODS.md` naming its source, and `README.md` carries an
      Acknowledgements section. METHODS already exists to record where a method came from and
      what its limits are; this is that register doing its job.

**Explicitly not a success criterion.** No metric here asserts that the eligibility or language
gate is *accurate on real adverts* — that needs corpus labels this repository does not yet hold,
and asserting it would be the same false success this document exists to remove.

> **✎ Notes** · `SPEC §1`
> _(your notes here — replace this line)_

## §2 Systems & Impact

Phases and the product-level system list are `status/specification.md`'s; this table covers only
what this increment touches.

| System | Type | Role | Needs changes? | Impact | Severity |
|--------|------|------|----------------|--------|----------|
| `src/integral/robots.py` | Primary | Decides whether a source may be read at all | **Yes** | Fails open today on a record containing a blank line, so a board that has disallowed us reads as permitted. `connectors/*/meta.yaml` asserts `robots_txt: respected` on top of it — the assertion is currently unbacked, and it ships to contributors | **High** |
| `connectors/*/connector.yaml` + a new health check | Primary | Declarative CSS-selector fetch per board | **Yes** (new module) | Scrapers rot silently; one real board (`trabajos_es`) means one restyle takes sourcing to zero with no signal. Fixtures to compare against already exist | **High** |
| `src/integral/liveness.py` | Primary | The three-verdict live/dead/unverified check | **Yes** | Verifies URL identity, not page identity. Extends a module that already has the right shape — a fourth reason for `unverified`, not a new concept | Medium |
| `src/integral/dedup.py` | Primary | Cross-source identity resolution | **Yes** | Survivor selection gains a source-rank preference. Silently costs a scored dimension today when the aggregator copy wins | Medium |
| Eligibility + language gate (new) | Primary | Refuses to rank an advert the candidate is barred from | **Yes** (new module) | Runs **before** the Pareto frontier as a hard filter. Highest candidate-visible value in this document: it is what stops a well-ranked list being useless in the first reply | **High** |
| `src/integral/rank.py` | Dependent | Frontier + salary-equivalent order | **Yes** (small) | Gains an Excluded section carrying the quoted wording. Frontier maths untouched | Medium |
| `dimensions/english_demand.yaml` | Shared resource | The language dimension | Validation only | The language *gate* is a hard filter and must not be confused with the soft dimension. Boundary stated, not merged | Low |
| `src/integral/cv_store.py` + step 11 outputs | Primary | Generated CV and letter | **Yes** | Gains a text-layer contract. **No renderer is added** — see §3 | Medium |
| ATS text-layer check (new) | Primary | Machine-readability of the generated document | **Yes** (new module) | Asserts a contract over the document text so a future PDF renderer inherits it via `pdftotext` | Medium |
| Application status vocabulary (new) | Primary | What happened to an application | **Yes** (small) | `applications/{offer_id}/` gains a canonical status set. Unblocks Phase 7 without building it | Low |
| `.claude/skills/step-07-sourcing`, `step-09-ranking`, `step-11-application` | Dependent | The candidate-facing protocols | **Yes** (prose) | Must state the new refusals and disclosures, or the code refuses and the conversation does not explain | Medium |
| `docs/METHODS.md`, `README.md` | Shared resource | Method register and attribution | **Yes** | Where the borrowing is recorded. A gate, not an afterthought | Low |
| `Makefile` (`evidence` target) + `plan_v2.py`, `process_spec.py`, `step_specs.py` | **Infrastructure** | Selects which modules regenerate gate evidence | **Yes** | Selects on `^def _main`, so three modules that write evidence are never run or drift-checked — including the plan↔queue drift guard. Must be fixed **before** the increment's sixteen tasks are relied on, or the guard against mis-seeding them is off while they land | **High** |
| `status/plan.md` divergence register | Shared resource | D-16, D-17, D-18, D-19 | **Yes** (D-23) | Several rows here are the same family; this document must not restate a D-row as new work. Adds D-23 for the unmeasured gate accuracy | Low |
| `claude-arsenal` | Infrastructure | Queue, gates, workers | No | Consumed as-is | Low |
| Job portals | External | Supply | No | Politeness posture **tightens**, never loosens — see §3 non-goals | Medium |

**Impact of inaction**: the first live session runs against a robots checker that can say
"permitted" about a board that disallowed us, a connector that cannot report its own breakage,
and a ranked list that may lead with a job requiring a permit the candidate does not have. Each
is the D-18 experience again — a number passing while the thing it stands for is false — and
each is cheaper to fix now than to explain to a candidate.

> **✎ Notes** · `SPEC §2`
> _(your notes here — replace this line)_

## §3 Options



> **✎ Notes** · `SPEC §3`
> _(your notes here — replace this line)_

### Option A: Fix the three that are bugs (Conservative)

- **Description**: `robots.py` fail-open, `liveness` page identity, connector health check.
  Leave the eligibility gate, the ATS contract, dedup preference and the status vocabulary for
  after the first live session.
- **Scope**: `robots.py`, `liveness.py`, one new health-check module, their tests.
- **Effort**: Small
- **Tradeoffs**: Ships the safety-critical subset fastest and touches nothing candidate-facing,
  so it cannot destabilise a session that is days away. But it leaves the highest-value item —
  a list that never leads with an unobtainable job — on the shelf precisely when the first real
  candidate meets it, and the eligibility gate is the one thing here a candidate would actually
  notice. Also leaves the attribution undone, which is a promise already made.
- **Compatibility**: Fully backwards compatible; no stored-schema change.

> **✎ Notes** · `SPEC › Option A: Fix the three that are bugs (Conservative)`
> _(your notes here — replace this line)_

### Option B: The full borrowed set, mechanism separated from accuracy (Recommended)

- **Description**: Everything in A, plus the eligibility and language gates, the canonical-source
  dedup preference, the ATS text-layer contract with the four-status keyword table, the
  application status vocabulary, the two step-11 drafting rules (relevance-weighted cutting, the
  interview backtrack test), and the attribution. Every gate measures a **mechanism** over
  fixtures; no gate here asserts accuracy over the corpus.
- **Scope**: The §2 table in full — three new modules, four modified, three skill files, METHODS
  and README.
- **Effort**: Medium
- **Tradeoffs**: The split is what makes this affordable, and it is not a new idea here: D-12 set
  the precedent when T15 was divided into a mechanism half and a scoring half (T56/T57/T59) that
  waits behind the corpus. Applying it again means the eligibility gate can be *built, tested and
  shipped* tomorrow while "does it fire correctly on real Spanish adverts" stays an honest open
  question with a labelled-corpus dependency. Risk: a gate that is mechanically perfect and
  empirically unvalidated could be trusted more than it deserves — mitigated by the FLAG verdict
  (below) and by saying so in the step-9 protocol.
- **Compatibility**: Three additive fields — **two on the offer record**
  (`eligibility` and `language_requirement`, §5.1) and **one on the application record**
  (`status`, §5.2). All optional, none backfilled — absence stays legible as "not recorded
  then", per the never-backfill rule adopted here.

> **✎ Notes** · `SPEC › Option B: The full borrowed set, mechanism separated from accuracy (Recommended)`
> _(your notes here — replace this line)_

### Option C: Option B plus the accuracy gates and Phase 7 outcome tracking

- **Description**: B, plus labelling the corpus for eligibility and language requirements to gate
  the filters empirically, plus the application status machine wired to outcome-driven
  recalibration of `weights.py`, plus the read-only mail sensor.
- **Scope**: B, plus corpus labelling, `weights.py`, a mail connector.
- **Effort**: Large
- **Tradeoffs**: The only option that closes the feedback loop, and the loop is genuinely where
  the borrowed repository fails worst — it collects interview and rejection outcomes and computes
  *nothing* from them. That is our opening, and taking it would be a real differentiator. But it
  is blocked twice over: the corpus labelling needs the candidate personally (`surface:human`),
  and outcome calibration needs application *volume* that will not exist until the tool has been
  used for weeks. Speccing it now is `status/specification.md` §3 Option C's mistake repeated —
  committing to decisions that need evidence phases 1–5 have not yet produced.
- **Compatibility**: Same as B, plus a corpus schema change.

> **✎ Notes** · `SPEC › Option C: Option B plus the accuracy gates and Phase 7 outcome tracking`
> _(your notes here — replace this line)_

### Comparison

| | Option A | Option B | Option C |
|---|---|---|---|
| Effort | Small | Medium | Large |
| Risk | Low build risk; leaves the candidate-visible defect in place for the first session | Medium — mechanism gates could be over-trusted, mitigated by FLAG | High — two hard blockers, neither removable by working harder |
| Completeness | The three bugs only | Every borrowed idea that can be honestly gated now | Full, including the loop |
| Compatibility | No schema change | Two additive fields | Additive + corpus schema |
| Maintenance | Three modules | Three new, four modified — all fixture-tested | Adds a labelling burden and a mail integration |
| Autonomous-work fit | ~3 tasks | **16 tasks, mostly independent** | Blocks on a human within one task |

> **✎ Notes** · `SPEC › Comparison`
> _(your notes here — replace this line)_

## §4 Recommendation

**Recommended option**: **Option B** — the full borrowed set, mechanism separated from accuracy.

Option A is tempting because the first live session is close, but it optimises for the wrong
risk: the three bugs are invisible to the candidate, while the thing they *will* see is a
ranked list that leads with a job requiring a work permit they do not hold. Option B costs one
extra day and fixes both.

**Option C is deferred, not rejected — owner's decision, 2026-08-25 spec review.** Its two
blockers are timing, not merit: the accuracy gates need a corpus round, and outcome calibration
needs application volume that only use produces. Both dissolve on their own once the tool has
run. So C is recorded here as **the next increment**, and this document's job is to leave it
reachable: D-23 (below) holds the accuracy gap open, the application status vocabulary (§5.2)
is the schema C's outcome calibration reads, and nothing in Option B forecloses it. What would
have foreclosed it is dropping the status vocabulary as "Phase 7, not now" — which is why it is
in scope here despite Phase 7 being deferred.

The decisive structural point is that **Option B is almost entirely parallel and needs no human
input** — sixteen tasks against fixtures, in separate modules, with mechanical gates. That is the
right shape for the autonomous session this is being specced for.

**A note on the third verdict.** Three separate mechanisms in this document — the connector
health check (`ok`/`broken`/`inconclusive`), the liveness check (`live`/`dead`/`unverified`) and
the eligibility gate (`PASS`/`FLAG`/`FAIL`) — all refuse a binary. That is not a coincidence and
should be stated as a principle rather than rediscovered a fourth time: **wherever this tool
judges the outside world, "I could not tell" is a distinct answer from "no", and collapsing
them is how the D-18 family of defects is produced.** `unmeasured` in the gate layer is the same
shape one level up.

**Immediate next action**: run `design` over this document to append sections 5–6 and produce the
task split, then seed the queue. **The first task is T85** — the evidence run reaching every
module that writes evidence — because it is what makes `plan_v2`'s drift check live, and the
selector returns it first (Small, no dependencies). It is deliberately *not* a blocking
dependency of the other fifteen: `plan_v2` guards plan↔queue membership, which changes only
when the queue is seeded, and that seeding was verified by hand at seed time
(`plan_queue_task_drift: 0`, 124 rows ↔ 124 tasks). The other tasks do not reseed, so they are
correct whether or not T85 has landed — T85 is first because the guard should be live, not
because anything downstream is unsafe without it.

Second is the robots fixture table (T70): a failing test that can be written before any fix, the
only item measured as broken today, and what `meta.yaml`'s compliance assertion rests on.

**Open questions**:

- [x] **1. Where does the eligibility gate's accuracy get measured?** **Decided 2026-08-25 by the
      owner: a `D`-row, filed now, blocked on a corpus round — the current round does not grow.**
      The mechanism is gated over fixtures in this increment; the accuracy half is tracked as a
      named, unmeasured gap rather than silently absent. This is the D-12 precedent applied a
      second time (T15 split into a mechanism half and a scoring half that waits behind the
      corpus), and it is the reason nothing in this increment blocks on `surface:human`.
- [x] **2. Does the language gate read `english_demand`, or its own field?** **Decided 2026-08-25
      by the owner: its own hard field.** The offer record gains `language_requirement`, read only
      by the gate; `dimensions/english_demand.yaml` stays a soft, scored preference read only by
      the ranker. Two tests assert the boundary — `test_a_hard_gate_field_is_never_read_by_the_ranker`
      and `test_a_dimension_weight_cannot_change_a_gate_verdict` — because the failure being
      prevented is a preference weight cancelling a legal bar, which would be invisible in any
      output either layer produces.
- [x] **3. Is a PDF renderer in scope later, and which?** **Decided 2026-08-25 by the owner: yes,
      one is needed — deferred until a live session actually needs a CV or letter to leave the
      machine.** Not in this increment, and the "which" stays open. What exists today is
      generation, not rendering: T45 (merged) assembles a **Markdown** document from store
      entries with a claim manifest, and nothing turns it into a file an employer receives. That
      is precisely why the ATS contract here is asserted over the document *text* — the check is
      real against what exists now, and the same assertions run over `pdftotext` output the day a
      renderer lands. The borrowed repository's LaTeX pipeline (moderncv + a custom class +
      bundled fonts, two CI legs because versions break differently) remains explicitly **not**
      recommended — their own docs treat that fragility as a cost borne by every fork user.
- [x] **4. Can `drawspec` carry a 2-D scatter?** **Closed as not blocking, 2026-08-25: drawspec is
      the owner's own project, and the owner will add the kind if it is missing.** Still out of
      scope for this increment — a Pareto frontier view is a reporting nicety, and nothing in
      Option B depends on it. Recorded so the reasoning survives: a frontier is two-dimensional
      and prose cannot show it, this repository already renders declarative JSON → SVG through
      drawspec (`docs/diagrams/critical-path.json`), so the cost when it is wanted is a spec file
      rather than a chart library. The schema was not checkable from here (the working checkout is
      not on this machine and `drawspec.dev` does not resolve), and it does not need to be.

**Non-goals, stated so they cannot drift in.** The borrowed repository's scoring rubric, its
retry policy (six retries on a 429, no per-host budget, scrapers that never read `robots.txt`),
its LinkedIn `jobs-guest` access (acknowledged by its own README as against LinkedIn's terms),
its exact-match dedup, and its unbounded read-whole state file. Our politeness posture only
tightens: `connectors/trabajos_es/connector.yaml` records boards already ruled out on
`robots.txt` grounds, and nothing in this increment may reverse one of those decisions.


> Sections 5–6 (contracts, risks) are appended by `design`.

> **✎ Notes** · `SPEC §4`
> _(your notes here — replace this line)_

## §5 Contracts

This increment adds no HTTP surface and no service boundary — the tool is a conversation over
local files. "Contract" here means the four things a later change could break silently: two
stored-record fields, one module boundary the owner ruled on, and the verdict vocabularies.

> **✎ Notes** · `SPEC §5`
> _(your notes here — replace this line)_

### §5.1 Stored record — offer (offers/*.json), additive

Two fields, both **optional and never backfilled**. Absence stays legible as "not recorded
then", which is the rule adopted from the borrowed repository and the reason no migration is
needed:

```json
{
  "id": "off-000123",
  "source": "trabajos",
  "url": "https://www.trabajos.com/ofertas/...",

  "language_requirement": {
    "language": "de",
    "level_stated": "fluent",
    "quote": "Verhandlungssicheres Deutsch ist Voraussetzung",
    "applies_to": "role"
  },

  "eligibility": {
    "verdict": "FAIL",
    "reason": "citizenship",
    "quote": "Applicants must hold EU citizenship at the time of application"
  }
}
```

- `applies_to` is `"role"` or `"company"`. It exists because a company-wide "we welcome
  international applicants" is **not** role-level permission, and collapsing the two is the
  named failure this field prevents.
- `quote` is a verbatim span of the advert text, on the same terms as `Candidate.spans`
  (`enrichment.py`): **nothing sourced outside the advert may appear here.** A verdict whose
  quote is not found in the advert text is a schema violation, not a warning.
- Neither field is read by the ranker. See §5.3.

> **✎ Notes** · `SPEC §5.1`
> _(your notes here — replace this line)_

### §5.2 Stored record — application (applications/{offer_id}/), additive

```json
{ "status": "applied", "recorded_at": "2026-08-25T19:20:00Z" }
```

Canonical vocabulary, underscored, adopted verbatim from the borrowed repository because a
vocabulary's value is entirely in being fixed:

| Status | Class |
|---|---|
| `drafted`, `applied`, `interview` | Open |
| `offer` | Open |
| `hired`, `rejected`, `no_response`, `offer_declined`, `withdrawn` | Final |

Legacy space-spellings (`no response`) are **accepted on read, never written** — the migration
strategy is tolerance at the boundary, not a rewrite of stored records.

> **✎ Notes** · `SPEC §5.2`
> _(your notes here — replace this line)_

### §5.3 Module boundary — hard gate vs soft dimension

Settled by the owner, 2026-08-25 (§4 open question 2), and asserted by tests rather than
convention:

| Reads | May read | Must never read |
|---|---|---|
| Eligibility/language gate | `offer.eligibility`, `offer.language_requirement` | `weights.json`, any `dimensions/*` score |
| Ranker (`rank.py`, `scoring.py`) | `dimensions/*` scores, `weights.json` | `offer.eligibility`, `offer.language_requirement` |

The failure being prevented — a preference weight cancelling a legal bar — would be invisible in
any output either layer produces, which is why it is pinned by a test and not by a comment.

> **✎ Notes** · `SPEC §5.3`
> _(your notes here — replace this line)_

### §5.4 Verdict vocabularies — three-valued, all of them

| Mechanism | Verdicts | "I could not tell" |
|---|---|---|
| Connector health (new) | `ok` / `broken` / `inconclusive` | `inconclusive` — a 429 or block page, **never** `broken` |
| Liveness (`liveness.py`, extended) | `live` / `dead` / `unverified` | `unverified` — now also when the page fetched is not the advert |
| Eligibility + language gate (new) | `PASS` / `FLAG` / `FAIL` | `FLAG` — ranked, marked, and the human is the tiebreaker |

`FLAG` is load-bearing: it is what makes an empirically unvalidated gate safe to ship. A gate
that can only pass or fail must be right; a gate that can hesitate may be approximately right
and still not cost the candidate an opportunity.

> **✎ Notes** · `SPEC §5.4`
> _(your notes here — replace this line)_

### §5.5 Configuration

None. No new environment variable, no feature flag, no dependency. The ATS check shells out to
`pdftotext` **only if a PDF exists**, and no code path in this increment creates one.

> **✎ Notes** · `SPEC §5.5`
> _(your notes here — replace this line)_

## §6 Risks & Validation

| Risk | Likelihood | Impact | Mitigation | Validation |
|------|-----------|--------|------------|------------|
| The eligibility gate excludes an offer the candidate could actually have taken — a false FAIL is invisible, because an excluded job is one they never see | **High** | **High** | `FLAG` is the default for anything short of an explicit, role-level, stated bar; "silence is not permission" governs what counts as stated, and every verdict carries the quote so the exclusion is auditable. The Excluded list is **shown**, never silently dropped — the same rule as D-18's withheld count | unit (`tests/test_eligibility.py`), and manual review of the excluded list in the first live session |
| The mechanism gates get mistaken for accuracy gates — "it passes" read as "it works on real adverts" | **High** | Medium | D-23 files the unmeasured accuracy explicitly; the step-9 protocol states the limit aloud to the candidate; no gate in this increment is named in a way that implies corpus validation | `tests/test_task_gate.py`, and the D-23 row itself |
| Rewriting robots matching introduces a *stricter* error, so we stop reading a board we are allowed to read | Medium | Medium | The fixture table asserts both directions — permitted paths resolve permitted, disallowed resolve disallowed. Failing closed is the safe direction and is accepted where ambiguous | unit (`tests/test_robots.py`) |
| The browser-UA robots fetch reads as evasion | Low | **High** | Scope is exactly one resource: `/robots.txt`, never content. The policy is then **obeyed more strictly**, not less. Recorded in METHODS with the reasoning, so the intent survives the author | unit, plus the METHODS entry required by T83 |
| The connector health check fires on a genuinely empty market and a board gets disabled | Medium | Medium | Zero yield is a signal only for a portal that **has produced offers before**; the sentinel probe uses the connector's own recorded example query; disabling always asks first and touches one connector | unit (`tests/test_connector_health.py`) |
| Two gate fields on the offer record drift into the dimension model over time | Medium | **High** | §5.3's boundary is a test, not a convention, and it fails in both directions | unit (`tests/test_eligibility.py`) |
| The ATS contract passes trivially because no renderer exists, so it certifies nothing | Medium | Medium | The contract is asserted over the **document text**, which does exist today; the same assertions run over `pdftotext` output when a renderer lands. This is the D-21 shape — presence standing in for a check — and is called out so it cannot recur quietly | unit (`tests/test_ats.py`) |
| 16 tasks land in one autonomous session and a late one silently contradicts an early one | Medium | Medium | `make host-gate` runs on every task PR as a hard precondition (D-22). The second guard — `plan_v2`'s plan↔queue drift check — **is inert today** and is why the `_main` fix is sequenced first in this increment rather than filed as a separate bug: the mitigation must be true before the rest of the increment relies on it | `make host-gate` per PR, and `S8.json` regenerating once the evidence run reaches `plan_v2` |
| **Every gate here counts violations, so an empty input set scores zero and passes** — the gate certifies that nothing was processed | **High** | **High** | Each evidence record carries a `<metric>_evaluated` denominator and each task asserts it is non-zero. Raised by review on PR #201, and it is this document's own thesis turned on its own gates: a check reporting success over work it did not do. Recorded here rather than only in the task files because the next increment will write gates in the same shape | unit — `test_the_gate_does_not_pass_on_an_empty_input_set`, one per task |
| The `_main` fix is made by renaming three functions, so the next module to define `main` is silently skipped again | Medium | Medium | Fix the **selection**, not the three modules: the evidence run must discover every module that writes evidence, and a module that writes evidence but is not reached is the failure the gate reports. Renaming `main`→`_main` three times satisfies today's symptom and rebuilds the trap | unit — a test that fails when a module writes evidence and the evidence run does not reach it |

**Rollback.** Every task is a single squash-merged PR closing one issue. Both stored fields are
additive and optional, so reverting a merge leaves earlier records valid and later ones merely
carrying a field nothing reads. No migration to unwind, and no state outside the repository is
touched.

> **✎ Notes** · `SPEC §6`
> _(your notes here — replace this line)_

