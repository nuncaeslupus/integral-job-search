"""T66 — the empty market: report a time, never a relaxed constraint.

`status/specs/iterative-sourcing.md` §5.6. The outcome a tool is most tempted to
dress up. When the search has been steered both ways and still returns the same
work, the honest answer is *"it looks like it's not a good day to find jobs — try
again tomorrow or next week"*. The dishonest one is a relaxed hard constraint,
which asks the candidate to want a different job than the one they want.

**"Survived steering in both directions" is read off T65's recorded decisions,
not off T64's proposals.** A proposal is a question; a `ScopeDecision` with
`accepted=True` is the search actually having been re-aimed. So `Cycle.steered_by`
carries the licence that re-aimed that cycle, and `market_is_empty` asks for one
of each direction. A widening the candidate refused proves nothing about the
market — the remedy was offered, never tried.

**It fails closed** (risk IS-6, the euphemism). Every uncertainty returns `False`
— one steering only, a sequence that starts with its first steering and so has no
before to compare against, any cycle after the steering that did improve. `False`
means the tool keeps proposing a change of scope, which is the answer that costs
nothing if wrong. `True` is the terminal one, so it is reached only from evidence.

**Its own module, and not a fourth line in `sourcing_strategy`, for a mechanical
reason**: it needs both T68's `Cycle` and T65's `ScopeDecision`, and
`sourcing_cycles` already imports from `sourcing_strategy` — putting it there
would close an import loop. `make evidence` discovers modules by their `_main`,
so a new one is picked up with no wiring.

**The forbidden move is forbidden by the type, and the word list is the belt.**
`EmptyMarketReport` has no field a scope change fits in, so `extra="forbid"`
rejects one outright; the validator then refuses any *text* naming a step-2
constraint, since the euphemism's natural home is prose. That list is
`CONSTRAINT_FIELD_NAMES` — step 2's own fields, so it cannot drift away from what
the candidate actually pinned — plus the handful of words the surface says them
with. ponytail: a word list is not an intent model, and is not meant to be; the
type is what makes the offer unable to carry a proposal at all.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from pydantic import ValidationError, model_validator

from integral.candidate import CONSTRAINT_FIELD_NAMES
from integral.sourcing_cycles import Cycle, improved
from integral.sourcing_strategy import ScopeAlternative, ScopeDecision, ScopeProposal, Strict

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T66.json"

#: The whole of what may be offered: when to come back. §5.6's sentence names two.
RETRY_TIMES: tuple[str, ...] = ("tomorrow", "next week")

#: What an empty-market report may never name. Step 2's field names, in the words
#: the surface uses for them — hard constraints stay where the candidate put them
#: (§5.8), and scope is the search's aim within them.
#: The candidate-facing words for the same things: a report saying "relax your remote
#: requirement" names `employment_mode` without using the field's name. This list is a
#: net and cannot be complete — free prose always has another phrasing. What is complete
#: is structural: `EmptyMarketReport` has no field a scope change fits, and
#: `retry_options` is a closed set, so the only place a relaxation could hide is
#: `reason`, and this is what watches it.
HARD_CONSTRAINT_TERMS: frozenset[str] = frozenset(
    {name.replace("_", " ") for name in CONSTRAINT_FIELD_NAMES}
    | {"pay floor", "relocate", "permit", "visa"}
    | {"remote", "hybrid", "on-site", "onsite", "in the office", "minimum"}
)

#: The probe has to *reach* an empty market, not merely fail to misreport one — a
#: run where the market was never empty has not tested the rule. Two, so both
#: orders of steering are exercised: widen-then-narrow and narrow-then-widen.
MINIMUM_EMPTY_MARKETS = 2


class EmptyMarketReport(Strict):
    """What the tool may say when the market, not the search, is the problem."""

    reason: str  # what was tried and did not work, in the candidate's terms
    #: A tuple, not a list: `Strict` is frozen, but a frozen model still hands out
    #: a mutable list, so the times could be emptied — or a relaxed constraint
    #: appended — after validation had passed.
    retry_options: tuple[str, ...]  # times to come back, never terms to accept

    @model_validator(mode="after")
    def _it_offers_a_time_and_names_no_constraint(self) -> EmptyMarketReport:
        if not self.reason.strip():
            raise ValueError("an empty-market report with no reason explains nothing")
        if not self.retry_options:
            raise ValueError("a report offering no time to come back offers nothing at all")
        unknown = sorted(set(self.retry_options) - set(RETRY_TIMES))
        if unknown:
            raise ValueError(
                f"{', '.join(unknown)} is not a time to come back — retry_options is a "
                f"closed set ({', '.join(RETRY_TIMES)}), so no phrasing can smuggle a "
                "relaxed constraint in as one"
            )
        said = " ".join([self.reason, *self.retry_options]).lower()
        named = sorted(term for term in HARD_CONSTRAINT_TERMS if term in said)
        if named:
            raise ValueError(
                f"an empty-market report naming {', '.join(named)} is a relaxed hard "
                "constraint wearing the words of a time"
            )
        return self


def market_is_empty(cycles: Sequence[Cycle]) -> bool:
    """Exhaustion that survived both a broadening and a narrowing.

    One stale cycle means look elsewhere. Repeated cycles returning the same
    adverts *after the scope was widened and narrowed* mean the market is the
    problem rather than the search — a diagnosis reached by having tried the
    remedy for the other one and watched it fail.

    `cycles` must run consecutively, for T68's reason: `pairwise` reads its left
    element as "the last search", and out of order the comparison silently
    inverts — a sequence that got worse would read as one that improved.
    """
    numbers = [c.cycle for c in cycles]
    if any(b != a + 1 for a, b in pairwise(numbers)):
        raise ValueError(f"cycles must run consecutively, got {numbers}")

    steered: list[int] = []
    directions: set[str] = set()
    for i, cycle in enumerate(cycles):
        licence = cycle.steered_by
        if licence is not None:
            steered.append(i)
            directions.add(licence.decision)
    if directions != {"widen", "narrow"}:
        return False  # only one remedy tried — the other diagnosis is still open
    if steered[0] == 0:
        return False  # nothing before the first steering to judge it against
    return not any(
        improved(cycle, previous) for previous, cycle in pairwise(cycles[steered[0] - 1 :])
    )


def _steering_order(cycles: Sequence[Cycle]) -> str:
    """What was actually tried, in the order it was tried — both orders are legal."""
    tried = [c.steered_by.decision for c in cycles if c.steered_by is not None]
    seen: list[str] = []
    for direction in tried:
        if direction not in seen:
            seen.append(direction)
    return " the search and then ".join(f"{d}ed" for d in seen) + " it"


def report_empty_market(cycles: Sequence[Cycle]) -> EmptyMarketReport:
    """The only thing the tool may say when the market is empty — a time.

    The return type is the gate: this branch cannot hand back a `ScopeProposal`,
    so an exhausted search has no path out of here that reads as a scope change.
    """
    if not market_is_empty(cycles):
        raise ValueError(
            "the market is not empty — the search has not been steered both ways and "
            "watched to fail, so what is owed is a scope proposal, not a date"
        )
    return EmptyMarketReport(
        reason=(
            "it looks like it is not a good day to find jobs — cycles "
            f"{cycles[0].cycle} to {cycles[-1].cycle} kept returning the same work "
            f"after we {_steering_order(cycles)}"
        ),
        retry_options=RETRY_TIMES,
    )


def _steer(cycle: int, direction: str, about: str) -> ScopeDecision:
    """One accepted decision — T65's licence, which is what re-aims a search."""
    return ScopeDecision(
        session="cse_t66",
        about=about,
        decision=direction,  # type: ignore[arg-type]
        accepted=True,
        cycle=cycle,
        reason="the candidate agreed to try the search this way",
        proposed_alternatives=("narrow:employer", "widen:country"),
        trigger="cycle 1 returned the same adverts it had returned before",
    )


