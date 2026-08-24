"""T22 — the `docs/METHODS.md` link check, over dimensions *and* computation sites.

Specification §5.1: *"`methods_ref` is **required** on every dimension and every
computation site. It is what makes the `undocumented_methods == 0` criterion
mechanically checkable: walk every dimension file and every scoring function,
resolve each `methods_ref` anchor against `docs/METHODS.md`, and fail on any that
does not resolve. Documentation enforced by a link check, not by discipline."*

`integral.dimensions` already resolves the YAML half inside `load_dimensions`, so
the half this module adds is the code: every `methods_ref` written in Python was
unchecked until now, and — the direction a forward-only walk cannot see — a
scoring function that declares nothing is invisible to a check that only follows
refs it finds. So the register is walked from both ends:

* **forward** — a citation whose anchor is no heading in `METHODS.md`;
* **reverse** — a `### 4.x` heading under `## 4. Formula register` that no
  computation site claims. §4 opens with *"Every computed number that reaches the
  candidate appears here"*, which makes each of its headings, by the register's
  own words, a number someone must be computing.

Both count into one number, because they are one failure seen from two sides: a
method in use and the register disagreeing about it.

**A dimension file cannot discharge a formula.** Dimension YAML is data read by
the extractor, not an implementation, so its citations resolve forwards but never
satisfy the reverse direction — otherwise pointing twenty dimension files at §4.1
would report the weighted mean as implemented while no code computed it.

**Stated ceiling.** "Computation site" is operationalised as *the formula
register*, not as an AST hunt for functions that look like they multiply things.
A heuristic for "is this a scoring function" is the sort of check that is wrong
in both directions and trusted anyway; the register is a list a person maintains
deliberately, and adding a formula to it is what puts a new site under the gate.
A number the candidate sees whose formula was never registered is invisible here
— it is also invisible to §4, which is the document that would have to change.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from integral.dimensions import methods_anchors

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METHODS_PATH = _REPO_ROOT / "docs" / "METHODS.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T22.json"

# A citation in YAML is a bare scalar at the start of a line; in Python it is a
# string literal bound to a `methods_ref`/`METHODS_REF` name — keyword argument,
# attribute, dict key or module constant. Requiring the quote is what keeps a
# `methods_ref: METHODS.md#TODO` line *inside* a generated template out: that one
# is text `integral.suggestions` writes into a file it says does not load as
# written, and reading it as a citation would fail the gate on a placeholder its
# own author already marked unfinished.
_YAML_CITATION = re.compile(r"^methods_ref:\s*(METHODS\.md#\S+)\s*$", re.MULTILINE)
_PY_CITATION = re.compile(
    r"""["']?methods_ref["']?\s*[=:]\s*["'](METHODS\.md#[^"']+)["']""", re.IGNORECASE
)

_FORMULA_REGISTER = re.compile(r"^##\s+\d+\.\s+Formula register\s*$", re.MULTILINE)
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


def _anchor(ref: str) -> str:
    return ref.split("#", 1)[1]


def citations(root: Path = _REPO_ROOT) -> list[tuple[Path, str]]:
    """Every `methods_ref` declared in the repo, as `(file, ref)`, sorted."""
    found: list[tuple[Path, str]] = []
    for path in sorted((root / "dimensions").glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        found += [(path, match.group(1)) for match in _YAML_CITATION.finditer(text)]
    for path in sorted((root / "src" / "integral").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        found += [(path, match.group(1)) for match in _PY_CITATION.finditer(text)]
    return found


def formula_anchors(methods_path: Path = DEFAULT_METHODS_PATH) -> set[str]:
    """Anchors of the `### x.y` headings under `## N. Formula register`.

    Scoped to that one section on purpose: `### 2.1 Structured behavioural
    elicitation` is a technique the dimensions cite, not a number anything
    computes, and requiring a code site for it would demand an implementation of
    a paragraph.
    """
    text = methods_path.read_text(encoding="utf-8")
    register = _FORMULA_REGISTER.search(text)
    if register is None:
        return set()

    anchors: set[str] = set()
    for match in _HEADING.finditer(text, register.end()):
        if len(match.group(1)) == 2:  # the next `##` closes the register
            break
        anchors.add(_slug(match.group(2)))
    return anchors


def _slug(heading: str) -> str:
    """GitHub's anchor rule — the same one `integral.dimensions` resolves against."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def undocumented(root: Path = _REPO_ROOT, methods_path: Path | None = None) -> list[str]:
    """Every §5.1 link violation, in both directions, as readable strings."""
    methods_path = methods_path or (root / "docs" / "METHODS.md")
    anchors = methods_anchors(methods_path)
    found = citations(root)

    problems = [
        f"{path.relative_to(root)}: methods_ref {ref!r} resolves to no heading in "
        f"{methods_path.name}"
        for path, ref in found
        if _anchor(ref) not in anchors
    ]

    claimed = {_anchor(ref) for path, ref in found if path.suffix == ".py"}
    problems += [
        f"{methods_path.name}#{anchor}: a registered formula with no computation site — "
        "no module declares methods_ref for it"
        for anchor in sorted(formula_anchors(methods_path) - claimed)
    ]
    return problems


def measure(root: Path = _REPO_ROOT, methods_path: Path | None = None) -> dict[str, object]:
    """T22's gate evidence."""
    methods_path = methods_path or (root / "docs" / "METHODS.md")
    problems = undocumented(root, methods_path)
    found = citations(root)
    return {
        "undocumented_methods": len(problems),
        "violations": problems,
        "citations": len(found),
        "citation_sites": len({path for path, _ in found}),
        "registered_formulas": len(formula_anchors(methods_path)),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, object]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T22's gate evidence; exit 1 on any unresolved link."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)

    violations = measured["violations"]
    assert isinstance(violations, list)
    for problem in violations:
        print(problem, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
