# Plan: Candidate-centred integral job search — v2, the thirteen-step process

**Date**: 2026-08-18
**Specification**: `status/spec-v2-process.md` (v2.1, the process) and
`status/spec-v2-steps.md` (v1.1, one spec per step), with
`status/spec-v2-steps.json` as the machine-readable step list
**Inherited contracts**: `status/specification.md` §5 — dimension model, offer
schema, extraction output, ranking output — unchanged and not restated
**Methods register**: `docs/METHODS.md`
**Supersedes**: `status/plan-v1.md` (the v1 thin vertical), whose tasks are
folded into the table below with their current status
**Author**: nuncaeslupus

---

## Why there is a v2 plan

Specification v2 settled *what the tool does* — thirteen steps, five of them
required, each with a goal, a visible output and one named gate metric. It
deliberately did not settle *what gets built in what order*:
`status/spec-v2-process.md` §2 says the steps are numbered as the candidate's
journey and "deliberately not aligned with the delivery phases in
`status/plan.md`, which are about build order."

That build order did not exist for v2. `status/plan-v1.md` was written against
`status/specification.md` and organised by subsystem; it has no row for session
state, resumption, freshness triggers, the annotation pass, document generation
or the interview. Meanwhile every one of the thirteen step gates reads
`not_implemented`, and four of them (`intake_field_provenance`,
`constraint_field_resolution`, `trait_evidence_sufficiency`,
`interview_lesson_linkage`) were attributed to a task in prose only — and one of
those attributions turns out to contradict where the work actually sits (D-4).

This plan closes that: one task table covering both generations of work, a gate
per task, and a named owner for every step gate. §"Reconciliation with v1"
records what changed about the tasks that already existed — the step the brief
asked for and the spec round did not deliver.

---

## Technical solution

### Architecture overview

Six layers. v1 had four; **RUNTIME** and **DOCUMENT** are new, and they are new
because specification v2 is a process specification rather than a matching one.
The old four are unchanged in shape and partly built.

```
                ┌────────────────────────────────────────────────────┐
    RUNTIME     │ identify → resume → step graph → freshness triggers │ step 0 +
    (new)       │ profile revision · staleness · scoring triggers     │ everything
                │ decline ledger · one skill + checkpoint per step    │ cross-cutting
                └──────────────────────┬─────────────────────────────┘
                                       │ decides which step may run, and says why
   ┌───────────────┬───────────────────┼──────────────────┬────────────────────┐
   │ DOCUMENT (new)│ PROFILE           │ SUPPLY           │ MATCH              │
   │ cv/source     │ evidence.jsonl    │ connectors       │ prefilter          │
   │ cv/master.json│ constraints.json  │ offer store      │ extraction         │
   │ generation    │ stories.jsonl     │ dedup            │ annotation (local) │
   │ applications/ │ traits.json       │ lifecycle        │ ranking            │
   │ interviews/   │ weights.json      │ tombstones       │ presentation       │
   │ steps 1,11,12 │ steps 2,3,4,5,6,10│ step 7           │ steps 8,9          │
   └───────────────┴───────────────────┴──────────────────┴────────────────────┘
                                       │ all four read
                             ┌─────────┴──────────┐
                    ONTOLOGY │ dimensions/*.yaml  │  ← the spine (data)
                             │ corpus/            │  ← ground truth + stimuli
                             │ docs/METHODS.md    │  ← every method, link-checked
                             └────────────────────┘
```

**RUNTIME is the layer this plan exists to add.** The v1 architecture assumed a
command run against a store. Specification v2 assumes a conversation that is
interrupted, resumed, revised and re-entered, across more than one person on one
machine — and almost everything in §3–§6 of the process spec is a RUNTIME
concern that no v1 task owns: the dependency graph that decides whether a step
may run (§3.1), sufficiency levels (§3.1), staleness propagation (§3.4),
resumption (§5.3), proactive re-entry (§5.2), and the handle resolution that
must happen before any path under `profiles/` is touched (§6.1).

**DOCUMENT is separated from PROFILE** because its artefacts belong to a
different class. The profile is *derived* and rebuilt from an append-only log;
generated CVs, letters, applications and interview records are *authored* or
*historical* (process §3.4) — never regenerated silently, never revised at all
in the historical case. One layer with two rebuild disciplines is how a CV that
is already with an employer gets overwritten.

### Data flow

**First run (steps 0–6).** identify → resolve handle → read `session/state.json`
→ announce where we are → run the next step the graph permits. Every step
appends to `profile/evidence.jsonl` and rewrites `session/state.json` at its
boundary. Derived files (`constraints.json`, `traits.json`, `weights.json`) are
recomputed at step boundaries, on request, or after N new trait-bearing rows —
never per message.

**Loop (steps 7–10).** constraints → connectors → normalised offers → dedup
against the offer store *and* tombstones → prefilter → staged extraction (rules
first, model last) → **local annotation pass** reading the profile on this
machine → ranking pinned to a profile revision and a sufficiency level →
presentation → feedback, which appends evidence and moves offer status, which
marks weights and rankings stale.

**Per opportunity (steps 11–12).** shortlisted offer + `cv/master.json` +
selected story episodes → generated CV and letter under
`cv/generated/<offer_id>/v<N>/` with a claim→store manifest → per-item approval
→ `applications/<offer_id>/` (immutable) → interview preparation, mock, and
afterwards `interviews/<offer_id>/` (immutable) plus evidence rows carrying the
lessons back into PROFILE.

**Egress is one-directional and narrow.** Advert text may go to a model.
Profile data never accompanies it — relating an offer to the candidate happens
in the local annotation pass. Generated documents are the only artefacts
intended to leave the machine, and each leaves by the candidate pressing send.

### State changes

Everything below lives under `profiles/<handle>/`, which is gitignored (T1) and
stays so. The tree is process spec §6.

| Layer | Store | Change | Description | Owner task |
|-------|-------|--------|-------------|------------|
| RUNTIME | `identity.json` | CREATE | handle, display name, language, locale, created_at | S3 |
| RUNTIME | `session/state.json` | UPDATE | current step, position, pending steps, open questions, sufficiency | T35 |
| DOCUMENT | `cv/source/*` | CREATE | originals as supplied; never modified, never sent | S4 |
| DOCUMENT | `cv/master.json` | CREATE/UPDATE | the CV store, every field carrying provenance | S4 |
| DOCUMENT | `cv/generated/<offer_id>/v<N>/` | CREATE | CV + letter + claim manifest; never overwritten | T45 |
| DOCUMENT | `applications/<offer_id>/` | CREATE | what was sent and when — immutable | T46 |
| DOCUMENT | `interviews/<offer_id>/` | CREATE/APPEND | preparation, questions, outcome, lessons — immutable | S6 |
| PROFILE | `profile/evidence.jsonl` | APPEND | source of truth; retractions are rows, not deletions | T6, T38 |
| PROFILE | `profile/constraints.json` | CREATE/UPDATE (derived) | every field `stated`, `declined` or `unknown` | T41 |
| PROFILE | `profile/stories.jsonl` | CREATE/UPDATE (derived) | episodes linked to dimensions | T8 |
| PROFILE | `profile/traits.json` | CREATE/UPDATE (derived) | score with evidence rows, or `insufficient` | T27, T39 |
| PROFILE | `profile/weights.json` | CREATE/UPDATE (derived) | part-worths in salary-equivalent terms | T10 |
| SUPPLY | `offers/<offer_id>.json` | CREATE/UPDATE | normalised offer + lifecycle status + history | T11, S5 |
| SUPPLY | `offers/tombstones.jsonl` | APPEND | purged ids, urls, hashes; no ad body | S5 |
| MATCH | `extractions/<offer_id>.json` | CREATE | candidate-independent; cacheable, shareable | T15 |
| MATCH | `annotations/<offer_id>.json` | CREATE (derived) | the same offer read against *this* candidate; never shared | T42 |
| MATCH | `rankings/<timestamp>.json` | CREATE | pinned to `profile_revision` and sufficiency level | T18 |

### Contracts — where each is pinned

Most contracts are already written down. This table exists so the three that are
not can be seen to have an owner, rather than being discovered missing by the
task that needs them.

| Contract | Pinned in | Status |
|----------|-----------|--------|
| Dimension model, offer schema, extraction output, ranking output | `status/specification.md` §5 | settled (v1) |
| Evidence row | process spec §4.1 | settled |
| Session state | process spec §5.1 | settled |
| Profile revision | process spec §3.4 | settled |
| Tombstone, and the text normalisation behind `text_sha256` | process spec §7.4 | settled, versioned |
| Offer status and allowed transitions | process spec §7.1 | settled |
| `constraints.json` field set and resolution states | — | **T24 pins it**; the step spec names the states, not the fields |
| `cv/master.json` | — | **S4 pins it**; step 1 names what it holds, not its shape |
| `annotations/<offer_id>.json` | — | **T42 pins it**; step 8 names what it records and that it never ships |

### Technology choices

Only the delta from v1. Everything in `status/plan-v1.md` still holds: Python
3.12+, uv, ruff, strict mypy, pytest, YAML dimensions, JSONL logs, files rather
than a database, Pydantic for schemas.

| Choice | Justification |
|--------|--------------|
| Document parsing: `pypdf` + `python-docx` for `cv/source/*` | Step 1 imports what the candidate already has. Both are pure-Python and read-only, which suits a file that must never be modified |
| A template engine for the ranking card, filled from normalised offer JSON | Step 9 requires it explicitly: "built once, filled fast, never assembled a paragraph at a time by a model." A model rendering the same card fifty times is both the expensive and the unreliable way |
| Staged extraction — normalise, then rules, then model on the remainder | Step 8: "the model is the last resort rather than the first." The cost of reading every advert with a model is what makes the loop stop being run |
| The candidate's own browser session for authenticated sources, never stored credentials | Process spec §2.6 / step 7. Nothing to leak and nothing to rotate; the shape of the connector file is T32's problem |
| Derived state recomputed, never migrated | The profile is a pure function of the evidence log (T6). A schema change to a derived file is a rebuild, so no migration path is owed for `constraints.json`, `traits.json`, `weights.json`, or annotations |

### Out of scope

- **Any autonomous outward action.** The tool prepares and stops one step short
  of sending, per process spec §6.2. This is a permanent boundary, not a phase.
- **Multi-tenant service.** Multi-user means several people on one machine with
  one directory each — not accounts, not a server.
- **An interactive UI.** Step 9's card is a filled template rendered to text or
  a page. Anything with state of its own waits.
- **A plugin, a published package, or a UI.** The distribution question
  (process spec §11.5) is **settled**: installed by cloning, candidate state
  outside the clone (`docs/distribution.md`, T29). A Claude Code plugin remains
  a delivery change that can be made whenever the friction justifies it, and is
  not v2 work.
- **CV templates and layouts** (brief §2.7). The store feeds templates; choosing
  layouts is not v2.
- **Re-litigating specification v2.** A task that finds the spec wrong seeds a
  `D-N` divergence and fixes the spec; it does not quietly diverge.

---

## Implementation tasks

Two columns beyond the v1 table: **Step** maps a task to the step(s) of
specification v2 it serves (`—` for infrastructure that serves all of them), and
**St** is status — ☑ merged · ◐ in progress · ☐ open · ☒ cancelled (absorbed or abandoned; never done). Rows T1–T33 are carried
forward from `status/plan-v1.md`; T34–T48 are new here. The **Gate** column is
the objective pass/fail, and a gate that could not run is not a pass.

**[HUMAN]** tasks require the candidate personally and carry
`requires: ["surface:human"]`, which `queue_batch.sh` enforces so no worker
claims them. **[LAPTOP]** tasks need egress the cloud session is denied
(confirmed 2026-08-15, 403 at the proxy for every board tried); they are tagged
`laptop` and run from a laptop session.

