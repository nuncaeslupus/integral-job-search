"""T164: the population every committed floor declares, or the reason it has none.

`floor_sweep` reads source, and a population assembled while the program runs is not
visible to a parser (T159's second reader: 17 floors no AST rule can ever reach, and 55
names ruled out of scope and never judged). So the sweep stops guessing what a floor
bounds and asks the floor. `FLOOR_POPULATIONS` maps `module.NAME` to one declaration:

    (kind, counter, compared_to, description)

* `counted` - the floor is compared against a population counted in `counter`: a
  `module.function` in `src/integral/`, or `tests/test_x.py::function` for a floor only a
  test reads. `compared_to` is the source text of the other operand of that comparison
  (`len(permitted)`), or empty where the floor is read through a table the sweep does
  not trace.
* `scalar` - the bound limits the size of one value (a string length, a word count, a
  pixel side). No collection of cases exists whose deletion could breach it, so there is
  no population to declare; `description` is the reason, reviewed here, never inferred.

A declaration is only checked structurally and never run: `floor_sweep.
measure_declarations` refuses one whose counter does not exist, whose counter never
mentions the floor, or whose `compared_to` is not the operand of a comparison against
the floor in that counter. A declaration that does not resolve is not a declaration, so
the floor it names is counted as undeclared.

The universe is not listed here. It is every floor-shaped constant the sweep reads
(`floor_sweep.measure`), minus those the sweep already resolves to a population itself
and those `floor_polarity.ADJUDICATIONS` rules out as a ceiling or `neither` with a
reason - so a constant added anywhere is judged the moment it exists, with no one
remembering to list it. Adding a floor means adding its entry here.
"""

from __future__ import annotations

