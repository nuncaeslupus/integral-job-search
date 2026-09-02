"""D-12 — an unmeasured metric must be recordable, and only when it is asserted.

The state these tests defend is the one D-2 named: "the extractor is not
broken, the corpus cannot yet say whether it is right" has to be
distinguishable from "the extractor scored 0". The first is a measurement that
came back unscorable; the second is a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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


def test_a_census_committed_as_an_exact_value_is_reported_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate, shown failing — by running the gate.

    The first version of this test hand-built two dicts one key apart and
    asserted `sensitive_keys` reported that key. Its docstring said "the gate,
    shown failing"; the gate never ran, and what it established was that dict
    comparison compares dicts. Put a census key back into what `record`
    *commits* and the reading itself has to find it — otherwise
    `board_sensitive_record_keys == 0` would hold over a record that stopped
    carrying the sensitive keys rather than being fixed. (#297, D-3.)
    """
    real_record = task_gate.record

    def with_the_census_back(measured: dict[str, Any]) -> dict[str, Any]:
        return real_record(measured) | {"evidence_gates_read": measured["evidence_gates_read"]}

    monkeypatch.setattr(task_gate, "record", with_the_census_back)

    reading = task_gate.measure_board_sensitivity()

    assert reading["board_sensitive"] == ["evidence_gates_read"]
    assert reading["board_sensitive_record_keys"] == 1
    assert reading["record_keys_compared"] == task_gate.MINIMUM_RECORD_KEYS_COMPARED + 1


def test_the_board_sensitivity_gate_counts_the_keys_it_compared() -> None:
    """A zero over nothing compared is the failure this repository's gates are
    built around. The denominator is asserted here too — against the module's
    floor, not against `len(record(measure()))`, which was `4 >= 4` and moved
    with whatever `record` happened to emit (#297, D-4)."""
    measured = task_gate.measure_board_sensitivity()

    assert measured["board_sensitive_record_keys"] == 0, measured["board_sensitive"]
    assert measured["record_keys_compared"] >= task_gate.MINIMUM_RECORD_KEYS_COMPARED
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


# --- the floors, enforced --------------------------------------------------
#
# Nothing invoked `_main` until #297's second-reader audit, so every line of
# the exit-code logic was untested and D-1 — a floor breach exiting 3, which
# `make evidence` prints as "unmeasured (recorded)" and walks past — sat behind
# a green suite. These are that audit's cases 1 and 2, as fixtures. The
# precedent is T100's `test_an_empty_scan_still_fails` in `tests/test_naming.py`.


def _board_of(tmp_path: Path, gates: int, *, status_key_gates: int = 0) -> Path:
    """A board carrying `gates` readable evidence gates — the census a floor counts.

    Every gate is recordable (a real number at its key), so `unrecordable_task_gates`
    is zero and the run reaches the floors rather than stopping on a finding.
    """
    tasks = tmp_path / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    evidence = tmp_path / "status" / "evidence" / "X.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({"score": 0.9, "score_status": "measured"}), encoding="utf-8")
    for n in range(gates):
        task_id = f"lo-{n:04d}"
        (tasks / f"{task_id}.md").write_text(
            _GATE.format(
                task_id=task_id,
                title="a task with a gate",
                status="merged",
                metric="score",
                evidence="status/evidence/X.json",
                key="score",
                extra="status-key: score_status\n" if n < status_key_gates else "",
            ),
            encoding="utf-8",
        )
    return tasks


def _read_the_board(monkeypatch: pytest.MonkeyPatch, tasks: Path, root: Path) -> None:
    """Point `_main` at `tasks`. The measuring is real; only the board moves.

    `measure`'s paths are default arguments, bound at definition, so patching
    `DEFAULT_TASKS_DIR` would do nothing. The module attribute is the seam:
    both `write_evidence` and `measure_board_sensitivity` look `measure` up by
    name, and the latter's perturbation is forwarded so the sensitivity reading
    stays a real comparison rather than a board compared with itself.
    """
    real_measure = task_gate.measure

    def bound(
        _tasks: Path = tasks,
        _history: Path = tasks,
        _root: Path = root,
        withheld: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        return real_measure(tasks, tasks / "_history", root, withheld)

    monkeypatch.setattr(task_gate, "measure", bound)


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tasks: Path) -> tuple[int, Path]:
    """`_main` over `tasks`, writing its evidence somewhere disposable."""
    _read_the_board(monkeypatch, tasks, tmp_path)
    target = tmp_path / "D12.json"
    return task_gate._main(["task_gate", "--write-evidence", str(target)]), target