### ONTOLOGY — the shared vocabulary

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T1 | Scaffold package: uv, ruff, strict mypy, pytest, Makefile, `profiles/` gitignored | — | S | — | `lint_typecheck_exit_code == 0` | `test_package_imports_cleanly_exposes_version` in `tests/test_scaffold.py` — importing `integral` yields a semver `__version__` | ☑ |
| T2 | Dimension schema (Pydantic) + loader + validator, incl. `methods_ref` anchor resolution | — | M | T1 | `dimension_schema_violations == 0` | `test_dimension_missing_methods_ref_is_rejected` in `tests/test_dimension_model.py` — a dimension without `methods_ref` fails validation | ☑ |
| T3 | Dimension model v0: 20–25 dimensions with ES/EN/CA cues and elicitation questions | 8 | L | T2 | `dimension_extractor_coverage >= 0.90` | `test_every_dimension_has_cues_in_all_three_languages` in `tests/test_dimension_content.py` — each dimension carries ≥1 cue per language | ☑ |
| T4 | Corpus harness: ad store, labelling CLI, split assignment, self-agreement report | 5, 8 | M | T2 | `corpus_harness_roundtrip_loss == 0` | `test_corpus_roundtrip_preserves_text_and_offsets` in `tests/test_corpus.py` — writing then reading an ad preserves text byte-for-byte and label offsets | ☑ |
| T4b | **[LAPTOP]** Collect ≥100 raw ads: ≈60 ES + 25 EN remote programming roles, plus ≈15 CA Catalan IT ads at large — the remote dimension mixed in, not filtered for (D-1) | 5, 8 | M | — | `raw_ad_count >= 100` | `test_raw_corpus_meets_size_and_language_mix` in `tests/test_corpus_raw.py` — ≥100 raw ads, mix within ±10% | ☑ |
| T5 | Corpus assembled and pre-marked; splits assigned. The hand-labelling campaign was **retired 2026-08-19** — the model reads each advert itself, and human labels accrue from use | 5, 8 | L | T3, T4, T4b | `corpus_size >= 100` | `test_raw_corpus_meets_size_and_language_mix` in `tests/test_corpus_raw.py` — ≥100 ads, language mix within ±10% | ◐ |
| T22 | `methods_ref` link check across dimensions and computation sites | — | S | T2, T18 | `undocumented_methods == 0` | `test_every_methods_ref_resolves_to_an_anchor` in `tests/test_methods_links.py` — every `methods_ref` resolves to a heading in `docs/METHODS.md` | ☐ |
| T23 | Dimension `side`: matched / candidate-fact / candidate-trait, and a coverage metric that stops asking ad-side questions of candidate-side entries | 4, 8 | M | T2 | `side_coverage_violations == 0` | `test_a_trait_dimension_without_cues_is_valid` in `tests/test_dimension_side.py`; `test_extractor_coverage_counts_only_ad_side_dimensions` | ☑ |
| T24 | Candidate attribute schema — languages, location, relocation, salary floor/target, availability, work authorisation, **and the reach and legality fields step 7 needs**: employed or contracting, paid where, taxed where. Pins the `constraints.json` field set and its `stated`/`declined`/`unknown` states | 2, 7 | M | T23 | `unsatisfiable_hard_constraint_leaks == 0` | `test_offer_failing_a_hard_constraint_never_ranks` in `tests/test_candidate_attributes.py`; `test_missing_attribute_is_unknown_not_satisfied` — an unstated constraint does not silently pass | ☑ |
| T25 | **[LAPTOP]** Broaden the corpus beyond remote programming: ≥6 job families, ≥15 ads each, same three languages | 5, 8 | L | — | `corpus_job_family_count >= 6` | `test_corpus_covers_at_least_six_job_families` in `tests/test_corpus_families.py` — no family below 15 ads | ☑ |
| T26 | Dimension model v1: widen to the broadened corpus; add candidate-trait dimensions. **Split and cancelled 2026-08-24** — job (1), widening by a corpus sweep, was already retired by the 2026-08-19 scope change (a dimension is coined when a live session turns one up, not by a batch exercise); job (2) is now **T26b**. Its gate was T57's own metric, `unmeasured` until T57 lands, so this task could never have been measured from inside itself | 4, 8 | L | T23, T25 | `ontology_hit_rate >= 0.85` | — carried to T26b as `trait_dimensions_ready >= 4` | ☒ |
| T26b | The four candidate-trait dimensions — creativity, ambition, learning orientation, spare-time engagement — `side: candidate_trait`, no cues, elicited only, rungs declared | 4, 8 | M | T23 | `trait_dimensions_ready >= 4` | `test_trait_dimensions_carry_no_cues` in `tests/test_dimension_content.py`; `test_every_trait_dimension_declares_its_rungs`; `test_a_trait_question_is_behavioural_not_a_self_rating` | ☐ |
| T29 | Record the product shape — packaging, phase skills, checkpoint scripts, and the distribution decision left open at process spec §11.5. **Decided**: cloned, with candidate state outside the clone (`docs/distribution.md`); implementation is T51–T54 | — | S | — | `phase_checkpoints_defined == 1` | `test_every_open_shape_question_has_a_recorded_answer` in `tests/test_product_shape.py` — each question in the shape doc carries a decision or a named blocker | ◐ |
| T30 | Encode step inputs/outputs in `spec-v2-steps.json` and gate on required-subset closure | — | M | — | `required_subset_closure_violations == 0` | `test_required_step_reads_only_required_or_optional_inputs` in `tests/test_step_graph.py` — a required step reading a required-absent input fails the check | ☑ |
| T31 | Detect note-key rebinding and a stale spec reader | — | S | — | `reader_note_rebindings == 0` | `test_renumbered_section_does_not_rebind_a_note` in `tests/test_spec_reader.py` — moving a section leaves its note unbound rather than re-bound | ☑ |
| T48 | Step gate state register: derive each step's `state` in `spec-v2-steps.json` from `status/evidence/*.json` instead of hand-editing it | — | S | T30 | `step_gate_state_drift == 0` | `test_step_state_matches_recorded_evidence` in `tests/test_step_gates.py` — a step whose evidence file records a passing measurement cannot read `not_implemented`; `test_missing_evidence_reads_not_implemented` | ☑ |

### RUNTIME — the process engine (new in v2)

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| S3 | Multi-user profile tree, identify-at-session-start, and handle resolution, with a `PreToolUse` hook refusing reads and writes under another handle's tree. **Session state is T35** | 0 | L | S1, T1 | `cross_user_leaks == 0` | `test_store_operation_under_another_handle_is_refused` in `tests/test_identity.py`; `test_single_existing_profile_is_confirmed_not_assumed` — one profile is offered for confirmation, never selected silently; `test_correct_operation_never_trips_the_hook` | ☑ |
| T35 | Session state and resumption: `session/state.json` written whenever something new is known, and the five-rule resumption order that announces which step it resumes and why | 0 | M | S3, T6 | `resumption_position_loss == 0` | `test_interrupted_step_resumes_at_recorded_position` in `tests/test_session_state.py`; `test_state_survives_a_session_that_never_reaches_a_boundary`; `test_resumption_names_the_step_and_the_reason` | ☑ |
| T34 | Step graph runtime: read declared inputs/outputs, answer *which steps may run* and *what is still owed*, and compute the sufficiency level L0/L1/L2 | — | M | T30, T35 | `unrunnable_step_dispatches == 0` | `test_step_without_its_required_inputs_is_never_offered` in `tests/test_step_graph_runtime.py`; `test_declining_every_offered_step_still_reaches_a_ranking`; `test_ranking_without_weights_is_l1` | ☑ |
| T37 | Profile revision and staleness: everything derived records the revision it was computed from; derived is recomputed, authored is marked stale with the reason, historical is never touched | — | M | T6 | `stale_artefact_detection_recall == 1.0` | `test_artefact_behind_current_revision_reads_stale` in `tests/test_revision.py`; `test_authored_artefact_is_marked_not_regenerated`; `test_historical_artefact_is_never_revised` | ☑ |
| T36 | Freshness triggers and proactive re-entry: elapsed time, life event in the conversation, and gap — each producing an **offer**, with declines recorded so they are not repeated | — | M | T35, T37 | `unoffered_reentries == 0` | `test_trigger_produces_an_offer_not_an_action` in `tests/test_freshness.py`; `test_declined_trigger_is_not_raised_again`; `test_life_event_reenters_the_step_the_spec_names` | ☑ |
| T38 | Retraction rows, and deletion of a person: "forget that" suppresses everywhere derived while the row survives; "delete everything about me" removes the tree, named once and irreversible, including another profile after confirming it by name | — | M | T6 | `retracted_rows_surviving_rebuild == 0` | `test_retracted_row_is_absent_from_every_derived_file` in `tests/test_retraction.py`; `test_retraction_is_itself_reversible`; `test_deletion_without_a_named_target_deletes_nothing` | ☑ |
| T39 | Scoring triggers: recompute at a step boundary, on explicit request, and after N new trait-bearing rows — never per message | 4, 6 | S | T37 | `unscheduled_scoring_runs == 0` | `test_scoring_does_not_run_per_message` in `tests/test_scoring_triggers.py`; `test_deferred_scoring_loses_no_evidence` — the log is never behind | ☑ |
| T40 | Decline ledger: a subject declined once is not raised again in that step, declined twice is not raised again at all unless the candidate reopens it | — | S | T6 | `repeat_asks_after_decline == 0` | `test_subject_declined_twice_is_never_asked_again` in `tests/test_non_insistence.py`; `test_candidate_reopening_a_subject_clears_the_ledger` | ☑ |
| S7 | One skill per step, thirteen of them, each carrying its checkpoint as a **script** rather than prose | all | L | S2r, T34, T35 | `steps_with_a_skill_fraction == 1.0` | `test_every_step_has_a_skill`; `test_every_skill_names_its_gate_metric`; `test_every_skill_checkpoint_is_a_script_not_prose`; `test_no_skill_contradicts_its_step_specification` | ☑ |

### PROFILE — evidence, constraints, stories, traits, weights

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T6 | Profile store: append-only `evidence.jsonl` + `rebuild` to byte-identical derived files; two-profile fixture | — | M | S3, T2 | `profile_rebuild_deterministic == 1` | `test_rebuild_twice_produces_identical_bytes` in `tests/test_profile_store.py`; `test_second_profile_does_not_leak_into_first` | ☑ |
| T41 | Constraints step engine: confirm-and-fill from Intake's claims when they exist, ask from scratch when they do not, and never promote an unconfirmed claim | 2 | M | T6, T24 | `constraint_field_resolution == 1.0` | `test_every_constraint_field_resolves_to_one_of_three_states` in `tests/test_constraints_step.py`; `test_unconfirmed_claim_stays_unknown`; `test_step_runs_with_no_claims_present` — the required-only path | ☑ |
| T7 | Question bank generation from the dimension model | 3, 4 | M | T3, T6 | `question_dimension_coverage == 1.0` | `test_every_generated_question_maps_to_a_dimension` in `tests/test_question_bank.py` | ☑ |
| T8 | Free-text answer extraction → dimension values + story-bank episodes | 1, 3 | L | T7 | `story_dimension_linkage == 1.0` | `test_every_episode_links_to_a_dimension` in `tests/test_elicit_extract.py`; `test_episode_defaults_to_private_disclosure` | ☑ |
| T27 | Onboarding interview protocol: sequencing, answer-dependent follow-ups, coverage tracking, the first-job branch, empathic framing, and the two-episode/two-occasion trait floor reading `insufficient` rather than refusing | 3, 4 | L | T7, T8, T24 | `interview_profile_coverage >= 0.90` | `test_every_trait_is_scored_or_explicitly_insufficient` in `tests/test_interview.py`; `test_scripted_respondent_yields_full_profile_coverage`; `test_every_negative_episode_gets_a_lesson_followup` | ☑ |
| T9 | Reaction elicitation: live multi-source stimuli by preference, corpus elicitation split as fallback, disjoint-split enforcement | 5 | M | T5, T8, T11 | `elicitation_eval_overlap == 0` | `test_elicitation_never_draws_from_evaluation_split` in `tests/test_reaction_elicit.py`; `test_live_stimuli_enter_the_offer_store_as_new`; `test_no_stimulus_is_invented` | ☐ |
| T10 | Preference weights: forced pairwise choices → part-worths → salary-equivalent scale | 6 | M | T9 | `weight_salary_equivalent_roundtrip_error <= 0.01` | `test_partworth_to_salary_equivalent_roundtrips` in `tests/test_weights.py` — converting a dimension to €/month and back recovers the part-worth within 1% | ☐ |
| T21 | Feedback loop: rejection reason → `evidence.jsonl` → rebuild → changed ranking, and the offer's lifecycle status moves with it | 10 | M | S5, T6, T19 | `feedback_traceability == 1.0` | `test_every_profile_value_traces_to_evidence_rows` in `tests/test_feedback.py`; `test_rejection_moves_offer_status_and_marks_weights_stale` | ☐ |
| T28 | Continuous profile capture: every candidate-facing surface appends evidence, not just onboarding | — | M | T6, T27 | `profile_capture_coverage == 1.0` | `test_every_candidate_facing_surface_writes_evidence` in `tests/test_profile_capture.py` — a surface that accepts free text and writes no evidence row fails | ☑ |
| T49 | Trait evidence sufficiency: score a trait only when its evidence floor is met, report `insufficient` otherwise — never refuse, never voice the floor to the candidate | 4 | M | T6, T27 | `trait_evidence_sufficiency == 1.0` | `test_a_trait_below_the_floor_is_insufficient_not_scored` in `tests/test_trait_sufficiency.py`; `test_insufficient_does_not_stop_the_step`; `test_the_floor_counts_occasions_not_repetitions` | ☑ |
| T50 | Wire an intake capture driver: S4 gave intake a real conversational free-text surface, so it should move from `pending_implementation` to a measured surface rather than sitting in the bucket that means "nothing was built" | 1 | S | T28, S4 | `profile_capture_coverage == 1.0` | `test_intake_is_a_measured_surface_not_a_pending_one` in `tests/test_profile_capture.py` — the number alone cannot show this was done, since it already read 1.0 over four surfaces; `test_a_conversational_intake_answer_reaches_the_evidence_log` | ☐ |
| T51 | Candidate state resolves from `$INTEGRAL_HOME` and is refused anywhere inside a git work tree — the distribution decision made mechanical, so "candidate data never reaches a repository" is a property of the code rather than a `.gitignore` line | — | M | — | `state_paths_inside_a_repo == 0` | `test_a_home_inside_a_git_work_tree_is_refused` in `tests/test_state_home.py`; `test_the_default_home_is_outside_the_clone`; `test_every_store_path_resolves_through_the_resolver` | ☑ |
| T52 | First-run bootstrap: a `SessionStart` hook and a step-0 re-check install the dependencies a clone does not carry, idempotently, and announce the first install to the candidate | — | M | T51 | `unbootstrapped_first_runs == 0` | `test_a_clone_without_dependencies_installs_them_before_step_zero` in `tests/test_bootstrap.py`; `test_bootstrap_is_silent_when_the_environment_is_current`; `test_a_missing_package_manager_is_reported_not_raised` | ◐ |

