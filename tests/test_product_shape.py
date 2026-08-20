"""The product-shape decision register (T29).

Each test is one of the ways this gate could report agreement it never
measured — a step whose checkpoint is blank, a `not_implemented` step counted as
delivered, a register that was deleted rather than answered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integral import product_shape

REGISTER = """# Shape

## What needed deciding

<!-- shape-questions: 2 -->

1. **First question?**
   **Decided: this way.** Because of a reason.

2. **Second question?**
   **Blocked: nobody has settled it.** Named, and therefore recorded.
"""


def _step(n: int, **gate: Any) -> dict[str, Any]:
    block = {"metric": f"metric_{n}", "op": "==", "threshold": 0, "state": "implemented"}
    block.update(gate)
    return {"n": n, "id": f"step_{n}", "gate": block}


def _steps(tmp_path: Path, *steps: dict[str, Any], declared: int | None = None) -> Path:
    """A step list. `declared` overrides `step_count` to model a deletion."""
    path = tmp_path / "steps.json"
    count = len(steps) if declared is None else declared
    path.write_text(json.dumps({"step_count": count, "steps": list(steps)}), encoding="utf-8")
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
    register = (
        "## What needed deciding\n\n<!-- shape-questions: 1 -->\n\n"
        "1. **Only question?**\n   We talked about it.\n"
    )
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


def test_a_deleted_step_is_caught(tmp_path: Path) -> None:
    """Twelve well-formed steps where thirteen were declared is not a clean sheet."""
    measured = product_shape.measure(
        _steps(tmp_path, _step(0), _step(1), declared=3), _shape(tmp_path)
    )

    assert measured["phase_checkpoints_defined"] == 0
    assert measured["steps_declared"] == 3
    assert measured["steps_measured"] == 2
    assert any("was removed, not measured" in v for v in measured["violations"])


def test_a_step_list_without_a_declared_count_is_not_measurable(tmp_path: Path) -> None:
    """The expected number must not come from the list being checked."""
    path = tmp_path / "steps.json"
    path.write_text(json.dumps({"steps": [_step(0)]}), encoding="utf-8")

    measured = product_shape.measure(path, _shape(tmp_path))

    assert measured["phase_checkpoints_defined"] == 0
    assert measured["steps_declared"] is None


def test_a_step_entry_that_is_not_an_object_is_a_violation(tmp_path: Path) -> None:
    """A replaced entry becomes a violation rather than being filtered away."""
    path = tmp_path / "steps.json"
    path.write_text(json.dumps({"step_count": 2, "steps": [_step(0), "step_1"]}), encoding="utf-8")

    measured = product_shape.measure(path, _shape(tmp_path))

    assert measured["phase_checkpoints_defined"] == 0
    assert [entry["step"] for entry in measured["steps_without_a_checkpoint"]] == ["entry 1"]


def test_a_deleted_question_is_caught(tmp_path: Path) -> None:
    """Deleting a question instead of answering it is the failure mode here."""
    register = (
        "## What needed deciding\n\n<!-- shape-questions: 2 -->\n\n"
        "1. **Kept question?**\n   **Decided: yes.**\n"
    )
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["phase_checkpoints_defined"] == 0
    assert measured["open_shape_questions_unanswered"] == -1
    assert any("deleted rather than answered" in v for v in measured["violations"])


def test_a_register_that_declares_no_count_is_not_measurable(tmp_path: Path) -> None:
    register = "## What needed deciding\n\n1. **A question?**\n   **Decided: yes.**\n"
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["phase_checkpoints_defined"] == 0
    assert measured["questions_declared"] is None


def test_a_gap_in_the_numbering_is_caught(tmp_path: Path) -> None:
    """1, 3 is a lost question even when the declared total was updated too."""
    register = (
        "## What needed deciding\n\n<!-- shape-questions: 2 -->\n\n"
        "1. **First?**\n   **Decided: yes.**\n\n3. **Third?**\n   **Decided: yes.**\n"
    )
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["phase_checkpoints_defined"] == 0
    assert any("went missing" in v for v in measured["violations"])


def test_the_word_blocked_in_prose_does_not_resolve_a_question(tmp_path: Path) -> None:
    """A resolution must be made, not merely mentioned."""
    register = (
        "## What needed deciding\n\n<!-- shape-questions: 1 -->\n\n"
        "1. **Unanswered?**\n   Whether this is **Blocked** is unresolved.\n"
    )
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["unanswered_questions"] == ["Unanswered?"]
    assert measured["phase_checkpoints_defined"] == 0


def test_a_marker_naming_nothing_does_not_resolve_a_question(tmp_path: Path) -> None:
    """`**Blocked:**` with no reason after the colon is not a named blocker."""
    register = (
        "## What needed deciding\n\n<!-- shape-questions: 1 -->\n\n"
        "1. **Unanswered?**\n   **Blocked:**\n"
    )
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["unanswered_questions"] == ["Unanswered?"]


def test_a_blocker_may_name_its_reason_in_parentheses(tmp_path: Path) -> None:
    """The documented `**Blocked (reason): …**` form still resolves."""
    register = (
        "## What needed deciding\n\n<!-- shape-questions: 1 -->\n\n"
        "1. **Answered?**\n   **Blocked (spec §11.1): the owner sets the number.**\n"
    )
    measured = product_shape.measure(_steps(tmp_path, _step(0)), _shape(tmp_path, register))

    assert measured["unanswered_questions"] == []
    assert measured["phase_checkpoints_defined"] == 1
