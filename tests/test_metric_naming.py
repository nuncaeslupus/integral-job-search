"""T123 — a metric named after a category is satisfiable by there being none of them.

Every verdict asserted here is derived from the rule as `metric_naming`'s docstring
states it and from the four instances `arsenal/tasks/t-21d5216a.md` names, not from what
the classifier happens to return: the four are written down in the task, which is the
nearest thing this check has to a spec, and the contrast case
(`bodyless_posts_sent_without_a_content_type`) is the task's own worked example of the
other verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import metric_naming

HEADER = "| T# | Description | Step | Size | Depends | Gate | Tests | St |"
DIVIDER = "|----|-------------|------|------|---------|------|-------|----|"


def _metric(name: str, comparison: str = "==", threshold: float = 0.0) -> metric_naming.Metric:
    return metric_naming.Metric(name=name, comparison=comparison, threshold=threshold)


def _verdict(name: str, comparison: str = "==", threshold: float = 0.0) -> str:
    return metric_naming.classify(_metric(name, comparison, threshold)).verdict


def _plan(tmp_path: Path, *gates: str) -> Path:
    rows = "\n".join(
        f"| T{n} | Do it | 0 | S | — | `{gate}` | `test_x` in `tests/t.py` | ☐ |"
        for n, gate in enumerate(gates, start=1)
    )
    plan = tmp_path / "plan.md"
    plan.write_text(f"## Implementation tasks\n\n{HEADER}\n{DIVIDER}\n{rows}\n", encoding="utf-8")
    return plan


def _task(directory: Path, stem: str, gate: str, evidence: str, key: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.md"
    path.write_text(
        "---\nid: t-0001\n---\n\n## Acceptance gate\n\n"
        f"```gate\n{gate}\nevidence: {evidence}\nkey: {key or gate.split()[0]}\n```\n",
        encoding="utf-8",
    )
    return path


def _payload(root: Path, relative: str, body: dict[str, object]) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def _board(
    tmp_path: Path, gate: str, payload: dict[str, object], *, key: str | None = None
) -> dict[str, object]:
    """One metric, declared in the plan and in a task file, with its payload written."""
    plan = _plan(tmp_path, gate)
    tasks = tmp_path / "arsenal" / "tasks"
    _task(tasks, "t-0001", gate, "status/evidence/X.json", key)
    _payload(tmp_path, "status/evidence/X.json", payload)
    return metric_naming.measure(plan, tasks, tasks / "_history", tmp_path)


# --- the rule, on the instances the task names -----------------------------


def test_the_three_clean_category_instances_the_task_names_are_category_named() -> None:
    """T115, T117 and T111, from `t-21d5216a.md`'s "Known instances" list.

    Each is satisfied by there being none of the things its head noun denotes — no
    floors, no probes, no classified keys — which is the definition of category-named.
    """
    assert _verdict("floors_that_do_not_fail_the_gate") == "category"
    assert _verdict("probes_identical_to_their_fixture") == "category"
    assert _verdict("growth_sensitive_evidence_keys") == "category"


def test_the_borderline_instance_is_category_named_and_says_what_pulled_the_other_way() -> None:
    """T108, which the task calls borderline.

    `named` predicates an act, which is the outcome-named shape; `fields` is a thing this
    repository holds, which is the category-named shape. The conservative verdict stands
    and the token that argued for the other one is reported, so the call can be disputed.
    """
    reading = metric_naming.classify(_metric("status_presence_fields_named_as_identity"))
    assert reading.verdict == "category"
    assert reading.borderline == "named"


def test_the_task_s_contrasting_example_is_outcome_named() -> None:
    """`bodyless_posts_sent_without_a_content_type` — an event that went wrong.

    A POST that was never sent is not a post lying around uncounted, so zero is the claim
    the gate means to make rather than a report about an empty population.
    """
    reading = metric_naming.classify(_metric("bodyless_posts_sent_without_a_content_type"))
    assert (reading.verdict, reading.clause, reading.head) == ("outcome", "E1", "posts")


def test_a_fault_marker_never_decides_the_verdict() -> None:
    """The fail-open rule this module refuses to be.

    Keying on privatives and fault predicates would call `floors_that_do_not_fail_the_gate`
    and `status_presence_fields_named_as_identity` outcome-named — two of the four cases
    the task exists to catch — so a marker is recorded and ignored.
    """
    for name in (
        "floors_that_do_not_fail_the_gate",
        "status_presence_fields_named_as_identity",
        "connector_packages_without_a_fixture",
        "task_rows_misnamed_by_their_gate",
    ):
        reading = metric_naming.classify(_metric(name))
        assert reading.borderline is not None, name
        assert reading.verdict == "category", name


def test_an_unrecognised_head_is_category_named() -> None:
    """C1 is the default, and the default is the conservative verdict.

    A wrong `category` costs one floor; a wrong `outcome` leaves a zero standing on an
    empty scan, which is the failure this module exists to prevent.
    """
    reading = metric_naming.classify(_metric("quuxes_beyond_the_frobnicator"))
    assert (reading.verdict, reading.clause) == ("category", "C1")


def test_a_gate_an_empty_scan_fails_is_out_of_scope() -> None:
    """Step 1. `corpus_size >= 500` is refused by an empty corpus, so it cannot be
    vacuously true and the category/outcome question does not arise."""
    assert _verdict("corpus_size", ">=", 500) == "out_of_scope"
    assert _verdict("dedup_precision", ">", 0.9) == "out_of_scope"
    assert _verdict("connector_contract_violations", "<=", 0) == "category"


def test_a_reading_of_one_quantity_is_not_a_count() -> None:
    """Step 2. There being "none of them" is not a way to satisfy an exit code or an
    error magnitude — there is one reading, not a population."""
    assert _verdict("lint_typecheck_exit_code") == "not_a_count"
    assert _verdict("weight_salary_equivalent_roundtrip_error", "<=", 0.05) == "not_a_count"
    assert _verdict("extraction_macro_f1", ">=", 0.7) == "out_of_scope"


def test_the_head_is_read_through_participles_and_qualifiers() -> None:
    assert metric_naming.head_noun("bodyless_posts_sent_without_a_content_type") == "posts"
    assert metric_naming.head_noun("probes_identical_to_their_fixture") == "probes"
    assert metric_naming.head_noun("growth_sensitive_evidence_keys") == "keys"
    assert metric_naming.head_noun("floors_that_do_not_fail_the_gate") == "floors"


# --- the finding -----------------------------------------------------------


def test_a_category_named_zero_with_nothing_behind_it_is_the_finding(tmp_path: Path) -> None:
    """The payload says "none of them" and cannot say how many were looked at.

    `"measured"` is deliberately in the payload: a status string is what a vacuous run
    writes too, so it must not count as evidence that anything was scanned.
    """
    measured = _board(
        tmp_path,
        "orphan_task_rows == 0",
        {"orphan_task_rows": 0, "gate_status": "measured", "orphans": []},
    )
    assert measured["category_named_metrics_recorded_without_a_denominator"] == 1
    assert measured["recorded_without_a_denominator"] == ["orphan_task_rows"]


def test_a_denominator_beside_the_zero_clears_it(tmp_path: Path) -> None:
    """T55's repair: `old_name_references == 0` is sound because `files_scanned_at_least`
    is committed beside it."""
    measured = _board(
        tmp_path,
        "orphan_task_rows == 0",
        {"orphan_task_rows": 0, "rows_scanned_at_least": 120, "orphans": []},
    )
    assert measured["recorded_without_a_denominator"] == []


def test_a_non_empty_collection_counts_as_a_denominator(tmp_path: Path) -> None:
    """D1, D10, T20a, T60 and T61 all evidence their scan with a list rather than a
    count, and each of those scans plainly happened."""
    measured = _board(
        tmp_path,
        "orphan_task_rows == 0",
        {"orphan_task_rows": 0, "rows_compared": ["a", "b"]},
    )
    assert measured["recorded_without_a_denominator"] == []


def test_an_empty_collection_and_a_zero_do_not(tmp_path: Path) -> None:
    """An empty list is what an empty scan produces, so it evidences nothing."""
    measured = _board(
        tmp_path,
        "orphan_task_rows == 0",
        {"orphan_task_rows": 0, "rows_compared": [], "rows_scanned": 0, "ok": True},
    )
    assert measured["recorded_without_a_denominator"] == ["orphan_task_rows"]


def test_an_outcome_named_metric_is_not_a_finding(tmp_path: Path) -> None:
    """The rule's whole point: an occurrence counted at zero needs no population."""
    measured = _board(
        tmp_path,
        "bodyless_posts_sent_without_a_content_type == 0",
        {"bodyless_posts_sent_without_a_content_type": 0},
    )
    assert measured["recorded_without_a_denominator"] == []
    assert measured["outcome_named"] == ["bodyless_posts_sent_without_a_content_type"]


