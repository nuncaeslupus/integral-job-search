"""D-29 — the merge-order table against the archive.

Each test is a way the milestone rows have actually drifted from the board, or a
way the checker could report a clean zero over a scan that measured nothing.
Merged state is always set on the *board* here and never inferred from a tick,
because the one thing this gate must not do is read the document it checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import plan_milestones, plan_v2

TABLE_HEADER = "| milestone | delivers | tasks |\n|-----------|----------|-------|\n"


def _plan(tmp_path: Path, *rows: str, ticks: str = "") -> Path:
    """A plan with a merge-order table; `ticks` is an optional task table whose
    `St` cells must never influence the verdict."""
    body = TABLE_HEADER + "".join(f"| **{m}** | d | {t} |\n" for m, t in enumerate_rows(rows))
    plan = tmp_path / "plan.md"
    plan.write_text(f"# plan\n\n{body}\n{ticks}", encoding="utf-8")
    return plan


def enumerate_rows(rows: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(f"M{n}", row) for n, row in enumerate(rows, start=1)]


def _queue(tmp_path: Path, **statuses: str) -> Path:
    """A board: keyword `T1="merged"` is a task titled `T1: x` in that status."""
    queue = tmp_path / "tasks.jsonl"
    lines = [
        json.dumps({"id": f"lo-{n:04d}", "title": f"{label}: x", "status": status})
        for n, (label, status) in enumerate(statuses.items())
    ]
    queue.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return queue


@pytest.fixture
def small_floors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_milestones, "MINIMUM_MERGED_RESOLVED", 1)
    monkeypatch.setattr(plan_milestones, "MINIMUM_ROW_LABELS", 1)


def _violations(measured: dict[str, object]) -> list[str]:
    found = measured["violations"]
    assert isinstance(found, list)
    return found


# --- the two directions ----------------------------------------------------


@pytest.mark.usefixtures("small_floors")
def test_a_plan_that_lists_each_open_task_once_and_no_merged_one_is_clean(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open", T3="open")
    measured = plan_milestones.measure(_plan(tmp_path, "T2", "T3"), queue)
    assert measured["milestone_row_membership_violations"] == 0
    assert measured["gate_status"] == "measured"


@pytest.mark.usefixtures("small_floors")
def test_a_merged_task_still_listed_is_a_violation(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    measured = plan_milestones.measure(_plan(tmp_path, "T1, T2"), queue)
    assert measured["milestone_row_membership_violations"] == 1
    assert measured["merged_still_listed"] == ["T1"]


@pytest.mark.usefixtures("small_floors")
def test_an_open_task_in_no_row_is_a_violation(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open", T3="open")
    measured = plan_milestones.measure(_plan(tmp_path, "T2"), queue)
    assert measured["milestone_row_membership_violations"] == 1
    assert measured["open_but_unlisted"] == ["T3"]


@pytest.mark.usefixtures("small_floors")
def test_the_two_directions_are_summed_not_either_or(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open", T3="open")
    measured = plan_milestones.measure(_plan(tmp_path, "T1, T2"), queue)
    assert measured["milestone_row_membership_violations"] == 2


@pytest.mark.usefixtures("small_floors")
def test_an_open_task_in_two_rows_or_twice_in_one_is_counted(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open", T3="open")
    across = plan_milestones.measure(_plan(tmp_path, "T2, T3", "T2"), queue)
    within = plan_milestones.measure(_plan(tmp_path, "T2, T2, T3"), queue)
    assert across["open_but_listed_more_than_once"] == ["T2"]
    assert within["open_but_listed_more_than_once"] == ["T2"]
    assert across["milestone_row_membership_violations"] == 1
    assert within["milestone_row_membership_violations"] == 1


@pytest.mark.usefixtures("small_floors")
def test_a_label_no_task_carries_and_a_non_label_token_are_violations(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    measured = plan_milestones.measure(_plan(tmp_path, "T2, T99, soon"), queue)
    assert measured["listed_without_a_task"] == ["T99"]
    assert any("`soon` is not a task label" in v for v in _violations(measured))
    assert measured["milestone_row_membership_violations"] == 2


@pytest.mark.usefixtures("small_floors")
def test_a_cancelled_task_is_neither_required_nor_forbidden(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open", T3="cancelled")
    unlisted = plan_milestones.measure(_plan(tmp_path, "T2"), queue)
    listed = plan_milestones.measure(_plan(tmp_path, "T2, T3"), queue)
    assert unlisted["milestone_row_membership_violations"] == 0
    assert listed["milestone_row_membership_violations"] == 0


# --- merged state is the archive's, never the plan's -----------------------

TICKED_TASKS = (
    "| T# | Description | Step | Size | Depends | Gate | Tests | St |\n"
    "|----|-------------|------|------|---------|------|-------|----|\n"
    "| T1 | a | 0 | S | — | `a == 0` | t | ☐ |\n"
    "| T2 | b | 0 | S | — | `b == 0` | t | ☑ |\n"
)


@pytest.mark.usefixtures("small_floors")
def test_the_plans_own_ticks_do_not_decide_what_is_merged(tmp_path: Path) -> None:
    # T1 is merged on the board and UNTICKED in the plan; T2 is open and TICKED.
    # Reading ticks would call T2 merged (listing it a violation) and T1 open
    # (so its listing correct). The archive says the opposite on both counts.
    queue = _queue(tmp_path, T1="merged", T2="open")
    clean = plan_milestones.measure(_plan(tmp_path, "T2", ticks=TICKED_TASKS), queue)
    dirty = plan_milestones.measure(_plan(tmp_path, "T1, T2", ticks=TICKED_TASKS), queue)
    assert clean["milestone_row_membership_violations"] == 0
    assert dirty["merged_still_listed"] == ["T1"]


def test_both_modules_resolve_the_same_merged_set(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="merged", T3="done", T4="open")
    tasks, _ = plan_v2.queue_tasks(queue)
    labelled = {str(plan_v2.task_label(r)): r for r in tasks}
    assert set(plan_v2.merged_tasks(labelled)) == {"T1", "T2"}
    plan = _plan(tmp_path, "T3, T4")
    assert plan_milestones.measure(plan, queue)["merged_tasks_resolved"] == 2
    assert plan_v2.measure(plan, queue)["merged_tasks_compared"] == 2


@pytest.mark.usefixtures("small_floors")
def test_the_milestone_module_follows_the_shared_merged_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    monkeypatch.setattr(plan_milestones, "merged_tasks", lambda labelled: {})
    measured = plan_milestones.measure(_plan(tmp_path, "T2"), queue)
    assert measured["merged_tasks_resolved"] == 0  # it asked the shared function


# --- unmeasured is not zero ------------------------------------------------


@pytest.mark.usefixtures("small_floors")
def test_an_archive_with_nothing_merged_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="open", T2="open")
    measured = plan_milestones.measure(_plan(tmp_path, "T1, T2"), queue)
    assert measured["milestone_row_membership_violations"] == -1
    assert measured["gate_status"] == "unmeasured"


@pytest.mark.usefixtures("small_floors")
def test_a_table_that_yields_no_label_is_unmeasured(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    plan = tmp_path / "plan.md"
    plan.write_text("# a plan with no merge-order table\n", encoding="utf-8")
    measured = plan_milestones.measure(plan, queue)
    assert measured["milestone_row_membership_violations"] == -1
    assert measured["gate_status"] == "unmeasured"


def test_a_missing_plan_or_queue_is_unmeasured(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged")
    for measured in (
        plan_milestones.measure(tmp_path / "nope.md", queue),
        plan_milestones.measure(_plan(tmp_path, "T1"), tmp_path / "nope"),
    ):
        assert measured["milestone_row_membership_violations"] == -1
        assert measured["gate_status"] == "unmeasured"


# --- the floors, the exit code and the record ------------------------------


def test_the_floors_are_literals_below_the_live_population() -> None:
    assert plan_milestones.MINIMUM_MERGED_RESOLVED == 100
    assert plan_milestones.MINIMUM_ROW_LABELS == 20


def test_a_thin_scan_breaches_each_floor(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    thin = plan_milestones.measure(_plan(tmp_path, "T2"), queue)
    breaches = plan_milestones.floor_breaches(thin)
    assert len(breaches) == 2
    assert any("merged_tasks_resolved" in b for b in breaches)
    assert any("milestone_labels_scanned" in b for b in breaches)


def test_a_floor_breach_writes_no_record_at_all(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    plan = _plan(tmp_path, "T2")
    evidence = tmp_path / "D-29.json"
    measured = plan_milestones.write_evidence(evidence, plan, queue)
    assert plan_milestones.floor_breaches(measured)
    assert not evidence.exists()


def test_a_breaching_run_leaves_an_existing_record_untouched(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    evidence = tmp_path / "D-29.json"
    evidence.write_text("sentinel", encoding="utf-8")
    plan_milestones.write_evidence(evidence, _plan(tmp_path, "T2"), queue)
    assert evidence.read_text(encoding="utf-8") == "sentinel"


def test_main_returns_1_on_a_floor_breach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    plan = _plan(tmp_path, "T2")
    monkeypatch.setattr(plan_milestones, "DEFAULT_PLAN", plan)
    monkeypatch.setattr(plan_milestones, "DEFAULT_QUEUE", queue)
    monkeypatch.setattr(
        plan_milestones,
        "write_evidence",
        lambda evidence: plan_milestones.measure(plan, queue),
    )
    assert plan_milestones._main([str(tmp_path / "D-29.json")]) == 1
    assert "floor" in capsys.readouterr().err


@pytest.mark.usefixtures("small_floors")
def test_main_returns_1_on_a_violation_and_0_on_a_clean_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    monkeypatch.setattr(plan_milestones, "DEFAULT_QUEUE", queue)
    real = plan_milestones.write_evidence

    def run(plan: Path) -> int:
        monkeypatch.setattr(plan_milestones, "DEFAULT_PLAN", plan)
        monkeypatch.setattr(
            plan_milestones, "write_evidence", lambda evidence: real(evidence, plan, queue)
        )
        return plan_milestones._main([str(tmp_path / "D-29.json")])

    assert run(_plan(tmp_path, "T1, T2")) == 1
    assert run(_plan(tmp_path, "T2")) == 0


@pytest.mark.usefixtures("small_floors")
def test_the_record_carries_the_floors_never_the_counts(tmp_path: Path) -> None:
    queue = _queue(tmp_path, T1="merged", T2="open")
    committed = plan_milestones.record(plan_milestones.measure(_plan(tmp_path, "T2"), queue))
    for count in ("merged_tasks_resolved", "milestone_labels_scanned", "open_tasks_evaluated"):
        assert count not in committed
    assert committed["merged_tasks_resolved_at_least"] == plan_milestones.MINIMUM_MERGED_RESOLVED
    assert committed["milestone_labels_scanned_at_least"] == plan_milestones.MINIMUM_ROW_LABELS


# --- the live plan ---------------------------------------------------------
# These two read the repository's own tree, which is archive-sensitive by design:
# the task that ships this file is open before `open_task_pr.sh` archives it and
# merged after, and the plan is correct only for the second. So the task's own
# gate deselects them (`-k "not live"`, it runs pre-archive) and `make test` runs
# them post-archive.


def test_the_live_plan_has_no_membership_violations_over_a_real_scan() -> None:
    measured = plan_milestones.measure()
    assert _violations(measured) == []
    assert measured["milestone_row_membership_violations"] == 0
    assert plan_milestones.floor_breaches(measured) == []
    assert measured["gate_status"] == "measured"


def test_the_committed_record_matches_a_fresh_live_measurement() -> None:
    committed = json.loads(plan_milestones.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == plan_milestones.record(plan_milestones.measure())
