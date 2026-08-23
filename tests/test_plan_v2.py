"""The plan/queue drift gate (S8).

Every test here is one of the ways the two documents have actually come apart,
or one of the ways a checker can report agreement it did not measure.
"""

from __future__ import annotations

import json
from pathlib import Path

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