### SUPPLY — connectors, offers, lifecycle

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T11 | Normalised offer schema + manual-paste connector | 7 | M | T1 | `offer_schema_violations == 0` | `test_pasted_text_produces_valid_offer` in `tests/test_connect_manual.py` — a pasted ad yields a schema-valid offer with verbatim `text` | ☑ |
| T32 | Declarative connector format and a shared connector library — data, never code, never a credential; authenticated sources drive the candidate's own browser session | 7 | M | T11 | `connector_executes_no_shared_code == 1` | `test_connector_file_is_data_only` in `tests/test_connectors.py`; `test_no_connector_stores_a_credential`; `test_authenticated_source_uses_the_candidate_session` | ☑ |
| T12 | **[LAPTOP]** One live portal connector against recorded fixtures | 7 | L | T11, T32 | `connector_fixture_parse_f1 >= 0.95` | `test_connector_parses_fixture_pages_to_offers` in `tests/test_connect_portal.py` | ☑ |
| T13 | Cross-source dedup by similarity over normalised text + expiry detection | 7 | M | T11 | `dedup_precision >= 0.95` | `test_crossposted_duplicates_are_collapsed` in `tests/test_dedup.py`; `test_distinct_roles_at_same_company_are_not_merged` | ☑ |
| S5 | Offer lifecycle: seven statuses and their allowed transitions, retention, the 60-day purge, and tombstones dedup cannot resurrect | 7 | L | S1, T11, T13 | `resurrected_purged_offers == 0` | `test_purged_offer_is_not_re_added_as_new` in `tests/test_offer_lifecycle.py`; `test_shortlisted_offer_is_never_purge_eligible`; `test_applied_cannot_return_to_new`; `test_explicit_revival_restores_and_keeps_the_tombstone` | ☑ |
| T33 | Net-from-gross pay estimation per country, generated when the advert states only gross | 9 | M | T24 | `generated_tax_rules_marked_unverified == 1.0` | `test_net_estimate_within_ten_percent_of_reference` in `tests/test_pay.py`; `test_absent_country_rules_yield_unknown_not_a_guess` | ☑ |
| T53 | Connector contract pack for the sources repository: one directory shape, one conformance command a contributor's agent and CI both run, and a fixture that is a sampled listing rather than an advert the candidate was reading | 7 | M | T32 | `connector_contract_violations == 0` | `test_a_connector_without_a_fixture_is_rejected` in `tests/test_connector_contract.py`; `test_a_connector_that_opens_its_own_socket_is_rejected`; `test_a_fixture_carrying_candidate_provenance_is_rejected` | ☑ |
| T54 | Connector exchange: discover an existing connector for a site, install it into `$INTEGRAL_HOME` and run its fixture before first use; then offer to contribute a new or repaired one, disclosing every file that would be sent — and treat declining as a complete outcome | 7 | L | T53 | `unconsented_contributions == 0` | `test_nothing_leaves_the_machine_without_an_explicit_yes` in `tests/test_connector_exchange.py`; `test_the_disclosure_lists_every_file_that_would_be_sent`; `test_declining_leaves_the_connector_installed_and_is_not_asked_again` | ☐ |

#### Iterative sourcing — the search is the conversation

From `status/specs/iterative-sourcing.md` (Option 2, then Option 3). **T60 is
deliberately first and deliberately small**: every other row depends on step 7 being
allowed to read what the candidate has taught the system, and a graph edge nobody
traverses is documentation rather than a feature.

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T60 | Close the sourcing loop: step 7 reads the fitted weights and the reaction/outcome evidence, in the prose graph and the JSON, all three `optional: true` so a first cycle still runs | 7 | S | — | `sourcing_inputs_excluding_learned_evidence == 0` | `test_step_seven_reads_the_learned_evidence` in `tests/test_step_graph.py` — step `sourcing` declares weights and reaction/outcome evidence among its inputs; `test_the_prose_graph_and_the_json_agree_on_step_seven` — `drift_violations == 0` across the edit; `test_sourcing_is_runnable_before_any_weight_is_fitted` — the new inputs are optional, so `missing_inputs` is empty on a first cycle | ☐ |
| T61 | §1 amendment: the dimensions are what make an iterative search steerable — one sentence gained, none lost, in every document that states the product's argument | — | S | T60 | `spec_consistency_violations == 0` | `test_every_document_states_the_same_differentiator` in `tests/test_spec_consistency.py` — D-3's three documents agree after the amendment; `test_the_amendment_adds_a_sentence_without_removing_the_mechanism` — the dimension-model claim survives verbatim | ☐ |
| T62 | Exhaustion as a measurement: a cycle whose offers dedupe against ones already seen, tombstones included, with the repeat share and the reason carried | 7 | M | T60 | `exhaustion_triggers_without_a_reason == 0` | `test_a_cycle_repeating_known_offers_is_exhausted` in `tests/test_sourcing_strategy.py` — repeat share above `EXHAUSTION_REPEAT_SHARE` sets `exhausted`; `test_a_cycle_that_returned_nothing_is_exhausted_for_its_own_reason` — zero offers does not read as zero repeats; `test_no_exhaustion_is_recorded_without_a_reason` — an empty reason is a violation, not a trigger | ☐ |
| T63 | Step 7 becomes offerable again on exhaustion — a new trigger kind beside staleness, never a change to it | 7 | M | T62 | `stuck_cycles_without_a_proposal == 0` | `test_an_exhausted_step_seven_is_offered_again` in `tests/test_freshness.py` — a finished sourcing step re-enters on an `exhausted` trigger; `test_staleness_behaviour_is_unchanged_by_the_new_kind` — the existing trigger fires exactly as before; `test_an_exhausted_cycle_never_reruns_the_same_search_silently` — re-entry carries a proposal | ☐ |
| T64 | Symmetric scope proposals: `alternatives` typed to require the opposite direction, so a one-way proposal cannot be constructed | 7 | M | T62 | `scope_proposals_offering_only_narrowing == 0` | `test_a_proposal_offering_only_narrowing_is_rejected` in `tests/test_sourcing_strategy.py` — construction fails without an opposite-direction alternative; `test_a_widening_is_proposable_when_the_search_is_too_focused`; `test_every_proposal_states_its_reason_in_candidate_terms` | ☐ |
| T65 | Consent: a narrowing is licensed by a recorded decision, a refusal is recorded too, and a refused proposal may return only on a changed trigger, new evidence, or a new session | 7, 10 | M | T64 | `narrowings_without_a_recorded_decision == 0` | `test_a_narrowing_without_a_recorded_decision_is_refused` in `tests/test_sourcing_strategy.py` — the scope change cannot apply without the evidence row; `test_a_refusal_is_recorded_as_evidence_not_as_a_veto`; `test_a_refused_proposal_is_not_reasked_on_the_next_cycle` — same facet and direction, same trigger, no intervening evidence | ☐ |
| T66 | The empty market: exhaustion that survived both a broadening and a narrowing is reported as **a time**, never as a relaxed constraint | 7 | M | T64, T65 | `exhausted_searches_reported_as_a_scope_change == 0` | `test_an_empty_market_is_reported_as_a_time_not_a_compromise` in `tests/test_sourcing_strategy.py` — the offer is to come back later, and names no constraint; `test_the_empty_market_needs_exhaustion_in_both_directions` — one stale cycle does not reach it; `test_no_hard_constraint_is_proposed_for_relaxation_on_an_empty_result` | ☐ |
| T67 | Standing scope re-surfaced on return: step 0's opening extends from position to substance, and every scope decision is correctable there | 0 | S | T65 | `standing_scope_decisions_not_resurfaced == 0` | `test_returning_shows_every_standing_scope_decision` in `tests/test_step_skills.py` — each recorded decision appears in the opening summary; `test_a_resurfaced_decision_can_be_corrected_in_place` — consent nobody can review is not consent | ☐ |
| T68 | The cycle improves or says why: rejection rate strictly decreasing across a candidate's cycles, or a scope change proposed — one measurement read twice | 7 | M | T63, T64 | `cycles_neither_improving_nor_proposing == 0` | `test_a_cycle_that_did_not_improve_proposes_a_scope_change` in `tests/test_sourcing_strategy.py`; `test_an_improving_cycle_is_left_alone` — the tool does not speak when the search is working; `test_the_rate_is_measured_within_subject_only` — no cross-candidate comparison exists to make | ☐ |
| T69 | **[HUMAN]** **Option 3** — when the search is exhausted *and* the evidence behind the deciding dimensions is thin, offer to go back for more history. **Gated on the exhaustion signal having been observed correct in a real cycle**, not merely built — carries `requires: [surface:human]`, because a dep on T68 resolves when T68 merges rather than when anyone has watched the signal fire | 3, 4, 7 | L | T68 | `unrequested_profile_reentries == 0` | `test_a_profile_reentry_is_offered_never_imposed` in `tests/test_step_runtime.py` — declining leaves the search running; `test_no_reentry_is_offered_while_the_deciding_evidence_is_sufficient`; `test_a_declined_reentry_is_not_reoffered_in_the_same_session` | ☐ |
| T70 | Robots matching that cannot fail open: RFC 9309 record grouping, longest-match precedence and `Allow` beating `Disallow` on an equal-length tie, replacing the `urllib.robotparser` delegation that reads a blank line as the end of a record | 7 | M | T32 | `robots_verdicts_misread == 0` | `test_a_blank_line_inside_a_record_does_not_end_it` in `tests/test_robots.py` — a `Disallow: /` after a blank line still binds its agent; `test_longest_match_wins_over_file_order`; `test_allow_beats_disallow_on_an_equal_length_tie` | ☐ |
| T71 | Read `robots.txt` with a browser user-agent when the honest one is refused — the policy resource only, never content, and the recovered policy is then obeyed more strictly rather than less | 7 | S | T70 | `robots_policies_abandoned_on_refusal == 0` | `test_a_403_on_the_policy_is_retried_with_a_browser_agent` in `tests/test_robots.py`; `test_only_the_policy_url_is_refetched_never_content`; `test_a_recovered_policy_is_obeyed_not_ignored` | ☐ |
| T72 | Connector health: free signals over evidence already in hand — company null on every row, undecoded entities, off-portal URLs, zero yield from a portal that has yielded before — then one bounded sentinel probe using the connector's own recorded example query | 7 | M | T12, T32 | `silent_connector_failures == 0` | `test_a_connector_whose_selectors_no_longer_match_is_reported_broken` in `tests/test_connector_health.py`; `test_zero_yield_from_a_portal_that_never_yielded_is_not_breakage`; `test_a_healthy_connector_over_its_fixture_reads_ok` | ☐ |
| T73 | The converse verdict: a 429 or a block page is never evidence of breakage but `inconclusive`, and disabling a connector always asks first and touches exactly one connector | 7 | S | T72 | `rate_limited_runs_reported_as_broken == 0` | `test_a_429_is_inconclusive_not_broken` in `tests/test_connector_health.py`; `test_a_block_page_is_inconclusive`; `test_disabling_a_connector_requires_confirmation` | ☐ |
| T74 | Liveness reads page identity, not only URL identity: a fetch landing on content that is not the advert is `unverified`, including the fragment-anchor case where the URL never changed | 7 | M | T11, T13 | `offers_presented_from_a_page_that_is_not_the_advert == 0` | `test_a_fragment_anchor_landing_on_a_listing_page_is_unverified` in `tests/test_liveness.py`; `test_a_page_whose_title_does_not_match_the_offer_is_unverified`; `test_the_advert_itself_still_reads_live` | ☐ |
| T75 | Dedup prefers the employer's own posting over an aggregator copy, because aggregators strip the grade that `seniority_expectation` reads | 7 | M | T13 | `duplicate_groups_resolved_away_from_the_canonical_source == 0` | `test_the_employers_own_posting_wins_over_an_aggregator_copy` in `tests/test_dedup.py`; `test_a_group_with_no_canonical_source_keeps_its_survivor`; `test_source_rank_never_overrides_a_liveness_verdict` | ☐ |