def test_a_healthy_synthetic_board_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control. Without it the three failures below could all be the harness."""
    exit_code, target = _run(monkeypatch, tmp_path, _board_of(tmp_path, 105, status_key_gates=25))

    assert exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["board_sensitive_record_keys"] == 0


def test_a_sub_floor_board_fails_instead_of_recording_a_floor_it_never_met(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit case 1: five readable gates against a floor of a hundred.

    Exit 3 was the old answer, and `Makefile`'s evidence loop maps 3 to
    "unmeasured (recorded)" and continues — so `make host-gate` was fully green
    over a board on which 126 of 131 gates were never read. Exit 1 is the only
    code that loop treats as a failure.
    """
    exit_code, target = _run(monkeypatch, tmp_path, _board_of(tmp_path, 5, status_key_gates=5))

    assert exit_code == 1
    assert "only 5 gate(s) counted for evidence_gates_read (floor 100)" in capsys.readouterr().err
    # And it wrote nothing. A record from this run could not tell the board
    # from a healthy one — a floor is a constant by construction, which is the
    # whole point of replacing the census — so writing it would assert a floor
    # the run had just failed. The exit code is the only thing that can carry
    # the finding, and it has to be one the caller stops on.
    assert not target.exists()


def test_a_near_floor_board_fails_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit case 2: ninety-two of a hundred and thirty-one.

    The interval [1, 99] is where a floor differs from a census, and it was
    silent for every value in it — a board that lost thirty per cent of its
    gates produced no artefact and no non-zero the caller respected.
    """
    exit_code, _ = _run(monkeypatch, tmp_path, _board_of(tmp_path, 92, status_key_gates=92))

    assert exit_code == 1
    assert "only 92 gate(s) counted for evidence_gates_read (floor 100)" in capsys.readouterr().err


def test_a_sub_floor_run_leaves_an_existing_record_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering, where it costs something: the exit code is not the only
    output of a failing run.

    `write_evidence` wrote before `_main` checked, so a five-gate board
    overwrote the committed D12 record with one claiming a hundred gates read
    — and that overwritten file is what the *next* run over a healthy board
    diffs against in `make evidence`. Byte-identical, not merely still valid.
    """
    tasks = _board_of(tmp_path, 5, status_key_gates=5)
    _read_the_board(monkeypatch, tasks, tmp_path)
    healthy = tmp_path / "D12.json"
    healthy.write_text('{"kept": true}\n', encoding="utf-8")
    before = healthy.read_bytes()

    exit_code = task_gate._main(["task_gate", "--write-evidence", str(healthy)])

    assert exit_code == 1
    assert healthy.read_bytes() == before


def test_a_board_that_stopped_declaring_status_keys_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-5: the adoption floor, raised from one to twenty and now enforced.

    The board declares twenty-nine `status-key` gates. Against a floor of one,
    this fixture — a hundred and five gates of which three still declare one —
    was a pass: an eighty-nine per cent collapse in the use of D-12's third
    outcome, invisible.
    """
    exit_code, target = _run(monkeypatch, tmp_path, _board_of(tmp_path, 105, status_key_gates=3))

    assert exit_code == 1
    assert (
        "only 3 gate(s) counted for gates_declaring_status_key (floor 20)"
        in capsys.readouterr().err
    )
    assert not target.exists()


def test_a_record_that_drops_a_key_fails_its_own_denominator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-4: `record_keys_compared` as something that can fail.

    `record` emits four keys unconditionally, so the old assertion
    `record_keys_compared >= len(record(measure()))` was `4 >= 4` — it moved
    with whatever `record` emitted and could not fail. Drop a key and the
    comparison spans three: zero sensitive keys over a shrunken record is a
    smaller claim than the gate makes, and it now says so.
    """
    tasks = _board_of(tmp_path, 105, status_key_gates=25)
    real_record = task_gate.record

    def without_the_finding(measured: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in real_record(measured).items() if k != "unrecordable_task_gates"}

    monkeypatch.setattr(task_gate, "record", without_the_finding)

    exit_code, _ = _run(monkeypatch, tmp_path, tasks)

    assert exit_code == 1
    assert "only 3 record key(s) were compared (floor 4)" in capsys.readouterr().err
