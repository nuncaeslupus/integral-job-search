"""Cross-document gate consistency (D-3).

`status/spec-v2-steps.md` is where a step's protocol is settled. When a
protocol revision makes an older numeric gate impossible to satisfy honestly,
the step spec says so explicitly, in one recurring sentence shape:

    **`<metric expression>` is superseded and must not be gated on.**

Step 3's revision is the instance that named this module: the v1 criterion
`story_failure_fraction >= 0.33` required digging for failure episodes, and
the revised History protocol (`status/spec-v2-steps.md` step 3) forbids
digging — "take the failure when it comes rather than digging for it." An
implementation would have to break the protocol or miss the gate; there is no
behaviour satisfying both. The step spec resolves the contradiction and marks
the floor superseded. But two older documents — `status/specification.md`'s
v1 success criteria and `docs/METHODS.md`'s methodology entry — still asserted
the floor as a live gate, because reconciling the step spec did not, by
itself, touch either of them.

**Why this is worse than an unfinished task.** A gate nobody can satisfy
honestly teaches whoever implements the step that the numbers are decorative
— but a gate that is *stated confidently and superseded silently* is worse
than that: a future reader has no signal that anything changed, builds to the
number they found, and their gate passes against a threshold the protocol
already abandoned. Reporting a fraction and gating on it are different
things, and a document that blurs them is lying by omission the moment the
step spec moves and it does not.

**The check is general, not string-shaped to `story_failure_fraction`.** It
never hardcodes which metric or threshold is superseded. Instead it parses
every "is superseded and must not be gated on" declaration out of the step
spec (there may be more than one, now or later) and then searches the target
documents for each declared expression appearing in a *gate-shaped* context —
a `- [ ]` checklist item (this repo's convention for a v1 success-criterion
gate) or a line carrying the word "gate" — so the next superseded floor left
stated as a gate anywhere is caught the same way, without a new string
literal here.

A gate-shaped mention of the *metric name alone*, with no threshold attached
(e.g. `docs/METHODS.md`'s "Gate metrics" table row defining
`story_failure_fraction` as a formula), is not a contradiction: naming a
metric and defining how it is computed is exactly what "reported, never
floored" requires. Only the metric **together with its superseded
comparison** (`story_failure_fraction >= 0.33`, not `story_failure_fraction`
on its own) in a gate context counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The document(s) that declare a gate superseded. Only `spec-v2-steps.md`
# carries the sentence shape today, but this is a tuple, not a constant path,
# so a second step-bearing document could be added without restructuring the
# scan.
SOURCE_DOCS: tuple[Path, ...] = (_REPO_ROOT / "status" / "spec-v2-steps.md",)

# The documents D-3 was asked to reconcile. `status/spec-annotated.md` and
# `docs/spec-v2-steps/spec-annotated.md` are generated readers of other
# documents (one of them a reader of a *source* doc above) — scanning a
# generated file would just duplicate whatever its source already reports, or
# flag the declaration sentence itself as if it were the violation it
# describes. Only the hand-authored documents are targets.
TARGET_DOCS: tuple[Path, ...] = (
    _REPO_ROOT / "status" / "specification.md",
    _REPO_ROOT / "docs" / "METHODS.md",
)

DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D3.json"

# A superseded declaration found is what makes a "0 contradictions" reading
# mean something. If the sentence shape ever stops matching — a rewording in
# `spec-v2-steps.md`, a moved file — the scan would find no declarations, find
# nothing to search for, and report zero contradictions having checked
# nothing. That is a silently vacuous pass, the exact failure this module
# exists to prevent one level up. The floor makes it a hard failure instead.
MINIMUM_DECLARATIONS_FOUND = 1

_DECLARATION_RE = re.compile(
    r"`(?P<expr>[^`]+?)`\s+is superseded and must not be gated on",
    re.IGNORECASE,
)

_GATE_WORD_RE = re.compile(r"\bgate\b", re.IGNORECASE)
_CHECKLIST_RE = re.compile(r"^\s*-\s*\[[ xX]\]")


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this schema — see `dimensions.Strict`."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Declaration(Strict):
    """One "is superseded and must not be gated on" sentence, as found."""

    expr: str
    document: str
    line: int
    text: str


class Contradiction(Strict):
    """A superseded expression still stated as a gate somewhere it was reconciled."""

    expr: str
    superseded_in: str
    superseded_at_line: int
    document: str
    line: int
    text: str


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:  # pragma: no cover - every configured path is under the repo
        return str(path)


def find_declarations(source_docs: tuple[Path, ...] = SOURCE_DOCS) -> list[Declaration]:
    """Every "is superseded and must not be gated on" sentence in the source docs.

    Reads every declaration the step spec makes, not just the first: a second
    superseded gate stated in the same document must not vanish because this
    stopped at the one D-3 was filed for.
    """
    found: list[Declaration] = []
    for doc in source_docs:
        if not doc.is_file():
            continue
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            for match in _DECLARATION_RE.finditer(line):
                found.append(
                    Declaration(
                        expr=match.group("expr").strip(),
                        document=_relative(doc),
                        line=lineno,
                        text=line.strip(),
                    )
                )
    return found


def _expr_pattern(expr: str) -> re.Pattern[str]:
    """A regex matching `expr` verbatim, tolerant only of run-of-whitespace width.

    Built fresh per expression rather than a fixed literal, because the
    expression itself is discovered at run time from `find_declarations` — the
    part of this module that must never hardcode a metric name.
    """
    pieces = [re.escape(token) for token in expr.split()]
    return re.compile(r"\s+".join(pieces))


def _is_gate_context(line: str) -> bool:
    """A `- [ ]` checklist item (this repo's v1-gate convention) or a line saying "gate"."""
    return bool(_CHECKLIST_RE.match(line) or _GATE_WORD_RE.search(line))


def find_contradictions(
    declarations: list[Declaration],
    target_docs: tuple[Path, ...] = TARGET_DOCS,
) -> list[Contradiction]:
    """Every gate-shaped restatement, in the target docs, of a superseded expression."""
    contradictions: list[Contradiction] = []
    for declaration in declarations:
        pattern = _expr_pattern(declaration.expr)
        for doc in target_docs:
            if not doc.is_file():
                continue
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
                if pattern.search(line) and _is_gate_context(line):
                    contradictions.append(
                        Contradiction(
                            expr=declaration.expr,
                            superseded_in=declaration.document,
                            superseded_at_line=declaration.line,
                            document=_relative(doc),
                            line=lineno,
                            text=line.strip(),
                        )
                    )
    return contradictions


def measure(
    source_docs: tuple[Path, ...] = SOURCE_DOCS,
    target_docs: tuple[Path, ...] = TARGET_DOCS,
) -> dict[str, Any]:
    """The D-3 gate reading, as it is written to evidence."""
    declarations = find_declarations(source_docs)
    contradictions = find_contradictions(declarations, target_docs)
    return {
        "spec_gate_contradictions": len(contradictions),
        "superseded_declarations_found": len(declarations),
        "declarations": [d.model_dump(mode="json") for d in declarations],
        "contradictions": [c.model_dump(mode="json") for c in contradictions],
        "source_documents": [_relative(p) for p in source_docs],
        "target_documents": [_relative(p) for p in target_docs],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    source_docs: tuple[Path, ...] = SOURCE_DOCS,
    target_docs: tuple[Path, ...] = TARGET_DOCS,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D3.json`."""
    measured = measure(source_docs, target_docs)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.spec_consistency [--check] [--write-evidence [PATH]]` → D-3's gate.

    `--check` measures and reports without writing a file. Without it (the
    default, and with `--write-evidence` explicit), the evidence file is
    written — `[PATH]` defaults to `status/evidence/D3.json` when the flag
    carries no value, matching every other gate module in this package.

    Exit 3 when fewer than `MINIMUM_DECLARATIONS_FOUND` supersession
    declarations were found (nothing trustworthy was measured), 1 when any
    contradiction was found, 0 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/D3.json)",
    )
    parser.add_argument(
        "--source-doc",
        action="append",
        metavar="PATH",
        help="a document to scan for supersession declarations (repeatable; "
        "default: status/spec-v2-steps.md)",
    )
    parser.add_argument(
        "--target-doc",
        action="append",
        metavar="PATH",
        help="a document to scan for gate-shaped restatements (repeatable; "
        "default: status/specification.md, docs/METHODS.md)",
    )
    args = parser.parse_args(argv[1:])

    source_docs = tuple(Path(p) for p in args.source_doc) if args.source_doc else SOURCE_DOCS
    target_docs = tuple(Path(p) for p in args.target_doc) if args.target_doc else TARGET_DOCS

    if args.check:
        measured = measure(source_docs, target_docs)
    else:
        measured = write_evidence(Path(args.write_evidence), source_docs, target_docs)

    print(json.dumps(measured, ensure_ascii=False))

    found = measured["superseded_declarations_found"]
    assert isinstance(found, int)
    if found < MINIMUM_DECLARATIONS_FOUND:
        print(
            f"only {found} superseded-gate declaration(s) were found in "
            f"{measured['source_documents']} (floor {MINIMUM_DECLARATIONS_FOUND}) — "
            "zero contradictions over nothing measured is not a pass",
            file=sys.stderr,
        )
        return 3

    contradictions = measured["contradictions"]
    assert isinstance(contradictions, list)
    for contradiction in contradictions:
        print(
            f"{contradiction['document']}:{contradiction['line']} still gates on "
            f"`{contradiction['expr']}`, superseded at "
            f"{contradiction['superseded_in']}:{contradiction['superseded_at_line']} "
            f"— {contradiction['text']}",
            file=sys.stderr,
        )
    return 1 if contradictions else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
