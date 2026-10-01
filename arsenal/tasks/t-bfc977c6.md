---
id: t-bfc977c6
title: "T220: T218's backfill loop still cannot close on a non-pinned constraint row, and the step-7 checkpoint has two unpinned error paths"
priority: 5
deps: [t-a4dc5d52]
---



Filed from #598's second readers: round 3 (F6, issuecomment-5921154493) and round 4 (N1–N3, issuecomment-5921451249). None of them blocked T218. T218 merged as `2dbc21c`.

**F6 (fail-closed, design).** `sourcing_exclusions.unrecorded_statements` lists every free-text `constraint` row of steps `identify`/`constraints`. It skips only step 2's own pinned-field write (`_is_a_pinned_field_write`). A constraint row on a dimension outside T24's pinned ten is therefore listed forever, and no honest `record` covers it. Example: `dimensions=["commute"]`, text "No quiero desplazarme más de 30 minutos.", the shape of `integral.feedback`'s own fixture. On such a profile `unrecorded` never exits 0. Step 7's SKILL.md ("Backfill") says both "re-run until it exits 0" and "leave such a row as it is", which cannot both be followed. T218's task text requires the loop to be closable.

The remedy must close the loop without silencing a topic row. Weigh fail-open over fail-closed. One option is a per-row acknowledgement ("not a topic") kept under `search/`, written only with the evidence id and the candidate's words, which `unrecorded` honours. A listed-then-acknowledged topic is the candidate's call, never the session's.

**N1.** The step-7 checkpoint's `UnicodeDecodeError` catch (`.claude/skills/step-07-sourcing/scripts/run_checkpoint.py`) is reached by no test. Add a not-UTF-8 twin of `test_a_corrupt_evidence_log_makes_the_checkpoint_main_exit_2`.

**N2 (fail-closed).** The checkpoint does not catch `OSError`. With `search/exclusions.json` as a directory it gives a traceback and exit 1, while the `unrecorded` CLI exits 2, and SKILL.md says the two agree. Add `OSError` to the tuple and pin it.

**N3 (fail-open in theory; no writer produces it today).** `_is_a_pinned_field_write` accepts `{"quote": <non-str>, "value": {}}`, and reverting its `"quote" in payload` check survives the test file. Require a string quote and a non-empty value dict, or validate the value through `candidate.FIELD_MODELS`. Pin it.

Run tests with `UV_PYTHON=3.12`. CI uses 3.12, and on 3.13 `tests/test_connector_policy.py` fails on main as well.

## Acceptance gate

```bash
uv run pytest tests/test_exclusion_backfill.py
```
