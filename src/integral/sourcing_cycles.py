"""T68 — the cycle improves, or it says why.

`status/specs/iterative-sourcing.md` §1, the `cycle_rejection_rate` row:

> strictly decreasing across a candidate's cycles, or the cycle proposes a scope
> change. Each search must be better than the last. Where it is not, that *is*
> the exhaustion condition — so this metric and the trigger are the same
> measurement read twice.

T62 read it the first way, as dedup: *are we finding the same jobs again?* This
module reads it the second way, as outcome: *are we finding better ones?* The
two are deliberately not folded together. A cycle can return twenty adverts none
of which were seen before and all of which the candidate rejects — new, and no
better — and dedup cannot see that. Nor is the answer to make T62 read
rejections: §5.2 settled its form as dedup precisely so it works on cycle two,
before the candidate has rejected anything at all.

**Improving means strictly fewer rejections per offer than this candidate's own
previous cycle.** Three consequences, each of them a test:

- *Strictly.* A flat rate is not an improvement. A search that keeps returning
  work at the same rejection rate has stopped getting better, and the point of
  the row is that standing still is the condition, not only going backwards.
- *The first cycle is never counted.* It has nothing to be better than.
- *A cycle that returned nothing has no rate at all* — `rejection_rate` is
  `None`, not `0.0`. This is T62's empty-return trap in its second form: zero
  rejections out of zero offers would otherwise read as the best cycle the
  candidate has ever had.

**Within-subject only, and the API is what enforces it.** One sequence in — one
candidate's own cycles, in order — and no identifier for whose they are. There
is no store, no module state, and no parameter a second candidate could be
passed through, so the cross-candidate comparison §5.8 rules out is not
something a caller could make by mistake. Judging somebody else's cycles in
between two judgements of these ones changes neither answer.

**What the tool must say instead is T64's, not this module's.** Where a cycle
did not improve, `Cycle.proposal` carries a `ScopeProposal` — already
symmetric by construction, already carrying its reason — and this module only
asks whether one is there. Two gates, one object: T64 makes the proposal
honest, T68 makes it obligatory.

It writes its own evidence file rather than adding a third line to
`sourcing_strategy._main`, for the mechanical reason T63 split out for: `make
evidence` runs one `_main` per module, and that one already writes two.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from integral.sourcing_strategy import ScopeAlternative, ScopeDecision, ScopeProposal, Strict

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T68.json"

#: The probe must contain at least this many cycles that did *not* improve, or
#: it has not exercised the rule: a sequence where every search got better
#: reports zero unproposed regressions by never having regressed.
MINIMUM_NON_IMPROVING = 2


class Cycle(Strict):
    """One sourcing cycle in one candidate's own sequence."""

    cycle: int = Field(ge=1)  # 1-based, within this candidate
    offers_returned: int = Field(ge=0)
    offers_rejected: int = Field(ge=0)
    #: What the tool said when this cycle did not improve. `None` is correct and
    #: usual — the tool does not speak when the search is working.
    proposal: ScopeProposal | None = None
    #: The scope change the candidate agreed to before this cycle ran — T65's
    #: recorded licence, and what tells §5.6 the search was actually re-aimed
    #: rather than merely asked about. `None` is the usual case: most cycles
    #: search the scope the last one did.
    steered_by: ScopeDecision | None = None

    @model_validator(mode="after")
    def _the_counts_hold_together(self) -> Cycle:
        if self.offers_rejected > self.offers_returned:
            raise ValueError("more offers were rejected than the cycle returned")
        if self.steered_by is not None and not self.steered_by.accepted:
            raise ValueError("a refused decision steered nothing — §5.5, a refusal licenses none")
        if self.steered_by is not None and self.steered_by.cycle > self.cycle:
            raise ValueError(
                f"cycle {self.cycle} cannot have been steered by a decision taken in "
                f"cycle {self.steered_by.cycle}"
            )
        return self

    @property
    def rejection_rate(self) -> float | None:
        """`None` when the cycle returned nothing — there is no rate to compare."""
        if not self.offers_returned:
            return None
        return self.offers_rejected / self.offers_returned


def improved(cycle: Cycle, previous: Cycle) -> bool:
    """Strictly fewer rejections per offer than the candidate's previous cycle.

    A cycle with no rate — either side of the pair — did not improve. That is
    the honest reading of "no rate to compare", and the generous one would let
    an empty return count as the best cycle in the sequence.
    """
    rate, before = cycle.rejection_rate, previous.rejection_rate
    if rate is None or before is None:
        return False
    return rate < before


def _did_not_improve(cycle: Cycle, previous: Cycle) -> str:
    if cycle.rejection_rate is None:
        return f"cycle {cycle.cycle} returned nothing, so it improved on nothing"
    if previous.rejection_rate is None:
        return f"cycle {cycle.cycle} follows a cycle that returned nothing to improve on"
    return (
        f"cycle {cycle.cycle} rejected {cycle.rejection_rate:.0%} against "
        f"cycle {previous.cycle}'s {previous.rejection_rate:.0%}"
    )


