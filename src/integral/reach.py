"""The reach gate (T201, issue #550): a fixed advert is not a reachable one.

`candidate.filter_hard_constraints` decides which offers survive a
candidate's stated constraints; this module does not re-test that function's
*shape* (`candidate.py`'s own T24 gate already does, exhaustively) — it pins
the *outcome* issue #550 describes, so a future change to the filter cannot
silently reopen either hole without turning this gate red.

The rule the issue states: reach is `remote OR inside a commutable region`,
per candidate — never "the board is in the right country". Country is
necessary for work authorisation, never sufficient for reach.

Three candidates, each isolating one check, so reverting any one of them
moves the metric rather than being answered by a sibling guard first:

  A. ES, commutes to Barcelona only, reach remote+commute (#550's candidate)
     1. remote                                  -> presented
     2. on site in Barcelona                    -> presented
     3. on site in Kraków (PL), ad's own
        `requires_relocation` left false        -> NOT presented
     4. on site in ES, region never stated      -> NOT presented (#547's
                                                   `unplaced`, not rejected)
     5. on site in Madrid                       -> NOT presented — the 45
                                                   Madrid vacancies #550 names
     6. hybrid in Madrid                        -> NOT presented
  B. ES, on site anywhere in ES, will not relocate, reach never stated
     7. on site in Kraków, flag left false      -> NOT presented (the
                                                   relocation check alone)
     8. on site in Madrid                       -> presented (control: the
                                                   rule must not over-refuse)
  C. ES, on site anywhere in ES, reach remote+commute, relocation unstated
     9. on site in Kraków, flag left false      -> NOT presented (the
                                                   reach check alone)
    10. on site in Madrid                       -> presented (control)

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
    Relocation,
    filter_hard_constraints,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T201.json"


def _candidate() -> CandidateConstraints:
    """Candidate A: the one #550 measured against — Barcelona-commuting, ES-based."""
    return CandidateConstraints(
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        ),
        reach=Reach(state="stated", modes=("remote", "commute")),
    )


def _anywhere_in_es() -> Location:
    return Location(state="stated", country="ES", accepts_onsite_in_country=True)


def _offer(offer_id: str, **overrides: Any) -> OfferFacts:
    base: dict[str, Any] = {"offer_id": offer_id, "country": "ES", "delivery": "onsite"}
    base.update(overrides)
    return OfferFacts(**base)


def _cases() -> dict[str, tuple[CandidateConstraints, list[tuple[OfferFacts, bool]]]]:
    """Per candidate: each offer, and whether it is inside remote-or-commutable
    range per the rule in the module docstring."""
    krakow = _offer("krakow-onsite", country="PL", requires_relocation=False)
    madrid = _offer("madrid-onsite", region="Madrid")
    return {
        "A": (
            _candidate(),
            [
                (_offer("remote-role", delivery="remote"), True),
                (_offer("barcelona-onsite", region="Barcelona"), True),
                (krakow, False),
                (_offer("region-unstated-onsite"), False),
                (madrid, False),
                (_offer("madrid-hybrid", delivery="hybrid", region="Madrid"), False),
            ],
        ),
        "B": (
            CandidateConstraints(
                location=_anywhere_in_es(),
                relocation=Relocation(state="stated", willingness="no"),
            ),
            [(krakow, False), (madrid, True)],
        ),
        "C": (
            CandidateConstraints(
                location=_anywhere_in_es(),
                reach=Reach(state="stated", modes=("remote", "commute")),
            ),
            [(krakow, False), (madrid, True)],
        ),
    }


def probe_reach() -> dict[str, Any]:
    """Run every fixture and report each offer presented outside
    remote-or-commutable range, and each one wrongly withheld from it."""
    wrongly_presented: list[str] = []
    wrongly_withheld: list[str] = []
    fixtures = 0
    for case, (candidate, rows) in _cases().items():
        result = filter_hard_constraints(candidate, [offer for offer, _ in rows])
        for offer, in_range in rows:
            fixtures += 1
            presented = offer.offer_id in result.surviving
            if presented and not in_range:
                wrongly_presented.append(f"{case}/{offer.offer_id}")
            if in_range and not presented:
                wrongly_withheld.append(f"{case}/{offer.offer_id}")

    return {
        "offers_presented_outside_every_commutable_region_and_not_remote": len(wrongly_presented),
        "offers_wrongly_withheld_from_range": len(wrongly_withheld),
        "fixtures_checked": fixtures,
        "wrongly_presented": sorted(wrongly_presented),
        "wrongly_withheld": sorted(wrongly_withheld),
    }


#: Zero slack — exactly the fixture set the module docstring names.
MINIMUM_FIXTURES = 10


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
