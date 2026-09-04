"""The plan/queue drift gate (S8).

Every test here is one of the ways the two documents have actually come apart,
or one of the ways a checker can report agreement it did not measure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import plan_v2, repo_gate

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
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path, "T1: Do it", "T9: Unplanned work"))
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
    measured = plan_v2.measure(_plan(tmp_path), _queue(tmp_path, "T1: Do it", "T1: Do it again"))
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
    """A run that could not measure must not look like a run that measured zero.

    **Every** count, not the three that happened to be written that way. A run
    with no plan to read compared no ticks either, so a `0` beside three `-1`s
    is a clean count over a scan that never happened — the exact shape this
    record exists to refuse, sitting in the record that says `unmeasured` in
    words two keys down. `write_evidence` never commits this dict (the floors
    stop it before the write), but `measure` is public and is what the tests
    read, so the sentinel has to be right in the object and not only in the
    file that is never written.
    """
    measured = plan_v2.measure(tmp_path / "absent.md", _queue(tmp_path, "T1: Do it"))
    assert measured["plan_queue_task_drift"] == -1
    assert measured["rows_without_a_measurable_gate"] == -1
    assert measured["merged_tasks_with_an_unticked_plan_row"] == -1
    assert measured["ticked_rows_without_a_merged_task"] == -1
    assert measured["merged_tick_status"] == "unmeasured"
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


def test_the_row_counts_are_committed_as_a_floor(tmp_path: Path) -> None:
    """T104's family. `plan_rows` and `queue_tasks` are denominators, and
    seeding a task moves both — leaving every open PR's `S8.json` correct for
    its branch and stale for its merge ref. The floor says what they were for
    without moving; the live counts stay in what `main` checks."""
    measured = plan_v2.measure()
    target = tmp_path / "S8.json"
    plan_v2.write_evidence(target)
    committed = json.loads(target.read_text(encoding="utf-8"))

    assert committed["plan_rows_at_least"] == plan_v2.MINIMUM_BOARD_SIZE
    assert committed["queue_tasks_at_least"] == plan_v2.MINIMUM_BOARD_SIZE
    assert "plan_rows" not in committed and "queue_tasks" not in committed
    # The floor is a guard, not a decoration: it has to be under what the
    # repository actually carries, and the live count has to be checked.
    for name in ("plan_rows", "queue_tasks"):
        count = measured[name]
        assert isinstance(count, int) and count >= plan_v2.MINIMUM_BOARD_SIZE


def test_a_plan_dependency_on_finished_work_is_not_drift(tmp_path: Path) -> None:
    """The board carries what a task is still waiting on; the plan's `Depends`
    column carries everything it ever waited on. Migrating to per-task files
    drops the deps that are already satisfied, so reading their absence as
    drift would make every completed prerequisite a permanent violation — 23 of
    them here on the day of the move — and a check that is always red is one
    nobody reads.
    """
    measured = plan_v2.measure(
        _plan(tmp_path, _two_task_plan("T1")),
        _queue(
            tmp_path,
            {"title": "T1: Do it", "status": "merged"},
            {"title": "T2: Do it after", "deps": []},
        ),
    )
    assert measured["dependency_mismatches"] == []
    assert measured["plan_queue_task_drift"] == 0


def test_a_plan_dependency_on_a_blocked_task_is_still_drift(tmp_path: Path) -> None:
    """The exemption above is for finished work only. `blocked` is a failure
    state, not a completion: a task sequenced behind one is still genuinely
    waiting, and dropping that dep would let it be built out of order."""
    measured = plan_v2.measure(
        _plan(tmp_path, _two_task_plan("T1")),
        _queue(
            tmp_path,
            {"title": "T1: Do it", "status": "blocked"},
            {"title": "T2: Do it after", "deps": []},
        ),
    )
    assert measured["dependency_mismatches"] == [
        "T2 depends on T1 in the plan and not in the queue"
    ]


# ---------------------------------------------------------------------------
# D-22 — a gate the docs require must have something that runs it


def _gate_docs(tmp_path: Path, *targets: str) -> Path:
    doc = tmp_path / "CLAUDE.md"
    listed = "\n".join(f"make {t}" for t in targets)
    doc.write_text(
        f"**Run the gate locally.** These are what CI would run, and all five must\n"
        f"pass before a merge:\n\n```bash\n{listed}\n```\n",
        encoding="utf-8",
    )
    return doc


def _gate_makefile(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "Makefile"
    path.write_text(body, encoding="utf-8")
    return path


_FOUR = "lint test evidence verify-gates"
_RULES = "".join(f"{t}:\n\ttrue\n" for t in _FOUR.split())


def test_every_gate_the_docs_require_has_a_runnable_enforcement_point() -> None:
    """D-22's gate. `required_gates_with_no_enforcement_point == 0`.

    Every `make` target `CLAUDE.md` requires before a merge is a real target
    *and* is reached by `make host-gate`, so one command runs the whole gate.
    Prose saying five things must pass is not an enforcement point; a target
    that runs them is.
    """
    measured = repo_gate.measure()

    assert measured["unenforced"] == []
    assert measured["required_gates_with_no_enforcement_point"] == 0
    # Not a vacuous zero: the requirement must still be declared, and the list
    # must actually have been read.
    assert measured["requirement_declared"]
    # Five: the four checks plus `host-gate` itself, which the instructions now
    # name as the one command to run.
    assert measured["gates_required"] == 5
    assert all(r["is_a_target"] and r["reached_by_aggregate"] for r in measured["readings"])
    assert {r["target"] for r in measured["readings"]} >= {
        "lint",
        "test",
        "evidence",
        "verify-gates",
    }


def test_a_task_pr_runs_the_repo_gate_not_only_its_payload_gate() -> None:
    """Hole 2 of D-22, as far as the host can close it.

    A worker re-runs `gate_run.sh` on its own payload and nothing in that path
    runs the repo suite, so a green task PR can break `make test`. The worker
    half is upstream's (`claude-arsenal#175`) — patching the bundle here would
    be reverted by the next `init.py` refresh out of the installed plugin.

    What the host owes is an enforcement point that is *more* than the payload
    gate, under the name upstream's `host-gate` key points at. If `host-gate`
    ever collapsed to what `gate` does — one lint run, recorded — the
    distinction that makes this hole visible would be gone with it.
    """
    rules = repo_gate.make_rules()

    assert repo_gate.AGGREGATE_TARGET in rules, "the host provides no repo-gate entry point"
    assert repo_gate.payload_gate_is_not_the_repo_gate(rules)

    repo = repo_gate.reached_from(repo_gate.AGGREGATE_TARGET, rules)
    payload = repo_gate.reached_from(repo_gate.PAYLOAD_TARGET, rules)
    # The payload gate runs lint and records its exit code. The repo gate runs
    # the suite, the evidence regeneration and the gate verifier on top.
    assert {"test", "evidence", "verify-gates"} <= repo
    assert "test" not in payload


def test_a_required_gate_the_aggregate_forgets_is_counted(tmp_path: Path) -> None:
    """The rot this check exists for: somebody adds a line to the docs and the
    target nobody wired up is the target nobody runs. It exists, it is
    runnable, and `make host-gate` sails past it."""
    doc = _gate_docs(tmp_path, *_FOUR.split(), "audit")
    makefile = _gate_makefile(tmp_path, f"{_RULES}audit:\n\ttrue\nhost-gate: {_FOUR}\n\ttrue\n")

    measured = repo_gate.measure(doc, makefile)

    assert measured["required_gates_with_no_enforcement_point"] == 1
    assert "audit" in measured["unenforced"][0]
    assert "does not reach it" in measured["unenforced"][0]


def test_a_required_gate_that_is_not_a_target_is_counted(tmp_path: Path) -> None:
    """The docs naming a command nothing defines — the same shape as D-20's
    plan row pointing at a file that does not exist."""
    doc = _gate_docs(tmp_path, *_FOUR.split(), "typecheck")
    makefile = _gate_makefile(tmp_path, f"{_RULES}host-gate: {_FOUR} typecheck\n\ttrue\n")

    measured = repo_gate.measure(doc, makefile)

    assert measured["required_gates_with_no_enforcement_point"] == 1
    assert "no such target exists" in measured["unenforced"][0]


def test_the_aggregate_may_be_reached_through_another_target(tmp_path: Path) -> None:
    """`ci` depends on `host-gate` rather than repeating its five, because two
    lists of the same five drift and the one that drifts is the one nobody
    runs. A check that only looked one level down would call that arrangement
    broken and push the repo back to the duplication."""
    doc = _gate_docs(tmp_path, *_FOUR.split())
    makefile = _gate_makefile(
        tmp_path, f"{_RULES}inner: {_FOUR}\n\ttrue\nhost-gate: inner\n\ttrue\n"
    )

    assert repo_gate.measure(doc, makefile)["required_gates_with_no_enforcement_point"] == 0


def test_no_enforcement_point_at_all_records_minus_one(tmp_path: Path) -> None:
    """`-1`, never `0`. Before D-22 the five existed and `ci` listed them, but
    nothing carried the name a worker could be pointed at — and a clean zero
    there would have said the gate was enforced."""
    doc = _gate_docs(tmp_path, *_FOUR.split())
    makefile = _gate_makefile(tmp_path, f"{_RULES}ci: {_FOUR}\n\ttrue\n")

    measured = repo_gate.measure(doc, makefile)

    assert measured["required_gates_with_no_enforcement_point"] == -1
    assert "host-gate" in measured["unenforced"][0]


def test_the_check_stops_measuring_when_the_docs_drop_the_requirement(tmp_path: Path) -> None:
    """If the instructions no longer require the gate before a merge, this is
    enforcing a policy the project has dropped. It records `-1` and says so."""
    doc = tmp_path / "CLAUDE.md"
    doc.write_text("Some prose. ```bash\nmake lint\n```\n", encoding="utf-8")
    makefile = _gate_makefile(tmp_path, f"{_RULES}host-gate: {_FOUR}\n\ttrue\n")

    measured = repo_gate.measure(doc, makefile)

    assert measured["required_gates_with_no_enforcement_point"] == -1
    assert not measured["requirement_declared"]


def test_a_make_command_outside_the_requirement_block_is_not_a_gate(tmp_path: Path) -> None:
    """The instructions show `make` commands for other purposes — regenerating
    a reader, upgrading the subtree. Scanning the whole file would promote each
    of them into a gate required before every merge, and then fail this check
    over a target nobody ever claimed belonged to the gate.
    """
    doc = tmp_path / "CLAUDE.md"
    doc.write_text(
        "## Upgrading\n\n```bash\nmake arsenal-upgrade REF=v0.1.0\n```\n\n"
        "These are what CI would run, and all five must pass before a merge:\n\n"
        f"```bash\n{chr(10).join('make ' + t for t in _FOUR.split())}\n```\n\n"
        "## Afterwards\n\n```bash\nmake reader-steps\n```\n",
        encoding="utf-8",
    )
    makefile = _gate_makefile(tmp_path, f"{_RULES}host-gate: {_FOUR}\n\ttrue\n")

    assert repo_gate.required_gates(doc) == _FOUR.split()
    assert repo_gate.measure(doc, makefile)["required_gates_with_no_enforcement_point"] == 0


def test_a_requirement_with_no_block_after_it_records_minus_one(tmp_path: Path) -> None:
    """The requirement stated and the list gone is not a pass — there is
    nothing to check the Makefile against."""
    doc = tmp_path / "CLAUDE.md"
    doc.write_text("all five must pass before a merge. Trust me.\n", encoding="utf-8")
    makefile = _gate_makefile(tmp_path, f"{_RULES}host-gate: {_FOUR}\n\ttrue\n")

    measured = repo_gate.measure(doc, makefile)

    assert measured["required_gates_with_no_enforcement_point"] == -1
    assert "names no `make` targets" in measured["unenforced"][0]


# --- the floor, enforced ---------------------------------------------------
#
# `main` had no test at all until #297's second-reader audit, and the floor it
# checks exited 3 — which `Makefile`'s evidence loop prints as "unmeasured
# (recorded)" and walks past, while `record` writes `plan_rows_at_least: 100`
# unconditionally. A two-row plan therefore committed a record claiming a
# hundred rows, produced no drift, and passed. Same defect and same repair as
# `task_gate._main`; these are the audit's two board sizes on S8's side.


def _rows(count: int) -> str:
    """A plan table of `count` agreeing rows, T1..T<count>.

    Ticked, and `_run` marks the matching tasks `merged`: agreement now has a
    fourth dimension (D-27), and a control that left every row unticked would
    breach the tick floor rather than demonstrate the pass it is named for.
    """
    body = "".join(
        f"| T{n} | Do it | 0 | S | — | `thing_violations == 0` "
        f"| `test_thing` in `tests/t.py` | ☑ |\n"
        for n in range(1, count + 1)
    )
    return f"## Implementation tasks\n\n{HEADER}\n{DIVIDER}\n{body}"


def _measuring(monkeypatch: pytest.MonkeyPatch, plan: Path, queue: Path) -> None:
    """Point `main` at `plan` and `queue`. The measuring itself stays real."""
    real_measure = plan_v2.measure

    def bound(_plan: Path = plan, _queue: Path = queue) -> dict[str, object]:
        return real_measure(plan, queue)

    monkeypatch.setattr(plan_v2, "measure", bound)


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: int) -> tuple[int, Path]:
    plan = _plan(tmp_path, _rows(rows))
    merged: list[dict[str, object]] = [
        {"title": f"T{n}: Do it", "status": "merged"} for n in range(1, rows + 1)
    ]
    queue = _queue(tmp_path, *merged)
    _measuring(monkeypatch, plan, queue)
    target = tmp_path / "S8.json"
    return plan_v2.main([str(target)]), target


def test_an_agreeing_plan_above_the_floor_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control: the two failures below are the floor, not the harness."""
    exit_code, target = _run(monkeypatch, tmp_path, 105)

    assert exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["plan_queue_task_drift"] == 0


