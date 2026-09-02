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
    assert measured["evidence_gates_read"] >= task_gate.MINIMUM_GATES_READ
    assert measured["gates_declaring_status_key"] >= task_gate.MINIMUM_STATUS_KEY_GATES


def _add_gate(tasks: Path, task_id: str) -> None:
    """Land one more readable gate on the board — what merging a task PR does."""
    (tasks / f"{task_id}.md").write_text(
        _GATE.format(
            task_id=task_id,
            title="somebody else's task, merged",
            status="merged",
            metric="score",
            evidence="status/evidence/X.json",
            key="score",
            extra="",
        ),
        encoding="utf-8",
    )


def test_the_committed_record_survives_another_task_pr_merging(tmp_path: Path) -> None:
    """The regression this task exists for.

    CI scores the **merge** ref, so every open PR is measured against a board
    that already has the merged task's gate block on it. When the record
    carried the census, that made every other open PR's `D12.json` stale the
    instant any one of them merged — quadratic churn, each round restarting
    the review bot, and one merge conflict whose only hunk was this file.
    """
    tasks = _board(tmp_path, value=0.9)
    before_measured = task_gate.measure(tasks, tasks / "_history", tmp_path)
    before = task_gate.record(before_measured)

    _add_gate(tasks, "lo-9999")
    after_measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    # The perturbation has to be real, or the equality below proves nothing.
    assert after_measured["evidence_gates_read"] == before_measured["evidence_gates_read"] + 1
    assert task_gate.record(after_measured) == before


def test_archiving_a_task_file_changes_nothing_either(tmp_path: Path) -> None:
    """T100's axis, checked here and found already clean.

    `measure` reads `arsenal/tasks/` and `arsenal/tasks/_history/` as one
    board, so `open_task_pr.sh` moving the file between them was never what
    moved this record — which is why `archive_sensitive_evidence_keys` reported
    zero for D12 throughout and the merge axis went unnoticed.
    """
    tasks = _board(tmp_path, value=0.9)
    before = task_gate.record(task_gate.measure(tasks, tasks / "_history", tmp_path))

    history = tasks / "_history"
    history.mkdir()
    (tasks / "lo-1111.md").rename(history / "lo-1111.md")

    assert task_gate.record(task_gate.measure(tasks, history, tmp_path)) == before


def test_a_census_committed_as_an_exact_value_is_reported_sensitive() -> None:
    """The gate, shown failing. Put a census key back and the metric finds it —
    otherwise `board_sensitive_record_keys == 0` would hold over a record that
    stopped carrying the sensitive keys rather than being fixed."""
    census = dict(task_gate.record(task_gate.measure()))
    census["evidence_gates_read"] = 126

    assert task_gate.sensitive_keys(census, {**census, "evidence_gates_read": 127}) == [
        "evidence_gates_read"
    ]


def test_the_board_sensitivity_gate_counts_the_keys_it_compared() -> None:
    """A zero over nothing compared is the failure this repository's gates are
    built around. The denominator is asserted here too."""
    measured = task_gate.measure_board_sensitivity()

    assert measured["board_sensitive_record_keys"] == 0, measured["board_sensitive"]
    assert measured["record_keys_compared"] >= len(task_gate.record(task_gate.measure()))
    assert measured["board_sensitivity_status"] == "measured"


def test_the_sensitivity_reading_is_unmeasured_with_no_gate_to_withhold(tmp_path: Path) -> None:
    """No readable gate, nothing to withhold, nothing proved. Not a pass."""
    tasks = tmp_path / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "lo-4444.md").write_text(
        '---\nid: lo-4444\ntitle: "no gate"\npriority: 5\n---\n\n## Acceptance gate\n\nprose\n',
        encoding="utf-8",
    )

    measured = task_gate.measure_board_sensitivity(tasks, tasks / "_history", tmp_path)

    assert measured["board_sensitivity_status"] == "unmeasured"
    assert measured["record_keys_compared"] == 0