FLOOR_POPULATIONS: dict[str, tuple[str, str, str, str]] = {
    "alert_mailbox.MINIMUM_PERMITTED_CASES": (
        "counted",
        "alert_mailbox.measure",
        "len(permitted)",
        "the permitted cases counted by `measure`",
    ),
    "alert_mailbox.MINIMUM_REFUSING_CASES": (
        "counted",
        "alert_mailbox.measure",
        "len(refusing)",
        "the refusing cases counted by `measure`",
    ),
    "annotation.MIN_IDENTIFYING_LENGTH": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`len(value)`): no collection of cases to delete from",
    ),
    "approval.MINIMUM_CARRIED_DISCLOSURE_CHECKS": (
        "counted",
        "approval._carried_disclosure_report",
        "measured['carried_disclosure_checks_evaluated']",
        "the carried disclosure checks counted by `_carried_disclosure_report`",
    ),
    "approval.MINIMUM_CARRIED_DISCLOSURE_STATES": (
        "counted",
        "approval._carried_disclosure_report",
        "measured['carried_disclosure_states_evaluated']",
        "the carried disclosure states counted by `_carried_disclosure_report`",
    ),
    "approval.MINIMUM_DISCLOSURE_PROBES": (
        "counted",
        "approval._disclosure_report",
        "",
        "the disclosure probes counted by `_disclosure_report`",
    ),
    "approval.MINIMUM_INTACT_SEAM_CHECKS": (
        "counted",
        "approval._intact_seam_report",
        "measured['intact_seam_checks_evaluated']",
        "the intact seam checks counted by `_intact_seam_report`",
    ),
    "approval.MINIMUM_INTACT_SEAM_STATES": (
        "counted",
        "approval._intact_seam_report",
        "measured['intact_seam_states_evaluated']",
        "the intact seam states counted by `_intact_seam_report`",
    ),
    "approval.MINIMUM_MANIFEST_DISCLOSURES_COMPARED": (
        "counted",
        "approval._disclosure_report",
        "",
        "the manifest disclosures compared counted by `_disclosure_report`",
    ),
    "approval.MINIMUM_PARAPHRASE_CHECKS": (
        "counted",
        "approval._paraphrase_report",
        "",
        "the paraphrase checks counted by `_paraphrase_report`",
    ),
    "approval.MINIMUM_PARAPHRASE_STATES": (
        "counted",
        "approval._paraphrase_report",
        "",
        "the paraphrase states counted by `_paraphrase_report`",
    ),
    "approval.MINIMUM_PROBES": ("counted", "approval._main", "", "the probes counted by `_main`"),
    "approval.MINIMUM_RETRACTED_APPROVALS_EVALUATED": (
        "counted",
        "approval._retraction_report",
        "",
        "the retracted approvals evaluated counted by `_retraction_report`",
    ),
    "approval.MINIMUM_RETRACTION_PROBES": (
        "counted",
        "approval._retraction_report",
        "",
        "the retraction probes counted by `_retraction_report`",
    ),
    "arsenal_source.MINIMUM_BUNDLE_FILES": (
        "counted",
        "arsenal_source._main",
        "measured['bundle_files']",
        "the bundle files counted by `_main`",
    ),
    "arsenal_source.MINIMUM_VENDORED_SKILLS": (
        "counted",
        "arsenal_source._main",
        "measured['vendored_skills']",
        "the vendored skills counted by `_main`",
    ),
    "bodyless_post.MINIMUM_PACKAGES": (
        "counted",
        "bodyless_post.measure",
        "packages",
        "the packages counted by `measure`",
    ),
    "capture_provenance.MINIMUM_CAPTURES_SCANNED": (
        "counted",
        "capture_provenance.measure",
        "scanned",
        "the captures scanned counted by `measure`",
    ),
    "connector_contract.MINIMUM_PACKAGES": (
        "counted",
        "connector_contract._main",
        "measured['packages_checked']",
        "the packages counted by `_main`",
    ),
    "connector_exchange.LEAK_NEEDLE_MINIMUM": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`len(s)`): no collection of cases to delete from",
    ),
    "connector_health.MINIMUM_PACKAGES_BYTE_COMPARED": (
        "counted",
        "connector_health.measure_probe_identity",
        "compared",
        "the packages byte compared counted by `measure_probe_identity`",
    ),
    "connector_health.MINIMUM_PROBES_COMPARED": (
        "counted",
        "connector_health.measure_probe_divergence",
        "len(compared)",
        "the probes compared counted by `measure_probe_divergence`",
    ),
    "connector_policy.ADJUDICATIONS_AT_LEAST": (
        "counted",
        "connector_policy.measure_second_readers",
        "checked",
        "the adjudications counted by `measure_second_readers`",
    ),
    "connector_policy.PACKAGES_AT_LEAST": (
        "counted",
        "connector_policy.measure_second_readers",
        "len(packages)",
        "the packages counted by `measure_second_readers`",
    ),
    "connector_procedure.MINIMUM_CASES": (
        "counted",
        "connector_procedure.measure",
        "checked",
        "the cases counted by `measure`",
    ),
    "connector_salary_audit.MINIMUM_DISTINCT_SALARY_VERDICTS_READ": (
        "counted",
        "connector_salary_audit.record",
        "",
        "the distinct salary verdicts read counted by `record`",
    ),
    "connector_salary_audit.MINIMUM_PACKAGES_MEASURED": (
        "counted",
        "connector_salary_audit.record",
        "",
        "the packages measured counted by `record`",
    ),
    "connector_salary_audit._MIN_REASON": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`len(reason)`): no collection of cases to delete from",
    ),
    "connector_transport.MINIMUM_CREDENTIAL_CASES": (
        "counted",
        "connector_transport.measure",
        "case_count",
        "the credential cases counted by `measure`",
    ),
    "connector_transport.MINIMUM_GET_PACKAGES": (
        "counted",
        "connector_transport.measure",
        "get_checked",
        "the get packages counted by `measure`",
    ),
    "connector_transport.MINIMUM_LEDGER_ENTRIES": (
        "counted",
        "connector_transport.measure",
        "scanned",
        "the ledger entries counted by `measure`",
    ),
    "connector_transport.MINIMUM_RECORD_KEYS_COMPARED": (
        "counted",
        "connector_transport._main",
        "sensitivity['evidence_keys_compared']",
        "the record keys compared counted by `_main`",
    ),
    "corpus.MIN_ADS_PER_FAMILY": (
        "counted",
        "corpus.write_family_evidence",
        "",
        "the ads per family counted by `write_family_evidence`",
    ),
    "corpus_scope.MINIMUM_CORPUS_ROWS": (
        "counted",
        "corpus_scope.measure_provenance",
        "rows_examined",
        "the corpus rows counted by `measure_provenance`",
    ),
    "corpus_scope.MINIMUM_EVALUATION_POOL": (
        "counted",
        "corpus_scope.measure_provenance",
        "evaluation_pool",
        "the evaluation pool counted by `measure_provenance`",
    ),
    "corpus_scope.MINIMUM_SERVING_MODULES": (
        "counted",
        "corpus_scope.measure_provenance",
        "scanned",
        "the serving modules counted by `measure_provenance`",
    ),
    "corpus_scope.MINIMUM_STIMULUS_POOL": (
        "counted",
        "corpus_scope.measure_provenance",
        "stimulus_pool",
        "the stimulus pool counted by `measure_provenance`",
    ),
    "cue_audit.MINIMUM_CASES": ("counted", "cue_audit.audit", "", "the cases counted by `audit`"),
    "cue_audit.MINIMUM_CITABLE_FIELDS_CITED": (
        "counted",
        "cue_audit.audit",
        "",
        "the citable fields cited counted by `audit`",
    ),
    "cue_audit.MINIMUM_CITATIONS_CHECKED": (
        "counted",
        "cue_audit.audit",
        "",
        "the citations checked counted by `audit`",
    ),
    "cue_audit.MINIMUM_FAIL_OPEN_CASES": (
        "counted",
        "cue_audit.audit",
        "",
        "the fail open cases counted by `audit`",
    ),
    "cue_audit.MINIMUM_MECHANISM_PINNED_CASES": (
        "counted",
        "cue_audit.audit",
        "",
        "the mechanism pinned cases counted by `audit`",
    ),
    "cv_store.MINIMUM_CHECKS": (
        "counted",
        "cv_store._main",
        "measured['checks_run']",
        "the checks counted by `_main`",
    ),
    "cv_store.MINIMUM_FIELDS_MEASURED": (
        "counted",
        "cv_store._main",
        "measured['fields_measured']",
        "the fields measured counted by `_main`",
    ),
    "document_reader.MINIMUM_CONTRACTS_EVALUATED": (
        "counted",
        "document_reader.measure",
        "contracts",
        "the contracts evaluated counted by `measure`",
    ),
    "elicit_extract.MINIMUM_CHECKS": (
        "counted",
        "elicit_extract._main",
        "measured['checks_run']",
        "the checks counted by `_main`",
    ),
    "elicit_extract.MIN_ANSWER_CHARS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`len(stripped)`): no collection of cases to delete from",
    ),
    "employer_boards.MINIMUM_CONFORMING": (
        "counted",
        "employer_boards._main",
        "measured['ats_host_connectors_conforming']",
        "the conforming counted by `_main`",
    ),
    "exclusion_live_round.MINIMUM_EXCLUDED_SERVED": (
        "counted",
        "exclusion_live_round.measure_live_round",
        "len(excluded_served)",
        "the excluded served counted by `measure_live_round`",
    ),
    "exclusion_live_round.MINIMUM_EXCLUSIONS_TRIPPED": (
        "counted",
        "exclusion_live_round.measure_live_round",
        "len(tripped_abouts)",
        "the exclusions tripped counted by `measure_live_round`",
    ),
    "exclusion_live_round.MINIMUM_UNEXCLUDED_SERVED": (
        "counted",
        "exclusion_live_round.measure_live_round",
        "len(unexcluded_served)",
        "the unexcluded served counted by `measure_live_round`",
    ),
    "extraction.MIN_EVALUATION_LABELS_PER_DIMENSION": (
        "counted",
        "extraction.negation_audit",
        "",
        "the evaluation labels per dimension counted by `negation_audit`",
    ),
    "extraction._CONFIRMING_MATCHES_FOR_BIPOLAR": (
        "counted",
        "extraction.cue_findings",
        "len(spans)",
        "the confirming matches one dimension carries, counted by `cue_findings`",
    ),
    "floor_sweep.MINIMUM_FLOORS_SWEPT": (
        "counted",
        "floor_sweep._analyse",
        "",
        "the floors this sweep counts into the census, checked by `_analyse` itself",
    ),
    "floor_sweep.MINIMUM_FLOORS_ARITHMETICALLY_CHECKED": (
        "counted",
        "floor_sweep._analyse",
        "",
        "the floors that reached an arithmetic check, counted by `_analyse` itself",
    ),
    "floor_sweep.MINIMUM_FLOORS_EVIDENCE_PINNED": (
        "counted",
        "floor_sweep._analyse",
        "",
        "the floors pinned by committed evidence, counted by `_analyse` itself",
    ),
    "floor_sweep._MINIMUM_REASON_WORDS": (
        "scalar",
        "",
        "",
        "bounds the word count of one description: no collection of cases to delete from",
    ),
    "floor_sweep.MINIMUM_FLOORS_JUDGED": (
        "counted",
        "floor_sweep.measure_declarations",
        "len(universe)",
        "every floor-shaped constant `measure_declarations` judges",
    ),
    "floor_sweep.MINIMUM_BOUNDS_READ_FOR_POLARITY": (
        "counted",
        "floor_sweep.measure_polarity",
        "bounds_read",
        "the bounds read for polarity counted by `measure_polarity`",
    ),
    "floor_sweep.MINIMUM_CEILINGS_SET_ASIDE": (
        "counted",
        "floor_sweep.measure_polarity",
        "len(set_aside)",
        "the ceilings set aside counted by `measure_polarity`",
    ),
    "floor_sweep.MINIMUM_PROSE_MUTATION_SCENARIOS": (
        "counted",
        "floor_sweep._measure_prose_clearance",
        "",
        "the prose mutation scenarios counted by `_measure_prose_clearance`",
    ),
    "gate_detector_states.MINIMUM_DETECTOR_STATES_PROBED": (
        "counted",
        "gate_detector_states.floor_breaches",
        "probed",
        "the detector states probed counted by `floor_breaches`",
    ),
    "gate_detector_states.MINIMUM_DISTINCT_STATE_TRACES": (
        "counted",
        "gate_detector_states.floor_breaches",
        "distinct",
        "the distinct state traces counted by `floor_breaches`",
    ),
    "gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED": (
        "counted",
        "gate_reader_agreement.floor_breaches",
        "probed",
        "the arrangements probed counted by `floor_breaches`",
    ),
    "gate_reader_agreement.MINIMUM_GATES_COMPARED": (
        "counted",
        "gate_reader_agreement.floor_breaches",
        "measured['gates_compared']",
        "the gates compared counted by `floor_breaches`",
    ),
    "interview.MINIMUM_CHECKS": (
        "counted",
        "interview._main",
        "measured['checks_run']",
        "the checks counted by `_main`",
    ),
    "interview.MINIMUM_TRAIT_EPISODES": (
        "counted",
        "interview.trait_floor_state",
        "",
        "the trait episodes counted by `trait_floor_state`",
    ),
    "interview.MINIMUM_TRAIT_OCCASIONS": (
        "counted",
        "interview.trait_floor_state",
        "",
        "the trait occasions counted by `trait_floor_state`",
    ),
    "interview_direction.MINIMUM_NON_SOFTWARE_ARTEFACT_FIELDS": (
        "counted",
        "tests/test_interview_direction.py::test_the_artefact_question_follows_the_candidates_field",
        "",
        "the non software artefact fields counted by `test_the_artefact_question_follows_the_cand`",
    ),
    "interview_direction.MINIMUM_OPEN_TALK_STEPS": (
        "counted",
        "tests/test_interview_direction.py::test_the_opening_invites_open_ended_talk",
        "",
        "the open talk steps counted by `test_the_opening_invites_open_ended_talk`",
    ),
    "language_set.MINIMUM_LANGUAGE_DECLARATIONS": (
        "counted",
        "language_set.measure",
        "resolved",
        "the language declarations counted by `measure`",
    ),
    "lesson_triage.MIN_REASON_WORDS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`MIN_REASON_WORDS`): no collection of cases to delete from",
    ),
    "lesson_triage.MIN_RULE_WORDS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`MIN_RULE_WORDS`): no collection of cases to delete from",
    ),
    "literal_pin.MINIMUM_PINS_SWEPT": (
        "counted",
        "literal_pin.measure",
        "swept",
        "the pins swept counted by `measure`",
    ),
    "markup_text.MINIMUM_FIXTURE_OFFERS": (
        "counted",
        "markup_text.measure",
        "offers_checked",
        "the fixture offers counted by `measure`",
    ),
    "markup_text.MINIMUM_MARKUP_VALUES_COMPARED": (
        "counted",
        "markup_text.measure",
        "values_compared",
        "the markup values compared counted by `measure`",
    ),
    "matcher_readings.MINIMUM_CONTESTED_TRIPLES": (
        "counted",
        "matcher_readings.measure",
        "contested",
        "the contested triples counted by `measure`",
    ),
    "matcher_readings.MINIMUM_TRIPLES": (
        "counted",
        "matcher_readings.measure",
        "compared",
        "the triples counted by `measure`",
    ),
    "metric_naming.MINIMUM_CATEGORY_NAMED_RECORDED": (
        "counted",
        "metric_naming.floor_breaches",
        "recorded",
        "the category named recorded counted by `floor_breaches`",
    ),
    "metric_naming.MINIMUM_METRICS_CLASSIFIED": (
        "counted",
        "metric_naming.floor_breaches",
        "classified",
        "the metrics classified counted by `floor_breaches`",
    ),
    "naming.MINIMUM_SCANNED": (
        "counted",
        "naming._main",
        "measured['files_scanned']",
        "the scanned counted by `_main`",
    ),
    "pagination_capture.MINIMUM_DUPLICATE_KEY_PROBES": (
        "counted",
        "pagination_capture.measure_duplicate_page_keys",
        "probes_checked",
        "the duplicate key probes counted by `measure_duplicate_page_keys`",
    ),
    "pagination_capture.MINIMUM_PACKAGES_SCANNED_FOR_FURTHER_PAGES": (
        "counted",
        "pagination_capture.measure_unrecordable_drops",
        "scanned",
        "the packages scanned for further pages counted by `measure_unrecordable_drops`",
    ),
    "pagination_capture.MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED": (
        "counted",
        "pagination_capture.measure_duplicate_page_keys",
        "query_key_occurrences_scanned",
        "the query key occurrences scanned counted by `measure_duplicate_page_keys`",
    ),
    "pagination_capture.MINIMUM_REQUEST_KEYS": (
        "counted",
        "pagination_capture.measure",
        "request_keys",
        "the request keys counted by `measure`",
    ),
    "pagination_capture.MINIMUM_URL_SIDE_PROBES": (
        "counted",
        "pagination_capture.measure",
        "url_side_probes",
        "the url side probes counted by `measure`",
    ),
    "pay_normalise.MINIMUM_REFUSAL_STATES": (
        "counted",
        "pay_normalise.measure",
        "",
        "the refusal states counted by `measure`",
    ),
    "photo_extract.MIN_SHORT_SIDE": (
        "scalar",
        "",
        "",
        "bounds the smaller pixel side of one image: no collection of cases to delete from",
    ),
    "plan_milestones.MINIMUM_MERGED_RESOLVED": (
        "counted",
        "plan_milestones.floor_breaches",
        "",
        "the merged resolved counted by `floor_breaches`",
    ),
    "plan_milestones.MINIMUM_ROW_LABELS": (
        "counted",
        "plan_milestones.floor_breaches",
        "",
        "the row labels counted by `floor_breaches`",
    ),
    "plan_v2.MINIMUM_BOARD_SIZE": (
        "counted",
        "plan_v2.floor_breaches",
        "count",
        "the board size counted by `floor_breaches`",
    ),
    "plan_v2.MINIMUM_MERGED_TASKS": (
        "counted",
        "plan_v2.floor_breaches",
        "compared",
        "the merged tasks counted by `floor_breaches`",
    ),
    "plan_v2._MIN_TASK_CELLS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`len(cells)`): no collection of cases to delete from",
    ),
    "process_spec.MIN_ITEM_WORDS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`words`): no collection of cases to delete from",
    ),
    "profile_capture.MINIMUM_CHECKS": (
        "counted",
        "profile_capture._main",
        "measured['checks_run']",
        "the checks counted by `_main`",
    ),
    "profile_capture.MINIMUM_SUBJECT_CHECKS": (
        "counted",
        "profile_capture._main",
        "measured['checks_run']",
        "the subject checks counted by `_main`",
    ),
    "query_capture.MINIMUM_STEERABLE_PACKAGES_CHECKED": (
        "counted",
        "query_capture.measure",
        "checked",
        "the steerable packages checked counted by `measure`",
    ),
    "question_bank.MINIMUM_PROBES": (
        "counted",
        "question_bank._main",
        "measured['adversarial_checks_run']",
        "the probes counted by `_main`",
    ),
    "reader_notes.MINIMUM_PROBES": (
        "counted",
        "reader_notes._main",
        "measured['adversarial_checks_run']",
        "the probes counted by `_main`",
    ),
    "repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED": (
        "counted",
        "repo_gate.measure_evidence_stability",
        "",
        "the evidence keys compared counted by `measure_evidence_stability`",
    ),
    "repo_gate.MINIMUM_EVIDENCE_SOURCES_COMPARED": (
        "counted",
        "repo_gate.measure_evidence_stability",
        "",
        "the evidence sources compared counted by `measure_evidence_stability`",
    ),
    "repo_gate.MINIMUM_FILES_FORMATTED": (
        "counted",
        "repo_gate.measure_formatting",
        "",
        "the files formatted counted by `measure_formatting`",
    ),
    "repo_gate.MINIMUM_PYTHON_FILES_FORMATTED": (
        "counted",
        "repo_gate.measure_formatting",
        "",
        "the python files formatted counted by `measure_formatting`",
    ),
    "review_reader.MINIMUM_DISTINCT_SCOPE_STATES": (
        "counted",
        "review_reader.measure_marker_scope",
        "",
        "the distinct scope states counted by `measure_marker_scope`",
    ),
    "review_reader.MINIMUM_PRS_EVALUATED": (
        "counted",
        "review_reader.measure",
        "",
        "the prs evaluated counted by `measure`",
    ),
    "review_reader.MINIMUM_REPORTS_FOUND": (
        "counted",
        "review_reader.measure",
        "",
        "the reports found counted by `measure`",
    ),
    "review_reader.MINIMUM_SCOPE_STATES": (
        "counted",
        "review_reader.measure_marker_scope",
        "",
        "the scope states counted by `measure_marker_scope`",
    ),
    "salary_period.MINIMUM_PERIOD_CONTRACTS": (
        "counted",
        "salary_period._main",
        "measured['period_contracts_evaluated']",
        "the period contracts counted by `_main`",
    ),
    "salary_recovery.HOUSE_ESTIMATE_MINIMUM": (
        "counted",
        "salary_recovery._check_corpus",
        "count",
        "the house estimate minimum counted by `_check_corpus`",
    ),
    "salary_recovery.MINIMUM_CORPUS_ADS": (
        "counted",
        "salary_recovery._check_corpus",
        "len(ads)",
        "the corpus ads counted by `_check_corpus`",
    ),
    "second_reader.FAIL_OPEN_CASES_AT_LEAST": (
        "counted",
        "second_reader.measure",
        "len(fail_open_cases)",
        "the fail open cases counted by `measure`",
    ),
    "second_reader.FIXTURES_AT_LEAST": (
        "counted",
        "second_reader.measure",
        "len(spec_derived)",
        "the fixtures counted by `measure`",
    ),
    "second_reader.REGRESSION_CASES_AT_LEAST": (
        "counted",
        "second_reader.measure",
        "len(regression)",
        "the regression cases counted by `measure`",
    ),
    "second_reader.STDLIB_DISAGREEMENTS_AT_LEAST": (
        "counted",
        "second_reader.measure",
        "len(stdlib_disagreements)",
        "the stdlib disagreements counted by `measure`",
    ),
    "session_kind.MINIMUM_SESSION_KIND_CASES": (
        "counted",
        "session_kind.measure",
        "checked",
        "the session kind cases counted by `measure`",
    ),
    "skill_budget.MIN_HEADROOM_CHARS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`headroom`): no collection of cases to delete from",
    ),
    "skill_requirement.FEWEST_NOT_REQUIRING_CASES": (
        "counted",
        "skill_requirement.measure",
        "verdicts['not_requiring_cases']",
        "the not requiring cases counted by `measure`",
    ),
    "skill_requirement.FEWEST_REQUIRING_CASES": (
        "counted",
        "skill_requirement.measure",
        "verdicts['requiring_cases']",
        "the requiring cases counted by `measure`",
    ),
    "sourcing.MINIMUM_BOARDS": (
        "counted",
        "sourcing.measure_fixture",
        "len(run.outcomes)",
        "the boards the committed-capture run consulted",
    ),
    "sourcing.MINIMUM_OFFERS_COLLECTED": (
        "counted",
        "sourcing.measure_fixture",
        "collected",
        "the offers collected counted by `measure_fixture`",
    ),
    "sourcing_exclusions.MINIMUM_PRESENTATIONS": (
        "counted",
        "tests/test_sourcing_exclusions.py::test_the_probe_reports_no_resurfaced_exclusions",
        "",
        "the presentations counted by `test_the_probe_reports_no_resurfaced_exclusions`",
    ),
    "sourcing_exclusions._MIN_STEM": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`_MIN_STEM`): no collection of cases to delete from",
    ),
    "spec_consistency.MINIMUM_DECLARATIONS_FOUND": (
        "counted",
        "spec_consistency._main",
        "found",
        "the declarations found counted by `_main`",
    ),
    "stack_fit.MINIMUM_CASES": (
        "counted",
        "stack_fit.measure",
        "len(cases)",
        "the cases counted by `measure`",
    ),
    "step_gates.MINIMUM_STEPS_CHECKED": (
        "counted",
        "step_gates._main",
        "measured['steps_checked']",
        "the steps checked counted by `_main`",
    ),
    "step_specs.MIN_FIELD_WORDS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`MIN_FIELD_WORDS`): no collection of cases to delete from",
    ),
    "strings.MINIMUM_STRINGS": (
        "counted",
        "strings.measure",
        "len(keys(catalogue))",
        "the strings counted by `measure`",
    ),
    "task_gate.MINIMUM_EMITTED_FIELDS_SCANNED": (
        "counted",
        "task_gate.field_naming_floor_breaches",
        "",
        "the emitted fields scanned counted by `field_naming_floor_breaches`",
    ),
    "task_gate.MINIMUM_GATES_READ": (
        "counted",
        "task_gate.record",
        "",
        "the gates read counted by `record`",
    ),
    "task_gate.MINIMUM_PRESENCE_RECORDING_FIELDS": (
        "counted",
        "task_gate.field_naming_floor_breaches",
        "",
        "the presence recording fields counted by `field_naming_floor_breaches`",
    ),
    "task_gate.MINIMUM_RECORD_KEYS_COMPARED": (
        "counted",
        "task_gate.write_evidence",
        "",
        "the record keys compared counted by `write_evidence`",
    ),
    "task_gate.MINIMUM_STATUS_KEY_GATES": (
        "counted",
        "task_gate.record",
        "",
        "the status key gates counted by `record`",
    ),
    "test_mode.PASTE_CHARS": (
        "scalar",
        "",
        "",
        "bounds the size of one value (`len(text)`): no collection of cases to delete from",
    ),
    "topic_scope_gate.FEWEST_HELD_CASES": (
        "counted",
        "topic_scope_gate.measure",
        "len(held_cases)",
        "the held cases counted by `measure`",
    ),
    "topic_scope_gate.FEWEST_SHOWN_CASES": (
        "counted",
        "topic_scope_gate.measure",
        "len(shown_cases)",
        "the shown cases counted by `measure`",
    ),
    "trait_sufficiency.MINIMUM_CHECKS": (
        "counted",
        "trait_sufficiency._main",
        "measured['checks_run']",
        "the checks counted by `_main`",
    ),
    "trait_sufficiency.MINIMUM_TRAITS": (
        "counted",
        "trait_sufficiency.trait_evidence_sufficiency",
        "len(dimension_ids)",
        "the traits counted by `trait_evidence_sufficiency`",
    ),
    "verified_gate.MINIMUM_CONTRACTS": (
        "counted",
        "verified_gate._main",
        "measured['verified_gate_contracts_checked']",
        "the contracts counted by `_main`",
    ),
}