def test_a_sub_floor_plan_fails_instead_of_recording_a_floor_it_never_met(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit case 1, on S8: five rows against a floor of a hundred."""
    exit_code, target = _run(monkeypatch, tmp_path, 5)

    assert exit_code == 1
    assert "only 5 plan_rows (floor 100)" in capsys.readouterr().err
    # And it wrote nothing. `record` emits `plan_rows_at_least: 100`
    # unconditionally, so the only artefact this run could produce is one
    # asserting the floor it just failed.
    assert not target.exists()


def test_a_near_floor_plan_fails_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit case 2, on S8: ninety-two rows. [1, 99] was silent for every value."""
    exit_code, target = _run(monkeypatch, tmp_path, 92)

    assert exit_code == 1
    assert "only 92 plan_rows (floor 100)" in capsys.readouterr().err
    assert not target.exists()


def test_a_sub_floor_run_leaves_an_existing_record_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering, where it costs something: the exit code is not the only
    output of a failing run.

    `write_evidence` wrote before `main` checked, so a five-row plan
    overwrote the committed S8 record with one claiming a hundred rows — and
    that overwritten file is what the *next* run over a healthy tree diffs
    against in `make evidence`. Byte-identical, not merely still valid.
    """
    healthy = tmp_path / "S8.json"
    healthy.write_text('{"kept": true}\n', encoding="utf-8")
    before = healthy.read_bytes()

    exit_code, _ = _run(monkeypatch, tmp_path, 5)

    assert exit_code == 1
    assert healthy.read_bytes() == before


# --- the tick: the archive against the plan's `St` box (D-27) --------------
#
# A task merges, its file moves into `arsenal/tasks/_history/` with
# `status: merged`, and nothing ever ticks the plan row. 47 of 123 had drifted
# when this was filed, so the board was reporting 44% of its finished work as
# unfinished with every gate green. The cases below are the four shapes that
# drift takes and the two ways a checker can report agreement it never made.


def _tick_row(label: str, status_cell: str) -> str:
    return (
        f"| {label} | Do it | 0 | S | — | `thing_violations == 0` "
        f"| `test_thing` in `tests/t.py` | {status_cell} |"
    )


def _tick_plan(tmp_path: Path, *rows: str) -> Path:
    body = "".join(row + "\n" for row in rows)
    return _plan(tmp_path, f"## Implementation tasks\n\n{HEADER}\n{DIVIDER}\n{body}")


def test_an_archived_merged_task_with_an_unticked_row_is_reported(tmp_path: Path) -> None:
    """The defect exactly: merged in the archive, `☐` in the plan."""
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☐")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 1
    assert measured["merged_tick_status"] == "measured"
    assert measured["unticked_merged_rows"] == [
        "T1 is archived as merged and its plan row reads `☐`, not `☑`"
    ]
    assert _violations(measured) == measured["unticked_merged_rows"]


def test_a_ticked_row_whose_task_is_still_live_is_the_same_fault(tmp_path: Path) -> None:
    """The converse, and not hypothetical: T15's row carried a tick for weeks
    while its task file sat `open` in `arsenal/tasks/`.

    A plan that claims a completion the archive does not have misreports in the
    direction that matters more — a reader trusts the tick and stops looking.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑"), _tick_row("T2", "☑")),
        _queue(
            tmp_path,
            {"title": "T1: Do it", "status": "merged"},
            {"title": "T2: Still going", "status": "open"},
        ),
    )

    assert measured["ticked_rows_without_a_merged_task"] == 1
    assert measured["wrongly_ticked_rows"] == [
        "T2 has a ticked plan row and is still `open` on the board"
    ]
    # And the merged direction is clean, so the two counts are independent
    # rather than one number reported twice.
    assert measured["merged_tasks_with_an_unticked_plan_row"] == 0