### MATCH — extraction, annotation, ranking

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T14 | Lexical prefilter (recall-oriented) ahead of LLM extraction. **Absorbed into T15 2026-08-20 and cancelled** — its gate was measured against corpus positives T5 never supplied (14 evaluation labels, four dimensions with none), so kept separate it blocked T15, and through it fifteen live tasks, on a number nobody could honestly take | 8 | M | T3, T5, T11 | `prefilter_recall >= 0.98` | `test_prefilter_retains_all_corpus_positives` in `tests/test_prefilter.py` — carried into T15 unchanged | ☒ |
| T15 | Staged extraction — normalise, then rules, then a model only on what they could not settle: dimension scores, evidence spans, `unmapped_concepts`. **T14's prefilter is the rules stage, folded in 2026-08-20.** **Acceptance split by D-12 2026-08-22** — the scoring half is T56, because scoring needs labels the corpus does not yet carry | 8 | L | T5, D-12 | `prefilter_suppressed_positives == 0` | `test_prefilter_retains_all_corpus_positives` in `tests/test_prefilter.py` and `test_the_suppression_check_would_notice_a_bad_cue`, which inverts a committed cue so the gate metric cannot pass by having no teeth; `test_score_without_evidence_span_is_rejected` and `test_model_is_not_called_for_a_dimension_rules_settled` in `tests/test_extract.py`; `test_extraction_matches_corpus_labels`, which stays here asserting the *refusal* — null, unmeasured, dimensions named — while the score it is named for is T56's | ☑ |
| T56 | Score the extractor: `extraction_macro_f1` over human-decided labels only, refused below the label floor, `n` beside every score. **Split out of T15 by D-12 2026-08-22** — its gate declares `status-key: extraction_status`, so "not yet scorable" records as unmeasured rather than as a hard failure | 8 | M | T25 | `extraction_macro_f1 >= 0.75` | `test_extraction_matches_corpus_labels` in `tests/test_extract.py` — macro-F1 ≥ 0.75 on the evaluation split, once the split can carry one | ☐ |
| T16 | Negation handling in extraction: a negator governs its own clause and nothing past it. **Acceptance split 2026-08-23 on D-12's precedent** — the recall half is T59, because the corpus carries 2 negated labels against a floor of 10 | 8 | M | T15 | `negation_scope_leaks == 0` | `test_negated_cue_inverts_not_drops_score` in `tests/test_negation.py` — "no on-call" yields a negative score, not a missing one; `test_negator_does_not_reach_past_a_full_stop` and `test_negator_does_not_reach_past_a_line_break`, the two real corpus adverts where a negator inverted the next clause; `test_negator_still_reaches_across_a_comma`, so the fix cannot pass by negating nothing; `test_no_negation_leaks_across_a_boundary_in_the_corpus` | ☑ |
| T59 | `extraction_negation_recall >= 0.80` over the corpus subset labelled as negated, once that subset can carry a number. **Split out of T16 2026-08-23** — its gate declares `status-key: negation_status`, so "2 negated labels against a floor of 10" records as unmeasured rather than as a hard failure | 8 | M | T25 | `extraction_negation_recall >= 0.80` | `test_negated_labels_are_recovered` in `tests/test_negation.py` — recall ≥ 0.80 over the negated subset, once the subset can carry one | ☐ |
| T17 | `ontology_hit_rate` reporting and staleness signal: every stated concept counted into mapped or unmapped, never dropped. **Acceptance split 2026-08-22 on D-12's precedent** — the threshold half is T57, because the only committed concept source was read by a pass handed the dimension list and so cannot report an unmapped concept | 8 | S | T15 | `discarded_concepts == 0` | `test_unmapped_concepts_are_counted_not_discarded` in `tests/test_ontology_health.py`, and `test_a_source_that_cannot_report_unmapped_concepts_leaves_the_rate_unmeasured`, which asserts the refusal rather than describing it | ☑ |
| T57 | `ontology_hit_rate >= 0.85` once a read pass over a corpus wide enough to fall outside the model is allowed to name what it cannot map. **Split out of T17 2026-08-22** — its gate declares `status-key: ontology_status`, so "no source can yet contradict a 1.0" records as unmeasured rather than as a hard failure | 8 | M | T25 | `ontology_hit_rate >= 0.85` | `test_unmapped_concepts_are_counted_not_discarded` in `tests/test_ontology_health.py`, extended to the widened model | ☐ |
| T42 | Local annotation pass: `annotations/<offer_id>.json`, the offer read against *this* candidate's constraints and weights, computed on this machine and never sent with the advert | 8 | M | T15, T24 | `annotation_profile_egress == 0` | `test_no_profile_bytes_appear_in_an_extraction_payload` in `tests/test_annotation.py` — 2 planted strings scanned against ~28 kB of what `model_request` would really send for 12 corpus adverts; `test_the_egress_check_would_notice_a_planted_leak`, so the metric cannot pass by having no teeth; `test_annotation_is_recomputed_when_constraints_change`; `test_extraction_schema_stays_candidate_independent` | ☑ |
| T43 | Outside-the-advert enrichment for adverts that say almost nothing, marked as not from the ad and excluded from verbatim spans | 8 | M | T15, T19 | `outside_source_spans_in_explanations == 0` | `test_outside_information_is_marked_not_from_the_advert` in `tests/test_enrichment.py`; `test_an_explanation_never_cites_an_outside_source_as_the_employer`; `test_lookup_is_skipped_when_the_candidate_declined_it` | ☐ |
| T18 | Pareto frontier + salary-equivalent ordering + facet lists, pinned to a profile revision and a sufficiency level | 9 | L | T10, T15 | `pareto_dominance_violations == 0` | `test_dominated_offer_never_appears_in_frontier` in `tests/test_rank.py`; `test_unknown_dimension_is_not_treated_as_neutral`; `test_ranking_records_its_revision_and_level` | ☐ |
| T19 | Explanations citing verbatim evidence spans and €/month contributions | 9 | M | T18 | `explained_fraction == 1.0` | `test_every_ranked_offer_cites_evidence` in `tests/test_explain.py` — each ranked offer carries ≥1 verbatim span per contributing dimension | ☐ |
| T44 | Ranking presentation: the offer card as a template filled from normalised JSON — facts as bullets, one plain line including the bad part, unknown shown as unknown, provisional labelled | 9 | M | T18, T19, T33 | `provisional_rankings_unlabelled == 0` | `test_l1_ranking_is_labelled_provisional` in `tests/test_presentation.py`; `test_unknown_field_renders_as_unknown_not_neutral`; `test_card_is_filled_from_json_not_generated_per_offer` | ☐ |
| T20a | The calibration harness for T20: draw 20 from the evaluation split, present them blind, record the ordering, compute `rank_spearman`. **Split out of T20 2026-08-24** — T20 is `[HUMAN]` and so excluded from the selector, which left the 90% of it that is software unbuildable by either half of the system | 9 | M | T9, T19 | `blind_ranking_leaks == 0` | `test_the_presentation_order_is_independent_of_the_system_ranking` in `tests/test_calibration.py`; `test_no_score_or_explanation_reaches_the_blind_page`; `test_spearman_matches_a_known_order`; `test_rank_spearman_is_unmeasured_until_an_ordering_is_recorded`; `test_the_twenty_are_drawn_from_the_evaluation_split_only` | ☐ |
| T20 | **[HUMAN]** Calibrate ranking against blind manual ranking of 20 held-out ads | 9 | M | T9, T19, T20a | `rank_spearman >= 0.60` | `test_ranking_correlates_with_manual_order` in `tests/test_calibration.py` — Spearman ρ ≥ 0.60 against the recorded manual order | ☐ |
| T76 | The eligibility gate: a stated, role-level bar the candidate cannot meet excludes the offer before scoring — "silence is not permission", and a company-wide welcome to international applicants is not role-level permission | 9 | L | T11 | `offers_ranked_despite_a_stated_disqualification == 0` | `test_a_stated_citizenship_requirement_excludes_the_offer` in `tests/test_eligibility.py`; `test_silence_about_permits_is_not_a_disqualification`; `test_a_company_wide_statement_is_not_role_level_permission` | ☐ |
| T77 | Every verdict carries the advert's own sentence — a veto with no quote is unfalsifiable — and the quote must be a span of the advert text, never of an outside source | 9 | S | T76 | `disqualification_verdicts_without_quoted_wording == 0` | `test_every_fail_verdict_carries_the_adverts_own_sentence` in `tests/test_eligibility.py`; `test_a_verdict_quote_is_a_span_of_the_advert_text`; `test_a_flag_verdict_quotes_too` | ☐ |
| T78 | `language_requirement` as its own hard field, read by the gate and never by the ranker so a preference weight cannot cancel a legal bar; it records the role's stated requirement, not the language the advert happens to be written in | 9 | M | T76 | `gate_fields_read_by_the_ranker == 0` | `test_a_hard_gate_field_is_never_read_by_the_ranker` in `tests/test_eligibility.py`; `test_a_dimension_weight_cannot_change_a_gate_verdict`; `test_the_role_language_is_read_not_the_adverts_own_language` | ☐ |
| T79 | Ranking shows an Excluded section carrying each exclusion's quoted reason, and a `FLAG` offer stays ranked with its marker — the withheld count is reported, never silently dropped | 9 | M | T18, T76 | `excluded_offers_shown_without_a_reason == 0` | `test_an_excluded_offer_appears_with_its_quoted_reason` in `tests/test_ranking.py`; `test_an_excluded_offer_is_not_on_the_frontier`; `test_a_flagged_offer_is_ranked_with_its_marker` | ☐ |
| T87 | The Excluded section on the page: `presentation.render()` reads `ranking["excluded"]` and shows each removed offer with the advert's own sentence, a `FLAG` offer is carded with its marker, and the excluded count is stated rather than implied by a truncated list | 9 | M | T79 | `excluded_offers_missing_from_the_page == 0` | `test_an_excluded_offer_appears_on_the_page_with_its_quote` in `tests/test_presentation.py`; `test_an_excluded_offer_gets_no_card`; `test_a_flagged_offer_is_carded_with_its_marker`; `test_the_page_reports_the_excluded_count_even_when_the_list_is_long` | ☐ |

### DOCUMENT — the CV store, generated documents, interviews

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| S4 | CV store: import pdf/docx into `cv/master.json`, or build the same store by conversation with someone who has no CV. Pins the `master.json` contract | 1 | L | S1, T6, T8 | `intake_field_provenance == 1.0` | `test_every_master_field_names_its_source` in `tests/test_cv_store.py` — every field traces to a document span or a conversation turn; `test_candidate_with_no_cv_reaches_the_same_store`; `test_source_document_is_never_modified` | ☑ |
| T45 | Per-advert generation: CV and letter drawn only from store entries, versioned `v<N>` and never overwritten, with a claim→store manifest | 11 | L | S4, S5, T15 | `cv_generation_traceability == 1.0` | `test_every_claim_traces_to_a_store_entry` in `tests/test_generate.py`; `test_regeneration_writes_a_new_version`; `test_advert_wording_is_mirrored_only_over_held_ground` | ☑ |
| T46 | Personal details collected at the point of use, per-use approval for story episodes, and the send boundary: prepared documents, text to paste, an email left in drafts | 11 | M | T45 | `unapproved_episode_disclosures == 0` | `test_episode_without_per_use_approval_never_enters_a_document` in `tests/test_approval.py`; `test_personal_details_are_asked_at_step_eleven_not_at_intake`; `test_nothing_is_sent_without_an_explicit_per_item_approval` | ☐ |
| S6 | Interview: preparation from the advert, the application and earlier interviews; then the log — questions asked, outcome, lessons — immutable and exempt from purge | 12 | L | S1, T8, T45 | `interview_lesson_linkage == 1.0` | `test_every_logged_interview_produces_a_linked_evidence_row` in `tests/test_interview_log.py`; `test_interview_record_is_immutable`; `test_outcome_arriving_days_later_resumes_the_record` | ☑ |
| T47 | The mock interview: a strict role-play announced before it starts, no coaching mid-answer, no breaking character, with dictation offered and feedback only at the end | 12 | M | S6 | `mock_interview_character_breaks == 0` | `test_no_coaching_turn_occurs_inside_the_roleplay` in `tests/test_mock_interview.py`; `test_roleplay_is_announced_before_it_begins`; `test_feedback_is_given_only_after_it_ends` | ☐ |
| T80 | The ATS text-layer contract, asserted over the generated document text so it is renderer-independent: contact e-mail, telephone and every employment date present as literal text, with no mojibake | 11 | M | T45 | `documents_missing_a_required_text_layer_field == 0` | `test_a_generated_cv_carries_contact_email_as_literal_text` in `tests/test_ats.py`; `test_a_document_missing_a_required_field_fails`; `test_a_replacement_character_in_the_text_layer_fails` | ☐ |
| T81 | Keyword coverage against the posting in four statuses, so a document bug stays distinguishable from a candidate gap: `covered`, `synonym-only`, `missing (have it)`, `missing (gap)` — and never keyword stuffing | 11 | M | T80 | `posting_keywords_left_unclassified == 0` | `test_every_posting_keyword_receives_exactly_one_status` in `tests/test_ats.py`; `test_a_keyword_the_store_holds_but_the_document_omits_is_missing_have_it`; `test_a_keyword_the_candidate_lacks_is_missing_gap` | ☐ |
| T82 | The application status vocabulary — `drafted`, `applied`, `interview`, `offer`, `hired`, `rejected`, `no_response`, `offer_declined`, `withdrawn`, split Open and Final — with legacy space-spellings accepted on read and never written | 11 | M | T45 | `applications_with_a_noncanonical_status == 0` | `test_a_status_outside_the_vocabulary_is_refused` in `tests/test_lifecycle.py`; `test_a_legacy_spelling_is_accepted_on_read_and_never_written`; `test_open_and_final_statuses_are_distinguishable` | ☐ |
| T84 | Step 11's two drafting rules, in prose: relevance-weighted cutting scored by relevance, uniqueness and narrative load; and the interview backtrack test for a line the candidate could not defend in the room | 11 | S | — | `step_skills_without_the_drafting_rules == 0` | `test_step_eleven_states_the_relevance_weighted_cut_rule` in `tests/test_step_skills.py`; `test_step_eleven_states_the_interview_backtrack_test`; `test_the_cut_rule_names_narrative_load` | ☐ |

