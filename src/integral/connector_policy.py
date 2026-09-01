"""T99 — a refusal that is ours, not the board's, needs an owner's decision.

`connectors/ruled-out.yaml` separates two kinds of ruling, and the separation
is the file's own idea: `robots_refused` is what the board said, adjudicated by
the audited RFC 9309 matcher, and `policy_refused` is what **we** decided about
a board the matcher allows. Collapsing them "would let a judgement call be read
later as a measurement, which is the one thing this file exists to prevent".

That is right, and it was not enough. A judgement kept apart from a measurement
is still a judgement with nobody's name on it. `policy_refused` grew its first
entry — remoteok.com — written by the implementing session on its own reading
of the operator's intent, and the owner had already stated the opposite
position in the same session:

    It is the user who will use the scraper, not you, and most of them did not
    allow massive scraping for AI, but they allow it for making some searches.

The ledger's own header says the same thing two hundred lines earlier: *"those
bans target bulk training crawls; a connector is one candidate's search."* So
the file contradicted its own stated rule, and nothing could see it, because
**nothing read this file** — the header said so outright. This module is the
first reader.

**The defect is the same whichever way the disagreement resolves.** A policy
that silently removes boards from a candidate's reach needs a decision recorded
next to it, saying whose call it was and when. So what is measured here is the
record, not the verdict:

* who decided, and it must be the **owner** — a session recording its own
  judgement in that field would satisfy a check that only asked whether the
  field was filled in, which is this task's defect wearing the fix's clothes;
* **when**, because a judgement made in one session reads a month later exactly
  like a settled position;
* whether the refusal is about **volume or access**, which are different
  refusals with different consequences: one throttles a connector, the other
  deletes a board from the candidate's reach;
* and, for a board the matcher allows, the **rule cited** — since the citation
  is the whole of the argument.

What this does not do: decide whether any particular board should be fetched.
That is the owner's, and this module's only claim is that the answer is written
down where it can be argued with.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = _REPO_ROOT / "connectors" / "ruled-out.yaml"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T99.json"

#: The one value that counts as a decision. Anything else — a session, a
#: reviewer, a bot — is a judgement being recorded, not a call being made.
OWNER = "owner"

#: What a refusal can be about. `volume` throttles how much a connector may
#: fetch; `access` removes the board. The owner's stated position distinguishes
#: exactly these two, and the first entry written did not.
REFUSAL_KINDS = ("volume", "access")


class PolicyLedgerError(Exception):
    """The ledger could not be read — never silently a clean run."""


@dataclass(frozen=True)
class PolicyRefusal:
    """One `policy_refused` row, read for the record it carries."""

    site: str
    refuses: str
    robots_verdict: str
    rule_cited: str
    decided_by: str
    decided_on: date | None
    decision: str

    @classmethod
    def from_mapping(cls, payload: Any) -> PolicyRefusal:
        """Read one row, tolerating everything — the reading is the check.

        A missing key becomes an empty value rather than an exception, so a
        malformed row is *counted* instead of aborting the run over the rows
        after it. A ledger that stops at its first bad entry reports a smaller
        number than the truth.
        """
        if not isinstance(payload, dict):
            return cls("", "", "", "", "", None, "")
        return cls(
            site=str(payload.get("site") or "").strip(),
            refuses=str(payload.get("refuses") or "").strip(),
            robots_verdict=str(payload.get("robots_verdict") or "").strip(),
            rule_cited=str(payload.get("rule_cited") or "").strip(),
            decided_by=str(payload.get("decided_by") or "").strip(),
            decided_on=_as_date(payload.get("decided_on")),
            decision=str(payload.get("decision") or "").strip(),
        )

    def problems(self) -> list[str]:
        """Everything missing from this row's record. Empty is the goal."""
        where = self.site or "(a row naming no site)"
        found: list[str] = []
        if not self.site:
            found.append(
                "a policy refusal naming no site cannot be argued with, retested "
                "or overturned"
            )
        if self.decided_by != OWNER:
            found.append(
                f"{where}: decided_by is {self.decided_by or 'unset'!r}, not {OWNER!r} — "
                "a policy refusal is the owner's call, and a session recording its own "
                "judgement here is the defect this check exists for"
            )
        if self.decided_on is None:
            found.append(f"{where}: no decided_on date — an undated call reads as settled")
        if not self.decision:
            found.append(f"{where}: no decision text — nothing says what was actually decided")
        if self.refuses not in REFUSAL_KINDS:
            found.append(
                f"{where}: refuses is {self.refuses or 'unset'!r}; it must say "
                f"{' or '.join(REFUSAL_KINDS)} — throttling a connector and deleting a "
                "board are different refusals"
            )
        if self.robots_verdict == "allowed" and not self.rule_cited:
            found.append(
                f"{where}: allowed by robots and refused with no rule cited — the "
                "citation is the whole of the argument"
            )
        return found


