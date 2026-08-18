"""The product-shape decision register (T29).

Two documents carry this task's obligations, and both fail the same silent way.

`status/spec-v2-steps.json` must give **every** step a named checkpoint — a
metric, an operator, a threshold, and an explicit state. A step with a blank
metric is indistinguishable from a step whose checkpoint was forgotten, which is
the distinction `phase_checkpoints_defined` exists to make. `not_implemented` is
therefore a recorded value and a *pass* for definedness, while remaining a
failure for the step itself: defining a checkpoint and meeting it are different
claims and this module never conflates them.

`docs/product-shape.md` opened five questions about the shape of the tool. A
question that is quietly deleted, or answered in a conversation nobody wrote
down, is the failure mode a decision document has — so each question must carry
either a **Decided:** or a **Blocked:** marker in the register at the end of that
document. "Blocked" is a legitimate answer; silence is not.

**A missing register is not agreement.** If the section is absent, or holds no
questions, this reports `-1` and a violation rather than the zero an empty scan
would otherwise produce. The same reasoning applies to the step list: the metric
is a *count* of steps lacking a checkpoint, never a division by the number of
steps, because a divisor that is also the numerator's source can only ever
report success — the failure `plan_v2` and `step_gates` both record having seen.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STEPS_PATH = _REPO_ROOT / "status" / "spec-v2-steps.json"
DEFAULT_SHAPE_PATH = _REPO_ROOT / "docs" / "product-shape.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T29.json"

DECISION_HEADING = "## What needed deciding"

# `1. **One long first interview, or several sittings?**` — the register's items.
_QUESTION_RE = re.compile(r"^(\d+)\.\s+(.*)$")
# The two resolutions a question may carry. `Blocked` may name its reason:
# `**Blocked: …**` and `**Blocked (no owner): …**` both resolve.
_RESOLUTION_RE = re.compile(r"\*\*(Decided|Blocked)\b")

_VALID_STATES = ("implemented", "not_implemented")
_OPERATORS = ("==", "!=", "<=", ">=", "<", ">")


def _load_steps(steps_path: Path) -> list[dict[str, Any]] | None:
    """The step list, or None when it cannot be read as one."""
    try:
        document = json.loads(steps_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    steps = document.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    return [step for step in steps if isinstance(step, dict)]


def checkpoint_problems(step: dict[str, Any]) -> list[str]:
    """Everything wrong with one step's checkpoint declaration."""
    problems: list[str] = []
    gate = step.get("gate")
    if not isinstance(gate, dict):
        return ["no gate block"]

    metric = gate.get("metric")
    if not isinstance(metric, str) or not metric.strip():
        problems.append("no metric")
    if gate.get("op") not in _OPERATORS:
        problems.append(f"operator {gate.get('op')!r} is not one of {', '.join(_OPERATORS)}")
    if not isinstance(gate.get("threshold"), (int, float)) or isinstance(
        gate.get("threshold"), bool
    ):
        problems.append("threshold is not a number")

    state = gate.get("state")
    if state not in _VALID_STATES:
        problems.append(f"state {state!r} is not one of {', '.join(_VALID_STATES)}")
    return problems


def shape_questions(shape_path: Path) -> list[dict[str, str]]:
    """Every question in the shape document's register, with its resolution.

    An item whose body carries neither marker resolves to the empty string,
    which is what `open_shape_questions_unanswered` counts.
    """
    try:
        text = shape_path.read_text(encoding="utf-8")
    except OSError:
        return []
    if DECISION_HEADING not in text:
        return []

    section = text.split(DECISION_HEADING, 1)[1]
    for line in section.splitlines():
        if line.startswith("## "):  # the register ends at the next heading
            section = section.split("\n" + line, 1)[0]
            break

    questions: list[dict[str, str]] = []
    current: list[str] = []

    def _close() -> None:
        if not current:
            return
        body = "\n".join(current)
        match = _RESOLUTION_RE.search(body)
        title = current[0].split(".", 1)[1].strip().strip("*")
        questions.append({"question": title, "resolution": match.group(1) if match else ""})

    for line in section.splitlines():
        if _QUESTION_RE.match(line):
            _close()
            current = [line]
        elif current:
            current.append(line)
    _close()
    return questions


def measure(
    steps_path: Path = DEFAULT_STEPS_PATH,
    shape_path: Path = DEFAULT_SHAPE_PATH,
) -> dict[str, Any]:
    """T29's gate: every step has a checkpoint, every shape question an answer."""
    violations: list[str] = []

    steps = _load_steps(steps_path)
    undefined: list[dict[str, Any]] = []
    not_implemented: list[str] = []
    implemented: list[str] = []

    if steps is None:
        violations.append(f"{steps_path} could not be read as a step list")
    else:
        for step in steps:
            name = str(step.get("id") or step.get("n"))
            problems = checkpoint_problems(step)
            if problems:
                undefined.append({"step": name, "problems": problems})
                violations.append(f"step {name}: {'; '.join(problems)}")
                continue
            gate = step["gate"]
            (implemented if gate["state"] == "implemented" else not_implemented).append(name)

    questions = shape_questions(shape_path)
    unanswered = [q["question"] for q in questions if not q["resolution"]]
    for question in unanswered:
        violations.append(f"shape question carries no decision or blocker: {question}")

    if not questions:
        violations.append(
            f"{shape_path} carries no '{DECISION_HEADING}' register — "
            "an absent register is not an answered one"
        )

    measurable = steps is not None and bool(questions)
    return {
        "phase_checkpoints_defined": (1 if measurable and not violations else 0),
        "open_shape_questions_unanswered": (len(unanswered) if questions else -1),
        "steps_measured": len(steps) if steps else 0,
        "steps_without_a_checkpoint": undefined,
        "steps_implemented": implemented,
        "steps_not_implemented": not_implemented,
        "shape_questions": questions,
        "unanswered_questions": unanswered,
        "violations": violations,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    steps_path: Path = DEFAULT_STEPS_PATH,
    shape_path: Path = DEFAULT_SHAPE_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T29.json`."""
    measured = measure(steps_path, shape_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T29's gate evidence. Exit 1 when a checkpoint or a decision is missing."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)

    violations = measured["violations"]
    assert isinstance(violations, list)
    for violation in violations:
        print(f"✗ {violation}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    return 0 if not violations else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
