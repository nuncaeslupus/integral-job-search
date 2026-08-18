"""The product-shape decision register (T29).

Each test is one of the ways this gate could report agreement it never
measured — a step whose checkpoint is blank, a `not_implemented` step counted as
delivered, a register that was deleted rather than answered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jobsearch import product_shape

REGISTER = """# Shape

## What needed deciding

1. **First question?**
   **Decided: this way.** Because of a reason.

2. **Second question?**
   **Blocked: nobody has settled it.** Named, and therefore recorded.
"""


def _step(n: int, **gate: Any) -> dict[str, Any]:
    block = {"metric": f"metric_{n}", "op": "==", "threshold": 0, "state": "implemented"}
    block.update(gate)
    return {"n": n, "id": f"step_{n}", "gate": block}


def _steps(tmp_path: Path, *steps: dict[str, Any]) -> Path:
    path = tmp_path / "steps.json"
    path.write_text(json.dumps({"step_count": len(steps), "steps": list(steps)}), encoding="utf-8")
    return path


def _shape(tmp_path: Path, text: str = REGISTER) -> Path:
    path = tmp_path / "product-shape.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_every_open_shape_question_has_a_recorded_answer() -> None:
    """The shipped documents: every question decided or explicitly blocked."""
    measured = product_shape.measure()

    assert measured["unanswered_questions"] == []
    assert measured["open_shape_questions_unanswered"] == 0
    assert measured["shape_questions"], "the register must carry questions to answer"


def test_every_step_has_a_checkpoint() -> None:
    """The shipped step list: no step without a metric, operator and state."""
    measured = product_shape.measure()

    assert measured["steps_without_a_checkpoint"] == []
    assert measured["phase_checkpoints_defined"] == 1
    assert measured["steps_measured"] == 13


def test_a_step_missing_from_the_checkpoint_table_is_caught(tmp_path: Path) -> None:
    """A blank metric is the forgotten checkpoint this gate exists to find."""
    measured = product_shape.measure(
        _steps(tmp_path, _step(0), _step(1, metric="")), _shape(tmp_path)
    )

    assert measured["phase_checkpoints_defined"] == 0
    assert [entry["step"] for entry in measured["steps_without_a_checkpoint"]] == ["step_1"]


def test_an_unimplemented_step_does_not_pass(tmp_path: Path) -> None:
    """`not_implemented` is a defined checkpoint and an undelivered step."""
    measured = product_shape.measure(
        _steps(tmp_path, _step(0), _step(1, state="not_implemented")), _shape(tmp_path)
    )

    assert measured["phase_checkpoints_defined"] == 1  # defined …
    assert measured["steps_not_implemented"] == ["step_1"]  # … and not delivered
    assert measured["steps_implemented"] == ["step_0"]


def test_an_invented_state_is_not_a_checkpoint(tmp_path: Path) -> None:
    """Only the two recorded states resolve; anything else is undeclared."""
    measured = product_shape.measure(
        _steps(tmp_path, _step(0, state="probably fine")), _shape(tmp_path)
    )

    assert measured["phase_checkpoints_defined"] == 0
    assert measured["steps_not_implemented"] == []


def test_a_question_without_a_marker_is_counted(tmp_path: Path) -> None:
    """An answer given in conversation and not written down is not an answer."""
    register = "## What needed deciding\n\n1. **Only question?**\n   We talked about it.\n"
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["open_shape_questions_unanswered"] == 1
    assert measured["unanswered_questions"] == ["Only question?"]
    assert measured["phase_checkpoints_defined"] == 0


def test_blocked_is_a_recorded_answer(tmp_path: Path) -> None:
    """A named blocker resolves a question; only silence does not."""
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path))

    resolutions = [q["resolution"] for q in measured["shape_questions"]]
    assert resolutions == ["Decided", "Blocked"]
    assert measured["open_shape_questions_unanswered"] == 0


def test_a_deleted_register_is_not_an_answered_one(tmp_path: Path) -> None:
    """Zero unanswered questions out of zero questions is not a pass."""
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, "# Shape\n"))

    assert measured["open_shape_questions_unanswered"] == -1
    assert measured["phase_checkpoints_defined"] == 0
    assert any("register" in violation for violation in measured["violations"])


def test_an_unreadable_step_list_is_not_a_pass(tmp_path: Path) -> None:
    """A run that could not measure records that, rather than a passing one."""
    broken = tmp_path / "steps.json"
    broken.write_text("{not json", encoding="utf-8")

    measured = product_shape.measure(broken, _shape(tmp_path))

    assert measured["phase_checkpoints_defined"] == 0
    assert measured["steps_measured"] == 0


def test_the_register_stops_at_the_next_heading(tmp_path: Path) -> None:
    """A numbered list further down the document is not a shape question."""
    register = REGISTER + "\n## Something else\n\n1. **Not a question**\n   No marker here.\n"
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert len(measured["shape_questions"]) == 2
    assert measured["open_shape_questions_unanswered"] == 0


def test_evidence_is_written_where_the_gate_reads_it(tmp_path: Path) -> None:
    evidence = tmp_path / "T29.json"
    product_shape.write_evidence(evidence, _steps(tmp_path, _step(0)), _shape(tmp_path))

    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded["phase_checkpoints_defined"] == 1
