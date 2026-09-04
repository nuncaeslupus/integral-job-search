# Session handover

Board: **163 tasks, 127 merged**. Seven PRs open. **Nothing merged this session** —
the previous session's hold on merging was not lifted.

## What this session did

Three things, in the order the previous handover asked for them.

1. **#320 (T57): the 41 audit findings are applied and are now fixtures** (`43135a6`),
   **and the eight CodeRabbit findings the head had never been reviewed for**
   (`ce86416`). See below — between them they produced two findings worth more than
   the number.
2. **#319 (T56): the independent adversarial read is done and posted**
   (comment `5533210387`). **19 findings, 12 fail-open.** Reported, not pushed —
   the second reader does not push, and the accepted cases have to land in the
   gate's own fixtures before it merges.
3. **T59's task file now declares `requires: [access:human]`.** It cannot be
   finished by any session without a person at the keyboard, and the selector had
   been handing it out anyway.

## #320 — the audit is in the fixtures, and English fell out of the floor

All 41 placements corrected: 33 unmapped, 8 moved, `company_stage` left with no
concept so its key is removed rather than left `null`. One addition on the same
spec-first reading: `evaluation practice required` → `ai_in_the_work`, on *"Strong
evals practice: golden sets, LLM-as-judge, regression detection"*.

`tests/test_ontology_health.py` goes **12 tests → 50**. Each accepted case is a
parametrized `(concept, the dimension the definitions require or None, why)` row
asserted against the map the gate reads, with the citing definition inline. Plus a
**vacuity guard**: a row naming a concept the read pass never stated asserts `None`
and passes for the same reason an empty scan does, so every audited name is checked
against the source's own `unmapped` list. That guard is the half that is easy to
skip and is the whole protection.

```
ontology_hit_rate              0.9071 -> 0.8798     gate is >= 0.85 — passes
ontology_hit_rate_by_language  ca 0.8942   es 0.8803   en 0.8423
```

**Nine accepted findings fall on English adverts**, and English was already the
weakest at 0.8731, so `test_no_language_falls_below_the_gate` — written by the
session that measured it — no longer holds. That is the circularity the second
reader exists to break, showing up one layer out from where it was expected.

I did not hunt for three occurrences to clear it. A second pass took the 42
remaining unmapped English occurrences (39 names, all but three singletons) back to
the 41 `definition:` blocks: **exactly one is reachable without stretching a
definition**, and it is the `evaluation practice required` case above. English is
short by 3 and there is no honest remapping that closes it.

So the shortfall gets its own reported key — `languages_below_gate: ["en"]` — pinned
by `test_the_per_language_shortfall_is_recorded_rather_than_averaged_away`, which
fails if English **recovers** as loudly as if a second language falls under. Neither
drifts silently. Raising English is **#321**, filed against this measurement.

**The open question, and it is the owner's:** T57's declared gate is the aggregate
and it passes at 0.8798. The per-language floor is an extra invariant this PR
volunteered, and a correct audit broke it. Recording the shortfall + filing #321 is
one answer; holding #320 until English clears 0.85 is the other. It is a scope call,
not a measurement call. CI is green on `43135a6` — lint, 2135 passed, no drift,
verify-gates 129/129.

## #320's second push — a review that was never on the head

