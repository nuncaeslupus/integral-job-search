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
- **The distribution question** (process spec §11.5). Undecided, blocks nothing
  until someone other than the owner installs this, and tracked by T29.
- **CV templates and layouts** (brief §2.7). The store feeds templates; choosing
  layouts is not v2.
- **Re-litigating specification v2.** A task that finds the spec wrong seeds a
  `D-N` divergence and fixes the spec; it does not quietly diverge.

---

## Implementation tasks

Two columns beyond the v1 table: **Step** maps a task to the step(s) of
specification v2 it serves (`—` for infrastructure that serves all of them), and
**St** is status — ☑ merged · ◐ in progress · ☐ open. Rows T1–T33 are carried
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
| T1 | Scaffold package: uv, ruff, strict mypy, pytest, Makefile, `profiles/` gitignored | — | S | — | `lint_typecheck_exit_code == 0` | `test_package_imports_cleanly_exposes_version` in `tests/test_scaffold.py` — importing `jobsearch` yields a semver `__version__` | ☑ |
| T2 | Dimension schema (Pydantic) + loader + validator, incl. `methods_ref` anchor resolution | — | M | T1 | `dimension_schema_violations == 0` | `test_dimension_missing_methods_ref_is_rejected` in `tests/test_dimension_model.py` — a dimension without `methods_ref` fails validation | ☑ |
| T3 | Dimension model v0: 20–25 dimensions with ES/EN/CA cues and elicitation questions | 8 | L | T2 | `dimension_extractor_coverage >= 0.90` | `test_every_dimension_has_cues_in_all_three_languages` in `tests/test_dimension_content.py` — each dimension carries ≥1 cue per language | ☑ |
| T4 | Corpus harness: ad store, labelling CLI, split assignment, self-agreement report | 5, 8 | M | T2 | `corpus_harness_roundtrip_loss == 0` | `test_corpus_roundtrip_preserves_text_and_offsets` in `tests/test_corpus.py` — writing then reading an ad preserves text byte-for-byte and label offsets | ☑ |
| T4b | **[LAPTOP]** Collect ≥100 raw ads: ≈60 ES + 25 EN remote programming roles, plus ≈15 CA Catalan IT ads at large — the remote dimension mixed in, not filtered for (D-1) | 5, 8 | M | — | `raw_ad_count >= 100` | `test_raw_corpus_meets_size_and_language_mix` in `tests/test_corpus_raw.py` — ≥100 raw ads, mix within ±10% | ☑ |
| T5 | **[HUMAN]** Label the collected ads against the dimension model; assign elicitation/evaluation split | 5, 8 | L | T3, T4, T4b | `corpus_size >= 100` | `test_corpus_meets_size_and_language_mix` in `tests/test_corpus_content.py` — ≥100 labelled ads and language mix within ±10% | ☐ |
| T22 | `methods_ref` link check across dimensions and computation sites | — | S | T2, T18 | `undocumented_methods == 0` | `test_every_methods_ref_resolves_to_an_anchor` in `tests/test_methods_links.py` — every `methods_ref` resolves to a heading in `docs/METHODS.md` | ☐ |
| T23 | Dimension `side`: matched / candidate-fact / candidate-trait, and a coverage metric that stops asking ad-side questions of candidate-side entries | 4, 8 | M | T2 | `side_coverage_violations == 0` | `test_a_trait_dimension_without_cues_is_valid` in `tests/test_dimension_side.py`; `test_extractor_coverage_counts_only_ad_side_dimensions` | ☑ |
| T24 | Candidate attribute schema — languages, location, relocation, salary floor/target, availability, work authorisation, **and the reach and legality fields step 7 needs**: employed or contracting, paid where, taxed where. Pins the `constraints.json` field set and its `stated`/`declined`/`unknown` states | 2, 7 | M | T23 | `unsatisfiable_hard_constraint_leaks == 0` | `test_offer_failing_a_hard_constraint_never_ranks` in `tests/test_candidate_attributes.py`; `test_missing_attribute_is_unknown_not_satisfied` — an unstated constraint does not silently pass | ☑ |
| T25 | **[LAPTOP]** Broaden the corpus beyond remote programming: ≥6 job families, ≥15 ads each, same three languages | 5, 8 | L | — | `corpus_job_family_count >= 6` | `test_corpus_covers_at_least_six_job_families` in `tests/test_corpus_families.py` — no family below 15 ads | ☐ |
| T26 | Dimension model v1: widen to the broadened corpus; add candidate-trait dimensions (creativity, ambition, learning orientation, spare-time engagement) | 4, 8 | L | T23, T25 | `ontology_hit_rate >= 0.85` | `test_every_job_family_reaches_dimension_coverage` in `tests/test_dimension_content.py` — no family below 0.80 | ☐ |
| T29 | Record the product shape — packaging, phase skills, checkpoint scripts, and the distribution decision left open at process spec §11.5 | — | S | — | `phase_checkpoints_defined == 1` | `test_every_open_shape_question_has_a_recorded_answer` in `tests/test_product_shape.py` — each question in the shape doc carries a decision or a named blocker | ◐ |
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