### Specification — the documents this plan is built on

These produced no code beyond their own checkers, and they are listed so the
plan is a complete ledger of the queue rather than of the implementation only.

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| S1 | Specification v2 — the whole process: steps, connections, artefact tree, lifecycle, resumption | all | L | — | `process_spec_complete == 1` | `test_every_required_item_is_present` in `tests/test_process_spec.py` | ☑ |
| S1r | Specification v2.1 — the owner's sixteen review annotations folded in | all | M | S1 | `process_spec_complete == 1` | `test_required_subset_closure_is_stated` in `tests/test_process_spec.py` | ☑ |
| S2 | One specification per step, twelve fields each | all | L | S1, S1r | `step_specs_complete_fraction == 1.0` | `test_every_step_carries_every_field` in `tests/test_step_specs.py`; `test_divisor_is_the_settled_step_count` | ☑ |
| S2r | The owner's twelve step-spec annotations folded in | all | M | S2 | `step_specs_complete_fraction == 1.0` | `test_duplicate_step_heading_does_not_collapse` in `tests/test_step_specs.py` | ☑ |
| S8 | This plan — the build order for the thirteen-step process, and the queue reconciled against it | all | M | S2r | `plan_queue_task_drift == 0` | `test_task_in_the_queue_without_a_plan_row_is_drift` in `tests/test_plan_v2.py`; `test_a_payload_gate_differing_from_the_plan_is_drift`; `test_a_plan_dependency_missing_from_the_queue_is_drift`; `test_evidence_log_is_not_read_as_a_task_table` | ◐ |
| S9 | Convert `claude-arsenal` from a vendored copy to a git subtree at a separate prefix, so upgrades are `git subtree pull` and the `ARSENAL_SHA` pin can go | all | M | — | `vendored_files_diverging_from_subtree == 0` | `test_every_bundle_file_matches_the_subtree_source` in `tests/test_arsenal_subtree.py`; `test_no_host_owned_path_is_inside_a_subtree_prefix`; `test_the_makefile_no_longer_pins_a_bare_sha` | ☑ |
| S10 | The skill listing budget (8,000 chars, a per-turn context cost) is exceeded at 11,140 once the thirteen step skills land. **Decided: raise it — to 13,000, set in `arsenal/config.toml`'s `listing-budget`** and measured by `integral.skill_budget`, since upstream's auditor does not yet read that key and `vendor/` must not be patched. The declared number must be round and leave headroom, and the reading records its source, so a cap fitted to the measurement fails instead of passing after | all | M | S7 | `skill_listing_budget_overage_chars == 0` | `test_the_library_is_within_its_listing_budget` in `tests/test_step_skills.py`; `test_every_step_is_still_reachable_after_the_change` — the saving may not come from dropping a step | ☑ |
| T58 | Drop the `claude-arsenal` subtree: `/init` writes the skills, the runtime tree and the skill-edit gate, so there is nothing to pull or reconcile. `vendor/`, `verify-subtree`, `arsenal-upgrade`, `update-skills` and `assemble-bundle` all retire and `host-gate` drops to four targets. **This supersedes S9.** The skills stay **committed**: a cloud session runs on a fresh clone and installs no plugins the repo asks for, verified live upstream (`claude-arsenal#200`), so the gate asserts two opposite counts — no subtree, and skills present | all | M | S9 | `upstream_subtree_files == 0` | `test_no_upstream_subtree_is_maintained` and `test_the_skills_are_committed_not_installed` in `tests/test_arsenal_source.py`; `test_re_adding_a_subtree_is_counted` and `test_an_unmarked_skill_directory_is_not_counted_as_vendored`, so neither number can pass by having no teeth | ☑ |
| S11 | Test mode — an orthogonal meta channel (`[[...]]`) for capturing notes about the tool during a live session, without disturbing it; notes are shown at the end and seeded only once confirmed | all | M | S7, S10 | `test_notes_reaching_candidate_evidence == 0` | `test_a_meta_note_never_reaches_the_evidence_log` in `tests/test_test_mode.py`; `test_a_pasted_advert_containing_brackets_is_not_eaten`; `test_the_visible_conversation_is_byte_identical_with_and_without_notes` | ☑ |
| S12 | Move "does this step take candidate free text" into `spec-v2-steps.json` so `profile_capture`'s denominator is fully machine-derived, instead of a hand-made map T28 guards but cannot derive | all | M | T28 | `unclassified_free_text_steps == 0` | `test_every_step_declares_whether_it_takes_candidate_free_text` in `tests/test_profile_capture.py`; `test_profile_capture_reads_the_declaration_not_a_local_map`; `test_coverage_is_unchanged_by_the_migration` | ☐ |
| T55 | Rename the project to `integral-job-search`: package path, imports, distribution and entry points, repository name and the documents that spell it out — while `$INTEGRAL_HOME`, the arsenal bundle and the thirteen step-skill directories keep their names | — | M | — | `old_name_references == 0` | `test_no_module_imports_the_old_package_name` in `tests/test_naming.py`; `test_no_document_names_the_old_repository`; `test_the_preserved_names_are_not_swept` | ☐ |
| T85 | The evidence run reaches every module that writes evidence. `make evidence` selects on `^def _main`, so `plan_v2`, `process_spec` and `step_specs` were never regenerated or drift-checked — `S8.json` read 81 rows against 107 measured while the gate printed "no drift". Fix the **selection**, not the three names | all | S | — | `gate_modules_outside_the_evidence_run == 0` | `test_every_module_writing_evidence_is_reached_by_the_evidence_run` in `tests/test_repo_gate.py`; `test_a_module_that_writes_evidence_and_is_missed_fails_the_check`; `test_the_selection_does_not_depend_on_a_private_name_convention` | ☐ |
| T86 | eligibility: a scoped citizenship / right-to-work vocabulary for ES/EN/CA, so `DE` clears "German citizenship" while `ES` does not — and a term outside the table resolves to FLAG, never a confident FAIL. Not a world gazetteer: coverage is a quality dial, incompleteness degrades to "a human decides". Clearances stay out of scope by decision | 9 | M | T76 | `false_disqualifications == 0` | `test_a_candidate_who_holds_the_required_citizenship_passes_it` in `tests/test_eligibility.py`; `test_a_target_outside_the_vocabulary_flags_rather_than_fails`; `test_the_false_disqualification_gate_fails_on_the_pre_fix_code_path` | ☐ |
| T88 | Language parity across every supported language: a scoped language vocabulary so `es`/`Spanish`/`español` are one fact rather than three, requirement patterns in ES and CA as well as EN so a Spanish advert stating a bar is not read as silence, and the same bar reaching the same verdict in all three | 9 | M | T86 | `cross_language_verdict_disagreements == 0` | `test_a_language_is_recognised_under_every_supported_spelling` in `tests/test_eligibility.py`; `test_the_same_bar_in_three_languages_reaches_the_same_verdict`; `test_a_spanish_advert_stating_a_bar_is_not_read_as_silence`; `test_an_unknown_language_flags_rather_than_fails` | ☐ |
| T89 | A connector may only issue a GET, so a board whose search is a POST is unreachable however public it is. `ListPage.url_pattern` is a URL with nowhere to put a method or a body. usajobs.gov answers `POST /Search/ExecuteSearch` with 25 rows to a plain curl — no key, no cookie — and sits in `ruled-out.yaml` under `corrected` describing a surface nothing here can fetch. A literal declared body, never a templated one — the single exception is `{page}` as a whole JSON value, substituted on the parsed structure rather than in the serialised text, with a brace anywhere else refused at load | 7 | M | T32 | `boards_readable_only_by_post == 0` | `test_a_list_page_may_declare_a_post_method_and_a_literal_body` in `tests/test_connectors.py`; `test_a_templated_request_body_is_refused_at_load`; `test_the_page_placeholder_substitutes_as_a_json_number`; `test_the_usajobs_package_parses_its_fixture_to_offers` | ☐ |
| T90 | A constraint the candidate stated is not applied to the next search. Fintech, e-commerce, frontend and cloud were each ruled out in words and each kept arriving — the candidate's own diagnosis was the right question, *"are you adding filters with everything I'm telling you?"*. A rank penalty is not an exclusion: a demoted advert still appears, which is what reads as not listening. The exclusion has to reach the query, and where a strong match overrides it that must be named rather than silent. From the live session of 2026-08-30 | 7 | S | — | `restated_exclusions_resurfaced == 0` | `test_an_exclusion_stated_at_cycle_n_shapes_the_query_at_cycle_n_plus_1` in `tests/test_sourcing_exclusions.py`; `test_a_penalised_offer_still_counts_as_resurfaced`; `test_an_exclusion_overridden_by_a_strong_match_is_named_not_silent` | ☑ |
| T91 | The sourcing loop stops at the connectors that already exist and calls that exhausted. `judge_cycle` measures exhaustion and `apply_scope_change` widens scope, but neither can propose **building a connector**, so "exhausted" is a statement about our coverage dressed as a statement about the market — three adverts, then a stop. The candidate wrote the missing loop out in eight steps. Carries two riders from the same thread: say what a connector is and that sharing it helps, and give a connector written mid-session a home before it is uploaded | 7 | L | T94 | `sourcing_stops_without_naming_an_unreadable_board == 0` | `test_an_exhausted_cycle_names_a_site_it_cannot_read` in `tests/test_sourcing_connector_gap.py`; `test_the_proposal_says_what_a_connector_is_and_that_sharing_helps`; `test_a_connector_written_mid_session_has_a_home_before_it_is_uploaded`; `test_a_library_miss_is_never_reported_as_a_market_miss` | ☐ |
| T92 | An advert with no salary is dropped and nobody looked for the figure. The *no salary and no cheap approximation therefore not shown* rule removed **13 of 17** survivors in round 3, so salary silence rather than salary level is what bounds what a candidate sees. Two lookups go unattempted: a canonical duplicate that does state a band (`dedup.py` already finds them), and the board's own detail route. An approximation is acceptable if labelled — and must never reach `Salary(stated=True)`, which is the getmanfred scale bug one layer up | 7 | M | — | `salary_silent_offers_dropped_without_a_lookup == 0` | `test_a_duplicate_that_states_a_band_supplies_the_silent_copy` in `tests/test_salary_recovery.py`; `test_a_detail_route_is_read_before_a_silent_offer_is_dropped`; `test_an_estimate_never_reads_as_stated`; `test_an_estimate_carries_its_basis`; `test_a_still_silent_offer_is_dropped_only_after_both_lookups` | ☐ |
| T93 | The session offers where it should lead. The candidate asked to be directed (*"You know what is needed, not the user"*), drawn out (*"You must induce the user to talk as much as possible"*), and followed up on (*"Anything that intrigued you about the CV, you must pull the string"*). The concrete miss — a developer never asked about their public repositories — generalises to asking for whatever artefacts the candidate's own field produces. Must not turn T36's consent boundary into coercion: the choice stays the candidate's, the recommendation becomes ours | 3 | M | T36 | `steps_offered_without_a_recommendation == 0` | `test_every_offered_step_carries_a_recommendation_and_a_reason` in `tests/test_interview_direction.py`; `test_a_declined_recommendation_is_still_honoured`; `test_the_opening_invites_open_ended_talk`; `test_an_unexplained_detail_in_the_intake_produces_a_follow_up_question`; `test_the_artefact_question_follows_the_candidates_field` | ☑ |
| T94 | Hundreds of adverts arrive and nothing filters them but a person. The JSON connectors return whole result sets in one request; the pipeline behind them was built for the handful a manual round produced. This is what makes T91 safe — a loop that keeps adding connectors is only an improvement if what they return reduces without a person, otherwise more coverage is more work. Bounded to **filter, not rank**: hard constraints, eligibility, expiry, duplicates and stated exclusions, and every rejection records the rule that dropped it | 7 | M | — | `bulk_offers_requiring_manual_triage == 0` | `test_a_few_hundred_offers_reduce_without_a_human_decision` in `tests/test_bulk_filter.py`; `test_every_rejection_records_which_rule_dropped_it`; `test_the_filter_never_drops_on_a_soft_preference` | ☐ |
| T95 | What reaches the candidate in one turn: too few adverts, and our vocabulary. Four adverts was too few — the instinct against long lists was right, the quantity was not, and the ask is the same total in two or three chunks. `"pasamos a convertir esto en pesos para el ranking"` leaked internal machinery before anything introduced it; `vocabulary_reach.py` does **not** cover this, it measures dimension coverage per market, a different sense of the word. Summaries themselves were right and need only a complete field set | 5 | S | — | `internal_terms_used_before_introduction == 0` | `test_a_batch_is_chunked_rather_than_truncated` in `tests/test_presentation_register.py`; `test_an_internal_term_is_introduced_before_it_is_used`; `test_a_summary_carries_every_field_a_decision_needs` | ☐ |
| T96 | The preference elicitation asked a question with no coherent answer — *"7 is weird. Given the same job, always better more money."* Step 6 asked for a level rating on a **monotone** dimension, where one end of the scale is incoherent, so the answer is cooperation with a malformed question and `weights.py` fits a part-worth to noise. The fix is a property of the question bank rather than of the fitter: a dimension declared monotone may not produce a level-rating item, and is elicited as a trade-off instead | 6 | S | — | `monotone_dimensions_asked_as_level_ratings == 0` | `test_a_monotone_dimension_never_yields_a_level_rating_item` in `tests/test_question_bank_monotone.py`; `test_pay_is_declared_monotone`; `test_a_monotone_dimension_is_elicited_as_a_trade_off`; `test_an_answer_to_a_retired_malformed_item_does_not_reach_the_fit` | ☐ |
| T97 | Step 1 could not read the CV and carried on. Every later step then ran on a thinner profile than the candidate had supplied, and nothing said so. Two failures to separate because they need different fixes: the file arriving as text at all (`ats.py` owns the text-layer contract) and knowing which fields the document should yield. A partial read is acceptable; a partial read that reports success is what leaves the candidate answering questions the CV already answered | 1 | S | — | `unreported_cv_read_failures == 0` | `test_an_unreadable_cv_is_reported_not_skipped` in `tests/test_intake_cv.py`; `test_a_partially_read_cv_names_what_it_could_not_extract`; `test_the_profile_records_which_fields_came_from_the_document`; `test_a_failed_read_does_not_certify_step_1` | ☐ |
| T98 | The corpus is a measurement set, not a serving cache — and it must not be one candidate's search. Owner ruling, twice: no candidate is ever served from stored adverts, because an advert is perishable and using the corpus as a source is what let one session return three and call the market exhausted. The ~2,755 rows the live session harvested are also the wrong sample to *measure* on — they are one person's queries, and an accuracy computed there would be quoted for everyone. The connector library replaces both: a corpus drawn by specification, reproducible, and enrichable for the eligibility labels D-23 actually needs | 7 | M | — | `corpus_rows_without_a_draw_specification == 0` | `test_no_ranking_path_reads_the_corpus_as_an_offer_source` in `tests/test_corpus_scope.py`; `test_every_corpus_row_records_the_draw_that_produced_it` in `tests/test_corpus_provenance.py`; `test_a_row_harvested_for_one_candidate_is_refused`; `test_a_draw_is_reproducible_from_its_specification` | ☐ |
| T99 | The owner's robots stance and the ledger's refusals do not agree. `policy_refused` holds remoteok.com — robots **allows** the endpoint under RFC 9309 group semantics and we refuse anyway, on legible intent. The owner had already stated the opposite during the session: it is the candidate who runs the scraper, and a board that forbids AI ingestion still permits a search. The defect is not which way it resolves but that the implementing session decided it alone and the ledger reads as though an owner had. Resolve in writing; if the stance holds, narrow the section to **volume** rather than access and re-test remoteok against it | 7 | S | T71 | `policy_refusals_without_an_owner_decision == 0` | `test_every_policy_refusal_cites_an_owner_decision_with_a_date` in `tests/test_connector_policy.py`; `test_a_refusal_distinguishes_volume_from_access`; `test_a_board_allowed_by_robots_is_never_refused_without_a_cited_rule` | ☑ |
| T100 | `open_task_pr.sh` cannot open a PR here: it runs the host gate on both sides of the task-file archive (`:227`, `:627`) and `T55.files_scanned` differs across the move — 615 before, 614 after — so no committed value satisfies both runs. Bundle v3.2.0 did **not** fix this; the v3.1.14 changelog only says so (`claude-arsenal#336`). Counting `_history/` is the wrong repair — those rows legitimately carry the old name and may never be edited. The fault is that a **denominator** is committed as an exact value; assert it as a floor, the pattern `retraction.py` already uses, and keep `old_name_references == 0` exact | — | S | — | `archive_sensitive_evidence_keys == 0` | `test_files_scanned_is_asserted_as_a_floor_not_a_census` in `tests/test_naming.py`; `test_an_empty_scan_still_fails`; `test_archiving_a_task_file_does_not_change_any_asserted_value` | ☑ |
| T101 | A CI job can name a Makefile target that does not exist. `integral.repo_gate` (D-22) reads every `make <target>` out of `CLAUDE.md`, asserts it is a real rule and asserts `host-gate` reaches it — and `DEFAULT_INSTRUCTIONS` is `CLAUDE.md` and nothing else, so the identical hole in `.github/workflows/` stayed open. `verify-subtree` lost its target in #123 and its job kept calling it, red on every run until 2026-09-01 and invisible while the runner outage failed everything. #267 deleted the job; this is the check. Assert only that a target **named in CI exists** — the converse would be false on a correct repo, since `format`, `clean` and `build` are deliberately not CI steps | all | S | — | `ci_targets_missing_from_makefile == 0` | `test_a_workflow_naming_an_absent_target_is_reported` in `tests/test_repo_gate.py`; `test_a_target_named_only_in_a_comment_is_not_read_as_a_step`; `test_a_multi_line_run_block_is_read`; `test_a_target_the_makefile_defines_but_ci_never_runs_is_not_a_violation` | ☐ |
| T102 | Case 22 of the round-2 T70 audit, the one case of 33 left uncommitted: does a robots product token match as a **prefix** of a longer crawler token? `User-agent: Bot` against crawler `Botly` — `_select_rules` compares by equality, so no group matches and the fetch is permitted. If RFC 9309 requires the match, a site writing one `googlebot` rule intending to cover `Googlebot-Image` governs neither. Derive the verdict from §2.2.1 before opening `robots.py`; whichever way it falls the case becomes a fixture, and the reverse direction gets its own | 7 | S | — | `uncommitted_audit_cases == 0` | `test_a_file_token_shorter_than_the_crawler_token_matches_per_rfc_9309` in `tests/test_robots.py`; `test_the_reverse_direction_is_asserted_separately`; `test_the_case_22_fixture_cites_the_section_it_was_derived_from` | ☐ |
| T103 | `merge-policy` is `after-review` because CI could not run; runners returned on 2026-09-01 and it should be `after-ci-and-review`. The dependency on T101 is not bookkeeping: the policy makes a red check blocking, so it may only be set over a CI that is green for real reasons — set while a permanently-failing job stood, it would have wedged the repository, and unwedging it would have meant weakening the policy again. Two preconditions, because the policy is a claim about Actions conclusions rather than about `make ci`: T101's key present and zero, and a recent green CI conclusion on `main` | all | S | T101 | `merge_policy_ignores_ci == 0` | `test_the_configured_merge_policy_requires_ci`; D-22 must carry `ci_targets_missing_from_makefile` and it must be 0 (T101 adds the key — its absence fails the gate legibly rather than as a `KeyError`); the latest `CI` run on `main` must have concluded `success` | ☐ |
| T83 | Attribution: an Acknowledgements section in `README.md`, and a `docs/METHODS.md` entry per borrowed technique naming its upstream source and its limits | all | S | T70, T71, T72, T73, T74, T75, T76, T77, T78, T79, T80, T81, T82, T84 | `borrowed_techniques_without_attribution == 0` | `test_every_borrowed_technique_has_a_methods_entry` in `tests/test_methods_links.py`; `test_the_readme_carries_an_acknowledgements_section`; `test_each_entry_names_its_upstream_source` | ☐ |

