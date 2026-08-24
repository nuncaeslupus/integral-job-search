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

**S12** moved one more judgement into this schema: `Step.accepts_candidate_free_text`
records whether a step's protocol puts free text about the candidate in front
of a writer at all. It used to live as a hand-maintained Python dict in
`integral.profile_capture` (`ACCEPTS_CANDIDATE_FREE_TEXT`), checked against
this file's live step ids on every measurement so it could not silently go
stale — now the fact is declared beside the step it describes instead of in a
second file a step author has to remember to edit. The field is optional
(`bool | None`, default `None`) rather than required: an undeclared step still
loads here so S1/S2/T30/S7 — which have nothing to do with free-text capture —
are unaffected; only `integral.profile_capture`'s own gate
(`unclassified_free_text_steps`) notices and fails on a step left undeclared.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

# src-layout repo root, as in `integral.dimensions`.
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


def _reject_blank(value: str) -> str:
    """Refuse a string that is technically present and says nothing.

    `min_length=1` admits `" "`, which reads as a value to the schema and as an
    omission to every human and to `collect_violations`. One rule, applied at
    the schema, keeps those two readings from ever disagreeing — a gate metric
    of `" "` must fail at load, not survive to be counted as named.
    """
    if not value.strip():
        raise ValueError("must not be blank or whitespace-only")
    return value


NonEmptyStr = Annotated[str, Field(min_length=1), AfterValidator(_reject_blank)]

#: A boolean that must arrive as a JSON boolean, not as something Pydantic can
#: talk into one. Pydantic's ordinary `bool` is lax: `1`, `0`, `"true"`,
#: `"false"` and `"yes"` all validate and silently become `True`/`False`. That
#: is wrong for every flag in this file, because this file is the settled model
#: other modules read instead of keeping their own copy — a typo that still
#: parses is precisely the failure the model exists to prevent, and the value
#: it produces looks entirely legitimate downstream.
#:
#: It matters most for `accepts_candidate_free_text`, whose S12 gate counts only
#: *absent* declarations on the stated grounds that a present non-boolean would
#: already have failed loading. Lax `bool` made that claim false: `"yes"` landed
#: as a declaration and was counted as one. `2` was already rejected, so only
#: the values that look deliberate got through.
StrictBool = Annotated[bool, Field(strict=True)]


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


class Read(BaseModel):
    """One declared input of a step — §3.1.

    `optional` is the prose graph's `?`, and those marks are what make §2.5
    true rather than merely stated: a required step whose every non-optional
    input comes from another required step can still be reached by a candidate
    who declined every offered one.
    """

    model_config = ConfigDict(extra="forbid")

    artefact: NonEmptyStr
    optional: StrictBool = False


class Step(BaseModel):
    """One step of the candidate's journey."""

    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=0)
    id: NonEmptyStr
    name: NonEmptyStr
    phase: Phase
    # Required steps are the ones without which there is nothing to show the
    # candidate. Everything else is offered, which is what makes the
    # non-insistence rule safe: declining a step always leaves a way forward.
    required: StrictBool
    goal: NonEmptyStr
    # Requirement 2.2 of the brief: a step that only fills internal state has no
    # visible output and will feel like an interrogation. Making it a required
    # field is the cheapest enforcement available.
    visible_output: NonEmptyStr
    automatic: StrictBool
    # S12: whether this step's protocol puts free text *about the candidate*
    # in front of a writer at all. Not derivable from `automatic` — only
    # `understanding` is `automatic: true`, and that field answers "is a
    # candidate present", not "does this step take free text about them"
    # (Ranking is an ordinary, non-automatic conversation that only presents).
    # `None` is deliberately a real state, not a default that reads as an
    # answer: a step landing here with the declaration unset must be
    # `None`, not silently `False`, so `integral.profile_capture`'s own gate
    # (`unclassified_free_text_steps`) can name it rather than mistake "not
    # yet decided" for "decided no". Optional rather than required so an
    # undeclared step still loads here (and every gate that has nothing to do
    # with free-text capture — S1, S2, T30, S7 — is unaffected); only the
    # capture gate that actually cares about this field fails on it.
    accepts_candidate_free_text: StrictBool | None = None
    gate: Gate
    reentry_events: list[str]
    # §3.1's declarations, moved out of the prose code block so the graph can be
    # checked rather than read. `integral.step_graph` holds both the closure
    # check and the drift check against the prose they came from.
    reads: list[Read] = []
    produces: list[NonEmptyStr] = []


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
    # Artefacts no step produces because they exist before the process starts —
    # the dimension model is the only one today. Declared rather than inferred:
    # "nothing produces it" is also what an unsatisfiable input looks like, and
    # a checker that guessed between the two would pass the broken graph.
    external_artefacts: list[NonEmptyStr] = []
    # Prose label → the canonical artefact ids it names, used only to check the
    # JSON against §3.1. One label may name more than one artefact ("reaction +
    # outcome evidence"), so the mapping is explicit rather than a parser
    # splitting English conjunctions.
    artefact_aliases: dict[str, list[NonEmptyStr]] = {}

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

        for step in self.steps:
            artefacts = [read.artefact for read in step.reads]
            repeated = sorted({a for a in artefacts if artefacts.count(a) > 1})
            if repeated:
                raise ValueError(
                    f"step {step.id!r} declares duplicate reads: {', '.join(repeated)}. "
                    "One artefact read twice can be optional in one declaration and "
                    "required in the other, which reads as declared to anything asking "
                    "whether it is optional and as blocking to `missing_inputs`"
                )

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

    if not any(step.required for step in steps.steps):
        violations.append(
            "no step is marked required — a process every part of which may be declined "
            "cannot put an offer in front of anyone"
        )

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
    # Counted, never assumed equal to step_count. Evidence that restates its own
    # denominator measures nothing, and a reader debugging a failed gate would
    # be told every step names a metric by the very file meant to show which
    # one does not.
    named_gate_metrics = 0
    required_steps: list[str] = []
    if steps_path.is_file():
        try:
            steps = load_steps(steps_path)
        except (ValidationError, ValueError, json.JSONDecodeError):
            steps = None
        if steps is not None:
            step_count = steps.step_count
            for step in steps.steps:
                steps_by_phase[step.phase] = steps_by_phase.get(step.phase, 0) + 1
                if step.gate.metric.strip():
                    named_gate_metrics += 1
                if step.gate.state == "implemented":
                    gates_implemented += 1
                if step.required:
                    required_steps.append(step.id)

    return {
        "process_spec_complete": 1 if not violations else 0,
        "violations": violations,
        "step_count": step_count,
        "steps_by_phase": steps_by_phase,
        "steps_with_named_gate_metric": named_gate_metrics,
        "required_steps": required_steps,
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