### SUPPLY — connectors, offers, lifecycle

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T11 | Normalised offer schema + manual-paste connector | 7 | M | T1 | `offer_schema_violations == 0` | `test_pasted_text_produces_valid_offer` in `tests/test_connect_manual.py` — a pasted ad yields a schema-valid offer with verbatim `text` | ☑ |
| T32 | Declarative connector format and a shared connector library — data, never code, never a credential; authenticated sources drive the candidate's own browser session | 7 | M | T11 | `connector_executes_no_shared_code == 1` | `test_connector_file_is_data_only` in `tests/test_connectors.py`; `test_no_connector_stores_a_credential`; `test_authenticated_source_uses_the_candidate_session` | ☑ |
| T12 | **[LAPTOP]** One live portal connector against recorded fixtures | 7 | L | T11, T32 | `connector_fixture_parse_f1 >= 0.95` | `test_connector_parses_fixture_pages_to_offers` in `tests/test_connect_portal.py` | ☐ |
| T13 | Cross-source dedup by similarity over normalised text + expiry detection | 7 | M | T11 | `dedup_precision >= 0.95` | `test_crossposted_duplicates_are_collapsed` in `tests/test_dedup.py`; `test_distinct_roles_at_same_company_are_not_merged` | ☑ |
| S5 | Offer lifecycle: seven statuses and their allowed transitions, retention, the 60-day purge, and tombstones dedup cannot resurrect | 7 | L | S1, T11, T13 | `resurrected_purged_offers == 0` | `test_purged_offer_is_not_re_added_as_new` in `tests/test_offer_lifecycle.py`; `test_shortlisted_offer_is_never_purge_eligible`; `test_applied_cannot_return_to_new`; `test_explicit_revival_restores_and_keeps_the_tombstone` | ☑ |
| T33 | Net-from-gross pay estimation per country, generated when the advert states only gross | 9 | M | T24 | `generated_tax_rules_marked_unverified == 1.0` | `test_net_estimate_within_ten_percent_of_reference` in `tests/test_pay.py`; `test_absent_country_rules_yield_unknown_not_a_guess` | ☑ |

