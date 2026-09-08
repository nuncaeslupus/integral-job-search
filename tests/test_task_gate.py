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


def test_a_healthy_synthetic_board_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_a_board_sensitive_reading_writes_no_evidence_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run whose record is board-sensitive must leave the artefact alone.

    `_main` returns 1, so CI stops — but the file it wrote stays on disk and
    becomes the baseline the next `make evidence` diffs against. That is the
    same shape the floor ordering already fixed one branch earlier: the only
    record this run could write is one whose values move on somebody else's
    merge, which is precisely what D-12's gate exists to refuse. (#297 review.)
    """
    real_record = task_gate.record

    def with_the_census_back(measured: dict[str, Any]) -> dict[str, Any]:
        return real_record(measured) | {"evidence_gates_read": measured["evidence_gates_read"]}

    monkeypatch.setattr(task_gate, "record", with_the_census_back)
    target = tmp_path / "D12.json"

    measured = task_gate.write_evidence(target)

    assert measured["board_sensitive_record_keys"] == 1
    assert not target.exists(), "a board-sensitive run wrote the record the gate refuses"


def test_a_thin_sensitivity_comparison_writes_no_evidence_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`board_sensitive_record_keys == 0` over too few keys is a vacuous zero.

    `record_keys_compared` is the denominator that says the comparison spanned
    the record. Below its floor the zero means "nothing was compared", and
    committing that artefact commits the vacuity. (#297 review.)
    """
    real_record = task_gate.record

    def one_key_only(measured: dict[str, Any]) -> dict[str, Any]:
        return {"unrecordable_task_gates": real_record(measured)["unrecordable_task_gates"]}

    monkeypatch.setattr(task_gate, "record", one_key_only)
    target = tmp_path / "D12.json"

    measured = task_gate.write_evidence(target)

    assert measured["board_sensitive_record_keys"] == 0
    assert measured["record_keys_compared"] < task_gate.MINIMUM_RECORD_KEYS_COMPARED
    assert not target.exists(), "a run that compared too few keys wrote its vacuous zero"


# --- T108: a field that records presence must not be named as an identity claim ---


def test_recordable_still_accepts_a_status_only_gate() -> None:
    """The rename is a rename: a gate with no number and an asserted status stays
    recordable.

    Both #286 and #290 proposed setting this field to `false` because the
    evidence says `measured` rather than `asserted`. That change would have made
    every status-only gate unrecordable — `recordable` is
    `value_is_numeric or <the presence field>` — so this pins the behaviour the
    rename must not move.
    """
    reading = task_gate.Reading(
        task_id="lo-1111",
        key="score",
        evidence="status/evidence/X.json",
        value_is_numeric=False,
        declares_status_key=True,
        status_key_resolves=True,
    )

    assert reading.recordable


def test_a_status_key_resolving_to_an_empty_value_is_not_recordable(tmp_path: Path) -> None:
    """Presence means a non-empty string, and whitespace is not one.

    The companion to `test_a_status_key_the_evidence_does_not_carry_is_not_a_third_outcome`:
    that one covers a key the file omits, this one a key the file carries and
    says nothing at. Both are the same hole — a gate that stops checking by
    omission — and only the second is reachable by a generated evidence file
    writing `""` where a status should be.
    """
    tasks = _board(
        tmp_path,
        value=None,
        status_line="status-key: score_status\n",
        status_field="   ",
    )

    measured = task_gate.measure(tasks, tasks / "_history", tmp_path)

    assert measured["unrecordable_task_gates"] == 1
    assert "asserts no status there" in measured["unrecordable"][0]


def test_no_emitted_gate_field_names_presence_as_identity() -> None:
    """T108's gate, over the fields this module actually emits.

    The finding is zero **and** the denominator is asserted: a rename verified
    over no fields at all is the clean zero every gate here exists to refuse,
    and this metric is category-named (T123), so the population it ranges over
    has to be shown non-empty in the same breath.
    """
    measured = task_gate.measure_field_naming()

    assert measured["field_naming_status"] == "measured"
    assert measured["status_presence_fields_named_as_identity"] == 0
    assert measured["identity_named_presence_fields"] == []
    assert measured["emitted_fields_scanned"] >= task_gate.MINIMUM_EMITTED_FIELDS_SCANNED
    assert (
        measured["presence_recording_fields_scanned"] >= task_gate.MINIMUM_PRESENCE_RECORDING_FIELDS
    )
    # And the population is the one the metric names: both presence fields the
    # emitted row carries were classified, not merely counted.
    assert measured["presence_recording_fields"] == ["declares_status_key", "status_key_resolves"]


