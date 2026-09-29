"""The reach gate (T201, issue #550): a fixed advert is not a reachable one.

`candidate.filter_hard_constraints` decides which offers survive a
candidate's stated constraints; this module does not re-test that function's
*shape* (`candidate.py`'s own T24 gate already does, exhaustively) — it pins
the *outcome* issue #550 describes, so a future change to the filter cannot
silently reopen either hole without turning this gate red.

The rule the issue states: reach is `remote OR inside a commutable region`,
per candidate — never "the board is in the right country". Country is
necessary for work authorisation, never sufficient for reach. One candidate
(Barcelona-commuting, will not relocate), four offers, one shape each:

  1. remote                                    -> must be presented
  2. on site, inside the candidate's own
     commutable region                          -> must be presented
  3. on site, a different country, the ad's
     own `requires_relocation` left false
     (hole 2 / PR #565's F5 — a country match
     is not a reach match)                      -> must NOT be presented
  4. on site, the candidate's own country,
     but the ad never states which region
     (hole 1 — an unread region used to be
     accepted by default)                       -> must NOT be presented, and
                                                     must not be rejected either:
                                                     #547's `unplaced`

Expected verdicts are derived from the issue text above, not from running the
filter — a gate written by reading its own subject's code would only ever
re-confirm what that code already does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from integral.candidate import (
    CandidateConstraints,
    Location,
    OfferFacts,
    Reach,
    filter_hard_constraints,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T201.json"


def _candidate() -> CandidateConstraints:
    """The candidate #550 measured against: Barcelona-commuting, ES-based."""
    return CandidateConstraints(
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        ),
        reach=Reach(state="stated", modes=("remote", "commute")),
    )


def _offer(offer_id: str, **overrides: Any) -> OfferFacts:
    base: dict[str, Any] = {"offer_id": offer_id, "country": "ES", "delivery": "onsite"}
    base.update(overrides)
    return OfferFacts(**base)


def probe_reach() -> dict[str, Any]:
    """Run the four fixture shapes and report every offer presented outside
    remote-or-commutable range, and every one wrongly withheld from it."""
    remote = _offer("remote-role", delivery="remote")
    commutable = _offer("barcelona-onsite", region="Barcelona")
    foreign_onsite = _offer("krakow-onsite", country="PL", requires_relocation=False)
    unplaced = _offer("region-unstated-onsite")  # country=ES, no region given

    # True means "inside remote-or-commutable range" per the rule above.
    in_range = {
        remote.offer_id: True,
        commutable.offer_id: True,
        foreign_onsite.offer_id: False,
        unplaced.offer_id: False,
    }

    result = filter_hard_constraints(_candidate(), [remote, commutable, foreign_onsite, unplaced])

    wrongly_presented = sorted(offer_id for offer_id in result.surviving if not in_range[offer_id])
    wrongly_withheld = sorted(
        offer_id
        for offer_id, reachable in in_range.items()
        if reachable and offer_id not in result.surviving
    )

    return {
        "offers_presented_outside_every_commutable_region_and_not_remote": len(wrongly_presented),
        "offers_wrongly_withheld_from_range": len(wrongly_withheld),
        "fixtures_checked": len(in_range),
        "wrongly_presented": wrongly_presented,
        "wrongly_withheld": wrongly_withheld,
    }


#: Zero slack — exactly the fixture set the module docstring names.
MINIMUM_FIXTURES = 4


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure the reach fixture and record it."""
    measured = probe_reach()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.reach [path]` -> T201's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["fixtures_checked"] < MINIMUM_FIXTURES:
        # A pass over nothing is not a pass — see every other T2x gate module.
        print(
            f"only {measured['fixtures_checked']} fixtures were checked (floor {MINIMUM_FIXTURES})",
            file=sys.stderr,
        )
        return 3
    for offer_id in measured["wrongly_presented"]:
        print(f"presented outside remote-or-commutable range: {offer_id}", file=sys.stderr)
    for offer_id in measured["wrongly_withheld"]:
        print(f"wrongly withheld from remote-or-commutable range: {offer_id}", file=sys.stderr)
    return 1 if measured["wrongly_presented"] or measured["wrongly_withheld"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
