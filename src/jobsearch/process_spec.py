"""The process specification, made checkable (S1).

`status/spec-v2-process.md` settles the process: the step list, how steps
connect forwards and backwards, the per-user tree, the offer lifecycle, the
resumption model, and the capture/scoring split. `status/spec-v2-steps.json` is
the same step list in a form a program can read.

Two things here exist because prose alone would not survive contact with the
next task:

* **The six required items are checked by anchor, not by heading text.** Each
  one carries a `<!-- required-item: id -->` marker and must be followed by
  real content. A document that settles the step list but leaves the offer
  lifecycle unwritten is not complete, and S2 would then specify steps against
  a process that does not exist.
* **The step count is loaded, never counted from files.** S2's gate is a
  fraction whose divisor is `step_count`. Dividing by the number of step specs
  that happen to exist would make any amount of work look complete, so the
  divisor comes from here.

Every step must name a gate metric. `not_implemented` is a valid state while a
step is unbuilt; a blank metric is not, because a step with an empty metric is
indistinguishable from a step whose gate was forgotten.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# src-layout repo root, as in `jobsearch.dimensions`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROCESS_DOC = _REPO_ROOT / "status" / "spec-v2-process.md"
DEFAULT_STEPS_PATH = _REPO_ROOT / "status" / "spec-v2-steps.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S1.json"

# The six items S1's payload requires the process document to answer. Order is
# the order they are reported in, not the order they must appear in.
REQUIRED_ITEMS: tuple[str, ...] = (
    "step-list",
    "connections",
    "artefact-tree",
    "offer-lifecycle",
    "resumption",
    "capture-scoring",
)

# A section that exists but says nothing passes an "is it present" check and
# fails the purpose of one. 150 words is roughly half a page — below it, an item
# has been named rather than answered.
MIN_ITEM_WORDS = 150

_ANCHOR_RE = re.compile(r"<!--\s*required-item:\s*([a-z0-9-]+)\s*-->")
# U+2019 is the typographic apostrophe the prose actually uses; spelled as an
# escape so the pattern carries no character a reader could mistake for a quote.
_WORD_RE = re.compile("\\b[\\w'\\u2019-]+\\b")

Phase = Literal["first_run", "loop", "per_opportunity"]
GateState = Literal["implemented", "not_implemented"]
GateOp = Literal["==", ">=", "<=", ">", "<"]

NonEmptyStr = Annotated[str, Field(min_length=1)]


class Gate(BaseModel):
    """A step's acceptance gate: a named metric, and whether it is built yet."""

    model_config = ConfigDict(extra="forbid")

    metric: NonEmptyStr
    op: GateOp
    threshold: float
    state: GateState
    # Which task owns the measurement. Free-form because it spans two id schemes
    # (`T24`, `S4`) and tasks are seeded after this file is written.
    task: NonEmptyStr


class Step(BaseModel):
    """One step of the candidate's journey."""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=0)
    id: NonEmptyStr
    name: NonEmptyStr
    phase: Phase
    goal: NonEmptyStr
    # Requirement 2.2 of the brief: a step that only fills internal state has no
    # visible output and will feel like an interrogation. Making it a required
    # field is the cheapest enforcement available.
    visible_output: NonEmptyStr
    automatic: bool
    gate: Gate
    reentry_events: list[str]


class StepList(BaseModel):
    """`status/spec-v2-steps.json` — the settled step list."""

    model_config = ConfigDict(extra="forbid")

    spec_version: NonEmptyStr
    settled_on: NonEmptyStr
    source: NonEmptyStr
    note: NonEmptyStr
    step_count: int = Field(ge=1)
    phases: dict[str, str]
    steps: list[Step]

    @model_validator(mode="after")
    def _check_internally_consistent(self) -> StepList:
        if self.step_count != len(self.steps):
            raise ValueError(
                f"step_count is {self.step_count} but {len(self.steps)} steps are listed; "
                "S2 divides by step_count, so a stale count would silently mis-measure it"
            )

        numbers = [step.n for step in self.steps]
        if numbers != list(range(len(self.steps))):
            raise ValueError(f"steps must be numbered contiguously from 0, got {numbers}")

        ids = [step.id for step in self.steps]
        duplicates = sorted({sid for sid in ids if ids.count(sid) > 1})
        if duplicates:
            raise ValueError(f"duplicate step ids: {', '.join(duplicates)}")

        unknown_phases = sorted({step.phase for step in self.steps} - set(self.phases))
        if unknown_phases:
            raise ValueError(f"steps use phases absent from `phases`: {', '.join(unknown_phases)}")

        return self


