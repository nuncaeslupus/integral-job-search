"""The plan/queue drift gate (S8).

Every test here is one of the ways the two documents have actually come apart,
or one of the ways a checker can report agreement it did not measure.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobsearch import plan_v2

HEADER = "| T# | Description | Step | Size | Depends | Gate | Tests | St |"
DIVIDER = "|----|-------------|------|------|---------|------|-------|----|"
ROW = "| T1 | Do it | 0 | S | — | `thing_violations == 0` | `test_thing` in `tests/t.py` | ☐ |"
TASK_TABLE = f"## Implementation tasks\n\n{HEADER}\n{DIVIDER}\n{ROW}\n"

EVIDENCE_TABLE = """## Evidence log

| T# | Gate | Measured | Command | SHA | Env | Date |
|----|------|----------|---------|-----|-----|------|
| T2 | `other_violations == 0` | 0 | `make gate` | `abc1234` | ci | 2026-08-18 |
"""


def _violations(measured: dict[str, object]) -> list[str]:
    problems = measured["violations"]
    assert isinstance(problems, list)
    return problems


def _queue(tmp_path: Path, *tasks: dict[str, object] | str) -> Path:
    """Write a queue. A bare string is shorthand for a task with that title."""
    queue = tmp_path / "tasks.jsonl"
    rows = []
    for n, task in enumerate(tasks):
        row: dict[str, object] = {"title": task} if isinstance(task, str) else dict(task)
        row.setdefault("id", f"lo-{n:04d}")
        rows.append(json.dumps(row))
    queue.write_text("".join(r + "\n" for r in rows), encoding="utf-8")
    return queue


def _plan(tmp_path: Path, body: str = TASK_TABLE) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text(body, encoding="utf-8")
    return plan


def _payload(tmp_path: Path, name: str, gate: str) -> None:
    (tmp_path / name).write_text(
        f"# payload\n\n## Acceptance gate\n\n```gate\n{gate}\nevidence: e.json\nkey: k\n```\n",
        encoding="utf-8",
    )


# --- membership ------------------------------------------------------------


def test_task_in_the_queue_without_a_plan_row_is_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(
        _plan(tmp_path), _queue(tmp_path, "T1: Do it", "T9: Unplanned work")
    )
    assert measured["plan_queue_task_drift"] == 1
    assert measured["in_queue_only"] == ["T9"]


def test_plan_row_without_a_queue_task_is_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path))
    assert measured["plan_queue_task_drift"] == 1
    assert measured["in_plan_only"] == ["T1"]


def test_agreeing_plan_and_queue_have_no_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path, "T1: Do it"))
    assert measured["plan_queue_task_drift"] == 0
    assert measured["violations"] == []


def test_duplicate_labels_are_reported_not_collapsed(tmp_path: Path) -> None:
    """Two queue records carrying one label is drift, not agreement.

    Comparing sets hides multiplicity: one plan row and two T1 tasks would
    otherwise report zero drift while the queue holds a task nobody planned.
    """
    measured = plan_v2.measure(
        _plan(tmp_path), _queue(tmp_path, "T1: Do it", "T1: Do it again")
    )
    assert measured["plan_queue_task_drift"] == 1
    assert measured["duplicate_labels"] == ["T1 appears 2 times in the queue"]


def test_duplicate_plan_rows_are_reported(tmp_path: Path) -> None:
    measured = plan_v2.measure(
        _plan(tmp_path, TASK_TABLE + ROW + "\n"), _queue(tmp_path, "T1: Do it")
    )
    assert measured["duplicate_labels"] == ["T1 appears 2 times in the plan"]


# --- table detection -------------------------------------------------------


def test_evidence_log_is_not_read_as_a_task_table(tmp_path: Path) -> None:
    """The Evidence log carries a T# column and a Gate column of its own.

    Read as a task table, its rows satisfy the plan side of the drift check, so
    a task that was measured but never sequenced would score zero drift — the
    one thing this gate exists to catch.
    """
    measured = plan_v2.measure(
        _plan(tmp_path, TASK_TABLE + "\n" + EVIDENCE_TABLE),
        _queue(tmp_path, "T1: Do it", "T2: Measured but never planned"),
    )
    assert measured["in_queue_only"] == ["T2"]
    assert measured["plan_rows"] == 1


def test_a_following_table_does_not_inherit_the_gate_column(tmp_path: Path) -> None:
    """Column state is cleared by any header, not only by a blank line.

    Without that, the Evidence log is safe by typography alone: remove the blank
    line between the two tables and its rows become plan rows carrying whatever
    cell the previous table's Gate index happens to land on.
    """
    glued = TASK_TABLE.rstrip("\n") + "\n" + EVIDENCE_TABLE.split("\n", 2)[2]
    measured = plan_v2.measure(_plan(tmp_path, glued), _queue(tmp_path, "T1: Do it"))
    assert measured["plan_rows"] == 1


def test_gate_column_is_found_by_header_not_by_index(tmp_path: Path) -> None:
    shifted = TASK_TABLE.replace(
        "| T# | Description | Step |", "| T# | Description | Owner | Step |"
    ).replace("| T1 | Do it | 0 | S | — |", "| T1 | Do it | nobody | 0 | S | — |")
    measured = plan_v2.measure(_plan(tmp_path, shifted), _queue(tmp_path, "T1: Do it"))
    assert measured["ungated_rows"] == []


# --- gate grammar and gate agreement ---------------------------------------


def test_a_row_without_a_measurable_gate_is_reported(tmp_path: Path) -> None:
    prose = TASK_TABLE.replace("`thing_violations == 0`", "tests pass")
    measured = plan_v2.measure(_plan(tmp_path, prose), _queue(tmp_path, "T1: Do it"))
    assert measured["rows_without_a_measurable_gate"] == 1
    assert _violations(measured)


def test_gate_metric_may_carry_digits(tmp_path: Path) -> None:
    f1 = TASK_TABLE.replace("`thing_violations == 0`", "`extraction_macro_f1 >= 0.75`")
    measured = plan_v2.measure(_plan(tmp_path, f1), _queue(tmp_path, "T1: Do it"))
    assert measured["ungated_rows"] == []


def test_a_payload_gate_differing_from_the_plan_is_drift(tmp_path: Path) -> None:
    """`gate_run.sh` executes the payload; a reader reads the plan.

    When they name different metrics — or the same metric with the opposite
    polarity — whichever gets implemented silently contradicts the other.
    """
    _payload(tmp_path, "lo-0000.md", "something_else == 1")
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path, "T1: Do it"))
    assert measured["gate_mismatches"] == [
        "T1: plan says `thing_violations == 0`, payload says `something_else == 1`"
    ]
    assert measured["plan_queue_task_drift"] == 1


def test_a_payload_gate_matching_the_plan_is_not_drift(tmp_path: Path) -> None:
    _payload(tmp_path, "lo-0000.md", "thing_violations  ==  0")
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path, "T1: Do it"))
    assert measured["gate_mismatches"] == []


# --- dependency agreement --------------------------------------------------


def _two_task_plan(depends: str) -> str:
    second = (
        f"| T2 | Do it after | 0 | S | {depends} | `other_violations == 0` "
        "| `test_other` in `tests/t.py` | ☐ |"
    )
    return TASK_TABLE + second + "\n"


def test_a_plan_dependency_missing_from_the_queue_is_drift(tmp_path: Path) -> None:
    """The queue is what dispatches; a prerequisite only in the plan is not one.

    `queue_batch.sh` reads blocking deps from the queue alone, so a task whose
    prerequisite lives only in the plan can be built before the thing it was
    sequenced behind.
    """
    measured = plan_v2.measure(
        _plan(tmp_path, _two_task_plan("T1")),
        _queue(tmp_path, "T1: Do it", {"title": "T2: Do it after", "deps": []}),
    )
    assert measured["dependency_mismatches"] == [
        "T2 depends on T1 in the plan and not in the queue"
    ]
    assert measured["plan_queue_task_drift"] == 1


def test_a_queue_dependency_missing_from_the_plan_is_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(
        _plan(tmp_path, _two_task_plan("—")),
        _queue(
            tmp_path,
            "T1: Do it",
            {"title": "T2: Do it after", "deps": [{"id": "lo-0000", "type": "blocks"}]},
        ),
    )
    assert measured["dependency_mismatches"] == [
        "T2 depends on T1 in the queue and not in the plan"
    ]


def test_matching_dependencies_are_not_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(
        _plan(tmp_path, _two_task_plan("T1")),
        _queue(
            tmp_path,
            "T1: Do it",
            {"title": "T2: Do it after", "deps": [{"id": "lo-0000", "type": "blocks"}]},
        ),
    )
    assert measured["dependency_mismatches"] == []
    assert measured["plan_queue_task_drift"] == 0


# --- malformed input reports, never raises ---------------------------------


def test_a_missing_plan_records_minus_one_not_zero(tmp_path: Path) -> None:
    """A run that could not measure must not look like a run that measured zero."""
    measured = plan_v2.measure(tmp_path / "absent.md", _queue(tmp_path, "T1: Do it"))
    assert measured["plan_queue_task_drift"] == -1
    assert _violations(measured)


def test_a_malformed_queue_line_is_reported_not_raised(tmp_path: Path) -> None:
    queue = tmp_path / "tasks.jsonl"
    queue.write_text('{"id": "lo-0000", "title": "T1: Do it"}\nnot json\n', encoding="utf-8")
    measured = plan_v2.measure(_plan(tmp_path), queue)
    assert any("not valid JSON" in v for v in _violations(measured))


def test_a_queue_line_that_is_not_an_object_is_reported_not_raised(tmp_path: Path) -> None:
    """`null`, a list and a bare scalar are all valid JSON and invalid records.

    Reaching `.get` on one raises, and a run that raises writes no evidence —
    indistinguishable from a run that never happened.
    """
    queue = tmp_path / "tasks.jsonl"
    queue.write_text('{"id": "lo-0000", "title": "T1: Do it"}\nnull\n[1, 2]\n7\n', encoding="utf-8")
    measured = plan_v2.measure(_plan(tmp_path), queue)
    reported = [v for v in _violations(measured) if "not a JSON object" in v]
    assert len(reported) == 3


def test_a_title_without_a_task_label_is_reported(tmp_path: Path) -> None:
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path, "T1: Do it", "housekeeping"))
    assert any("does not start with a task label" in v for v in _violations(measured))


# --- the committed state ---------------------------------------------------


def test_the_committed_plan_and_queue_agree() -> None:
    measured = plan_v2.measure()
    assert measured["violations"] == []
    assert measured["plan_queue_task_drift"] == 0