def test_the_old_name_is_the_worked_example_the_classifier_catches() -> None:
    """The mutation, without editing the module: the pre-rename row scores 1.

    `status_is_asserted` is invariant under the status's *content* changing
    (`measured` and `pending` both resolve) and flips when the status goes
    away — so it records presence — while its name binds the subject to a
    claim with a copula. That pair is the defect, and it is what two cold
    readers read off the name.
    """
    present_a = {"status_is_asserted": True, "value_is_numeric": True, "task": "lo-1111"}
    present_b = {"status_is_asserted": True, "value_is_numeric": False, "task": "lo-1111"}
    absent = {"status_is_asserted": False, "value_is_numeric": False, "task": "lo-1111"}

    presence, identity = task_gate.classify_emitted_fields(present_a, present_b, absent)

    assert presence == ["status_is_asserted"]
    assert identity == ["status_is_asserted"]


def test_a_copula_over_a_content_predicate_is_not_the_defect() -> None:
    """`value_is_numeric` keeps its name, and the rule has to say why.

    It changes when the value's content changes, so it is a claim about the
    value and its name is accurate. A rule that banned every `_is_` name would
    have renamed it too, and would have been a keyword list rather than a
    reading of what the field records.
    """
    present_a = {"value_is_numeric": True}
    present_b = {"value_is_numeric": False}
    absent = {"value_is_numeric": False}

    presence, identity = task_gate.classify_emitted_fields(present_a, present_b, absent)

    assert presence == []
    assert identity == []


def test_a_probe_that_classifies_no_presence_field_writes_no_evidence(tmp_path: Path) -> None:
    """Zero identity-named fields out of zero presence fields is not a pass.

    The same argument as D-12's own floors, on the axis T123 names: this
    metric counts a category, so it is satisfiable by the category being
    empty. A probe that stopped classifying anything must refuse to write the
    record, or the artefact asserting a floor it never met becomes the
    baseline the next `make evidence` diffs against.
    """
    degenerate = {
        "status_presence_fields_named_as_identity": 0,
        "identity_named_presence_fields": [],
        "presence_recording_fields": [],
        "emitted_fields": ["task", "key", "evidence", "value_is_numeric", "declares_status_key"],
        "emitted_fields_scanned": 5,
        "presence_recording_fields_scanned": 0,
        "field_naming_status": "measured",
    }
    target = tmp_path / "T108.json"

    assert task_gate.field_naming_floor_breaches(degenerate)
    task_gate.write_field_naming_evidence(target, measured=degenerate)

    assert not target.exists()


