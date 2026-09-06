"""T136 — the judgement behind `connector-new`, in the package rather than the skill.

The gate is `connector_probe_misclassifications == 0`, and what it measures is
the one call in that procedure a person cannot make by eye: whether CPython's
`robotparser`, used as the second reader on a board's robots.txt, was
**competent on that particular file**.

That distinction is the whole of `robots-adjudications.yaml`'s `standing`
column. On any robots.txt opening with `Allow: /`, CPython returns the first
matching rule rather than RFC 9309's longest match, so it answers True to every
path and cannot disagree — an "agreement" with it is an agreement with a parser
that could not have refused. `foorilla.com` is exactly that file and
`landing.jobs` is not, and nothing short of running the parser on each tells
them apart.

**Why the logic lives here and the skill's script imports it.** The first draft
put it in `.claude/skills/connector-new/scripts/query_board.py` and had this
module import that file back. `test_nothing_in_the_codebase_executes_a_contributed_parse_module`
refused it, and rightly: `spec_from_file_location` plus `exec_module` is the
machinery that would let a contributed connector ship code, and a gate is not a
reason to introduce it. Inverting the dependency costs nothing and removes the
question — the script is a CLI over this, so the two cannot drift.

**Why it is measured by running rather than by reading.** `T121` is the
standing lesson: three rounds of grepping `verified_gate.sh` for the commands
it should run were defeated first by its own comments and then by an unused
string holding all twelve patterns. So the cases below are real robots.txt
snapshots the connector library already commits, classified by the same
function the script calls.
"""

from __future__ import annotations

import json
import sys
import urllib.robotparser
from pathlib import Path
from typing import Any

import yaml

from integral.robots import USER_AGENT

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T136.json"
LEDGER = _REPO_ROOT / "connectors" / "robots-adjudications.yaml"

#: The verdict for a second reader that ran and answered True to everything.
#: Spelled out rather than returned as a flag because it is what a session
#: writes into the ledger's `reason`, and "ran and could not refuse" and "was
#: never run" are different findings the ledger refuses to conflate.
INCOMPETENT = (
    "RAN AND COULD NOT REFUSE — it answered True to every path, so it cannot "
    "agree with anything. Record `standing: single_parser` with that as the "
    "reason, not `two_parsers_agreed`."
)

#: The client header sets a connector may declare, by name, for the probe to
#: try. Kept in step with `connectors.client_headers`: a set here the engine
#: cannot emit would promise a connector nobody can write.
CLIENTS: dict[str, dict[str, str]] = {
    "none": {},
    "htmx": {"HX-Request": "true", "HX-Target": "mc_1"},
}

#: Floor. A zero over one file says nothing about telling two files apart.
MINIMUM_CASES = 2


def second_reader_verdict(robots_text: str, urls: list[str]) -> str:
    """Classify CPython's parser on one robots.txt. Pure: no network."""
    if not urls:
        return "not run — no path given"
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(robots_text.splitlines())
    verdicts = [parser.can_fetch(USER_AGENT, url) for url in urls]
    if all(verdicts):
        return INCOMPETENT
    return f"competent — refused {verdicts.count(False)} of {len(verdicts)} path(s)"


def _snapshots() -> list[dict[str, Any]]:
    """Ledger rows carrying a committed `robots_txt` — the only rows whose file
    this gate can read without the network."""
    rows = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))["adjudications"]
    return [row for row in rows if row.get("robots_txt")]


def measure() -> dict[str, Any]:
    defects: list[str] = []
    checked = 0
    for row in _snapshots():
        paths = list(row.get("allowed", [])) + list(row.get("second_reader_refused", []))
        if not paths:
            continue
        checked += 1
        origin = f"https://{row['site']}"
        verdict = second_reader_verdict(row["robots_txt"], [origin + p for p in paths])
        incompetent = verdict == INCOMPETENT
        # The ledger's own standing is the expectation. A row claiming two
        # parsers agreed, over a file the second parser cannot refuse on, is
        # the defect that column exists to catch.
        if row["standing"] == "two_parsers_agreed" and incompetent:
            defects.append(
                f"{row['site']}: recorded `two_parsers_agreed`, and the second reader "
                f"answers True to all {len(paths)} path(s) — it could not have agreed"
            )
        if row["standing"] not in ("two_parsers_agreed", "single_parser") and not incompetent:
            defects.append(
                f"{row['site']}: the second reader refuses on this file, so "
                f"`{row['standing']}` understates what was available"
            )
    measured: dict[str, Any] = {
        "connector_probe_misclassifications": len(defects),
        "connector_probe_cases": checked,
        "connector_probe_defects": defects,
        "gate_status": "measured",
    }
    if checked < MINIMUM_CASES:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {checked} committed robots.txt snapshot(s) (floor {MINIMUM_CASES}) — "
            "a zero over one file says nothing about telling two files apart"
        ]
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main() -> int:
    measured = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        for reason in measured.get("reasons", ()):
            print(reason, file=sys.stderr)
        return 3
    return 1 if measured["connector_probe_misclassifications"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