def probe_empty_market() -> dict[str, Any]:
    """Judge four exhausted sequences and count every one answered with a scope change."""
    stuck = [
        Cycle(cycle=1, offers_returned=20, offers_rejected=18),
        Cycle(cycle=2, offers_returned=20, offers_rejected=19),
        Cycle(cycle=3, offers_returned=20, offers_rejected=19),
    ]
    widen = _steer(2, "widen", "location:madrid")
    narrow = _steer(3, "narrow", "employer:acme")
    both_ways = [
        stuck[0],
        stuck[1].model_copy(update={"steered_by": widen}),
        stuck[2].model_copy(update={"steered_by": narrow}),
    ]
    the_other_order = [
        stuck[0],
        stuck[1].model_copy(update={"steered_by": _steer(2, "narrow", "employer:acme")}),
        stuck[2].model_copy(update={"steered_by": _steer(3, "widen", "location:madrid")}),
    ]
    one_way_only = both_ways[:2]
    the_narrowing_worked = [
        *both_ways[:2],
        Cycle(cycle=3, offers_returned=20, offers_rejected=4, steered_by=narrow),
    ]

    failures: list[str] = []
    reported: list[EmptyMarketReport] = []
    tried_both = (("widen then narrow", both_ways), ("narrow then widen", the_other_order))
    for name, sequence in tried_both:
        report = report_empty_market(sequence)
        reported.append(report)
        said = " ".join([report.reason, *report.retry_options]).lower()
        named = sorted(term for term in HARD_CONSTRAINT_TERMS if term in said)
        if named:
            failures.append(f"the {name} report offered a relaxed {', '.join(named)}")
        if set(report.retry_options) - set(RETRY_TIMES):
            failures.append(f"the {name} report offered something other than a time")

    # The diagnosis must not be reachable early, either: an empty market declared
    # before both remedies failed is the euphemism this gate is named after.
    failures += [
        f"the market was declared empty {why}"
        for why, sequence in (
            ("after one direction only", one_way_only),
            ("after a steering that worked", the_narrowing_worked),
            ("from a single stale cycle", stuck[:1]),
            ("with no steering at all", stuck),
        )
        if market_is_empty(sequence)
    ]

    # Negative control 1: the relaxed constraint, offered in the words of a time.
    try:
        EmptyMarketReport(
            reason="it looks like it is not a good day to find jobs",
            retry_options=("tomorrow", "or we could lower your salary floor"),
        )
    except ValidationError:
        relaxed_rejected = True
    else:
        relaxed_rejected = False
        failures.append("a report offering to relax a hard constraint was accepted")

    # Negative control 2: the scope change smuggled in as a field of its own.
    try:
        EmptyMarketReport(
            reason="it looks like it is not a good day to find jobs",
            retry_options=RETRY_TIMES,
            proposal=ScopeProposal(  # type: ignore[call-arg]
                direction="narrow",
                facet="employer",
                reason="we could read only Acme",
                alternatives=(
                    ScopeAlternative(
                        direction="widen", facet="country", reason="or look further out"
                    ),
                ),
            ),
        )
    except ValidationError:
        proposal_field_rejected = True
    else:
        proposal_field_rejected = False
        failures.append("an empty-market report carrying a scope proposal was accepted")

    return {
        "exhausted_searches_reported_as_a_scope_change": len(failures),
        "sequences_judged": 6,
        "empty_markets_reported": len(reported),
        "retry_times_offered": sorted({when for r in reported for when in r.retry_options}),
        "relaxed_constraint_rejected": relaxed_rejected,
        "scope_change_field_rejected": proposal_field_rejected,
        "failures": failures,
    }


def write_market_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T66's measurement to `evidence`, and return it."""
    measured = probe_empty_market()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_market [path]` → T66's gate evidence.

    Exit 3 when the probe never reached an empty market, 1 on any violation, 0
    otherwise.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_market_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["empty_markets_reported"] < MINIMUM_EMPTY_MARKETS:
        print(
            f"only {measured['empty_markets_reported']} empty market(s) were reported "
            f"(floor {MINIMUM_EMPTY_MARKETS}) — a probe where the market was never empty "
            "reports zero scope changes by never having had the chance",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