def test_a_metric_with_no_payload_yet_is_not_a_finding(tmp_path: Path) -> None:
    """A metric nobody has measured claims nothing, so there is no zero to protect —
    the check bites when the payload lands."""
    plan = _plan(tmp_path, "orphan_task_rows == 0")
    tasks = tmp_path / "arsenal" / "tasks"
    _task(tasks, "t-0001", "orphan_task_rows == 0", "status/evidence/absent.json")
    measured = metric_naming.measure(plan, tasks, tasks / "_history", tmp_path)
    assert measured["recorded_without_a_denominator"] == []
    assert measured["category_named_metrics_recorded"] == 0


# --- the vacuity this module is itself exposed to --------------------------


def test_a_scan_that_reads_no_metrics_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    """The obvious trap, named in the task: a classifier reporting zero findings because
    it parsed nothing is its own subject."""
    plan = _plan(tmp_path)
    tasks = tmp_path / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    measured = metric_naming.measure(plan, tasks, tasks / "_history", tmp_path)
    assert measured["metric_naming_status"] == "unmeasured"
    assert measured["category_named_metrics_recorded_without_a_denominator"] == -1
    assert measured["violations"]


def test_removing_a_metric_from_the_scan_moves_the_denominator(tmp_path: Path) -> None:
    """The mutation the task requires: the finding must not be what disappears.

    Withhold a metric and it is `metrics_classified` that falls — the count of what was
    looked at — rather than a finding quietly vanishing from a still-green record.
    """
    plan = _plan(tmp_path, "orphan_task_rows == 0", "stray_probes == 0")
    tasks = tmp_path / "arsenal" / "tasks"
    _task(tasks, "t-0001", "orphan_task_rows == 0", "status/evidence/X.json")
    _task(tasks, "t-0002", "stray_probes == 0", "status/evidence/Y.json")
    both = metric_naming.measure(plan, tasks, tasks / "_history", tmp_path)
    (tasks / "t-0002.md").unlink()
    (tmp_path / "plan.md").write_text(
        (tmp_path / "plan.md")
        .read_text(encoding="utf-8")
        .replace(
            "| T2 | Do it | 0 | S | — | `stray_probes == 0` | `test_x` in `tests/t.py` | ☐ |\n", ""
        ),
        encoding="utf-8",
    )
    fewer = metric_naming.measure(plan, tasks, tasks / "_history", tmp_path)
    assert fewer["metrics_classified"] == both["metrics_classified"] - 1