def cycles_neither_improving_nor_proposing(cycles: Sequence[Cycle]) -> list[str]:
    """One candidate's cycles, in order: every one that got no better and said nothing.

    The gate is that this is empty. Note the single argument: there is no
    second candidate to pass, which is how §5.8's "cross-candidate anything" is
    kept out — by there being nothing to call.

    `cycles` must run consecutively — 3 then 4 then 5, no gaps and no
    reordering — because `pairwise` reads its left element as "the last
    search", and "each search must be better than the last" is a claim about
    the one immediately before. Out of order, the comparison silently inverts:
    a regression handed over as [3, 1] reads as an improvement and the gate
    passes on a cycle that got worse. It need not start at 1; judging a later
    window of one candidate's cycles is a fair question, and only adjacency is
    load-bearing.
    """
    numbers = [c.cycle for c in cycles]
    if any(b != a + 1 for a, b in pairwise(numbers)):
        raise ValueError(f"cycles must run consecutively, got {numbers}")
    return [
        f"{_did_not_improve(cycle, previous)} and proposed no change of scope"
        for previous, cycle in pairwise(cycles)
        if not improved(cycle, previous) and cycle.proposal is None
    ]


def _proposal(direction: Literal["widen", "narrow"], facet: str, reason: str) -> ScopeProposal:
    other: Literal["widen", "narrow"] = "narrow" if direction == "widen" else "widen"
    return ScopeProposal(
        direction=direction,
        facet=facet,
        reason=reason,
        alternatives=(
            ScopeAlternative(
                direction=other,
                facet="seniority",
                reason=f"or go the other way and {other} on seniority instead",
            ),
        ),
    )


def probe_cycles() -> dict[str, Any]:
    """Walk one candidate's five cycles and count every silent non-improvement."""
    mine = [
        # Cycle 1 is the baseline: nothing to be better than, so never counted.
        Cycle(cycle=1, offers_returned=20, offers_rejected=19),
        # Better, and silent — the tool does not speak when the search is working.
        Cycle(cycle=2, offers_returned=20, offers_rejected=12),
        # Worse than cycle 2, and says so.
        Cycle(
            cycle=3,
            offers_returned=20,
            offers_rejected=14,
            proposal=_proposal(
                "widen",
                "country",
                "cycle 3 rejected more than cycle 2 did — we could look outside Spain",
            ),
        ),
        # Flat against cycle 3. Standing still is not improving, and it says so too.
        Cycle(
            cycle=4,
            offers_returned=20,
            offers_rejected=14,
            proposal=_proposal(
                "narrow",
                "employer",
                "cycle 4 landed exactly where cycle 3 did — shall we read only the two "
                "employers whose adverts you finished?",
            ),
        ),
        Cycle(cycle=5, offers_returned=20, offers_rejected=6),
    ]
    stuck = cycles_neither_improving_nor_proposing(mine)
    pairs = list(pairwise(mine))
    non_improving = [cycle for previous, cycle in pairs if not improved(cycle, previous)]

    # Not the gate's count, but worth failing on: a tool that proposes a change
    # of scope while the search is getting better is talking over a result.
    other = [
        f"cycle {cycle.cycle} improved and proposed a scope change anyway"
        for previous, cycle in pairs
        if improved(cycle, previous) and cycle.proposal is not None
    ]

    # Negative control: the rule has to bite, or the count is zero by nothing
    # ever having tried it.
    regressed = [
        Cycle(cycle=1, offers_returned=20, offers_rejected=10),
        Cycle(cycle=2, offers_returned=20, offers_rejected=18),
    ]
    detected = bool(cycles_neither_improving_nor_proposing(regressed))
    if not detected:
        stuck.append("a cycle that got worse and proposed nothing went uncounted")

    return {
        "cycles_neither_improving_nor_proposing": len(stuck),
        "cycles_judged": len(mine),
        "non_improving_cycles": len(non_improving),
        "rejection_rates": [cycle.rejection_rate for cycle in mine],
        "proposals_made": sum(1 for cycle in mine if cycle.proposal is not None),
        "unproposed_regression_detected": detected,
        "failures": stuck + other,
    }


def write_cycle_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T68's measurement to `evidence`, and return it."""
    measured = probe_cycles()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_cycles [path]` → T68's gate evidence.

    Exit 3 when the probe exercised too little to be trusted, 1 on any
    violation, 0 otherwise.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    if "--bulk" in argv[1:]:
        # T94's gate names `python -m integral.sourcing_cycles --bulk`, because
        # the bulk pass is what makes a cycle's volume tractable. It is its own
        # module — `make evidence` discovers and runs it directly through
        # `repo_gate --list-evidence-modules` — so this is an alias for the
        # gate's convenience, not a second implementation.
        from integral.bulk_filter import _main as bulk_main

        return bulk_main([argv[0], *positional])
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_cycle_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["non_improving_cycles"] < MINIMUM_NON_IMPROVING:
        print(
            f"only {measured['non_improving_cycles']} cycle(s) failed to improve "
            f"(floor {MINIMUM_NON_IMPROVING}) — a probe whose every search got better "
            "has not tested the rule that the others must speak",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