def test_a_thin_field_naming_denominator_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 1, not 3 — `make evidence` maps 3 to "unmeasured (recorded)" and
    carries on, so a floor that returned it would only ever be advice."""
    monkeypatch.setattr(
        task_gate,
        "measure_field_naming",
        lambda: {
            "status_presence_fields_named_as_identity": 0,
            "identity_named_presence_fields": [],
            "presence_recording_fields": [],
            "emitted_fields": [],
            "emitted_fields_scanned": 0,
            "presence_recording_fields_scanned": 0,
            "measure_fields_not_classified": [],
            "measure_emits_the_classified_row": True,
            "field_naming_status": "measured",
        },
    )

    exit_code = task_gate._main(
        [
            "task_gate",
            "--write-evidence",
            str(tmp_path / "D12.json"),
            "--write-t108-evidence",
            str(tmp_path / "T108.json"),
        ]
    )

    assert exit_code == 1
    assert "emitted_fields_scanned" in capsys.readouterr().err
    assert not (tmp_path / "T108.json").exists()


def _live_probe_rows(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """This module's own emitted row, with the gate's target present and gone."""
    present = task_gate._probe_row(tmp_path / "p", value=5, status="measured", declares=True)
    absent = task_gate._probe_row(
        tmp_path / "q", value=task_gate._MISSING, status=task_gate._MISSING, declares=False
    )
    return present, absent


def test_the_next_name_the_denylist_would_have_passed_is_caught() -> None:
    """F1 (#399) — `status_asserted`, the likeliest name after the rename.

    The classifier's first form denied four copulas, which is a fail-open
    filter: every name avoiding `is`/`are`/`was`/`were` walked through it, so
    dropping one underscore from the defect's own name scored a clean zero.
    The comment above `_RESOLUTION_VERBS` states a **positive** rule — a
    presence field must carry a verb of resolution or declaration — and
    `asserted` is a past participle, the grammar that reads as the subject's
    value. Same presence behaviour as the old name; same verdict.
    """
    present_a = {"status_asserted": True, "value_is_numeric": True}
    present_b = {"status_asserted": True, "value_is_numeric": False}
    absent = {"status_asserted": False, "value_is_numeric": False}

    presence, identity = task_gate.classify_emitted_fields(present_a, present_b, absent)

    assert presence == ["status_asserted"]
    assert identity == ["status_asserted"]
    assert not task_gate.names_presence_honestly("status_asserted")
    # And the two names the module does emit pass the same positive rule.
    assert task_gate.names_presence_honestly("status_key_resolves")
    assert task_gate.names_presence_honestly("declares_status_key")
    # A verb of resolution does not license a copula built around it.
    assert not task_gate.names_presence_honestly("status_is_resolved")


def test_measure_emits_the_row_the_classification_scans() -> None:
    """F2 (#399) — the classification is about `measure`, so say so.

    `classify_emitted_fields` reads `_emitted_row`. Nothing asserted that
    `measure` routes through it, so reverting `measure` to its pre-T108 inline
    dict left the module emitting `status_is_asserted` — the exact defect T108
    removes — while the metric read 0 and `--check` exited 0.
    """
    measured = task_gate.measure_field_naming()

    assert measured["measure_emits_the_classified_row"] is True
    assert measured["measure_fields_not_classified"] == []


def test_a_measure_that_stops_routing_through_the_emitted_row_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The F2 mutation, without editing the module: the pre-T108 inline dict.

    `measure` emits the same six values under the old fifth name. The
    classification never sees it, and that disagreement is the finding.
    """
    real = task_gate.measure

    def pre_t108(*args: Any, **kwargs: Any) -> dict[str, Any]:
        measured = real(*args, **kwargs)
        measured["readings"] = [
            {("status_is_asserted" if k == "status_key_resolves" else k): v for k, v in row.items()}
            for row in measured["readings"]
        ]
        return measured

    monkeypatch.setattr(task_gate, "measure", pre_t108)

    agrees, emitted, classified = task_gate.measure_emits_the_classified_row(tmp_path / "d")

    assert agrees is False
    assert "status_is_asserted" in emitted
    assert "status_is_asserted" not in classified


def test_a_presence_field_that_is_not_a_bool_escapes_and_this_row_has_none(
    tmp_path: Path,
) -> None:
    """F3 (#399) — the accepted limitation, and the assertion that bounds it.

    `classify_emitted_fields` requires a field to be a `bool` in all three
    probes, so a presence field emitted as `"yes"`/`"no"` is never classified
    and can never be reported however it is named. That is fail-open, and it
    is committed here rather than answered in prose.

    The second half is what makes the fixture load-bearing: **this module's
    emitted row does not exercise the hole**. Every field that changes when
    the gate's target disappears is a bool, so a future row that records
    presence as a string turns this red rather than going quietly unclassified.
    """
    stringly_a = {"status_asserted": "yes", "value_is_numeric": True}
    stringly_b = {"status_asserted": "yes", "value_is_numeric": False}
    stringly_absent = {"status_asserted": "no", "value_is_numeric": False}

    presence, identity = task_gate.classify_emitted_fields(stringly_a, stringly_b, stringly_absent)

    assert presence == []  # the documented limitation
    assert identity == []

    present, absent = _live_probe_rows(tmp_path)
    changed = [name for name in present if present[name] != absent[name]]
    assert changed, "the probes must vary something, or there is nothing to classify"
    non_bool = [name for name in changed if not isinstance(present[name], bool)]
    assert non_bool == [], f"presence recorded as a non-bool escapes classification: {non_bool}"


def test_a_presence_field_the_probes_never_vary_escapes_and_this_row_has_none(
    tmp_path: Path,
) -> None:
    """F4 (#399) — the second accepted limitation, bounded the same way.

    A field the probes answer identically in all three rows fails
    `present_a[name] != absent[name]` and is dropped, so a presence field
    hard-wired to `True` is invisible to the metric whatever it is called.
    Committed as a fixture, with the half that binds this module: **no bool
    the emitted row carries is constant across the probes**, so a field the
    probes cannot move turns this red.
    """
    frozen_a = {"status_asserted": True, "value_is_numeric": True}
    frozen_b = {"status_asserted": True, "value_is_numeric": False}
    frozen_absent = {"status_asserted": True, "value_is_numeric": False}

    presence, identity = task_gate.classify_emitted_fields(frozen_a, frozen_b, frozen_absent)

    assert presence == []  # the documented limitation
    assert identity == []

    present, absent = _live_probe_rows(tmp_path)
    frozen = [
        name
        for name in present
        if isinstance(present[name], bool) and present[name] == absent[name]
    ]
    assert frozen == [], f"a bool the probes never vary is never classified: {frozen}"