def _as_date(value: Any) -> date | None:
    """A canonical `YYYY-MM-DD` date, or `None`. PyYAML parses a bare date.

    Two shapes that look like dates are refused, because this ledger is read
    years later and a record that is not canonical is not the same record.
    A `datetime` is a `date` subtype, so a YAML timestamp passes an
    `isinstance` check written for a day; and `strptime` accepts an unpadded
    `2026-8-1`. So the timestamp is rejected before the subtype check, and a
    string is kept only when it round-trips through `date.isoformat()`.
    """
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    try:
        parsed = datetime.strptime(trimmed, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed.isoformat() == trimmed else None


def refusals(ledger: Path = DEFAULT_LEDGER_PATH) -> list[PolicyRefusal]:
    """Every `policy_refused` row in the ledger."""
    try:
        payload = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PolicyLedgerError(f"{ledger}: could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise PolicyLedgerError(f"{ledger}: is not a mapping")
    rows = payload.get("policy_refused") or []
    if not isinstance(rows, list):
        raise PolicyLedgerError(f"{ledger}: policy_refused is not a list")
    return [PolicyRefusal.from_mapping(row) for row in rows]


#: Rows that are malformed by construction, put through the same reader on
#: every run. One live entry is a thin denominator and a rule true of one row
#: is nearly a rule true of nothing — and each control names a way the record
#: could look complete while saying nothing.
MALFORMED_CONTROLS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "no decision at all",
        {"site": "a.test", "refuses": "access", "robots_verdict": "allowed",
         "rule_cited": "x"},
    ),
    (
        "the implementing session recorded as the decider",
        {"site": "b.test", "refuses": "access", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "implementing session",
         "decided_on": "2026-08-31", "decision": "the intent is legible"},
    ),
    (
        "an owner decision with no date",
        {"site": "c.test", "refuses": "volume", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "owner", "decision": "throttle it"},
    ),
    (
        "volume and access not distinguished",
        {"site": "d.test", "robots_verdict": "allowed", "rule_cited": "x",
         "decided_by": "owner", "decided_on": "2026-08-31", "decision": "no"},
    ),
    (
        "allowed by robots, refused with no rule cited",
        {"site": "e.test", "refuses": "access", "robots_verdict": "allowed",
         "decided_by": "owner", "decided_on": "2026-08-31", "decision": "no"},
    ),
    (
        "a row naming no board",
        {"refuses": "access", "robots_verdict": "allowed", "rule_cited": "x",
         "decided_by": "owner", "decided_on": "2026-08-31", "decision": "no"},
    ),
    (
        "a YAML timestamp where the day was the record",
        {"site": "f.test", "refuses": "access", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "owner",
         "decided_on": datetime(2026, 8, 31, 14, 30), "decision": "no"},
    ),
    (
        "an unpadded date that is not what the ledger says it holds",
        {"site": "g.test", "refuses": "volume", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "owner", "decided_on": "2026-8-1",
         "decision": "throttle it"},
    ),
)


def measure(
    ledger: Path = DEFAULT_LEDGER_PATH,
    *,
    controls: tuple[tuple[str, dict[str, Any]], ...] = MALFORMED_CONTROLS,
) -> dict[str, Any]:
    """T99's gate: `policy_refusals_without_an_owner_decision`.

    The live rows and the constructed controls go through one reader. A
    control that comes back clean is counted as a violation of its own,
    because the only way that happens is the check having been lost.
    """
    live = refusals(ledger)
    violations = [problem for refusal in live for problem in refusal.problems()]
    incomplete = sum(1 for refusal in live if refusal.problems())

    accepted = [
        name
        for name, payload in controls
        if not PolicyRefusal.from_mapping(payload).problems()
    ]
    violations += [f"accepted a malformed control: {name}" for name in accepted]

    checked = len(live) + len(controls)
    return {
        "policy_refusals_without_an_owner_decision": incomplete + len(accepted),
        # Both names, as every gate in this increment carries.
        "policy_refusals_without_an_owner_decision_evaluated": checked,
        "policy_refusals_checked": checked,
        "live_refusals": len(live),
        "controls_checked": len(controls),
        "gate_status": "measured" if checked else "unmeasured",
        "sites": sorted(r.site for r in live if r.site),
        "violations": violations,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, ledger: Path = DEFAULT_LEDGER_PATH
) -> dict[str, Any]:
    """Measure and record `status/evidence/T99.json`."""
    measured = measure(ledger)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connector_policy [path]` → T99's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    try:
        measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    except PolicyLedgerError as exc:
        # Exit 3, not 1: nothing was read, so nothing passed and nothing failed.
        print(f"connector_policy: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(measured, ensure_ascii=False))
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    if measured["policy_refusals_without_an_owner_decision"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            "policy_refusals_without_an_owner_decision: UNMEASURED — no refusal was "
            "read. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