def test_a_merged_task_whose_row_is_ticked_is_no_drift(tmp_path: Path) -> None:
    """The control. Without it the two above pass on a checker that always
    reports one."""
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 0
    assert measured["ticked_rows_without_a_merged_task"] == 0
    assert measured["merged_tasks_compared"] == 1


def test_a_merged_task_with_no_plan_row_at_all_is_not_compliant(tmp_path: Path) -> None:
    """Absent is not ticked.

    The fail-open reading of a checkbox is "there is no box, so nothing is
    unticked" — which would make the metric satisfiable by *deleting* the row
    that embarrasses it rather than ticking it. `plan_queue_task_drift` reports
    the same task from the membership side; both must, because either check
    could be relaxed on its own.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑")),
        _queue(
            tmp_path,
            {"title": "T1: Do it", "status": "merged"},
            {"title": "T9: Merged and unplanned", "status": "merged"},
        ),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 1
    assert measured["unticked_merged_rows"] == [
        "T9 is archived as merged and has no row in the plan"
    ]
    assert "T9 is in the queue and has no row in the plan" in _violations(measured)


def test_an_in_progress_glyph_is_not_a_tick(tmp_path: Path) -> None:
    """`◐` means in progress in the plan's own legend, and three of the eight
    rows this landed with had drifted to it rather than to `☐`. Reading it as
    close enough is how they stayed invisible."""
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "◐")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 1


def test_a_cancelled_task_is_not_required_to_carry_a_tick(tmp_path: Path) -> None:
    """`☒` is cancelled — absorbed or abandoned, never done. Demanding a tick
    for it would make two real rows permanently red and train a reader to
    ignore the count."""
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑"), _tick_row("T2", "☒")),
        _queue(
            tmp_path,
            {"title": "T1: Do it", "status": "merged"},
            {"title": "T2: Absorbed elsewhere", "status": "cancelled"},
        ),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 0
    assert measured["ticked_rows_without_a_merged_task"] == 0


def test_the_status_column_is_found_by_header_not_by_index(tmp_path: Path) -> None:
    """A plan that gains a column somewhere must still be measured correctly.
    A fixed index reads the neighbouring cell and reports every row as
    unticked — the loudest possible way to be wrong about the quietest cause."""
    header = "| T# | Note | Description | Step | Size | Depends | Gate | Tests | St |"
    divider = "|----|------|-------------|------|------|---------|------|-------|----|"
    row = (
        "| T1 | n/a | Do it | 0 | S | — | `thing_violations == 0` "
        "| `test_thing` in `tests/t.py` | ☑ |"
    )
    plan = _plan(tmp_path, f"## Implementation tasks\n\n{header}\n{divider}\n{row}\n")

    measured = plan_v2.measure(plan, _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}))

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 0


def test_no_merged_task_reports_unmeasured_rather_than_a_clean_zero(tmp_path: Path) -> None:
    """The vacuous pass this repository keeps catching: zero unticked rows over
    an archive nobody read.

    Point the scan at a board with nothing merged and the metric must not read
    `0`. It reads `-1`, the sentinel `_unmeasurable` already uses, and the
    record says `unmeasured` in words beside it so a reader is not left to
    infer the difference from a negative number.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☐")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "open"}),
    )

    assert measured["merged_tasks_compared"] == 0
    assert measured["merged_tick_status"] == "unmeasured"
    assert measured["merged_tasks_with_an_unticked_plan_row"] == -1
    assert plan_v2.record(measured)["merged_tick_status"] == "unmeasured"