### MATCH — extraction, annotation, ranking

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T14 | Lexical prefilter (recall-oriented) ahead of LLM extraction | 8 | M | T3, T5, T11 | `prefilter_recall >= 0.98` | `test_prefilter_retains_all_corpus_positives` in `tests/test_prefilter.py` | ☐ |
| T15 | Staged extraction — normalise, then rules, then a model only on what they could not settle: dimension scores, evidence spans, `unmapped_concepts` | 8 | L | T5, T14 | `extraction_macro_f1 >= 0.75` | `test_extraction_matches_corpus_labels` in `tests/test_extract.py` — macro-F1 ≥ 0.75 on the evaluation split; `test_score_without_evidence_span_is_rejected`; `test_model_is_not_called_for_a_dimension_rules_settled` | ☐ |
| T16 | Negation handling in extraction | 8 | M | T15 | `extraction_negation_recall >= 0.80` | `test_negated_cue_inverts_not_drops_score` in `tests/test_negation.py` — "no on-call" yields a negative score, not a missing one | ☐ |
| T17 | `ontology_hit_rate` reporting and staleness signal | 8 | S | T15 | `ontology_hit_rate >= 0.85` | `test_unmapped_concepts_are_counted_not_discarded` in `tests/test_ontology_health.py` | ☐ |
| T42 | Local annotation pass: `annotations/<offer_id>.json`, the offer read against *this* candidate's constraints and weights, computed on this machine and never sent with the advert | 8 | M | T15, T24 | `annotation_profile_egress == 0` | `test_no_profile_bytes_appear_in_an_extraction_payload` in `tests/test_annotation.py`; `test_annotation_is_recomputed_when_constraints_change`; `test_extraction_schema_stays_candidate_independent` | ☐ |
| T43 | Outside-the-advert enrichment for adverts that say almost nothing, marked as not from the ad and excluded from verbatim spans | 8 | M | T15, T19 | `outside_source_spans_in_explanations == 0` | `test_outside_information_is_marked_not_from_the_advert` in `tests/test_enrichment.py`; `test_an_explanation_never_cites_an_outside_source_as_the_employer`; `test_lookup_is_skipped_when_the_candidate_declined_it` | ☐ |
| T18 | Pareto frontier + salary-equivalent ordering + facet lists, pinned to a profile revision and a sufficiency level | 9 | L | T10, T15 | `pareto_dominance_violations == 0` | `test_dominated_offer_never_appears_in_frontier` in `tests/test_rank.py`; `test_unknown_dimension_is_not_treated_as_neutral`; `test_ranking_records_its_revision_and_level` | ☐ |
| T19 | Explanations citing verbatim evidence spans and €/month contributions | 9 | M | T18 | `explained_fraction == 1.0` | `test_every_ranked_offer_cites_evidence` in `tests/test_explain.py` — each ranked offer carries ≥1 verbatim span per contributing dimension | ☐ |
| T44 | Ranking presentation: the offer card as a template filled from normalised JSON — facts as bullets, one plain line including the bad part, unknown shown as unknown, provisional labelled | 9 | M | T18, T19, T33 | `provisional_rankings_unlabelled == 0` | `test_l1_ranking_is_labelled_provisional` in `tests/test_presentation.py`; `test_unknown_field_renders_as_unknown_not_neutral`; `test_card_is_filled_from_json_not_generated_per_offer` | ☐ |
| T20 | **[HUMAN]** Calibrate ranking against blind manual ranking of 20 held-out ads | 9 | M | T9, T19 | `rank_spearman >= 0.60` | `test_ranking_correlates_with_manual_order` in `tests/test_calibration.py` — Spearman ρ ≥ 0.60 against the recorded manual order | ☐ |