### Divergences

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| D-1 | Catalan corpus slice covers IT roles at large, not remote programming as T4b specifies | 8 | S | — | `corpus_language_slice_mismatch == 0` | `test_every_language_slice_matches_its_declared_scope` in `tests/test_corpus_raw.py` | ☑ |
| D-2 | v0 gold examples are cue-derived, not independent — T15 must measure `extraction_macro_f1` against independent labels | 8 | S | T5 | `cue_derived_gold_in_evaluation_split == 0` | `test_no_evaluation_example_is_derived_from_a_cue` in `tests/test_dimension_content.py` — the file this row named (`tests/test_corpus_content.py`) was never created, and the subject is the dimension model's gold set rather than the corpus | ☑ |
| D-3 | `story_failure_fraction` floor contradicts the revised History protocol; reconcile `status/specification.md` and `docs/METHODS.md` | 3 | S | — | `spec_gate_contradictions == 0` | `test_no_document_states_a_superseded_gate` in `tests/test_spec_consistency.py` — the floor appears nowhere as a gate, and the fraction is reported | ☑ |
| D-4 | The Traits gate is assigned to T28 by the specification and to T27 by the work; neither task's own gate is the step metric | 4 | S | — | `trait_gate_owner_contradictions == 0` | `test_step_gate_metric_is_some_task_gate` in `tests/test_step_gates.py` — every step gate metric is some task's acceptance gate; `test_no_two_documents_name_different_owners_for_one_step_gate` | ☑ |
| D-6 | `rebuild()` writes only `stated` rows to `constraints.json`, so a refresh after the constraints step drops every `declined` and `unknown` field — the refusal T40 depends on reverts to never-asked | 2 | S | T41 | `constraint_states_survive_rebuild == 1.0` | `test_a_declined_field_survives_a_rebuild` in `tests/test_revision.py`; `test_an_unknown_field_survives_a_rebuild` — both must fail before the fix | ☑ |
| D-7 | `spec-v2-steps.md` names two owners for the Ranking gate (T18, T19) while the JSON names one (T19); same class as D-4 | 9 | S | — | `step_gate_owner_contradictions == 0` | `test_every_step_gate_names_exactly_one_owner` in `tests/test_step_specs.py`; `test_the_gate_task_is_the_task_that_writes_the_metric`; `test_no_prose_document_names_a_different_owner_than_the_json` | ☑ |
| D-8 | Captured evidence cannot say which offer a reason was about — `EvidenceRow` carries `step`, `source` and `recorded_at`, so T28's required provenance "in response to what" is unmet and two rejections of two different jobs are indistinguishable in the log | 4 | M | T28, T6 | `captures_without_a_subject == 0` | `test_two_rejections_of_different_offers_are_distinguishable_in_the_log` in `tests/test_profile_capture.py`; `test_a_captured_reason_survives_rebuild_with_its_subject`; `test_an_answer_to_a_question_needs_no_subject_field` | ☑ |
| D-9 | Non-insistence is not honoured on intake's conversational write path — `cv_store.py` is the only free-text writer with no `DeclineLedger` reference, so `add_conversation_entry` records an answer on a subject the candidate declined and has not reopened, the outcome T40 exists to prevent | 1 | M | S4, T40 | `intake_declined_subjects_written == 0` | `test_a_declined_subject_is_not_written_by_the_conversational_path` in `tests/test_cv_store.py`; `test_a_reopened_decline_lets_the_subject_be_recorded_again` — the second so the fix cannot be “never write anything” | ☐ |
| D-10 | `connectors/<site-id>/parse.py` is in the shared connector shape (`docs/distribution.md` §5) but nothing executes it — a connector for a site the declarative form cannot express passes the whole conformance check and cannot work. **Resolved 2026-08-20 by withdrawing `parse.py` from the shape** rather than sandboxing it: real isolation is a milestone, the hatch had no user, and T54 was already written assuming it was gone | 7 | M | T53 | `advertised_connector_mechanisms_without_a_runtime == 0` | `test_every_file_named_in_the_shared_shape_has_a_runtime_or_is_not_advertised` in `tests/test_connector_contract.py` | ☑ |
| D-11 | The conformance command §5 hands a contributor — `--connectors <their dir>` — wrote *this* repository's `status/evidence/T53.json`, so a check over somebody else's library replaced the number T53's gate is asserted against. Found by running the documented command once while investigating D-10 | 7 | S | T53 | `evidence_writes_for_a_foreign_library == 0` | `test_the_contributors_command_leaves_our_committed_evidence_alone` in `tests/test_connector_contract.py`; `test_the_gate_still_records_when_the_caller_names_a_destination`; `test_the_foreign_write_metric_is_measured_over_the_real_decision` | ☑ |
| D-12 | D-2 binds T15 to three outcomes — a score, a failure, or **unmeasured** — and the gate layer had only two: it read the null that `extraction_macro_f1` honestly is as a `non-numeric value` and hard-failed, so T15 could never reach terminal and the fifteen tasks behind it stayed blocked. **Resolved 2026-08-22**: upstream's `status-key` third outcome (claude-arsenal#168) landed and is now used, and T15's acceptance is split so the scoring half (T56) waits behind the corpus instead of holding the queue | 8 | M | — | `unrecordable_task_gates == 0` | `test_a_task_whose_metric_is_unmeasured_is_not_reported_as_failing` in `tests/test_task_gate.py` — the state "not broken, not yet measurable" must be distinguishable from "scored 0" | ☐ |
| D-13 | Every step skill opens work before acknowledging the person: profile creation, script runs and file writes happen in silence while the candidate waits, and no skill's protocol requires saying what is being done | 0 | S | — | `step_skills_without_a_progress_disclosure_rule == 0` | `test_every_step_skill_requires_acknowledging_before_a_silent_setup` in `tests/test_step_skills.py` | ☑ |
| D-14 | The employment-mode question offers `autónomo`/`falso autónomo` as a mode the candidate might want; falso autónomo is an illegal arrangement, so it may be asked about as a status but never offered as an option | 2 | S | — | `skills_offering_an_illegal_employment_mode == 0` | `test_no_skill_offers_falso_autonomo_as_a_choice` in `tests/test_step_skills.py` | ☑ |
| D-15 | Every step skill's Boundary example closes by offering to end the session, so a candidate who answers four steps is asked four times whether they want to stop — §2.5's right to decline becomes a prompt to leave | — | S | — | `step_boundaries_offering_an_exit == 0` | `test_a_step_boundary_does_not_offer_to_end_the_session` in `tests/test_step_skills.py` | ☑ |
| D-16 | Sourcing has no connector for any real board — `connectors/` holds only `examplejobs_es`, whose own header says the site is fictitious — and step 7 presents web-search results without saying so or offering to build one | 7 | M | T32, T53 | `undisclosed_connectorless_sourcing == 0` | `test_sourcing_without_a_connector_says_so` in `tests/test_connectors.py`; `test_a_search_result_is_not_presented_as_a_connector_result` | ☑ |
| D-17 | The ranking card drops `offer.url` although every stored record carries it, so a candidate is shown seven offers with no way to reach any of them — the model assembled prose where T44 requires a filled template | 9 | S | T44 | `ranked_offers_without_a_url == 0` | `test_every_ranked_offer_renders_its_url` in `tests/test_ranking.py`; `test_an_offer_with_no_url_shows_the_absence` | ☐ |
| D-18 | Offers are collected from a search index and never checked at source: all seven sourced on 2026-08-20 were dead (403, or "puesto ocupado") while `offer_schema_violations` passed — schema validity is not liveness, and `integral.freshness` is not wired into the sourcing path | 7 | M | T11, T13 | `offers_presented_without_a_liveness_check == 0` | `test_a_dead_advert_is_marked_expired_not_offered` in `tests/test_dedup.py`; `test_a_search_index_hit_is_verified_at_source_before_it_becomes_an_offer` | ☑ |
| D-19 | The dimension model is entirely software-sector, so `extract()` settled 0 of 25 dimensions on all seven construction adverts and step 8 reported success over a vocabulary that matched nothing | 8 | L | — | `markets_with_no_applicable_dimension_reported_as_extracted == 0` | `test_an_extraction_that_settled_nothing_is_not_reported_as_read` in `tests/test_extract.py`; `test_every_supported_market_has_applicable_dimensions` | ☐ |
| D-20 | No pinned constraint field can hold a commutable radius: `location` takes a country, `reach` takes modes, and `relocation` refuses destinations when willingness is `no` — so "Barcelona province, at most Girona or Tarragona" survives only as quote text and nothing downstream can filter on it | 2 | M | T24, T41 | `unfilterable_stated_constraints == 0` | `test_a_stated_commute_radius_reaches_the_hard_constraint_filter` in `tests/test_candidate_attributes.py`; `test_no_stated_constraint_is_recorded_only_as_prose` | ☑ |
| D-21 | `run_checkpoint.py` reports `coverage_met: true` and exits 0 for a step whose gate is `not_implemented`, so steps 8 and 9 certified clean over an unbuilt gate — the inert-gate problem one level up, where artefact presence stands in for a check nobody ran | — | M | — | `steps_certified_on_an_unimplemented_gate == 0` | `test_a_step_with_an_unimplemented_gate_is_not_reported_as_met` in `tests/test_step_gates.py`; `test_an_implemented_gate_still_certifies` | ☑ |
| D-22 | The five-command repo gate `CLAUDE.md` requires before a merge is enforced by nothing: Actions is out of runner minutes so `ci.yml` and `arsenal-queue.yml` never run, `open_task_pr.sh` re-runs only the task's own payload gate, and `keyword-guard` fires only on `arsenal/**` branches — PR #89 fell through all three and `make test` failed on nine violations that would otherwise have merged. **Split:** the bundle half (worker.md asks for a host gate no script enforces) is upstream at `claude-arsenal#175`; this row is the host half — a `make host-gate` target for upstream's `host-gate` key to point at | — | M | — | `required_gates_with_no_enforcement_point == 0` | `test_every_gate_the_docs_require_has_a_runnable_enforcement_point` in `tests/test_plan_v2.py`; `test_a_task_pr_runs_the_repo_gate_not_only_its_payload_gate` | ☑ |
| D-23 | The eligibility and language gates are gated on **mechanism** over fixtures and never on **accuracy** over real adverts: no corpus labels exist for permit, citizenship, clearance or role-language requirements, so a gate firing wrongly on a Spanish advert passes every check in this increment. Filed per the D-12 precedent — the mechanism ships, the accuracy waits behind a corpus round | 9 | M | T76 | `unlabelled_gate_accuracy_claims == 0` | `test_no_document_claims_the_eligibility_gate_is_accurate_on_real_adverts` in `tests/test_spec_consistency.py`; `test_the_gate_reports_its_accuracy_as_unmeasured` | ☐ |
| D-24 | A retracted episode stays sendable: `measure_prepared` backs an episode line by `approvals.json` **and nothing else**, and nothing invalidates an approval when its evidence is retracted — `approval.py` never mentions retraction, `retraction.py` never mentions approval. Approve for `<offer>/v1`, retract the row, send `v1`: `record_sent` re-measures, finds the line backed, and records the send. §6.2 says an episode reaches an employer only with per-use approval, and retraction is how that approval's subject is withdrawn — the code keeps the approval and loses the withdrawal. **Fail-open.** The fix is not a store lookup (episode authority was deliberately routed away from list positions); it is to invalidate or re-confirm approvals when a retraction lands | — | M | T46 | `retracted_episodes_still_sendable == 0` | `test_a_retracted_episode_cannot_be_sent` in `tests/test_approval.py`; `test_an_unretracted_approval_still_sends` | ☐ |
| D-25 | `docs/simulation-prompt.md` §2 classifies all thirteen stages — eight faithful, four degraded, one manual — and every verdict was derived by reading the step skills, not by running anything. The file says so; nothing acts on it. Filed per the D-12 and D-23 precedent: the artifact ships, the measurement waits — here behind a real run of the tool itself, since comparing the simulation against more reasoning about the tool measures nothing. `requires: surface:human`, because no bot can hold the candidate side of either conversation | — | M | — | `simulation_stages_unverified == 0` | `test_every_stage_verdict_cites_an_observation` in `tests/test_simulation_parity.py`; `test_a_stage_with_no_observation_counts_as_unverified`; `test_an_observation_without_transcript_provenance_is_rejected`; `test_the_gate_reports_unmeasured_when_nothing_was_observed`; `test_a_verdict_changed_by_an_observation_is_recorded_not_overwritten`; `test_a_stage_observed_on_only_one_side_is_unverified` | ☐ |