def test_an_empty_archive_breaches_the_tick_floor(tmp_path: Path) -> None:
    """And the floor is what makes `unmeasured` cost something.

    `main` exits 1 on a breach and `write_evidence` writes nothing, so a run
    that compared no archive cannot leave behind a record claiming it did.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☐")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "open"}),
    )

    assert any("merged_tasks_compared (floor 100)" in b for b in plan_v2.floor_breaches(measured))


def test_the_tick_denominator_is_committed_as_a_floor_not_a_count(tmp_path: Path) -> None:
    """T100's lesson, applied to the third denominator.

    Archiving the task file is exactly what a task PR does, so an exact
    `merged_tasks_compared` would be wrong on one side of every archive and
    `make evidence` would go red on a change that is not a finding.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )
    committed = plan_v2.record(measured)

    assert "merged_tasks_compared" not in committed
    assert committed["merged_tasks_compared_at_least"] == plan_v2.MINIMUM_MERGED_TASKS
    assert committed["merged_tasks_with_an_unticked_plan_row"] == 0


def test_the_tick_check_reads_the_archive_and_never_the_plans_own_ticks(
    tmp_path: Path,
) -> None:
    """The direction is the whole point.

    One plan, two boards. The ticks are identical; the verdicts are opposite —
    so the answer is derived from `status: merged` in the archive, and a check
    that could be satisfied by editing the document it checks would return the
    same number twice.

    **Both** metrics, because the gate key is
    `merged_tasks_with_an_unticked_plan_row` and that is the number the claim
    is made about — the converse is its sibling. Asserting only the
    converse leaves the gate key itself resting on a property demonstrated for
    its sibling — a citation one key wide of what it cites, which is how a
    stated invariant ends up with nothing measuring it.

    Three rows, held against two archives:

    | label | row | archive A | archive B |
    |-------|-----|-----------|-----------|
    | T1    | ☑   | merged    | merged    |
    | T2    | ☐   | merged    | open      |
    | T3    | ☑   | merged    | open      |

    T2 is the gate's case — unticked, and only A archives it as merged. T3 is
    the converse's — ticked, and only B leaves it open. Nothing about the plan
    changes between the two runs.
    """
    plan = _tick_plan(tmp_path, _tick_row("T1", "☑"), _tick_row("T2", "☐"), _tick_row("T3", "☑"))
    merged = plan_v2.measure(
        plan,
        _queue(
            tmp_path,
            {"title": "T1: Done and ticked", "status": "merged"},
            {"title": "T2: Done and unticked", "status": "merged"},
            {"title": "T3: Also done", "status": "merged"},
        ),
    )
    live = plan_v2.measure(
        tmp_path / "plan.md",
        _queue(
            tmp_path,
            {"title": "T1: Done and ticked", "status": "merged"},
            {"title": "T2: Done and unticked", "status": "open"},
            {"title": "T3: Also done", "status": "open"},
        ),
    )

    # The gate metric: same unticked T2 row, opposite verdicts.
    assert merged["merged_tasks_with_an_unticked_plan_row"] == 1
    assert merged["unticked_merged_rows"] == [
        "T2 is archived as merged and its plan row reads `☐`, not `☑`"
    ]
    assert live["merged_tasks_with_an_unticked_plan_row"] == 0

    # And the converse: same ticked T3 row, opposite verdicts.
    assert merged["ticked_rows_without_a_merged_task"] == 0
    assert live["ticked_rows_without_a_merged_task"] == 1
    assert live["wrongly_ticked_rows"] == [
        "T3 has a ticked plan row and is still `open` on the board"
    ]

    # Both runs measured — neither verdict is the `unmeasured` sentinel wearing
    # a number, which is the way this pair of assertions could pass vacuously.
    assert merged["merged_tick_status"] == "measured"
    assert live["merged_tick_status"] == "measured"