**Read `commit_id`, not the check.** The only review object on #320 carried
`commit_id: 05f1e04` — the previous head — and its **nine actionable findings had
never been worked**, while the PR read as reviewed. The later *"No actionable
comments were generated"* comment covers only the delta `05f1e04..43135a6`, and its
own `final_review_risk_coverage` still says `coveredCommitId: 05f1e04`. **This is
D-28 (#313) happening, on our own PR, one day after it was filed.** The handover's
query is the gate; run it before believing any green CodeRabbit check.

One of the nine was already fixed by the audit push. The other eight are `ce86416`,
and every one holds against its rung's own `tell`:

- **A gold example derived from the cue it exists to check.** `contracted_hours`'s
  English gold was `remotive-1919265`, span *"…prefer consistent contract work **over
  a full-time role**…"*, `value: 0.9`, `derived_from: cue`. That advert says the post
  is **not** full time. Replaced with an advert whose field reads `Full-time`.

  **The first fix for it was incomplete and I reported it as done** (`7ecf5c3` is the
  real one). It kept a `full[- ]time\s+(role|position|…)` branch, so the comparison
  still matched. Two lessons, both general:

  - **`extraction.py:331` compiles cues with `re.IGNORECASE` alone — no
    `re.MULTILINE`.** A `^…$` branch therefore binds to the whole advert and can never
    fire. Mine did not, and nothing noticed, because `_gold` runs a pattern against the
    **isolated span** (`:654`) where the span *is* the whole string. **A cue checked
    only where its own gold points cannot be caught being dead** — the gold and the cue
    were agreeing about a string, not about an advert. Write cue fixtures over whole
    documents.
  - **Measure what a branch buys before keeping it.** That phrase branch matched
    exactly **one** advert in the corpus — the comparison itself. Dropping it cost
    nothing. The instinct to patch a pattern rather than count its matches is what made
    round one incomplete.
- **Three language-parity breaks where one slice was already right.**
  `domain_knowledge` scored *"banking clients"* 0.8 in EN while ES/CA split the rungs
  correctly; `hiring_process_burden` had ES at 0.4 for all four cues and CA at 0.8 for
  all three, so the same omission was **fail-closed in Spanish and fail-open in
  Catalan**; `tool_specificity` scored `domini de les eines` 0.5 in CA and the same
  statement 0.8 in ES.
- **`formal_credential` scored `degree or equivalent` 0.9** — on a `hard`
  admissibility dimension whose definition says *"a candidate without the paper is
  refused"*. An advert accepting equivalent experience refuses nobody. Bare
  `titulación`/`titulació` arrive by the same road (they match *"titulación
  valorable"*) and are split the same way.
- `physical_demand` scored `reposición`/`almacenaje` 0.8 where *"stock handling"* is
  the 0.5 tell verbatim; `tool_specificity` scored a bare technology name 0.8 where
  naming tools is 0.5.
- **`dimensions/README.md` said five groups**, listing the five that existed before
  this PR added `requirements` and `skills`, and claimed `dealbreakers` is exactly the
  `kind: hard` set — six dimensions falsify that.
  `test_the_readme_names_every_group_the_model_declares` now reads the paragraph
  against `load_dimensions()`, **including the spelled count**: the sentence said
  "five" *while listing five stale names*, so either half alone would have passed.
- **`ontology_health` resolved with `entry.get("dimension") or concept_map.get(…)`**,
  which short-circuits on any truthy value — an entry naming a dropped dimension never
  reached the map. The module's two halves disagreed about a stale name:
  `read_concept_map` refuses a map key naming an unknown dimension, the reader fell
  silent on the same fact. Not reachable today; it is a widening's own failure mode,
  so it has a red-first test.

  **The first fix for it was wrong and the suite caught it**, which is worth keeping:
  routing everything through `_resolve` replaced the unmapped *label* with the quote,
  breaking `test_unmapped_concepts_are_counted_not_discarded`. That test was right.
  `_resolve` answers *where a concept lands*; the staleness signal answers *what could
  not be named*, and a dropped id says which question the model stopped asking.

None of the six dimensions is in T56's scored subset, so `extraction_macro_f1` does
not move and **#319's measurement is untouched** — nor do the two PRs share a file.
`ontology_hit_rate` unmoved at 0.8798. Gate green: 2137 passed, no drift, 129/129.

Also answered on the PR, since the pre-merge check asks for a justification: the
`S6.json` / `T47.json` changes are **not** out-of-scope churn.
`interviews_refused_for_teaching_nothing` goes **31 → 0** and `sessions_rehearsed`
177 → 208 because the twelve new dimensions settle on adverts that previously had
nothing to rehearse. That is the widening working, and `make evidence` requires it
committed or the drift check is red.

## #319 — 19 findings, and two of them contradict artefacts already in this repo

Full report in the PR comment. The ones that matter most:

- **`remote_arrangement`'s 0.5 cue is a strict superset of its own 1.0 cue**, in all
  three languages: bare `\bremote\b`, `teletrabajo`, `teletreball`. A fully-remote
  advert fires both rungs. The non-overlap discipline is **stated in this same PR**,
  in `seniority_expectation`'s new comment, and was not applied here. `hard`
  dealbreaker.
- **A driving licence is scored as `travel_requirement` 0.4.** `commute_burden`'s
  definition claims it by name — *"holding a driving licence, or providing your own
  vehicle… distinct from `travel_requirement`, which is travel done as part of the
  job."*
- **`movilidad nacional e internacional` is added at 0.8 — the exact string #320's
  audit unmapped** from `travel_requirement` because the read pass annotated it
  *"offered as a benefit"*. Two sessions, one string, opposite verdicts, and #319
  holds the fail-open one. **Both PRs must not merge carrying both answers.**
- **`english (proficiency|skills)` at 0.7, `negatable: false`**: `English skills not
  required` returns 0.7, because the deny cue is `english (is )?not required` and the
  intervening `skills` defeats it. Same shape for `advanced english` at 1.0.
- **`\bresponsable\s+de\b` at 0.8 on `seniority_expectation`** — that phrase opens a
  duties list on a large share of Spanish adverts. Highest firing rate in the diff.
- **`\d{1,2}\s*pagas\b` at 0.9 on `compensation_transparency`** — a payment count is
  neither a band nor a figure, and `12 o 14 pagas` is boilerplate.

The structural one: **negation coverage is asymmetric by construction.** The positive
cues were widened into long alternations, the deny cues stayed narrow literals, and
most new positive cues are `negatable: false` — which `extraction.py:340` reads as
*never consult the negator*. Every widened dimension therefore has a family of adverts
that state the negative in wording only the positive cue carries.

**Why the gate cannot see any of this:** eight of eleven scored dimensions have no
negative class, which this PR reports itself. Over-firing cannot lower F1 there. The
0.774 is not evidence against the report.

Clean on inspection: `talking_clients`, the `jornada intensiva` **tightening** (the
best change in the diff, correctly reasoned from its rung's tell), the `\bformaci`
guard against `información`, `diseño y fabricación`, and the
`dimensions_with_no_negative_class` key.

## T59 needs a person, and the selector did not know

`arsenal/tasks/lo-4b17.md` now carries `requires: [access:human]`.

Its own *"What it must not become"* carries D-2's first requirement unchanged:
**"Score only what a person decided. Negated `Label` rows whose `source` is `human`,
`confirmed` or `edited`."** The shortfall is 9 labels against a floor of 10 and it is
labels, not code — so no autonomous session can finish it, and each one handed it
spends an attempt discovering that. **It has now happened twice**: the dispatched
worker whose diagnosis is #318, and this session, which `task_select.py` handed it as
the top of the queue.

Verified both ways: a bare `task_select.py` now returns **T94** (`t-506d8fa5`), and
`--capability access:human` still returns T59. `/continue HUMAN` is how the owner
reaches it.

**When a person does sit down to it, the previous session's finding stands and is the
whole of the job**: the cheap unblock is **three labels, not one** — one EN, one CA,
one more ES on a `negatable` cue. `negated_label_count_by_language` is
`{en: 0, es: 9, ca: 0}` and `negation_recall_hits_by_mechanism` is
`{scope: 3, denies: 3}`. A tenth *Spanish* label alone clears the floor and turns the
gate green over a measurement in which Catalan `no … pas` and every English negator
were never once scored, and in which half the hits never exercise the scope rule T59
exists to score. Worse than the current silence.

Also worth knowing: **the claim ref `arsenal/claims/lo-4b17` still exists** (at
`235c757`) from the released attempt, because remote ref deletion is a no-op on this
surface. It is stale. A retry needs `ARSENAL_CLAIM_STALE_OK=1` and the honest
judgement that goes with it; do not read the surviving ref as a live claim.

## Open PRs

| PR | task | head | waiting on |
|---|---|---|---|
| #295 | T89 usajobs POST connector | `cbf881b` | review on head |
| #305 | D-24 retraction (+ D-26 task file) | `a7d809d` | review on head |
| #307 | T98 corpus is a measurement set | `499eb3e` | review on head |
| #312 | T92 salary recovery | `98c9a09` | review on head |
| #318 | T59 diagnosis — **closes nothing** | `e3db5f3` | first review |
| #319 | T56 extractor macro-F1 0.774 | `1c248cf` | **19 findings to apply**, above |
| #320 | T57 ontology hit rate 0.8798 | `7ecf5c3` | the scope call above |
| #322 | T59 capability + this handover | `d18f2c9` | first review |
| #323 | T94 bulk filter | `10cf105` | **a second reader**, see below |

Both #319 and #320 are subscribed for PR activity in this session.

## T94 is done and is #323 — and it wants a second reader

`src/integral/bulk_filter.py`. 322 offers in, 156 out, every removal naming its rule.
Bounded to **filter, not rank**.

The design decision everything follows from: this module **deletes rows the
candidate will never see**, so the costly error is the drop. Every rule fires only
on a fact the advert *states*; unknown always keeps — an unstated salary (T92's
subject), an unstated country, a stated remote arrangement, an `eligibility.FLAG`
(§5.4), an unparseable date. `HardConstraints()` with no countries means **no
location rule**, not *nothing permitted*: it is the default, and a default that
deleted every located offer is the worst reachable fail-closed.

**Stated exclusions cannot reach it.** `reduce` has no exclusions parameter, and
the test asserts the signature as well as the behaviour — a function cannot apply
a preference it is never handed, which is stronger than a rule saying it must not.

Two things worth carrying forward:

- **The plan's metric refused mine.** I wrote `drops_with_no_rule <= 0` into the
  gate fence and `test_the_committed_plan_and_queue_agree` rejected it: the plan
  row already declared `bulk_offers_requiring_manual_triage == 0`, written before
  the implementation existed. **That refusal is the check working** — a task whose
  implementer also picks its metric can pick one the code already satisfies. Use
  the plan's metric; if none is declared, that is the thing to raise, not to fill in.
- **The archived task carried no ` ```gate ` fence.** `verify_gates.py` reads only
  that fence; the ` ```bash ` block is a human recipe, and `task_select.py`'s
  `gate: true` counts the bash block, so the two disagree. Archiving T94 therefore
  turned `129/129` into `128 of 129`. **Check for a `gate` fence before working any
  task whose file predates the convention** — the failure only appears after the
  archive, i.e. after the PR is already open.

**#323 is not merge-ready on its gate alone**, and its own PR body says so. The
drop-side rules are exactly the shape CLAUDE.md wants an independent reader for: a
wrong *keep* is invisible in every number recorded, because nothing counts offers
that should have been dropped and were not. Two judgements named for that reader:
whether treating **any** stated `remote` string as a keep is too generous, and
whether `_below_pay_floor` preferring `salary.max` over `salary.min` is the right
end of a stated band to compare against a floor.

Its probe batch was also wrong twice, and the gate caught both — recorded in the PR
because it is a fixture failure mode, not a code one. A batch whose adverts vary in
one sentence over a shared prefix gets collapsed by `find_duplicates` (134 of 322
rows the first time), and **a reduction ratio measured over a repetitive fixture
measures the fixture**. `rules_never_exercised` is what made it visible.

## The queue after this session

T94 was claimed and worked (see above). `task_select.py`'s next answer should be
re-read at the start of the next session rather than trusted from here.

**#321 is filed and not yet seeded.** It carries `arsenal:queue`, so next session's
step 4b picks it up. Remember the previous session's lesson: `issue_import.py --apply`
writes the task file and **nothing else** — the plan row is the other half, and the
gate that enforces the pair only runs at the repo level, so a missing row goes red on
somebody else's branch. Label the issue *and* its task file, then write the plan row.

## CodeRabbit is gone, and the review half of `merge-policy` is now a second session

The account **lost CodeRabbit for private repositories** on 2026-09-04 and the owner's
decision is to go without. Everything below about nudges, quota windows, Free-vs-Team
plans and `@coderabbitai full review` is now history — do not spend a minute on it.
The measurement trail is kept on **#313** because it is what justified the re-scope.

`merge-policy` **stays** `after-ci-and-review`. What satisfies the review half is now
written in **CLAUDE.md**, which is the durable place for it:

> A code PR may merge once a **session other than its implementer** has read it and
> reported on the PR, naming for each finding the input, the verdict, and the section
> of spec or definition it derives from. The implementer never signs it off. Accepted
> findings are committed as fixtures before merge. **Docs-only PRs are exempt** — a
> handover merges on green CI.

This is not a downgrade. On the PRs open when the bot left, the independent reads
found **41** fail-open placements in `concept_map.yaml` and **19** in the cue
vocabulary, against CodeRabbit's **9** on the same PR that carried the 41.

**D-28 (#313) is re-scoped** to give that rule a reader, and it is checkable now in a
way the bot's signal never was: a second-reader report is *our* artefact — a PR
comment, by an author other than the PR's author, carrying a marker naming the head
commit it read. Its metric is unchanged, because `status/plan.md` already declared
`merges_allowed_without_a_review_of_the_head == 0` and "a review of the head" is
exactly what such a report is. Only the author changed.

**Note the near-miss, which is the same lesson twice in one day.** The first draft of
the re-scoped issue invented `merges_without_a_second_reader_report`. The plan already
had a metric; `test_the_committed_plan_and_queue_agree` had caught the identical
mistake on T94 an hour earlier. **Read the plan row before writing a gate block.**

### What this means for the nine open PRs

Every one of them predates the rule, so **none carries a second-reader report** except
where a session happened to write one:

| PR | second reader? |
|---|---|
| #320 T57 | **yes** — the concept-map audit and the cue findings, both applied |
| #319 T56 | **yes** — 19 findings posted; the implementer has not applied them |
| #323 T94 | **no**, and I implemented it, so I cannot be its reader |
| #322 | **exempt** — docs only |
| #295, #305, #307, #312, #318 | **no** — implemented by earlier sessions, so a later session *can* read them |

That last row is the available work: five PRs whose implementer was a previous
session, which this or any later session may read and report on. #323 needs a session
that is not this one.

## Mechanics that held this session

The previous handover's list is all still true. Two confirmations worth keeping:

- **`make evidence` regenerates but does not stage.** Hit once here, exactly as
  described: `git add -A && make evidence && git add -A && make host-gate`.
- **Confirm the worktree's branch is the PR's head branch before pushing.** #320's
  head is `arsenal/lo-7c14-…`; the worktree branch was `t57-review`, pushed as
  `git push origin t57-review:arsenal/lo-7c14-…`. The explicit refspec is what makes
  that safe.

One new one, small: **`ruff format` before `make host-gate`** on a file with long
table rows. Six E501s in a fixture table cost a whole gate run.

## Candidate deliverables

Unchanged: both Spanish reports are complete in the previous session's scratchpad and
await owner review. Step-0 `.active.json` binding is per-session and must be re-run.
Nothing goes out before the owner reads it.
