---
id: t-29ceb4f4
title: "review: test diet — tests to cut or move off every-push CI"
priority: 5
requires: [human:gate]
---

Imported from issue #935

From the test-diet pass of the repo review of 2026-11-11. Nothing was changed; tick or delete as triaged.

**Numbers:** test_files=186, tests=7838, test_functions=4287, test_lines=80960, source_lines=102135, suite_seconds=189, ci_jobs_per_push=4, ran_suite=True, run_notes=pytest -n 4 on 4 cores, Python 3.13.18 (CI installs 3.12): 7797 passed, 15 failed, 26 skipped, 188.9s wall

**Estimated saving:** ~30-35% of pytest wall time (~245 of ~750 measured worker-seconds are gate re-measurement / whole-tree e2e tests that the `evidence` job already executes; derived from --durations=60 sums) for ~45 tests and ~1.5k lines moved or removed; plus 100% of CI time on pushes touching only docs/status/arsenal via a path filter. Only ~2-3% of test lines are outright deletable (meta + duplicate evidence assertions); this suite's cost is in few tests, not many.

- Time is extremely concentrated: the 60 slowest items (0.8% of 7838 collected tests) sum to ~362 worker-seconds, roughly half of the ~750 worker-seconds the 4-worker run spent. The other ~7780 tests are cheap; the 3551 parametrize expansions are already table-driven parser/matcher cases and are not the problem.
- About 245 of those 362 seconds are tests that re-run a module's whole-corpus acceptance-gate measurement (measure()/write_evidence()/main() over the committed corpus or connector library) and compare it with status/evidence/*.json. CI already has a dedicated `evidence` job that regenerates all 114 evidence modules and fails on any diff, and a `verify-gates` job that asserts thresholds. The pytest copies are a third execution of the same measurement.
- A real meta layer exists: ~20 test files read .claude/skills/*/SKILL.md, CONTRIBUTING/README or the Makefile; 5 files (21 tests) import nothing from the product at all, and the single slowest test in the suite (27s) checks a sentence in a skill file by regenerating all evidence in a copied tree.
- Ratio of 0.79 test lines per source line is high but most behaviour tests sampled (step0_open, pay_dominance, explain, parsers) assert real outcomes; the suite is not mostly junk. The cut is narrow and specific, not a broad cull.
- Biggest single win is CI config, not deletion: 4 jobs each pay checkout + uv install with no path filter, so a docs/status/task-file-only push runs lint, 7838 tests, 114 evidence regenerations and gate verification.
- pytest runs with -n auto --dist loadfile; test_connectors.py (3684 lines, 252 tests) and other 2-3k-line files pin one worker each, which caps the parallel speed-up.

### Cuts and moves
- [ ] **[ci-config] No path filter: docs/status/task-file pushes run all four jobs** (7838 tests) — ci.yml triggers on every pull_request and push to main with no paths/paths-ignore. This repo commits heavily to status/, arsenal/tasks/, docs/ and *.md; each such push runs lint, pytest (7838 tests), evidence (114 modules) and verify-gates. The workflow's own comment records the account ran out of its 2000 monthly minutes four days into a period. `.github/workflows/ci.yml:26-52`
  - Protection lost: small: verify-gates must still run when arsenal/tasks or status/evidence change, so filter per job rather than per workflow
  - Action: Add per-job change detection (dorny/paths-filter or `git diff --name-only`): run lint+test+evidence only when src/, tests/, tools/, corpus/, connectors/, dimensions/, strings/, taxes/, pyproject.toml, uv.lock or Makefile change; keep verify-gates for arsenal/tasks/** and status/evidence/** changes.
- [ ] **[duplicate] Pytest re-runs whole-corpus gate measurements the `evidence` job already runs** (22 tests) — ~20 tests named like test_the_committed_evidence_matches_what_the_code_measures_now / test_the_gate_holds / test_the_gate_measures_zero_over_a_real_denominator call the module's measure() over the real corpus and compare to status/evidence/<task>.json or its threshold. `make evidence` regenerates every one of these and fails on `git diff`, and `make verify-gates` asserts the thresholds. They account for most of the top-20 durations (e.g. substance_sweep 20.0s, claim_trace setup 17.9s, matcher_readings setup 17.8s, connector_contract setup 17.3s, vocabulary_reach 11.4s, document_reader setup 9.5s, sourcing_exclusions_live setup 9.0s, salary_recovery 6.4s, mock_interview 6.6s, connector_salary_audit setup 7.0s). `tests/test_pay_dominance.py:320, tests/test_vocabulary_reach.py:120, tests/test_substance_sweep.py:436, tests/test_claim_trace.py:441, tests/test_matcher_readings.py:149, tests/test_connector_contract.py (test_the_committed_library_conforms), tests/test_document_reader.py:53-60, tests/test_document_render.py:54-61, tests/test_form_answers.py:359, tests/test_pay_normalise.py:218, tests/test_rank_missing_inputs.py:170, tests/test_rank_order_readings.py:195, tests/test_second_reader.py:173, tests/test_skill_requirement.py:885, tests/test_stated_pricing.py:387, tests/test_test_mode.py:566, tests/test_connector_exchange.py:559, tests/test_salary_recovery.py:343, tests/test_mock_interview.py:408, tests/test_connector_shape.py:40`
  - Protection lost: none in CI — the evidence job fails on the same drift and verify-gates on the same threshold; locally, `make host-gate` runs both. Lost only for someone who runs bare `pytest` and skips `make evidence`.
  - Action: Delete the committed-evidence-equality tests outright; mark the remaining corpus-scale gate tests `@pytest.mark.gate` and run them with `-m 'not gate'` in the pytest job (the evidence job is their runner).
- [ ] **[meta] 27s test regenerates all evidence in a copied tree to police a SKILL.md sentence** (7 tests) — test_a_new_package_moves_more_keys_than_the_skill_ever_claimed copies the tracked tree, adds a connector package, runs the full evidence regeneration, and asserts more than 2 keys moved — to prove a number once written in .claude/skills/connector-new/SKILL.md was wrong. The file's other 6 tests regex the skill's step-6 prose for any number word. Slowest test in the suite. `tests/test_connector_new_skill.py:333 (whole file, 355 lines, 7 tests)`
  - Protection lost: none for product behaviour; a skill doc could again state a stale count
  - Action: Delete the 27s test (it is historic: the claim it refutes is gone); keep at most the cheap prose check, in a lint target rather than pytest.
- [ ] **[slow-tier] Slow end-to-end and time-budget tests on the every-push path** (12 tests) — A handful of valuable but heavy tests: library walk wall-clock budget (16.1s, by design ~10s), offline install of the published connector tree (13.2s), live-round skill exclusion (18.4s), salary_recovery corpus sweeps (9.4+9.3+5.8s), sourcing_exclusions_live red-gate (9.3s), connector_contract population/IP scans (9.1+5.1s), pagination_capture exit-code subprocess tests (6.0+3.5s). `tests/test_connector_contract.py:1401, tests/test_publish_connectors.py, tests/test_skill_requirement.py (test_the_live_round_says_a_skill_exclusion_was_not_applied), tests/test_salary_recovery.py, tests/test_sourcing_exclusions_live.py, tests/test_pagination_capture.py`
  - Protection lost: small: regressions in these paths surface on main/nightly instead of on the PR; path-filter them to connectors/** and corpus/** to keep PR coverage where it matters
  - Action: Add a `slow` marker; PR job runs `-m 'not slow and not gate'`, main push and a nightly schedule run everything. A wall-clock budget test in particular is flaky on shared runners and belongs in the nightly.
- [ ] **[ci-config] Four jobs each repeat checkout(fetch-depth 0) + uv + python install** (0 tests) — lint, test, evidence and verify-gates are separate runners, each billed with a 1-minute minimum and each doing a full-history checkout and environment sync. The workflow comment says a run is ~75-85s, so setup and per-job rounding are a large share of billed minutes; evidence and verify-gates are short and sequentially dependent in meaning. `.github/workflows/ci.yml jobs: lint/test/evidence/verify-gates`
  - Protection lost: none — keep them as separately named steps so 'stale' and 'fails its gate' remain distinguishable
  - Action: Merge evidence + verify-gates into one job with two steps (and lint into it too if minutes matter more than wall time); drop fetch-depth: 0 where no step reads history; skip on draft PRs.
- [ ] **[meta] Tests that only read skill/process prose, with no product import** (40 tests) — 5 files import nothing from `integral` and assert on wording in .claude/skills/*/SKILL.md or CLAUDE.md (21 tests, 407 lines). A further ~15 files mix such prose checks into behaviour tests (e.g. test_recommendation_prompts.py builds a recommendation linter over 13+ SKILL.md files and then unit-tests that linter with synthetic examples). `tests/test_compaction_hint.py, tests/test_multiple_downloads_warning.py, tests/test_session_kind_rule.py, tests/test_step03_public_work.py, tests/test_sourcing_fallback_synonyms.py; partly tests/test_recommendation_prompts.py:108-198, tests/test_step_skills.py, tests/test_step_specs.py`
  - Protection lost: small: agent-facing skill wording could drift; nothing a user-facing code path depends on
  - Action: Move prose checks into one `make lint-skills` script run only when .claude/skills/** changes; delete the tests-of-the-prose-linter. Saves lines and review noise, not time.
- [ ] **[trivial] write_evidence round-trip tests repeated per module** (20 tests) — ~20 near-identical tests (test_write_evidence_records_the_gate_key, ..._returns_what_it_wrote, test_the_module_writes_its_evidence, bare-invocation variants) call write_evidence(tmp) and assert the JSON equals the return value or holds the gate key at its passing value. Each re-runs the module's full measurement to check a json.dump; vocabulary_reach's costs 5.0s, sourcing_exclusions' 4.7s. `tests/test_enrichment.py:246, tests/test_explain.py:267, tests/test_feedback.py:232, tests/test_presentation.py:254, tests/test_pay_dominance.py:334, tests/test_vocabulary_reach.py:130, tests/test_dedup.py:351, tests/test_cv_store.py:613, tests/test_profile_capture.py:601, tests/test_question_bank.py:263, tests/test_elicit_extract.py:402, tests/test_connect_manual.py:263, tests/test_sourcing_exclusions.py:173, tests/test_step_skills.py:192`
  - Protection lost: none — the evidence job executes every module's __main__ write path on each run and diffs the bytes
  - Action: Delete; if a shared writer helper exists, keep one test of that helper.
- [ ] **[ci-config] Multi-thousand-line test files defeat --dist loadfile balancing** (0 tests) — addopts forces --dist loadfile, so a file is one scheduling unit. test_connectors.py (3684 lines, 252 collected), test_sourcing.py (2782), test_substance_sweep.py (2315), test_pagination_capture.py (2010), test_connector_contract.py (1956, >50s of durations alone) each occupy a single worker; on a 2-4 core runner the slowest file sets the floor. `pyproject.toml [tool.pytest.ini_options] addopts; tests/test_connector_contract.py, tests/test_connectors.py`
  - Protection lost: none
  - Action: After moving gate/slow tests out, split test_connector_contract.py so its corpus-scale fixture tests sit in their own file.

### Keep
- Table-driven parser/matcher suites (salary_recovery wording 153 cases, stack_fit 140, topic_scope 138, skill_requirement 2x133, employer_exclusion 2x75, advert_identity): real branch logic, already parametrized, cheap
- Money paths: pay_dominance, pay_normalise, stated_pricing, salary_period, salary_currency_bound behaviour tests (only their committed-evidence equality tests are flagged)
- Privacy/identity: test_step0_open.py (nothing read before a handle resolves), test_identity.py, test_state_home*.py, test_profile_guard.py
- Network politeness/security: test_robots.py, test_connector_policy.py, connector_contract checks that no contributed parse module is executed and no IP address is committed
- Approval/send path: test_approval.py, test_send_folder.py
- test_verify_gates.py and test_evidence_parallel.py: they test the CI tooling the gate system relies on, small (23 tests)
- AST architecture guards (test_report_style.py, test_generated_index.py, test_cue_whole_words.py): ~12s total, they enforce single-write-path invariants; acceptable, could move to lint

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