# --- the tick, second reading (findings on #329) ---------------------------
#
# Four cases an independent read of the check turned up, each committed here
# rather than answered in a comment: a report that is read and waved through
# leaves the code exactly as unprotected as it was.


def test_an_archived_done_task_is_outside_this_checks_scope(tmp_path: Path) -> None:
    """The hole this check has, pinned so it is a choice and not a surprise.

    D-27's Scope says "every task with a file in `arsenal/tasks/_history/`
    carrying `status: merged`", so `done` is out of the numerator by the letter
    of the task. The consequence is a way to zero the metric without ticking
    anything: change one word in the front matter of the file being archived,
    in the very commit that archives it, and an unticked row goes green — the
    denominator drops by one and the floor of 100 absorbs it.

    Two reasons it is pinned here rather than closed. First, `_TERMINAL` (the
    wider set this module already uses for dependency satisfaction) would close
    it, but the plan's own legend has **no glyph for `done`** —
    ☑ merged · ◐ in progress · ☐ open · ☒ cancelled — so every archived-`done`
    task would have to be ticked as *merged* or the legend extended, and that
    is a decision about the document, not about the checker. Second, T29
    (`arsenal/tasks/_history/lo-2293.md`) is `status: done`, archived, and its
    plan row reads `◐`: the plan asserts a finished task is in progress, and
    widening the numerator today would make it red with no honest glyph to fix
    it with.

    So this test asserts what the narrower reading **does**, and it is written
    to fail the moment someone widens the scope — at which point the failure
    is the reminder to settle the legend, which is exactly what it is for.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑"), _tick_row("T2", "☐")),
        _queue(
            tmp_path,
            {"title": "T1: Merged", "status": "merged"},
            {"title": "T2: Archived as done, row unticked", "status": "done"},
        ),
    )

    # Out of the numerator...
    assert measured["merged_tasks_with_an_unticked_plan_row"] == 0
    assert measured["unticked_merged_rows"] == []
    # ...and out of the denominator, which is what makes it silent: the floor
    # is the only thing watching that number and it is 100 wide.
    assert measured["merged_tasks_compared"] == 1
    # Nothing else fires either. `plan_queue_task_drift` sees a task with a row
    # and a row with a task, so membership is satisfied.
    assert measured["plan_queue_task_drift"] == 0
    assert _violations(measured) == []


def test_a_ticked_row_over_an_archived_done_task_is_not_reported_either(
    tmp_path: Path,
) -> None:
    """The converse of the same scope, pinned for the same reason.

    `ticked_rows_without_a_merged_task` reads `status != "merged"`, so an
    archived-`done` task with a **ticked** row *is* a violation today — the
    stricter direction of the same asymmetry, and the one that would have to
    be relaxed rather than tightened if `done` were ever admitted. Recorded so
    that widening the numerator without touching the converse is caught as the
    inconsistency it would be, instead of quietly leaving one status strict in
    one direction and lax in the other.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑"), _tick_row("T2", "☑")),
        _queue(
            tmp_path,
            {"title": "T1: Merged", "status": "merged"},
            {"title": "T2: Archived as done, row ticked", "status": "done"},
        ),
    )

    assert measured["ticked_rows_without_a_merged_task"] == 1
    assert measured["wrongly_ticked_rows"] == [
        "T2 has a ticked plan row and is still `done` on the board"
    ]


