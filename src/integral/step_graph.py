"""The step graph, and the closure §2.5 depends on (T30).

Process specification §3.1 declares what each step reads and produces — in a
prose code block, which nothing could check. T30 moves the declarations into
`spec-v2-steps.json` and gates the property the whole "any offered step may be
declined" promise rests on:

> Every input of a required step is produced by another required step, or is
> external, or is optional.

Stated in prose that is a promise. Checked, it is a guarantee — and the
difference is not hypothetical. PR #16 introduced the graph and violated it in
the same diff: required **Constraints** read `claimed facts`, which only the
*offered* **Intake** step produces, so a candidate with no CV — exactly the
person §2.5 exists to serve — would have reached a required step with a missing
input. A reviewer caught it. This catches it before the commit.

Two checks live here, and they fail for different reasons:

* **closure** — the property above, over whichever steps the owner has marked
  required. Which steps those are is a decision recorded in the JSON, so it is
  read from there rather than hardcoded: a validator carrying its own copy of
  the answer fails on the next legitimate change until somebody edits the
  constant to match, and a check that gets edited to pass protects nothing.
* **drift** — the JSON against §3.1's prose. The checked graph has to be the
  documented one, or the document and the gate drift apart and only one of them
  is true.

No acyclicity check, deliberately. Feedback (10) produces reaction evidence
that Preferences (6) reads, whose weights Ranking (9) reads, whose ranking
Feedback reads — the loop is the product, not a defect in the graph.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from integral.process_spec import (
    DEFAULT_PROCESS_DOC,
    DEFAULT_STEPS_PATH,
    StepList,
    load_steps,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T30.json"
SOURCING_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T60.json"

#: What the loop learns and step 7 must read, or the offer set is fixed by the
#: least-informed moment in the process. Every one of them is optional: a first
#: cycle runs before any of them exists.
LEARNED_SOURCING_INPUTS = frozenset({"weights", "reaction_evidence", "outcome_evidence"})

# One line of §3.1's graph block:
#   `9  ranking       → rankings/<ts>.json  [reads: extractions, weights.json?]`
_GRAPH_LINE = re.compile(
    r"^\s*(?P<n>\d+)\s+(?P<id>\S+)\s+→\s+(?P<produces>.+?)\s*\[reads:\s*(?P<reads>.*?)\]\s*$"
)
# The block itself, so a code fence elsewhere in the document is not mistaken
# for it. Anchored on the step-zero line, which is the only line that can start
# the graph.
_GRAPH_BLOCK = re.compile(r"```\n(0\s+identify.*?)```", re.DOTALL)

# What the prose writes when a step reads nothing at all.
_NOTHING = "—"


class StepGraphError(Exception):
    """The declared graph cannot be read."""


def _artefact_ids(steps: StepList) -> set[str]:
    produced = {artefact for step in steps.steps for artefact in step.produces}
    return produced | set(steps.external_artefacts)


def closure_violations(steps: StepList) -> list[str]:
    """Which required steps read something the required steps alone cannot supply.

    Reports rather than raises: a gate that crashes records no number, and the
    point of this one is the number.
    """
    required = [step for step in steps.steps if step.required]
    if not required:
        return ["no step is marked required, so there is no process to close over"]

    reachable = {artefact for step in required for artefact in step.produces}
    reachable |= set(steps.external_artefacts)

    violations: list[str] = []
    for step in required:
        for read in step.reads:
            if read.optional or read.artefact in reachable:
                continue
            producers = sorted(other.id for other in steps.steps if read.artefact in other.produces)
            if producers:
                violations.append(
                    f"required step {step.id!r} reads {read.artefact!r}, which only the "
                    f"offered step(s) {', '.join(producers)} produce — a candidate who "
                    "declines them reaches a required step with a missing input"
                )
            else:
                violations.append(
                    f"required step {step.id!r} reads {read.artefact!r}, which no step "
                    "produces and which is not declared external"
                )
    return violations


def unproduced_inputs(steps: StepList) -> list[str]:
    """Any step at all reading an artefact nothing produces — required or not.

    Weaker than closure and worth its own line: an offered step with an input
    nobody can supply is dead code in the graph rather than a broken promise,
    but it is still wrong and still silent.
    """
    known = _artefact_ids(steps)
    return [
        f"step {step.id!r} reads {read.artefact!r}, which nothing produces"
        for step in steps.steps
        for read in step.reads
        if read.artefact not in known
    ]


# ---------------------------------------------------------------------------
# drift against §3.1


def parse_prose_graph(document: str) -> dict[int, tuple[list[str], list[tuple[str, bool]]]]:
    """§3.1's code block as `{n: (produces_labels, [(read_label, optional)])}`.

    Labels are split on `, ` only. A `+` is left alone — "reaction + outcome
    evidence" is one label here, and `artefact_aliases` is where it becomes two
    artefacts, because a parser that split English conjunctions would be
    guessing at the one place the graph must not be guessed at.
    """
    block = _GRAPH_BLOCK.search(document)
    if not block:
        raise StepGraphError("§3.1's graph block was not found in the process specification")
    parsed: dict[int, tuple[list[str], list[tuple[str, bool]]]] = {}
    for line in block.group(1).splitlines():
        if not line.strip():
            continue
        match = _GRAPH_LINE.match(line)
        if not match:
            raise StepGraphError(f"cannot read this line of §3.1's graph: {line!r}")
        produces = [part.strip() for part in match.group("produces").split(",") if part.strip()]
        reads: list[tuple[str, bool]] = []
        raw_reads = match.group("reads").strip()
        if raw_reads and raw_reads != _NOTHING:
            for part in raw_reads.split(","):
                label = part.strip()
                if not label:
                    continue
                reads.append((label.removesuffix("?"), label.endswith("?")))
        parsed[int(match.group("n"))] = (produces, reads)
    return parsed


def _resolve(steps: StepList, label: str) -> list[str]:
    try:
        return steps.artefact_aliases[label]
    except KeyError:
        raise StepGraphError(
            f"§3.1 names {label!r}, which `artefact_aliases` does not map to an artefact"
        ) from None


def drift_violations(steps: StepList, spec_path: Path = DEFAULT_PROCESS_DOC) -> list[str]:
    """Where `spec-v2-steps.json` and §3.1 disagree.

    Both directions matter. A JSON that says less than the prose leaves an
    input unchecked; a JSON that says more checks a graph nobody documented.
    """
    try:
        prose = parse_prose_graph(spec_path.read_text(encoding="utf-8"))
    except (OSError, StepGraphError) as exc:
        return [str(exc)]

    violations: list[str] = []
    if set(prose) != {step.n for step in steps.steps}:
        violations.append(
            f"§3.1 lists steps {sorted(prose)} but the step list has "
            f"{sorted(step.n for step in steps.steps)}"
        )
    for step in steps.steps:
        if step.n not in prose:
            continue
        produces_labels, reads_labels = prose[step.n]
        try:
            expected_produces = [
                artefact for label in produces_labels for artefact in _resolve(steps, label)
            ]
            expected_reads = sorted(
                (artefact, optional)
                for label, optional in reads_labels
                for artefact in _resolve(steps, label)
            )
        except StepGraphError as exc:
            violations.append(f"step {step.id!r}: {exc}")
            continue
        if sorted(step.produces) != sorted(expected_produces):
            violations.append(
                f"step {step.id!r} produces {sorted(step.produces)} in the step list but "
                f"{sorted(expected_produces)} in §3.1"
            )
        declared_reads = sorted((read.artefact, read.optional) for read in step.reads)
        if declared_reads != expected_reads:
            violations.append(
                f"step {step.id!r} reads {declared_reads} in the step list but "
                f"{expected_reads} in §3.1"
            )
    return violations


def sourcing_inputs_excluded(steps: StepList) -> list[str]:
    """Learned inputs step 7 does not read — or reads in a way that blocks it.

    A required learned input is excluded too, and not on a technicality: step 7
    that cannot run until a weight is fitted makes the loop a precondition for
    entering the loop, which is the same offer set as not reading it at all.
    """
    sourcing = next((step for step in steps.steps if step.id == "sourcing"), None)
    if sourcing is None:
        return sorted(LEARNED_SOURCING_INPUTS)
    optional = {read.artefact for read in sourcing.reads if read.optional}
    return sorted(LEARNED_SOURCING_INPUTS - optional)


# ---------------------------------------------------------------------------
# the gate


def measure(
    steps_path: Path = DEFAULT_STEPS_PATH, spec_path: Path = DEFAULT_PROCESS_DOC
) -> dict[str, Any]:
    """Every number this task's gate records."""
    steps = load_steps(steps_path)
    closure = closure_violations(steps)
    unproduced = unproduced_inputs(steps)
    drift = drift_violations(steps, spec_path)
    required = [step.id for step in steps.steps if step.required]
    return {
        "required_subset_closure_violations": len(closure) + len(unproduced),
        "step_graph_prose_drift": len(drift),
        "required_steps": required,
        "declared_reads": sum(len(step.reads) for step in steps.steps),
        "closure_violations": closure,
        "unproduced_inputs": unproduced,
        "drift": drift,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    steps_path: Path = DEFAULT_STEPS_PATH,
    spec_path: Path = DEFAULT_PROCESS_DOC,
) -> dict[str, Any]:
    measured = measure(steps_path, spec_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def measure_sourcing(steps_path: Path = DEFAULT_STEPS_PATH) -> dict[str, Any]:
    """T60's gate: the learned inputs step 7 still leaves out."""
    excluded = sourcing_inputs_excluded(load_steps(steps_path))
    return {
        "sourcing_inputs_excluding_learned_evidence": len(excluded),
        "learned_inputs": sorted(LEARNED_SOURCING_INPUTS),
        "excluded": excluded,
    }


def write_sourcing_evidence(
    evidence: Path = SOURCING_EVIDENCE_PATH, steps_path: Path = DEFAULT_STEPS_PATH
) -> dict[str, Any]:
    """Write T60's measurement to `evidence`, and return it."""
    measured = measure_sourcing(steps_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.step_graph [path]` → T30's and T60's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    sourcing = write_sourcing_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    print(json.dumps(sourcing, ensure_ascii=False))
    for artefact in sourcing["excluded"]:
        print(f"step 'sourcing' does not read {artefact!r} as an optional input", file=sys.stderr)
    if measured["declared_reads"] == 0:
        # Every step declaring nothing satisfies closure trivially, which is a
        # pass over an empty graph rather than over a closed one.
        print("no step declares any input — nothing was checked", file=sys.stderr)
        return 3
    problems = [
        *sourcing["excluded"],
        *measured["closure_violations"],
        *measured["unproduced_inputs"],
        *measured["drift"],
    ]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
