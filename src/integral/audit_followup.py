"""Does every audit case that found something end up in a gate? (T102)

`CLAUDE.md` requires that fixtures for a correctness-critical gate be derived by
a session other than the implementer, and then says what must happen to the
result:

> **Every accepted case is then committed into the gate's own fixtures before
> the PR merges** — not merely answered in a comment. A report that is read and
> waved through leaves the code exactly as unprotected as it was, and the next
> regression re-opens the same hole with nothing to catch it.

Nothing enforced that. The round-2 T70 audit derived 35 cases and left one —
case 22 — as an open discrepancy with an unverified citation, and it stayed open
across four merges because a finding in a markdown file is invisible to every
target in the `Makefile`. T102 is that case, and this module is the reason it
cannot happen silently again: an audit case that names a defect is a **red gate**
until it is either fixed or answered against the spec.

## What counts as uncommitted

A case section is `### <n>. \\`<name>\\` — <verdict>`. The verdict vocabulary is
the audits' own, declared in their preamble ("**DISCREPANCY (fail-open)** = spec
requires block, implementation allows"), so this module reads the audits' terms
rather than inventing a taxonomy that happens to fit today's files:

- `MATCH` — the implementation already agrees. Nothing owed.
- `DISCREPANCY` — a finding. **Owed**, and counted here until resolved.
- `RESOLVED` — a finding that has been settled. Counted **unless** the section
  earns it, below.
- anything else (the round-2 audit's `NEITHER pass nor a fail-open/fail-closed
  defect`, for a case whose schema the harness cannot express) — not a finding,
  so not owed. Excluded by its own heading, not by a rule written after reading
  it.

## Why `RESOLVED` is not self-certifying

The obvious hole in a metric keyed on headings is that a session can close a case
by typing eight letters. So a resolved section must also carry:

1. a **section citation** (`§`) — the discipline `CLAUDE.md` demands of the
   second reader, which is to justify a verdict "by citing the spec, never by
   running the code"; and
2. either the name of a fixture that **exists in the committed table**, or the
   words `no defect` — the two honest outcomes. A case is closed by a fixture
   that now holds it, or by a finding that there was nothing to hold.

That is not proof, and this docstring will not pretend it is: a determined
session can still write both. It raises the floor from "delete the sentence" to
"state a section and name a fixture that is really there", and the second-reader
rule covers the rest. What it makes impossible is the failure that actually
happened — a finding going quiet because no tool ever looked at it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from integral.robots import FIXTURES

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDITS_DIR = _REPO_ROOT / "arsenal" / "audits"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T102.json"

# The denominator, a FLOOR and never the count of the day (T100 is the
# precedent). Zero unresolved findings over a directory the glob missed is the
# vacuous pass this whole module exists to refuse, and an audit that lands three
# more cases must not turn it red.
CASES_AT_LEAST = 35

_CASE_RE = re.compile(r"^### +(?P<number>\d+)\. +(?P<heading>.*)$", re.M)


def _sections(text: str) -> list[tuple[str, str, str]]:
    """`(number, heading, body)` for every `### n.` case section in one audit."""
    matches = list(_CASE_RE.finditer(text))
    out = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        out.append((match["number"], match["heading"].strip(), text[match.end() : end]))
    return out


def _committed_fixture_names() -> set[str]:
    return {fixture.name for fixture in FIXTURES}


def _why_uncommitted(heading: str, body: str, fixture_names: set[str]) -> str | None:
    """The reason this case is still owed, or `None` when it is settled."""
    upper = heading.upper()
    if "RESOLVED" in upper:
        section = heading + body
        if "§" not in section:
            return "resolved without citing a section of the spec it was derived from"
        named = any(name in section for name in fixture_names)
        if not named and "no defect" not in section.lower():
            return "resolved without naming a committed fixture or stating that there was no defect"
        return None
    if "DISCREPANCY" in upper:
        return "an open discrepancy: the audit found something and no gate holds it yet"
    return None


def measure(audits_dir: Path = DEFAULT_AUDITS_DIR) -> dict[str, Any]:
    """Count audit cases that found something and are not yet held by a gate."""
    fixture_names = _committed_fixture_names()
    evaluated = 0
    open_cases: list[dict[str, str]] = []
    for path in sorted(audits_dir.glob("*.md")):
        for number, heading, body in _sections(path.read_text(encoding="utf-8")):
            evaluated += 1
            why = _why_uncommitted(heading, body, fixture_names)
            if why is not None:
                open_cases.append(
                    {"audit": path.name, "case": number, "heading": heading, "why": why}
                )
    return {
        "uncommitted_audit_cases": len(open_cases),
        "uncommitted_audit_cases_evaluated": evaluated,
        "uncommitted_audit_cases_evaluated_at_least": CASES_AT_LEAST,
        "gate_status": "measured" if evaluated else "unmeasured",
        "open_cases": open_cases,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    audits_dir: Path = DEFAULT_AUDITS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T102.json`."""
    measured = measure(audits_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T102's gate evidence. Exit 1 while any audit finding is unheld.

    python -m integral.audit_followup [evidence-path]
    """
    positional = [a for a in argv[1:] if not a.startswith("-")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    for case in measured["open_cases"]:
        print(
            f"✗ {case['audit']} case {case['case']}: {case['why']} — {case['heading']}",
            file=sys.stderr,
        )
    print(json.dumps(measured, ensure_ascii=False))
    if measured["uncommitted_audit_cases"]:
        return 1
    # The floor last, and below the finding, for the reason `naming` gives: a
    # real finding outranks a thin denominator. Exit 3 is "nothing was counted",
    # which `make evidence` records and `verify-gates` adjudicates.
    if measured["uncommitted_audit_cases_evaluated"] < CASES_AT_LEAST:
        print(
            f"uncommitted_audit_cases_evaluated: {measured['uncommitted_audit_cases_evaluated']} "
            f"is below the floor of {CASES_AT_LEAST} — zero unheld findings over an audit "
            "directory this thin is not a measurement",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
