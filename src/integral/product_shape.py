"""The product-shape decision register (T29).

Two documents carry this task's obligations, and both fail the same silent way.

`status/spec-v2-steps.json` must give **every** step a named checkpoint — a
metric, an operator, a threshold, and an explicit state. A step with a blank
metric is indistinguishable from a step whose checkpoint was forgotten, which is
the distinction `phase_checkpoints_defined` exists to make. `not_implemented` is
therefore a recorded value and a *pass* for definedness, while remaining a
failure for the step itself: defining a checkpoint and meeting it are different
claims and this module never conflates them.

`docs/product-shape.md` opened questions about the shape of the tool. A question
that is quietly deleted, or answered in a conversation nobody wrote down, is the
failure mode a decision document has — so each question must carry a **Decided:**
or **Blocked:** resolution in the register at the end of that document.
"Blocked" is a legitimate answer; silence is not, and neither is the *word*
appearing in prose. The marker is recognised only at the start of a line and
only when it names something after the colon, because a resolution that is
merely mentioned is not one that was made.

**Nothing here counts only what survived.** Both sides declare their own
length — `step_count` in the JSON, a `shape-questions` marker in the Markdown —
and both are compared against what was actually parsed. Deleting the twelfth
step, or the fourth question, is otherwise invisible: every remaining entry is
well formed, so a scan of the survivors reports a clean sheet. That is the same
shape of bug as dividing by the number you meant to measure, which `plan_v2` and
`step_gates` each record having seen; here it would let a question be removed
instead of answered. A register that cannot be measured reports `-1` and a
violation, never the zero an empty scan would produce.
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

# The register declares its own length, as `spec-v2-steps.json` declares
# `step_count`. Without it a deleted question is a question that was never asked.
_COUNT_MARKER_RE = re.compile(r"<!--\s*shape-questions:\s*(\d+)\s*-->")

# `1. **One long first interview, or several sittings?**` — the register's items.
_QUESTION_RE = re.compile(r"^(\d+)\.\s+(.*)$")

# A resolution: at the start of a line, bold, and naming something after the
# colon. `**Blocked: no owner**` and `**Blocked (spec §11.1): …**` both resolve;
# the word `**Blocked**` inside a sentence does not, and neither does a bare
# `**Blocked:**` — the character after the colon may not be the closing marker,
# or a blocker could be recorded without ever naming what blocks it.
_RESOLUTION_RE = re.compile(r"^\s*\*\*(Decided|Blocked)\b[^*\n]*:[^\S\n]*[^*\s]", re.MULTILINE)

_VALID_STATES = ("implemented", "not_implemented")
_OPERATORS = ("==", "!=", "<=", ">=", "<", ">")


def _load_document(steps_path: Path) -> dict[str, Any] | None:
    """The step document, or None when it cannot be read as one."""
    try:
        document = json.loads(steps_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or not isinstance(document.get("steps"), list):
        return None
    return document


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
    threshold = gate.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        problems.append("threshold is not a number")

    state = gate.get("state")
    if state not in _VALID_STATES:
        problems.append(f"state {state!r} is not one of {', '.join(_VALID_STATES)}")
    return problems


def shape_register(shape_path: Path) -> dict[str, Any]:
    """The register: its declared length, its questions, and what is wrong with it.

    Items are numbered, and the numbering is checked as well as counted — a
    register that jumps from 3 to 5 has lost a question whether or not anyone
    remembered to update the declared total.
    """
    problems: list[str] = []
    try:
        text = shape_path.read_text(encoding="utf-8")
    except OSError:
        return {"declared": None, "questions": [], "problems": [f"{shape_path} cannot be read"]}

    if DECISION_HEADING not in text:
        return {
            "declared": None,
            "questions": [],
            "problems": [
                f"{shape_path} carries no '{DECISION_HEADING}' register — "
                "an absent register is not an answered one"
            ],
        }

    section = text.split(DECISION_HEADING, 1)[1]
    for line in section.splitlines():
        if line.startswith("## "):  # the register ends at the next heading
            section = section.split("\n" + line, 1)[0]
            break

    declared_match = _COUNT_MARKER_RE.search(section)
    declared = int(declared_match.group(1)) if declared_match else None
    if declared is None:
        problems.append(
            "the register declares no question count — a count taken from what "
            "survived cannot notice a deletion"
        )

    questions: list[dict[str, str]] = []
    numbering: list[int] = []
    current: list[str] = []

    def _close() -> None:
        if not current:
            return
        body = "\n".join(current)
        match = _RESOLUTION_RE.search(body)
        title = current[0].split(".", 1)[1].strip().strip("*")
        questions.append({"question": title, "resolution": match.group(1) if match else ""})

    for line in section.splitlines():
        numbered = _QUESTION_RE.match(line)
        if numbered:
            _close()
            numbering.append(int(numbered.group(1)))
            current = [line]
        elif current:
            current.append(line)
    _close()

    if numbering and numbering != list(range(1, len(numbering) + 1)):
        problems.append(
            f"the register is numbered {numbering}, not 1…{len(numbering)} — "
            "a gap or a repeat is a question that went missing"
        )
    if declared is not None and declared != len(questions):
        problems.append(
            f"the register declares {declared} question(s) and carries {len(questions)} — "
            "a question was deleted rather than answered, or the declaration is stale"
        )
    if not questions:
        problems.append(f"{shape_path} carries no questions under '{DECISION_HEADING}'")

    return {"declared": declared, "questions": questions, "problems": problems}


def measure(
    steps_path: Path = DEFAULT_STEPS_PATH,
    shape_path: Path = DEFAULT_SHAPE_PATH,
) -> dict[str, Any]:
    """T29's gate: every step has a checkpoint, every shape question an answer."""
    violations: list[str] = []

    document = _load_document(steps_path)
    undefined: list[dict[str, Any]] = []
    not_implemented: list[str] = []
    implemented: list[str] = []
    declared_steps: int | None = None
    entries: list[Any] = []

    if document is None:
        violations.append(f"{steps_path} could not be read as a step list")
    else:
        entries = document["steps"]
        declared = document.get("step_count")
        declared_steps = (
            declared if isinstance(declared, int) and not isinstance(declared, bool) else None
        )
        if declared_steps is None:
            violations.append(
                f"{steps_path} declares no `step_count` — the expected number of "
                "steps must not come from the list being checked"
            )
        elif declared_steps != len(entries):
            violations.append(
                f"{steps_path} declares {declared_steps} step(s) and carries "
                f"{len(entries)} — a step was removed, not measured"
            )

        for position, entry in enumerate(entries):
            if not isinstance(entry, dict):
                name = f"entry {position}"
                undefined.append({"step": name, "problems": ["not an object"]})
                violations.append(f"step {name}: not an object")
                continue
            name = str(entry.get("id") or entry.get("n"))
            problems = checkpoint_problems(entry)
            if problems:
                undefined.append({"step": name, "problems": problems})
                violations.append(f"step {name}: {'; '.join(problems)}")
                continue
            gate = entry["gate"]
            (implemented if gate["state"] == "implemented" else not_implemented).append(name)

    register = shape_register(shape_path)
    questions: list[dict[str, str]] = register["questions"]
    unanswered = [q["question"] for q in questions if not q["resolution"]]
    for question in unanswered:
        violations.append(f"shape question carries no decision or blocker: {question}")
    violations.extend(register["problems"])

    measurable = document is not None and bool(questions) and not register["problems"]
    return {
        "phase_checkpoints_defined": (1 if measurable and not violations else 0),
        "open_shape_questions_unanswered": (len(unanswered) if measurable else -1),
        "steps_declared": declared_steps,
        "steps_measured": len(entries),
        "steps_without_a_checkpoint": undefined,
        "steps_implemented": implemented,
        "steps_not_implemented": not_implemented,
        "questions_declared": register["declared"],
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