def test_a_duplicate_ticked_row_does_not_mask_an_unticked_one(tmp_path: Path) -> None:
    """Appending a compliant row must not answer for the row beside it.

    `by_label` is last-wins, so a checker reading the collapsed mapping sees
    only whichever row is written last: leave the unticked row in place, append
    a second ticked one, and the gate key reads 0. That is the same fail-open
    shape as *deleting* the row — the metric satisfied by editing the plan
    rather than by doing the work — and this module's own docstring already
    refuses it for label counting ("collapsing them into a set hides a
    duplicated row instead of reporting it").

    `plan_queue_task_drift` does catch the duplicate, and that is not enough on
    its own. It is a **different gate key**, and D-27's argument for counting a
    missing row here as well as there applies unchanged: either check could be
    relaxed on its own, and a gate key that leans on a neighbouring key reads
    green the day the neighbour moves.

    Both counts are asserted below so that a future change moving the finding
    from one key to the other cannot pass.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☐"), _tick_row("T1", "☑")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 1
    assert measured["unticked_merged_rows"] == [
        "T1 is archived as merged and its plan row reads `☐`, not `☑`"
    ]
    # The duplicate is still the membership check's finding as well.
    assert measured["duplicate_labels"] == ["T1 appears 2 times in the plan"]
    assert measured["plan_queue_task_drift"] == 1


def test_the_row_order_of_a_duplicate_does_not_change_the_verdict(tmp_path: Path) -> None:
    """The ticked row first, the unticked one second — same answer.

    Without this, the case above passes on a checker that merely reads the
    *first* row rather than the last: one off-by-one collapse swapped for
    another, with the same hole opened by writing the rows the other way round.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☑"), _tick_row("T1", "☐")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 1