**Status legend**: ☐ open · ◐ in progress · ☑ merged · ☒ cancelled (absorbed or abandoned; never done)

**Merge order** — four milestones. Within a milestone, order is the dependency
graph below; across milestones it is strict. Merged tasks (T1–T4b, T23) are not
listed; every open task appears in exactly one milestone.

| milestone | delivers | tasks |
|-----------|----------|-------|
| **M1 — the spine** | a candidate is identified, resumed and never mixed up with another; the graph can say what is owed | S3, T6, T35, T30, T34, T37, T36, T38, T40, T48 |
| **M2 — L1, a rough list end to end** | constraints → offers → extraction → annotation → a provisional, labelled ranking | T24, T41, T11, T32, T12, T13, S5, T14, T15, T16, T17, T42, T18, T19, T33, T44, D-6, D-7 |
| **M3 — L2, the full first run** | history, traits, reactions, weights, feedback — the ranking gets sharp and the loop closes | T7, T8, T27, T5, T9, T10, T39, T21, T28, T49, T50, T20a, T20, D-1, D-2, D-3, D-4, D-8 |
| **M4 — per opportunity** | documents for one advert, and the interview around it | S4, D-9, T45, T46, S6, T47, T43, T22, T26b, T25, T29, T51, T52, T53, T54, T55, S9, S10, S11, S12, D-24 |
| **M5 — contact with the world** | the layers that touch the outside stop reporting success over work they did not do: robots, connector health, liveness identity, canonical-source dedup, the eligibility and language gates, the ATS text-layer contract, the application status vocabulary | T85, T70, T71, T72, T73, T74, T75, T76, T77, T78, T79, T80, T81, T82, T84, T86, T83, D-23, D-25 |
| **cross-cutting** | S7 lands once M1 exists — a checkpoint script needs state to read | S7, T31, S8 |

**S7 is deliberately not first.** The handover recommended it as the next task,
and it is the task that turns the specification into something that runs — but
each of the thirteen skills carries a checkpoint script that reads session
state, decides whether coverage is met, and writes gate evidence. None of that
exists until T35 and T34 land. Written before them, the scripts have nothing to
read and the skills become the prose transcription S7's own payload warns
against.

**T5 no longer paces anything.** It was the choke point — T9, T14, D-2 and,
through T14, the whole of T15's chain blocked on a hand-labelling campaign. That
campaign was retired on 2026-08-19: the owner read four pre-marked ads, judged
the read good enough, and decided the model should find the dimensions in each
advert on its own. T5 closed against PR #42 on `corpus_size >= 100`, the
threshold it always carried, and the three tasks behind it are unblocked.

What did *not* go away is the measurement. `extraction_macro_f1` and
`prefilter_recall` were both specified against the hand-labelled corpus, and the
corpus holds **39 human labels over 4 ads — 14 of them in the evaluation half**,
no dimension above 4, four dimensions with none. `status/evidence/T5.json`
carries those counts per dimension so the gap is visible before a number is
computed rather than after. D-2 (`lo-77a6`) settles what to do about it: score
only what a person decided, report `n`, and refuse the score outright below a
floor — unmeasured being a third outcome, distinct from pass and from fail.

**Milestones are queue tags.** Every task carries `m1`, `m2`, `m3`, `m4`, `m5`
or `cross`, so a worker session scopes to the milestone rather than to raw
priority: `/continue m1`, which sets `LOOP_TAGS` and makes `queue_batch.sh`
return only that milestone's unblocked tasks. Without the tag the selector is
ordered by priority alone and will hand back an M4 task beside an M1 one.

**Branch pattern**: `T<N>-short-description` from the default branch.

### Step gate ownership

Every step of specification v2 names one gate metric. This table mirrors
`status/spec-v2-process.md` §9 **exactly** — the plan does not reassign a metric
the specification has settled, and where the plan's work disagrees with §9 that
is a divergence, not an edit.

A step's gate metric is not the same thing as the owning task's own acceptance
gate. Ten metrics belong to a task whose gate they already are; four are step
metrics whose owner must additionally measure and record them.

| step metric | §9 owner | that task's own gate |
|-------------|----------|----------------------|
| `intake_field_provenance` | S4 | `intake_field_provenance == 1.0` — the same |
| `constraint_field_resolution` | T41 | `constraint_field_resolution == 1.0` — the same |
| `trait_evidence_sufficiency` | T49 | `trait_evidence_sufficiency == 1.0` — owner writes the metric (D-4 resolved) |
| `interview_lesson_linkage` | S6 | `interview_lesson_linkage == 1.0` — the same |

**D-4** was the one contradiction this plan found and could not resolve by
editing: §9 assigned the Traits metric to T28 (continuous capture), while the
two-episode floor that produces the measurement is specified in T27 (the
interview protocol). Neither task's own gate is `trait_evidence_sufficiency`,
so reassigning between them would have made the documents agree and the
register still wrong — the plan recorded §9's answer and pointed at the
divergence rather than quietly overriding a settled specification.

