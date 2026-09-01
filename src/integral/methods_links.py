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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


#: T83. Who the failure-handling layer came from, spelled exactly as the
#: README and every adapting module spell it — the gate compares these
#: strings, so one drifting spelling is a finding rather than a formatting
#: preference.
UPSTREAM = "MadsLorentzen/ai-job-search"
UPSTREAM_URL = "https://github.com/MadsLorentzen/ai-job-search"
UPSTREAM_LICENCE = "MIT, © 2026 Mads Lorentzen"

#: The heading in `docs/METHODS.md` that holds the register.
ATTRIBUTION_HEADING = "### 2.9 Techniques adapted from `ai-job-search`"

DEFAULT_ATTRIBUTION_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T83.json"

#: A module that says it adapted something. Matched on the sentence the
#: adapting modules already carry, so a *future* borrowing that adds the line
#: and forgets the register row is caught by the same check — which is the
#: half of this task that outlives the fourteen it was written for.
_ADAPTED_MARKER = re.compile(rf"Adapted from `{re.escape(UPSTREAM)}`")


@dataclass(frozen=True)
class Borrowing:
    """One technique taken from upstream, and where it landed."""

    task: str
    #: Repo-relative paths this technique lives in. Checked to exist, because
    #: a register pointing at a file nobody can open credits upstream for
    #: nothing and tells a reader nothing.
    sites: tuple[str, ...]


#: What was actually borrowed. T85 is deliberately absent — the evidence run
#: reaching every module was found here, while validating this increment's own
#: specification — and so is T83 itself. An over-broad acknowledgement is as
#: misleading as a missing one.
BORROWED: tuple[Borrowing, ...] = (
    Borrowing("T70", ("src/integral/robots.py",)),
    Borrowing("T71", ("src/integral/robots.py",)),
    Borrowing("T72", ("src/integral/connector_health.py",)),
    Borrowing("T73", ("src/integral/connector_health.py",)),
    Borrowing("T74", ("src/integral/liveness.py",)),
    Borrowing("T75", ("src/integral/dedup.py",)),
    Borrowing("T76", ("src/integral/eligibility.py",)),
    Borrowing("T77", ("src/integral/eligibility.py",)),
    Borrowing("T78", ("src/integral/offers.py",)),
    Borrowing("T79", ("src/integral/rank.py",)),
    Borrowing("T80", ("src/integral/ats.py",)),
    Borrowing("T81", ("src/integral/ats.py",)),
    Borrowing("T82", ("src/integral/lifecycle.py",)),
    Borrowing("T84", (".claude/skills/step-11-application/SKILL.md",)),
)


def attribution_entries(
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> dict[str, dict[str, str]]:
    """The register's rows, by task id.

    Parsed out of the markdown table rather than kept in this module, because
    a register the gate holds its own copy of is a gate checking itself. The
    prose in `METHODS.md` is the deliverable; this only reads it.
    """
    text = methods_path.read_text(encoding="utf-8")
    start = text.find(ATTRIBUTION_HEADING)
    if start < 0:
        return {}
    section = text[start:]
    end = re.search(r"^#{2,3} ", section[len(ATTRIBUTION_HEADING) :], re.MULTILINE)
    if end:
        section = section[: len(ATTRIBUTION_HEADING) + end.start()]

    entries: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not re.fullmatch(r"T\d+", cells[0]):
            continue
        entries[cells[0]] = {"taken": cells[1], "where": cells[2], "limit": cells[3]}
    return entries


def adapted_modules(root: Path = _REPO_ROOT) -> list[str]:
    """Every tracked source file that says it adapted something from upstream."""
    found: list[str] = []
    for directory in ("src/integral", ".claude/skills"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in {".py", ".md"} or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _ADAPTED_MARKER.search(text):
                found.append(path.relative_to(root).as_posix())
    return found


def measure_attribution(
    root: Path = _REPO_ROOT,
    methods_path: Path | None = None,
    *,
    borrowed: tuple[Borrowing, ...] = BORROWED,
) -> dict[str, Any]:
    """T83's gate: `borrowed_techniques_without_attribution`.

    Four ways a row fails to be attribution: it is missing; it does not say
    what was taken; it does not say where the technique lives; or it records
    no limit. The fourth is not decoration — the borrowing that matters most
    here is a *rejection* (upstream's scoring rubric), and a register that
    only ever says "we took this" is how that judgement gets forgotten and the
    rubric re-imported on the strength of the acknowledgement itself.
    """
    methods_path = methods_path or (root / "docs" / "METHODS.md")
    entries = attribution_entries(methods_path)
    problems: list[str] = []

    for borrowing in borrowed:
        row = entries.get(borrowing.task)
        if row is None:
            problems.append(
                f"{borrowing.task}: no row in {methods_path.name} {ATTRIBUTION_HEADING}"
            )
            continue
        for field in ("taken", "where", "limit"):
            if not row[field].strip() or row[field].strip() in {"-", "\u2014", "TBD"}:
                problems.append(f"{borrowing.task}: the register records no {field}")
        for site in borrowing.sites:
            if not (root / site).exists():
                problems.append(f"{borrowing.task}: names {site}, which does not exist")
            elif site not in row["where"]:
                problems.append(f"{borrowing.task}: the register does not name {site}")

    registered = {site for borrowing in borrowed for site in borrowing.sites}
    stray = [path for path in adapted_modules(root) if path not in registered]
    problems += [
        f"{path}: says it adapted something from {UPSTREAM} and is in no register row"
        for path in stray
    ]

    checked = len(borrowed)
    return {
        "borrowed_techniques_without_attribution": len(problems),
        # Both names, as every gate in this increment carries: the payload
        # names the first, the `status-key` mechanism was written against the
        # second.
        "borrowed_techniques_without_attribution_evaluated": checked,
        "borrowed_techniques_checked": checked,
        "gate_status": "measured" if checked else "unmeasured",
        "upstream": UPSTREAM,
        "adapted_modules_found": len(adapted_modules(root)),
        "adapted_modules_outside_the_register": stray,
        "violations_attribution": problems,
    }


def write_attribution_evidence(
    evidence: Path = DEFAULT_ATTRIBUTION_EVIDENCE_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T83.json`."""
    measured = measure_attribution()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, object]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T22's gate evidence; exit 1 on any unresolved link."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    # T83's record, beside T22's — one module, two questions of the same
    # document: whether every method is documented, and whether every
    # borrowed one says whose it was.
    attribution = write_attribution_evidence(target.parent / "T83.json")
    for problem in attribution["violations_attribution"]:
        print(problem, file=sys.stderr)

    violations = measured["violations"]
    assert isinstance(violations, list)
    for problem in violations:
        print(problem, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