def load_steps(path: Path = DEFAULT_STEPS_PATH) -> StepList:
    """Load and validate the step list. Raises — a caller cannot proceed without it."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return StepList.model_validate(raw)


def required_item_words(document: str) -> dict[str, int]:
    """Word count of each required-item section, keyed by anchor id.

    A section runs from its anchor to the next anchor or the end of the
    document. Ids present more than once are reported by `collect_violations`;
    here the last occurrence wins, which is harmless because a duplicate is a
    violation either way.
    """
    matches = list(_ANCHOR_RE.finditer(document))
    counts: dict[str, int] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        counts[match.group(1)] = len(_WORD_RE.findall(document[start:end]))
    return counts


def collect_violations(
    process_doc: Path = DEFAULT_PROCESS_DOC,
    steps_path: Path = DEFAULT_STEPS_PATH,
) -> list[str]:
    """Every reason the process specification is not complete. Reports, never raises.

    A gate that crashes records no number, so a malformed step list becomes a
    violation string rather than a traceback.
    """
    violations: list[str] = []

    if not process_doc.is_file():
        return [f"process document missing: {process_doc}"]
    document = process_doc.read_text(encoding="utf-8")

    anchors = _ANCHOR_RE.findall(document)
    for item in REQUIRED_ITEMS:
        occurrences = anchors.count(item)
        if occurrences == 0:
            violations.append(
                f"required item `{item}` has no `<!-- required-item: {item} -->` anchor"
            )
        elif occurrences > 1:
            violations.append(f"required item `{item}` is anchored {occurrences} times")

    for unexpected in sorted(set(anchors) - set(REQUIRED_ITEMS)):
        violations.append(f"unknown required-item anchor `{unexpected}`")

    counts = required_item_words(document)
    for item in REQUIRED_ITEMS:
        words = counts.get(item)
        if words is not None and words < MIN_ITEM_WORDS:
            violations.append(
                f"required item `{item}` has {words} words, below the {MIN_ITEM_WORDS} "
                "that distinguishes an answer from a heading"
            )

    if not steps_path.is_file():
        violations.append(f"step list missing: {steps_path}")
        return violations

    try:
        steps = load_steps(steps_path)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        violations.append(f"step list is invalid: {exc}")
        return violations

    for step in steps.steps:
        # Redundant with the schema, and kept: this is the rule S1's payload
        # states in words, and a future schema relaxation should trip it here.
        if not step.gate.metric.strip():
            violations.append(f"step {step.n} ({step.id}) names no gate metric")

    return violations


def measure(
    process_doc: Path = DEFAULT_PROCESS_DOC,
    steps_path: Path = DEFAULT_STEPS_PATH,
) -> dict[str, object]:
    """The S1 gate reading, as it is written to evidence."""
    violations = collect_violations(process_doc, steps_path)
    document = process_doc.read_text(encoding="utf-8") if process_doc.is_file() else ""
    counts = required_item_words(document)

    step_count = 0
    steps_by_phase: dict[str, int] = {}
    gates_implemented = 0
    if steps_path.is_file():
        try:
            steps = load_steps(steps_path)
        except (ValidationError, ValueError, json.JSONDecodeError):
            steps = None
        if steps is not None:
            step_count = steps.step_count
            for step in steps.steps:
                steps_by_phase[step.phase] = steps_by_phase.get(step.phase, 0) + 1
                if step.gate.state == "implemented":
                    gates_implemented += 1

    return {
        "process_spec_complete": 1 if not violations else 0,
        "violations": violations,
        "step_count": step_count,
        "steps_by_phase": steps_by_phase,
        "steps_with_named_gate_metric": step_count,
        "gates_implemented": gates_implemented,
        "required_item_words": {item: counts.get(item, 0) for item in REQUIRED_ITEMS},
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    process_doc: Path = DEFAULT_PROCESS_DOC,
    steps_path: Path = DEFAULT_STEPS_PATH,
) -> dict[str, object]:
    """Measure and record `status/evidence/S1.json`."""
    measured = measure(process_doc, steps_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def main(argv: list[str] | None = None) -> int:
    """Write the S1 gate evidence. Exit 1 when the specification is incomplete."""
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH

    measured = write_evidence(evidence)
    violations = measured["violations"]
    assert isinstance(violations, list)

    for violation in violations:
        print(f"✗ {violation}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    return 0 if not violations else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