def test_every_duplicated_unticked_row_is_counted(tmp_path: Path) -> None:
    """Counted with multiplicity, like every other label count in this module.

    Two unticked rows for one merged task are two findings, not one: the count
    is a count of rows that misreport, and collapsing them would report the
    second as answered by the presence of the first.
    """
    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☐"), _tick_row("T1", "◐")),
        _queue(tmp_path, {"title": "T1: Do it", "status": "merged"}),
    )

    assert measured["merged_tasks_with_an_unticked_plan_row"] == 2
    assert measured["unticked_merged_rows"] == [
        "T1 is archived as merged and its plan row reads `☐`, not `☑`",
        "T1 is archived as merged and its plan row reads `◐`, not `☑`",
    ]


def test_a_missing_status_column_and_a_blank_cell_are_the_same_verdict(
    tmp_path: Path,
) -> None:
    """`PlanRow.status_cell` does not tell the two apart, and must not claim to.

    A table with no `St` column and a table whose `St` cell is blank both parse
    to `""`. `""` is not `☑`, so a merged task is reported either way — the
    fail-closed direction, and loud: a plan that loses the column reports every
    merged row rather than none. The docstring on `PlanRow` used to assert the
    two were distinguishable, which was a claim about a fail-open boundary and
    was false; this holds the code to the corrected sentence.
    """
    no_column_header = "| T# | Description | Step | Size | Depends | Gate | Tests |"
    no_column_divider = "|----|-------------|------|------|---------|------|-------|"
    no_column_row = (
        "| T1 | Do it | 0 | S | — | `thing_violations == 0` | `test_thing` in `tests/t.py` |"
    )
    body = f"## Implementation tasks\n\n{no_column_header}\n{no_column_divider}\n{no_column_row}\n"
    absent = tmp_path / "no-column.md"
    absent.write_text(body, encoding="utf-8")
    queue = _queue(tmp_path, {"title": "T1: Do it", "status": "merged"})
    without_column = plan_v2.measure(absent, queue)

    blank = _tick_plan(tmp_path, _tick_row("T1", ""))
    with_blank_cell = plan_v2.measure(blank, queue)

    assert plan_v2.plan_rows(absent)[0].status_cell == ""
    assert plan_v2.plan_rows(blank)[0].status_cell == ""
    assert (
        without_column["unticked_merged_rows"]
        == with_blank_cell["unticked_merged_rows"]
        == ["T1 is archived as merged and its plan row reads ` `, not `☑`"]
    )
    assert without_column["merged_tasks_with_an_unticked_plan_row"] == 1
    assert with_blank_cell["merged_tasks_with_an_unticked_plan_row"] == 1