It is now **resolved by a task, not an edit**: **T49** scores trait evidence
and is measured on `trait_evidence_sufficiency` itself, so §9, this table and
T49's own gate row name one task and mean the same thing. T27 keeps the floor
as part of the interview and T28 keeps evidence arriving from every surface;
what T49 adds is the decision to withhold a score, which belonged to neither.

## Evidence log

`execution` appends one row per task as it lands (RED → GREEN → RECORD). A gated
task is not done until its row is complete and the measured value meets the
gate. The SHA is the commit that carries the artefact, and the value is what
*that* commit's own checker read.

| T# | Gate | Measured | Command | SHA | Env | Date |
|----|------|----------|---------|-----|-----|------|
| T1 | `lint_typecheck_exit_code == 0` | 0 | `make gate` (runs `ruff check .` + `mypy .`) | `9581811` | cloud | 2026-08-15 |
| S1 | `process_spec_complete == 1` | 1 | `uv run python -m integral.process_spec status/evidence/S1.json` | `f282705` | cloud | 2026-08-17 |
| S1r | `process_spec_complete == 1` | 1 | `uv run python -m integral.process_spec status/evidence/S1.json` | `258b2de` | cloud | 2026-08-17 |
| S2 | `step_specs_complete_fraction == 1.0` | 1.0 | `uv run python -m integral.step_specs status/evidence/S2.json` | `8c59a7f` | cloud | 2026-08-17 |
| S2r | `step_specs_complete_fraction == 1.0` | 1.0 | `uv run python -m integral.step_specs status/evidence/S2.json` | `83032bb` | cloud | 2026-08-18 |
| S8 | `plan_queue_task_drift == 0` | 0 | `uv run python -m integral.plan_v2 status/evidence/S8.json` | `1605cdd` | cloud | 2026-08-18 |
| S3 | `cross_user_leaks == 0` | 0 | `uv run python -m integral.identity status/evidence/S3.json` | `5c0600b` | cloud | 2026-08-18 |
| T6 | `profile_rebuild_deterministic == 1` | 1 | `uv run python -m integral.profile status/evidence/T6.json` | `92f8657` | cloud | 2026-08-18 |
| T35 | `resumption_position_loss == 0` | 0 | `uv run python -m integral.session status/evidence/T35.json` | `4b03625` | cloud | 2026-08-18 |
| T30 | `required_subset_closure_violations == 0` | 0 | `uv run python -m integral.step_graph status/evidence/T30.json` | `0ce3beb` | cloud | 2026-08-18 |
| T34 | `unrunnable_step_dispatches == 0` | 0 | `uv run python -m integral.step_runtime status/evidence/T34.json` | `92274a1` | cloud | 2026-08-18 |
| T37 | `stale_artefact_detection_recall == 1.0` | 1.0 | `uv run python -m integral.revision status/evidence/T37.json` | `bd4984d` | cloud | 2026-08-18 |
| T38 | `retracted_rows_surviving_rebuild == 0` | 0 | `uv run python -m integral.retraction status/evidence/T38.json` | `73ee68a` | cloud | 2026-08-18 |
| T40 | `repeat_asks_after_decline == 0` | 0 | `uv run python -m integral.decline status/evidence/T40.json` | `ac6c873` | cloud | 2026-08-18 |
| T39 | `unscheduled_scoring_runs == 0` | 0 | `uv run python -m integral.scoring status/evidence/T39.json` | `d09e90a` | cloud | 2026-08-18 |
| T36 | `unoffered_reentries == 0` | 0 | `uv run python -m integral.freshness status/evidence/T36.json` | `f233d52` | cloud | 2026-08-18 |
| T48 | `step_gate_state_drift == 0` | 0 | `uv run python -m integral.step_gates status/evidence/T48.json` | `f3e6a50` | cloud | 2026-08-18 |

> Rows for T2, T3, T4, T4b and T23 are in `status/plan-v1.md` and in
> `status/evidence/`; they are not restated here. The five above are restated
> because v2's gate discipline descends directly from them — in particular the
> correction that a row records the gate **as it stood**, measured by the
> checker that shipped with that commit, not a promise that a later, stricter
> gate passes on older text.

### Dependency graph

```
                        ┌── T30 ──┬── T34 ──┐
                        │         │         │
  S3 ── T6 ─┬── T35 ────┴─────────┘         ├── S7
            │                               │
            ├── T37 ──┬── T36 ──────────────┘
            │         └── T39
            ├── T38
            ├── T40
            │
            ├── T24 ──┬── T41
            │         ├── T33 ──────────────────────┐
            │         │                             │
            ├── T7 ── T8 ──┬── T27                  │
            │              ├── S4 ── T45 ─┬── T46   │
            │              │              └── S6 ── T47
            │              │                        │
            └── T28        │                        │
                           │                        │
  T11 ─┬── T32 ── T12      │                        │
       ├── T13 ── S5       │                        │
       └── T14 ── T15 ─┬── T16                      │
                       ├── T17                      │
                       ├── T42                      │
                       └── T18 ── T19 ─┬── T44 ◄────┘
                                       ├── T43
                                       ├── T20a ── T20*
                                       └── T21
  T5* ──────────────► T9 ── T10 ──► T18
  T4b ─► T5*          (T5 also gates T15's evaluation split)

  iterative sourcing — T60 first, and everything hangs off it:

  T60 ─┬── T61
       └── T62 ─┬── T63 ──────────┬── T68 ── T69*
                └── T64 ─┬────────┘
                         ├── T65 ─┬── T66
                         │        └── T67
                         └── T66

  * T5, T20 and T69 are [HUMAN]; T12 and T25 are [LAPTOP].
    T5 paces every gate measured on the evaluation split and nothing in M1.
    T69 is [HUMAN] because its prerequisite — the exhaustion signal having been
    watched on a real cycle — is not something a dep on T68 can express.
```

---

## Risks

| # | What could go wrong | L | I | Mitigation | Rollback |
|---|---------------------|---|---|------------|----------|
| R1 | **T5 stays unlabelled** and M2's extraction gates cannot be measured, so extraction ships ungated | H | H | M1 is designed not to touch the corpus, so the spine proceeds regardless; T15 lands RED against the evaluation split and is not released `done` until the gate runs | Extraction code stays behind a flag; nothing ranks on unmeasured scores |
| R2 | **The profile leaks into an extraction payload** — the one privacy failure that cannot be undone once it reaches a model | L | H | T42 separates the candidate-independent extraction from the local annotation pass, and gates on `annotation_profile_egress == 0` measured over the actual outbound payload, not over intent | Extraction runs offline on fixtures; no live calls until the gate is green |
| R3 | **One candidate's evidence lands in another's tree.** The log is append-only, so this is unpickable rather than undoable | M | H | S3 resolves every path beneath a handle *and* adds a `PreToolUse` hook below the tool; `cross_user_leaks == 0`; the hook is tested for false positives so correct operation never trips it | Restore the tree from git-external backup; the evidence log's row ids make the foreign rows identifiable |
| R4 | **An authored document is silently regenerated** after it was sent, leaving the candidate unable to answer a question about their own application | M | H | T37's three artefact classes, and T45 writing `v<N+1>` rather than overwriting | Earlier versions survive by construction — that is the mitigation |
| R5 | **Purge deletes something that mattered.** Purge is irreversible by design | L | M | S5's four-part eligibility test, the retention list, the report-before-purge, and explicit revival of a tombstoned ad | Tombstone + revival restores as `new`; the ad body is gone, which is the accepted cost |
| R6 | **Model cost makes the loop too expensive to run**, so it stops being run | M | M | T15's staged extraction with the model last; T14's prefilter; per-run extraction budget; the card is a filled template, not a generated paragraph | Rules-only extraction still produces a ranking, marked as such |
| R7 | **The non-insistence rule is unmeasurable** and quietly degrades into a form with a progress bar | M | H | T40 makes the mechanical half measurable (`repeat_asks_after_decline == 0`); the rest is a review question against the step specs, and §2.5's five required steps are what make obeying it safe | None needed — a violation is a defect, not a state to roll back |
| R8 | **Thirteen steps is too much scope** and nothing finishes | H | M | Milestones deliver a working L1 product at M2 with five required steps; the other eight are offered by specification, so an unbuilt step is a declined step rather than a hole | Ship at M2; M3 and M4 sharpen it |
| R9 | **A skill and its step specification drift apart** once both exist | M | M | S7 forbids re-deciding a spec in a skill and requires a divergence task instead; `test_no_skill_contradicts_its_step_specification` checks the stop rule and the required flag, the two that drift first | Regenerate the skill from the spec; the spec is the source |
| R10 | **The cloud session cannot do the laptop work** and T12/T25 stall the connector and corpus story | M | M | Both are tagged `laptop` and refused a `done` from a cloud session by `release.sh`; T11's manual-paste connector keeps SUPPLY unblocked without egress | Manual paste is a complete path for a single candidate |
| R11 | **The strategy conversation anchors the candidate.** *"Shall we focus on US companies?"* plants the idea it pretends to ask about, and a conversational guide is the most anchoring surface this product has — more than a ranking, far more than a card | H | H | T64 types `alternatives` to require the opposite direction, so a one-way proposal cannot be constructed; `scope_proposals_offering_only_narrowing == 0` measures what was offered, not what was intended | The whole surface sits behind T63's trigger; disabling it returns step 7 to a single pass with no conversation |
| R12 | **Exhaustion fires on an unlucky search**, and the candidate re-steers one that would have worked | M | M | `EXHAUSTION_REPEAT_SHARE` is a named constant carrying its reasoning rather than a tuned number pretending to be evidence; it needs two cycles to fire at all | One constant, whose docstring already says it expects revision once a real candidate has run four or more cycles |
| R13 | **Option 3 becomes interrogation** — the candidate is sent back through answered questions because a search failed, which is the experience that makes people close a tool | M | H | T69 is sequenced after T68 and gated on the exhaustion signal being *observed* correct, not merely built; `unrequested_profile_reentries == 0` | T69 is a separate merge; not shipping it leaves the feature whole |
| R14 | **Consent becomes theatre**: the decision is recorded, never re-surfaced, and the search quietly narrows for a month | M | H | T67 re-surfaces standing scope on return and makes it correctable in place — consent nobody can review is not consent | Scope decisions are evidence rows; suppressing them returns sourcing to constraints-only |

---

## Reconciliation with v1

The brief's §6.3 asked the specification round to produce "queue tasks derived
from those specifications, replacing or refining T24–T29 where they overlap."
That did not happen, so the queue carried v1 tasks and ad-hoc spec-v2 tasks side
by side with the overlap unresolved. This is that reconciliation.

**Refined — the task survives, its scope changed:**

| task | change |
|------|--------|
| T24 | Now also pins the `constraints.json` field set and its three resolution states, and gains step 7's reach and legality fields (employed or contracting, paid where, taxed where). It owns `constraint_field_resolution` per process spec §9, but the *step engine* that resolves the fields is T41 |
| T27 | Carries the two-episode/two-occasion trait floor — reading `insufficient` rather than refusing to score, and never voiced to the candidate. Its own gate stays `interview_profile_coverage >= 0.90`; **the step 4 metric is not reassigned here** (see D-4) |
| T9 | Stimuli are **fetched live** by preference with the corpus as fallback (process §2.3); live stimuli enter the offer store as ordinary `new` offers |
| T13 | Dedup is a similarity problem over normalised text; `text_sha256` catches re-collection of one listing and is explicitly the cheap half (process §7.4) |
| T15 | Staged — normalise, rules, then a model only on the remainder. Extraction stays candidate-independent; relating an offer to the candidate moves to T42 |
| T18 | A ranking records the `profile_revision` and the sufficiency level that produced it |
| T21 | Feedback moves offer lifecycle status as well as weights |
| T29 | Its step table is superseded by specification v2. What remains is the packaging and distribution decision (process §11.5) — hence ◐, not ☐ |
| S4 | Narrowed to the CV **store**: import, build-from-nothing, and the `master.json` contract. Per-advert generation splits out as T45 because its gate (`cv_generation_traceability`) is a different measurement on a different artefact |
| S6 | Narrowed to preparation and the log; the strict mock role-play splits out as T47 |
| S3 | Keeps identity and the tree; session state and resumption split out as T35, which is where the resumption order and the continuous-write rule live |

**Superseded — do not build as written:**

- The `story_failure_fraction >= 0.33` floor, wherever it is still gated. Both
  kinds of episode present once there are ≥4, fraction reported not floored.
  D-3 reconciles the v1 documents.
- The step table in `docs/product-shape.md`, superseded by specification v2.

**Unchanged**: T1–T5, T7, T8, T10, T11, T12, T14, T16, T17, T19, T20, T22, T23,
T25, T26, T28, T30, T31, T32, T33, S5, S7, D-1, D-2.

---

## Sign-off

- [ ] Owner has read the task table and the milestones
- [ ] Step gate ownership read and the D-4 divergence resolved
- [ ] Queue reconciled against this table
- [ ] Ready for execution
