"""The plan/queue drift gate (S8).

Every test here is one of the ways the two documents have actually come apart,
or one of the ways a checker can report agreement it did not measure.
"""

from __future__ import annotations

import json
from pathlib import Path

from jobsearch import plan_v2

TASK_TABLE = """## Implementation tasks

| T# | Description | Step | Size | Depends | Gate | Tests | St |
|----|-------------|------|------|---------|------|-------|----|
| T1 | Do it | 0 | S | — | `thing_violations == 0` | `test_thing` in `tests/t.py` | ☐ |
"""

EVIDENCE_TABLE = """## Evidence log

| T# | Gate | Measured | Command | SHA | Env | Date |
|----|------|----------|---------|-----|-----|------|
| T2 | `other_violations == 0` | 0 | `make gate` | `abc1234` | ci | 2026-08-18 |
"""


def _violations(measured: dict[str, object]) -> list[str]:
    problems = measured["violations"]
    assert isinstance(problems, list)
    return problems


def _queue(tmp_path: Path, *titles: str) -> Path:
    queue = tmp_path / "tasks.jsonl"
    queue.write_text(
        "".join(json.dumps({"id": f"lo-{n:04d}", "title": t}) + "\n" for n, t in enumerate(titles)),
        encoding="utf-8",
    )
    return queue


def _plan(tmp_path: Path, body: str) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text(body, encoding="utf-8")
    return plan


def test_task_in_the_queue_without_a_plan_row_is_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(
        _plan(tmp_path, TASK_TABLE), _queue(tmp_path, "T1: Do the thing", "T9: Unplanned work")
    )
    assert measured["plan_queue_task_drift"] == 1
    assert measured["in_queue_only"] == ["T9"]


def test_plan_row_without_a_queue_task_is_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(_plan(tmp_path, TASK_TABLE), _queue(tmp_path))
    assert measured["plan_queue_task_drift"] == 1
    assert measured["in_plan_only"] == ["T1"]


def test_agreeing_plan_and_queue_have_no_drift(tmp_path: Path) -> None:
    measured = plan_v2.measure(_plan(tmp_path, TASK_TABLE), _queue(tmp_path, "T1: Do the thing"))
    assert measured["plan_queue_task_drift"] == 0
    assert measured["violations"] == []


def test_evidence_log_is_not_read_as_a_task_table(tmp_path: Path) -> None:
    """The Evidence log carries a T# column and a Gate column of its own.

    Read as a task table, its rows satisfy the plan side of the drift check, so
    a task that was measured but never sequenced would score zero drift — the
    one thing this gate exists to catch.
    """
    measured = plan_v2.measure(
        _plan(tmp_path, TASK_TABLE + "\n" + EVIDENCE_TABLE),
        _queue(tmp_path, "T1: Do the thing", "T2: Measured but never planned"),
    )
    assert measured["in_queue_only"] == ["T2"]
    assert measured["plan_rows"] == 1


def test_gate_column_is_found_by_header_not_by_index(tmp_path: Path) -> None:
    shifted = TASK_TABLE.replace(
        "| T# | Description | Step | Size | Depends | Gate | Tests | St |",
        "| T# | Description | Owner | Step | Size | Depends | Gate | Tests | St |",
    ).replace(
        "| T1 | Do it | 0 | S | — |",
        "| T1 | Do it | nobody | 0 | S | — |",
    )
    measured = plan_v2.measure(_plan(tmp_path, shifted), _queue(tmp_path, "T1: Do the thing"))
    assert measured["ungated_rows"] == []


def test_a_row_without_a_measurable_gate_is_reported(tmp_path: Path) -> None:
    prose = TASK_TABLE.replace("`thing_violations == 0`", "tests pass")
    measured = plan_v2.measure(_plan(tmp_path, prose), _queue(tmp_path, "T1: Do the thing"))
    assert measured["rows_without_a_measurable_gate"] == 1
    assert measured["violations"]


def test_gate_metric_may_carry_digits(tmp_path: Path) -> None:
    f1 = TASK_TABLE.replace("`thing_violations == 0`", "`extraction_macro_f1 >= 0.75`")
    measured = plan_v2.measure(_plan(tmp_path, f1), _queue(tmp_path, "T1: Do the thing"))
    assert measured["ungated_rows"] == []


def test_a_missing_plan_records_minus_one_not_zero(tmp_path: Path) -> None:
    """A run that could not measure must not look like a run that measured zero."""
    measured = plan_v2.measure(tmp_path / "absent.md", _queue(tmp_path, "T1: Do the thing"))
    assert measured["plan_queue_task_drift"] == -1
    assert measured["violations"]


def test_a_malformed_queue_line_is_reported_not_raised(tmp_path: Path) -> None:
    queue = tmp_path / "tasks.jsonl"
    queue.write_text('{"id": "lo-0000", "title": "T1: Do the thing"}\nnot json\n', encoding="utf-8")
    measured = plan_v2.measure(_plan(tmp_path, TASK_TABLE), queue)
    assert any("not valid JSON" in v for v in _violations(measured))


def test_a_title_without_a_task_label_is_reported(tmp_path: Path) -> None:
    measured = plan_v2.measure(
        _plan(tmp_path, TASK_TABLE), _queue(tmp_path, "T1: Do the thing", "housekeeping")
    )
    assert any("does not start with a task label" in v for v in _violations(measured))


def test_the_committed_plan_and_queue_agree() -> None:
    measured = plan_v2.measure()
    assert measured["violations"] == []
    assert measured["plan_queue_task_drift"] == 0