def test_the_tick_check_reads_a_real_history_directory_on_disk(tmp_path: Path) -> None:
    """The join the shipped gate actually runs, which no test here exercised.

    Every other tick test writes the board as a JSONL ledger, where `status` is
    a field the test sets by hand. The real board is a **directory**, and "the
    archive decides" is implemented one layer down, in `taskboard.load_board`:
    `arsenal/tasks/` is read with `default_status="open"` and
    `arsenal/tasks/_history/` with `default_status="merged"`, so a file's
    *location* is what makes it merged. `load_board` had no callers in `tests/`
    at all, so every ledger test above could pass with that mapping reversed.

    Two files, identical but for the directory they sit in, and identical
    unticked rows. Only the archived one is required to carry a tick.
    """
    tasks = tmp_path / "tasks"
    history = tasks / "_history"
    history.mkdir(parents=True)
    (tasks / "t-live.md").write_text(
        '---\nid: t-live\ntitle: "T2: Still going"\n---\n\nbody\n', encoding="utf-8"
    )
    # No `status:` line: the directory is what says `merged`, which is the
    # property under test. A file declaring its own status would prove nothing
    # about where the answer came from.
    (history / "t-archived.md").write_text(
        '---\nid: t-archived\ntitle: "T1: Finished"\n---\n\nbody\n', encoding="utf-8"
    )

    measured = plan_v2.measure(
        _tick_plan(tmp_path, _tick_row("T1", "☐"), _tick_row("T2", "☐")), tasks
    )

    assert measured["merged_tasks_compared"] == 1
    assert measured["merged_tick_status"] == "measured"
    assert measured["unticked_merged_rows"] == [
        "T1 is archived as merged and its plan row reads `☐`, not `☑`"
    ]
    # The live task's unticked row is not a finding, and nothing is wrongly
    # ticked, so neither direction fires on it.
    assert measured["ticked_rows_without_a_merged_task"] == 0


def test_moving_a_task_file_into_the_archive_is_what_turns_its_row_red(
    tmp_path: Path,
) -> None:
    """The same directory board, with one file moved and nothing else changed.

    This is the sentence `CLAUDE.md` now makes to every future task PR —
    "ticking the row is part of archiving the task" — asserted rather than
    described. Without it the test above is satisfiable by a `load_board` that
    reports everything it finds as merged.
    """
    tasks = tmp_path / "tasks"
    history = tasks / "_history"
    history.mkdir(parents=True)
    live = tasks / "t-one.md"
    live.write_text('---\nid: t-one\ntitle: "T1: Do it"\n---\n\nbody\n', encoding="utf-8")
    plan = _tick_plan(tmp_path, _tick_row("T1", "☐"))

    before = plan_v2.measure(plan, tasks)
    live.rename(history / "t-one.md")
    after = plan_v2.measure(plan, tasks)

    assert before["merged_tasks_compared"] == 0
    assert before["merged_tick_status"] == "unmeasured"
    assert after["merged_tasks_compared"] == 1
    assert after["merged_tasks_with_an_unticked_plan_row"] == 1
