"""D-12 — an unmeasured metric must be recordable, and only when it is asserted.

The state these tests defend is the one D-2 named: "the extractor is not
broken, the corpus cannot yet say whether it is right" has to be
distinguishable from "the extractor scored 0". The first is a measurement that
came back unscorable; the second is a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from integral import task_gate

_GATE = """---
id: {task_id}
title: "{title}"
priority: 5
status: {status}
---

## Acceptance gate

```gate
{metric} >= 0.75
evidence: {evidence}
key: {key}
{extra}```
"""


def _board(
    tmp_path: Path,
    *,
    value: object,
    status_line: str = "",
    status_field: object = None,
    task_id: str = "lo-1111",
) -> Path:
    """A one-task board whose evidence records `value` at the gate's key."""
    tasks = tmp_path / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    evidence = tmp_path / "status" / "evidence" / "X.json"
    evidence.parent.mkdir(parents=True)
    payload: dict[str, object] = {"score": value}
    if status_field is not None:
        payload["score_status"] = status_field
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    (tasks / f"{task_id}.md").write_text(
        _GATE.format(
            task_id=task_id,
            title="a task with a gate",
            status="open",
            metric="score",
            evidence="status/evidence/X.json",
            key="score",
            extra=status_line,
        ),
        encoding="utf-8",
    )
    return tasks


def test_a_task_whose_metric_is_unmeasured_is_not_reported_as_failing(tmp_path: Path) -> None:
    """The named test of D-12: an asserted `unmeasured` is not a failure.

    A gate that declares where its status lives, over an evidence file that
    positively says the metric could not be scored, has recorded what it found.
    That is the third outcome, and it must not be counted as a gate with
    nowhere to put its measurement.
    """
    tasks = _board(
        tmp_path,
        value=None,
        status_line="status-key: score_status\n",
        status_field="unmeasured",
    )

    measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    assert measured["unrecordable_task_gates"] == 0
    assert measured["gates_declaring_status_key"] == 1
    assert measured["unrecordable"] == []


def test_a_null_with_nowhere_to_record_it_is_counted(tmp_path: Path) -> None:
    """The pre-fix state: the honest measurement reads as a hard failure."""
    tasks = _board(tmp_path, value=None)

    measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    assert measured["unrecordable_task_gates"] == 1
    assert "declares no `status-key`" in measured["unrecordable"][0]


def test_a_scored_gate_is_recordable_whether_it_passes_or_fails(tmp_path: Path) -> None:
    """A number is recordable by being a number. Failing its threshold is a verdict."""
    for value in (0.0, 0.9):
        tasks = _board(tmp_path / str(value), value=value)
        measured = task_gate.measure(tasks, tasks / "_history", tmp_path / str(value))
        assert measured["unrecordable_task_gates"] == 0, value


def test_a_status_key_the_evidence_does_not_carry_is_not_a_third_outcome(tmp_path: Path) -> None:
    """Declaring `status-key` is not enough — the status has to be asserted.

    Otherwise a gate stops checking by omission, which is the vacuous-pass hole
    these gates were added to close, reopened somewhere new.
    """
    tasks = _board(tmp_path, value=None, status_line="status-key: absent_key\n")

    measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    assert measured["unrecordable_task_gates"] == 1
    assert "asserts no status there" in measured["unrecordable"][0]


def test_a_board_with_no_readable_gate_records_minus_one(tmp_path: Path) -> None:
    """Never a vacuous zero: nothing checked is not everything clean."""
    tasks = tmp_path / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "lo-2222.md").write_text(
        '---\nid: lo-2222\ntitle: "no gate"\npriority: 5\n---\n\n## Acceptance gate\n\nprose\n',
        encoding="utf-8",
    )

    measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    assert measured["unrecordable_task_gates"] == -1
    assert measured["unrecordable"] and "nothing was checked" in measured["unrecordable"][0]


def test_a_missing_evidence_file_is_left_to_the_gate_checker(tmp_path: Path) -> None:
    """CA-12's hole stays a hard failure — it is not excused as `unrecordable`.

    A declared gate with no evidence has measured nothing, and calling that
    "could not be recorded" would turn "we never looked" into a third outcome.
    """
    tasks = tmp_path / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "lo-3333.md").write_text(
        _GATE.format(
            task_id="lo-3333",
            title="gate with no evidence file",
            status="open",
            metric="score",
            evidence="status/evidence/missing.json",
            key="score",
            extra="",
        ),
        encoding="utf-8",
    )

    measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    assert measured["unrecordable_task_gates"] == -1  # nothing readable to check


def test_the_repository_board_can_record_every_gate_it_measures() -> None:
    """The live number D-12's gate asserts, over the real board."""
    measured = task_gate.measure()

    assert measured["evidence_gates_read"] > 0
    assert measured["unrecordable_task_gates"] == 0, measured["unrecordable"]
    # The split-off scoring task is the one that needs the third outcome, and
    # it is the proof the board uses it rather than merely permitting it.
    assert measured["gates_declaring_status_key"] >= 1