def test_a_run_under_the_floor_fails_and_writes_nothing(tmp_path: Path) -> None:
    """T115's finding, applied on the day the floor was written.

    Exit **1**, not the 3 `make evidence` prints as "unmeasured (recorded)" and carries
    past — and no artefact, because the only record such a run could write is one
    asserting the floor it just missed.
    """
    plan = _plan(tmp_path, "orphan_task_rows == 0")
    tasks = tmp_path / "arsenal" / "tasks"
    _task(tasks, "t-0001", "orphan_task_rows == 0", "status/evidence/X.json")
    _payload(tmp_path, "status/evidence/X.json", {"orphan_task_rows": 0, "rows_at_least": 5})
    evidence = tmp_path / "out.json"
    measured = metric_naming.write_evidence(evidence, plan, tasks, tasks / "_history", tmp_path)
    assert metric_naming.floor_breaches(measured)
    assert not evidence.exists()


def test_the_repository_s_own_board_is_over_both_floors() -> None:
    """The floors are claims about this repository, so they are checked against it."""
    measured = metric_naming.measure()
    assert metric_naming.floor_breaches(measured) == []
    assert measured["metrics_classified"] >= metric_naming.MINIMUM_METRICS_CLASSIFIED
    assert (
        measured["category_named_metrics_recorded"] >= metric_naming.MINIMUM_CATEGORY_NAMED_RECORDED
    )


# --- what the record commits ----------------------------------------------


