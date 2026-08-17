"""The per-step specifications, made checkable (S2).

`status/spec-v2-steps.md` writes one specification per step, each filling the
template in `status/spec-v2-brief.md` §4 plus the two fields
`status/spec-v2-process.md` §10 requires every step to repeat.

The gate is a **fraction**, and its divisor is the settled step count loaded
from `spec-v2-steps.json` — never the number of step sections that happen to
exist in the document. Dividing by what was written makes any amount of work
look complete: eleven flawless step specs out of thirteen would score 1.0 under
a self-counting denominator, and the two missing steps would never be noticed.

A step counts as complete only when **every** field is present and says
something. A field heading over an empty body passes a presence check and
answers nothing, which is the same failure `jobsearch.process_spec` guards
against at the document level.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from jobsearch.process_spec import load_steps

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STEP_SPECS_DOC = _REPO_ROOT / "status" / "spec-v2-steps.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S2.json"

# The ten fields of the brief's §4 template, plus the two that
# `spec-v2-process.md` §10 requires every step specification to carry:
# `boundary` (what the step says out loud when it ends, and the `last_activity`
# write) and `when declined` (the non-insistence rule, per step). Both were
# added because a rule stated only in the process document is a rule the last
# step spec written will not have.
REQUIRED_FIELDS: tuple[str, ...] = (
    "Purpose",
    "Preconditions",
    "Inputs",
    "Protocol",
    "Stop rule",
    "When declined",
    "Outputs",
    "Boundary",
    "Gate",
    "Resume",
    "Re-run",
    "Privacy",
)

# Below this a field has been named rather than answered. Deliberately low —
# "Purpose" is one sentence by instruction — so it catches the empty stub and
# not the terse-but-real answer.
MIN_FIELD_WORDS = 12

_STEP_HEADING_RE = re.compile(r"^##\s+Step\s+(\d+)\s+—\s+(.+?)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^\*\*(?P<name>[A-Z][^.*]*)\.\*\*", re.MULTILINE)
_WORD_RE = re.compile("\\b[\\w'\\u2019-]+\\b")


def split_steps(document: str) -> dict[int, str]:
    """The document's step sections, keyed by step number."""
    matches = list(_STEP_HEADING_RE.finditer(document))
    sections: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        sections[int(match.group(1))] = document[start:end]
    return sections


def field_words(section: str) -> dict[str, int]:
    """Word count per `**Field.**` in one step section."""
    matches = list(_FIELD_RE.finditer(section))
    counts: dict[str, int] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        counts[match.group("name").strip()] = len(_WORD_RE.findall(section[start:end]))
    return counts


def collect_violations(
    doc: Path = DEFAULT_STEP_SPECS_DOC,
    steps_path: Path | None = None,
) -> list[str]:
    """Every reason the step specifications are incomplete. Reports, never raises."""
    violations: list[str] = []

    steps = load_steps() if steps_path is None else load_steps(steps_path)
    expected = {step.n: step for step in steps.steps}

    if not doc.is_file():
        return [f"step specification document missing: {doc}"]
    sections = split_steps(doc.read_text(encoding="utf-8"))

    for n in sorted(set(sections) - set(expected)):
        violations.append(f"step {n} is specified but is not in the settled step list")

    for n, step in sorted(expected.items()):
        section = sections.get(n)
        if section is None:
            violations.append(f"step {n} ({step.id}) has no specification")
            continue
        counts = field_words(section)
        for field in REQUIRED_FIELDS:
            words = counts.get(field)
            if words is None:
                violations.append(f"step {n} ({step.id}) is missing `{field}`")
            elif words < MIN_FIELD_WORDS:
                violations.append(
                    f"step {n} ({step.id}) `{field}` has {words} words, below the "
                    f"{MIN_FIELD_WORDS} that distinguishes an answer from a heading"
                )

    return violations


def measure(
    doc: Path = DEFAULT_STEP_SPECS_DOC,
    steps_path: Path | None = None,
) -> dict[str, object]:
    """The S2 gate reading, as it is written to evidence."""
    steps = load_steps() if steps_path is None else load_steps(steps_path)
    divisor = steps.step_count

    sections = split_steps(doc.read_text(encoding="utf-8")) if doc.is_file() else {}
    complete: list[int] = []
    incomplete: dict[str, list[str]] = {}
    for step in steps.steps:
        section = sections.get(step.n)
        counts = field_words(section) if section is not None else {}
        missing = [f for f in REQUIRED_FIELDS if counts.get(f, 0) < MIN_FIELD_WORDS]
        if missing:
            incomplete[step.id] = missing
        else:
            complete.append(step.n)

    return {
        # The divisor is the settled count, never len(sections): a document that
        # specifies eleven steps perfectly is 11/13, not 11/11.
        "step_specs_complete_fraction": round(len(complete) / divisor, 4),
        "steps_specified": len(complete),
        "step_count": divisor,
        "incomplete_steps": incomplete,
        "violations": collect_violations(doc, steps_path),
        "required_fields": list(REQUIRED_FIELDS),
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    doc: Path = DEFAULT_STEP_SPECS_DOC,
    steps_path: Path | None = None,
) -> dict[str, object]:
    """Measure and record `status/evidence/S2.json`."""
    measured = measure(doc, steps_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def main(argv: list[str] | None = None) -> int:
    """Write the S2 gate evidence. Exit 1 when a step specification is incomplete."""
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