### DOCUMENT — the CV store, generated documents, interviews

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| S4 | CV store: import pdf/docx into `cv/master.json`, or build the same store by conversation with someone who has no CV. Pins the `master.json` contract | 1 | L | S1, T6, T8 | `intake_field_provenance == 1.0` | `test_every_master_field_names_its_source` in `tests/test_cv_store.py` — every field traces to a document span or a conversation turn; `test_candidate_with_no_cv_reaches_the_same_store`; `test_source_document_is_never_modified` | ☑ |
| T45 | Per-advert generation: CV and letter drawn only from store entries, versioned `v<N>` and never overwritten, with a claim→store manifest | 11 | L | S4, S5, T15 | `cv_generation_traceability == 1.0` | `test_every_claim_traces_to_a_store_entry` in `tests/test_generate.py`; `test_regeneration_writes_a_new_version`; `test_advert_wording_is_mirrored_only_over_held_ground` | ☐ |
| T46 | Personal details collected at the point of use, per-use approval for story episodes, and the send boundary: prepared documents, text to paste, an email left in drafts | 11 | M | T45 | `unapproved_episode_disclosures == 0` | `test_episode_without_per_use_approval_never_enters_a_document` in `tests/test_approval.py`; `test_personal_details_are_asked_at_step_eleven_not_at_intake`; `test_nothing_is_sent_without_an_explicit_per_item_approval` | ☐ |
| S6 | Interview: preparation from the advert, the application and earlier interviews; then the log — questions asked, outcome, lessons — immutable and exempt from purge | 12 | L | S1, T8, T45 | `interview_lesson_linkage == 1.0` | `test_every_logged_interview_produces_a_linked_evidence_row` in `tests/test_interview_log.py`; `test_interview_record_is_immutable`; `test_outcome_arriving_days_later_resumes_the_record` | ☐ |
| T47 | The mock interview: a strict role-play announced before it starts, no coaching mid-answer, no breaking character, with dictation offered and feedback only at the end | 12 | M | S6 | `mock_interview_character_breaks == 0` | `test_no_coaching_turn_occurs_inside_the_roleplay` in `tests/test_mock_interview.py`; `test_roleplay_is_announced_before_it_begins`; `test_feedback_is_given_only_after_it_ends` | ☐ |

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
| S10 | The skill listing budget (8,000 chars, a per-turn context cost) is exceeded at 11,140 once the thirteen step skills land. **Decided: raise it.** The constant is hardcoded upstream with no override, so this is an upstream change first (`claude-arsenal` issue #143) and a re-measure here after | all | M | S7 | `skill_listing_budget_overage_chars == 0` | `test_the_library_is_within_its_listing_budget` in `tests/test_step_skills.py`; `test_every_step_is_still_reachable_after_the_change` — the saving may not come from dropping a step | ☐ |
| S11 | Test mode — an orthogonal meta channel (`[[...]]`) for capturing notes about the tool during a live session, without disturbing it; notes are shown at the end and seeded only once confirmed | all | M | S7, S10 | `test_notes_reaching_candidate_evidence == 0` | `test_a_meta_note_never_reaches_the_evidence_log` in `tests/test_test_mode.py`; `test_a_pasted_advert_containing_brackets_is_not_eaten`; `test_the_visible_conversation_is_byte_identical_with_and_without_notes` | ☐ |
| S12 | Move "does this step take candidate free text" into `spec-v2-steps.json` so `profile_capture`'s denominator is fully machine-derived, instead of a hand-made map T28 guards but cannot derive | all | M | T28 | `unclassified_free_text_steps == 0` | `test_every_step_declares_whether_it_takes_candidate_free_text` in `tests/test_profile_capture.py`; `test_profile_capture_reads_the_declaration_not_a_local_map`; `test_coverage_is_unchanged_by_the_migration` | ☐ |

### Divergences

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| D-1 | Catalan corpus slice covers IT roles at large, not remote programming as T4b specifies | 8 | S | — | `corpus_language_slice_mismatch == 0` | `test_every_language_slice_matches_its_declared_scope` in `tests/test_corpus_raw.py` | ☑ |
| D-2 | v0 gold examples are cue-derived, not independent — T15 must measure `extraction_macro_f1` against independent labels | 8 | S | T5 | `cue_derived_gold_in_evaluation_split == 0` | `test_no_evaluation_example_is_derived_from_a_cue` in `tests/test_corpus_content.py` | ☐ |
| D-3 | `story_failure_fraction` floor contradicts the revised History protocol; reconcile `status/specification.md` and `docs/METHODS.md` | 3 | S | — | `spec_gate_contradictions == 0` | `test_no_document_states_a_superseded_gate` in `tests/test_spec_consistency.py` — the floor appears nowhere as a gate, and the fraction is reported | ☑ |
| D-4 | The Traits gate is assigned to T28 by the specification and to T27 by the work; neither task's own gate is the step metric | 4 | S | — | `trait_gate_owner_contradictions == 0` | `test_step_gate_metric_is_some_task_gate` in `tests/test_step_gates.py` — every step gate metric is some task's acceptance gate; `test_no_two_documents_name_different_owners_for_one_step_gate` | ☑ |
| D-6 | `rebuild()` writes only `stated` rows to `constraints.json`, so a refresh after the constraints step drops every `declined` and `unknown` field — the refusal T40 depends on reverts to never-asked | 2 | S | T41 | `constraint_states_survive_rebuild == 1.0` | `test_a_declined_field_survives_a_rebuild` in `tests/test_revision.py`; `test_an_unknown_field_survives_a_rebuild` — both must fail before the fix | ☑ |
| D-7 | `spec-v2-steps.md` names two owners for the Ranking gate (T18, T19) while the JSON names one (T19); same class as D-4 | 9 | S | — | `step_gate_owner_contradictions == 0` | `test_every_step_gate_names_exactly_one_owner` in `tests/test_step_specs.py`; `test_the_gate_task_is_the_task_that_writes_the_metric`; `test_no_prose_document_names_a_different_owner_than_the_json` | ☑ |
| D-8 | Captured evidence cannot say which offer a reason was about — `EvidenceRow` carries `step`, `source` and `recorded_at`, so T28's required provenance "in response to what" is unmet and two rejections of two different jobs are indistinguishable in the log | 4 | M | T28, T6 | `captures_without_a_subject == 0` | `test_two_rejections_of_different_offers_are_distinguishable_in_the_log` in `tests/test_profile_capture.py`; `test_a_captured_reason_survives_rebuild_with_its_subject`; `test_an_answer_to_a_question_needs_no_subject_field` | ☑ |
| D-9 | Non-insistence is not honoured on intake's conversational write path — `cv_store.py` is the only free-text writer with no `DeclineLedger` reference, so `add_conversation_entry` records an answer on a subject the candidate declined and has not reopened, the outcome T40 exists to prevent | 1 | M | S4, T40 | `intake_declined_subjects_written == 0` | `test_a_declined_subject_is_not_written_by_the_conversational_path` in `tests/test_cv_store.py`; `test_a_reopened_decline_lets_the_subject_be_recorded_again` — the second so the fix cannot be “never write anything” | ☐ |

**Status legend**: ☐ open · ◐ in progress · ☑ merged

**Merge order** — four milestones. Within a milestone, order is the dependency
graph below; across milestones it is strict. Merged tasks (T1–T4b, T23) are not
listed; every open task appears in exactly one milestone.

| milestone | delivers | tasks |
|-----------|----------|-------|
| **M1 — the spine** | a candidate is identified, resumed and never mixed up with another; the graph can say what is owed | S3, T6, T35, T30, T34, T37, T36, T38, T40, T48 |
| **M2 — L1, a rough list end to end** | constraints → offers → extraction → annotation → a provisional, labelled ranking | T24, T41, T11, T32, T12, T13, S5, T14, T15, T16, T17, T42, T18, T19, T33, T44, D-6, D-7 |
| **M3 — L2, the full first run** | history, traits, reactions, weights, feedback — the ranking gets sharp and the loop closes | T7, T8, T27, T5, T9, T10, T39, T21, T28, T49, T50, T20, D-1, D-2, D-3, D-4, D-8 |
| **M4 — per opportunity** | documents for one advert, and the interview around it | S4, D-9, T45, T46, S6, T47, T43, T22, T26, T25, T29, S9, S10, S11, S12 |
| **cross-cutting** | S7 lands once M1 exists — a checkpoint script needs state to read | S7, T31, S8 |

**S7 is deliberately not first.** The handover recommended it as the next task,
and it is the task that turns the specification into something that runs — but
each of the thirteen skills carries a checkpoint script that reads session
state, decides whether coverage is met, and writes gate evidence. None of that
exists until T35 and T34 land. Written before them, the scripts have nothing to
read and the skills become the prose transcription S7's own payload warns
against.

**The critical path is M1, and it is not blocked by T5.** T5 ([HUMAN] corpus
labelling) still paces `extraction_macro_f1`, `elicitation_eval_overlap` and
everything that measures against the evaluation split — but nothing in M1
touches the corpus. The two run in parallel: the spine is built while the
labelling happens, and M2's extraction gates land when T5 does.

**Milestones are queue tags.** Every task carries `m1`, `m2`, `m3`, `m4` or
`cross`, so a worker session scopes to the milestone rather than to raw
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
| S1 | `process_spec_complete == 1` | 1 | `uv run python -m jobsearch.process_spec status/evidence/S1.json` | `f282705` | cloud | 2026-08-17 |
| S1r | `process_spec_complete == 1` | 1 | `uv run python -m jobsearch.process_spec status/evidence/S1.json` | `258b2de` | cloud | 2026-08-17 |
| S2 | `step_specs_complete_fraction == 1.0` | 1.0 | `uv run python -m jobsearch.step_specs status/evidence/S2.json` | `8c59a7f` | cloud | 2026-08-17 |
| S2r | `step_specs_complete_fraction == 1.0` | 1.0 | `uv run python -m jobsearch.step_specs status/evidence/S2.json` | `83032bb` | cloud | 2026-08-18 |
| S8 | `plan_queue_task_drift == 0` | 0 | `uv run python -m jobsearch.plan_v2 status/evidence/S8.json` | `1605cdd` | cloud | 2026-08-18 |
| S3 | `cross_user_leaks == 0` | 0 | `uv run python -m jobsearch.identity status/evidence/S3.json` | `5c0600b` | cloud | 2026-08-18 |
| T6 | `profile_rebuild_deterministic == 1` | 1 | `uv run python -m jobsearch.profile status/evidence/T6.json` | `92f8657` | cloud | 2026-08-18 |
| T35 | `resumption_position_loss == 0` | 0 | `uv run python -m jobsearch.session status/evidence/T35.json` | `4b03625` | cloud | 2026-08-18 |
| T30 | `required_subset_closure_violations == 0` | 0 | `uv run python -m jobsearch.step_graph status/evidence/T30.json` | `0ce3beb` | cloud | 2026-08-18 |
| T34 | `unrunnable_step_dispatches == 0` | 0 | `uv run python -m jobsearch.step_runtime status/evidence/T34.json` | `92274a1` | cloud | 2026-08-18 |
| T37 | `stale_artefact_detection_recall == 1.0` | 1.0 | `uv run python -m jobsearch.revision status/evidence/T37.json` | `bd4984d` | cloud | 2026-08-18 |
| T38 | `retracted_rows_surviving_rebuild == 0` | 0 | `uv run python -m jobsearch.retraction status/evidence/T38.json` | `73ee68a` | cloud | 2026-08-18 |
| T40 | `repeat_asks_after_decline == 0` | 0 | `uv run python -m jobsearch.decline status/evidence/T40.json` | `ac6c873` | cloud | 2026-08-18 |
| T39 | `unscheduled_scoring_runs == 0` | 0 | `uv run python -m jobsearch.scoring status/evidence/T39.json` | `d09e90a` | cloud | 2026-08-18 |
| T36 | `unoffered_reentries == 0` | 0 | `uv run python -m jobsearch.freshness status/evidence/T36.json` | `f233d52` | cloud | 2026-08-18 |
| T48 | `step_gate_state_drift == 0` | 0 | `uv run python -m jobsearch.step_gates status/evidence/T48.json` | `f3e6a50` | cloud | 2026-08-18 |

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
                                       ├── T20*
                                       └── T21
  T5* ──────────────► T9 ── T10 ──► T18
  T4b ─► T5*          (T5 also gates T15's evaluation split)

  * T5 and T20 are [HUMAN]; T12 and T25 are [LAPTOP].
    T5 paces every gate measured on the evaluation split and nothing in M1.
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