def test_the_censuses_are_committed_as_floors_not_as_counts() -> None:
    """T104's finding: a census committed exactly goes stale the moment any other task PR
    lands a gate block, reddening `make evidence` on work that changed nothing here."""
    committed = metric_naming.record(metric_naming.measure())
    assert committed["metrics_classified_at_least"] == metric_naming.MINIMUM_METRICS_CLASSIFIED
    for census in ("metrics_classified", "category_named_gate_metrics", "readings"):
        assert census not in committed


def test_another_task_landing_a_gate_block_does_not_change_the_record(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "orphan_task_rows == 0")
    tasks = tmp_path / "arsenal" / "tasks"
    _task(tasks, "t-0001", "orphan_task_rows == 0", "status/evidence/X.json")
    _payload(tmp_path, "status/evidence/X.json", {"orphan_task_rows": 0, "rows_at_least": 5})
    before = metric_naming.record(metric_naming.measure(plan, tasks, tasks / "_history", tmp_path))
    _task(tasks, "t-0002", "stray_probes == 0", "status/evidence/Y.json")
    _payload(tmp_path, "status/evidence/Y.json", {"stray_probes": 0, "probes_at_least": 3})
    after = metric_naming.record(metric_naming.measure(plan, tasks, tasks / "_history", tmp_path))
    assert before == after


def test_archiving_a_task_file_changes_nothing(tmp_path: Path) -> None:
    """Archiving is what every task PR does, so a record that moved across it would be
    wrong on one side of every merge (T100)."""
    plan = _plan(tmp_path, "orphan_task_rows == 0")
    tasks = tmp_path / "arsenal" / "tasks"
    history = tasks / "_history"
    _task(tasks, "t-0001", "orphan_task_rows == 0", "status/evidence/X.json")
    _payload(tmp_path, "status/evidence/X.json", {"orphan_task_rows": 0, "rows_at_least": 5})
    live = metric_naming.measure(plan, tasks, history, tmp_path)
    history.mkdir(parents=True, exist_ok=True)
    (tasks / "t-0001.md").rename(history / "t-0001.md")
    archived = metric_naming.measure(plan, tasks, history, tmp_path)
    assert metric_naming.record(live) == metric_naming.record(archived)
    assert live["metrics_classified"] == archived["metrics_classified"]


def test_the_committed_evidence_matches_what_the_code_measures_now() -> None:
    committed = json.loads(metric_naming.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == metric_naming.record(metric_naming.measure())
    assert committed["category_named_metrics_recorded_without_a_denominator"] == 0


def test_this_module_s_own_metric_is_category_named_and_carries_the_floor_that_repairs_it() -> None:
    """The check applied to itself, and it does not exempt itself.

    `category_named_metrics_recorded_without_a_denominator` is headed by *metrics* — a
    thing this repository holds — so C1 makes it category-named, privative and all. That
    is not a contradiction: the rule says a category-named metric is one that **requires
    a floor**, and this one commits two. Its own zero is therefore read together with
    proof that the scan happened, which is the whole prescription.
    """
    reading = metric_naming.classify(
        _metric("category_named_metrics_recorded_without_a_denominator")
    )
    assert (reading.verdict, reading.head) == ("category", "metrics")
    committed = json.loads(metric_naming.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed["metrics_classified_at_least"] > 0
    assert committed["category_named_metrics_recorded_at_least"] > 0
    assert metric_naming.denominators(
        committed, "category_named_metrics_recorded_without_a_denominator"
    )


def test_the_entry_point_exits_1_on_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finding is a failure, not a note in a file nobody reads."""
    plan = _plan(tmp_path, "orphan_task_rows == 0")
    tasks = tmp_path / "arsenal" / "tasks"
    _task(tasks, "t-0001", "orphan_task_rows == 0", "status/evidence/X.json")
    _payload(tmp_path, "status/evidence/X.json", {"orphan_task_rows": 0})
    monkeypatch.setattr(metric_naming, "DEFAULT_PLAN", plan)
    monkeypatch.setattr(metric_naming, "DEFAULT_TASKS", tasks)
    monkeypatch.setattr(metric_naming, "DEFAULT_HISTORY", tasks / "_history")
    monkeypatch.setattr(metric_naming, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(metric_naming, "MINIMUM_METRICS_CLASSIFIED", 1)
    monkeypatch.setattr(metric_naming, "MINIMUM_CATEGORY_NAMED_RECORDED", 1)
    assert metric_naming._main([str(tmp_path / "out.json")]) == 1
