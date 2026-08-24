"""Sourcing strategy — when a cycle has stopped finding work, and what may be offered.

T62 is the measurement (`§5.2`); T64 is the shape of what the tool may then say
(`§5.4`). They share a module because they are the two halves of one moment: a
cycle judged exhausted is the only thing that licenses a scope proposal.

## T62 — exhaustion: judging that a cycle has stopped finding anything new


`status/specs/iterative-sourcing.md` §5.2 settles the form as **dedup**, not
preference: *"we are finding the same jobs again."* No fitted weights, no
rejection history, nothing the candidate has to have done first — which is why
it works on cycle two, when nothing has been learned yet.

Two decisions carry the whole of the gate, `exhaustion_triggers_without_a_reason`.

**A reason is part of the trigger, not commentary on it.** `Exhaustion` refuses
to be constructed with `exhausted` set and an empty `reason`, so a reasonless
trigger is a `ValidationError` rather than a row somebody later has to explain
to a candidate. The measurement's negative control constructs exactly that and
records that it was rejected; without it the count would be zero because nothing
ever tried, which is a pass over an empty probe rather than over a working rule.

**A cycle that returned nothing is exhausted for a different reason.** Its
`repeat_share` is `0.0` — there is nothing to divide — and 0.0 is also what a
perfectly healthy cycle of all-new offers reads. The two are told apart by
`reason`, never by the share, so the reason for an empty return names the empty
return and does not mention repetition.

`§5.3`'s trigger kind — `exhausted` beside `stale` in `integral.freshness` — is
T63's, not this module's. This measures; nothing here re-opens a step.

## T64 — the scope proposal: symmetric by construction

`scope_proposals_offering_only_narrowing == 0` is enforced by the type and not
by the skill's prose, because prose is what drifts. A `ScopeProposal` cannot be
built without an alternative pointing the other way, so the tool has no way to
ask *"shall we focus on US companies?"* without in the same breath offering the
candidate somewhere wider to go.

**Alternatives are leaves, and that is a deliberate call.** §5.4 writes the
field as `list[ScopeProposal]`, but a recursive form with a mandatory non-empty
list has no base case: building one proposal would require building another,
without end. So the base case is its own type — `ScopeAlternative`, the same
three fields without the list — and the nesting stops at depth one because
nothing deeper is expressible, rather than because a validator counted. That
also matches what the surface actually does: the tool offers one question and
the ways out of it, not a tree the candidate has to navigate.

The negative control does for this what T62's does for the reason rule: it
attempts the all-narrowing proposal the type forbids and records that it was
rejected, so a count of zero cannot mean nothing ever tried.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T62.json"
SCOPE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T64.json"

#: A cycle is exhausted when this share of what it returned was already seen. Chosen by
#: common sense and not by evidence: there is no cycle to tune against yet, and a tuned
#: number pretending to be evidence is worse than an honest guess that says so. Revisit
#: once a real candidate has run four or more cycles.
EXHAUSTION_REPEAT_SHARE = 0.8

#: The probe has to fire the rule, not merely fail to break it — a run that
#: triggered nothing would report zero reasonless triggers by never having one.
MINIMUM_TRIGGERS = 2

#: The scope probe has to *offer* something, not merely fail to offer a bad
#: thing — a run that proposed nothing would report zero one-way proposals by
#: never having opened its mouth. Two, because one of each direction is the
#: smallest set that shows the type is not simply refusing everything.
MINIMUM_PROPOSALS = 2


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Exhaustion(Strict):
    """Why a sourcing cycle is judged to have stopped finding anything new."""

    cycle: int = Field(ge=1)  # 1-based, within this candidate
    offers_returned: int = Field(ge=0)
    offers_already_seen: int = Field(ge=0)  # deduped against the candidate's whole
    # tree, purged tombstones included — an ad the search keeps re-finding after
    # it was purged is the definition of stuck.
    repeat_share: float = Field(ge=0.0, le=1.0)
    exhausted: bool
    reason: str

    @model_validator(mode="after")
    def _the_measurement_holds_together(self) -> Exhaustion:
        if self.offers_already_seen > self.offers_returned:
            raise ValueError("more offers were already seen than the cycle returned")
        expected = self.offers_already_seen / self.offers_returned if self.offers_returned else 0.0
        if not math.isclose(self.repeat_share, expected, abs_tol=1e-9):
            raise ValueError(f"repeat_share {self.repeat_share} is not {expected} for these counts")
        if self.exhausted and not self.reason.strip():
            raise ValueError("an exhaustion with no reason is a violation, not a trigger")
        return self


def judge_cycle(*, cycle: int, offers_returned: int, offers_already_seen: int) -> Exhaustion:
    """Judge one cycle's return against `EXHAUSTION_REPEAT_SHARE`."""
    share = offers_already_seen / offers_returned if offers_returned else 0.0
    if offers_returned == 0:
        reason = f"cycle {cycle} returned no offers at all — the search found nothing to dedupe"
    elif share >= EXHAUSTION_REPEAT_SHARE:
        reason = (
            f"cycle {cycle} returned {offers_returned} offers and "
            f"{offers_already_seen} were already seen — a repeat share of "
            f"{share:.0%}, at or above the {EXHAUSTION_REPEAT_SHARE:.0%} threshold"
        )
    else:
        reason = ""
    return Exhaustion(
        cycle=cycle,
        offers_returned=offers_returned,
        offers_already_seen=offers_already_seen,
        repeat_share=share,
        exhausted=bool(reason),
        reason=reason,
    )


class ScopeAlternative(Strict):
    """A way the search could change instead — the base case of §5.4's list.

    Deliberately without an `alternatives` field of its own: that is what stops
    the nesting at depth one and gives the recursive form a base case it could
    not otherwise have.
    """

    direction: Literal["widen", "narrow"]
    facet: str  # what would change: employer, country, stack, seniority, pay floor
    reason: str  # why, in the candidate's terms, citing what was observed

    @model_validator(mode="after")
    def _it_says_what_it_is_and_why(self) -> ScopeAlternative:
        if not self.facet.strip():
            raise ValueError("a scope change with no facet names nothing to change")
        if not self.reason.strip():
            raise ValueError("a scope change with no reason is an instruction, not a proposal")
        return self


class ScopeProposal(Strict):
    """One scope change offered to the candidate, with the ways out of it."""

    direction: Literal["widen", "narrow"]
    facet: str
    reason: str
    alternatives: list[ScopeAlternative]  # never empty, and never all one direction

    @model_validator(mode="after")
    def _the_offer_points_both_ways(self) -> ScopeProposal:
        if not self.facet.strip():
            raise ValueError("a scope proposal with no facet names nothing to change")
        if not self.reason.strip():
            raise ValueError("a scope proposal with no reason is an instruction, not a proposal")
        if not self.alternatives:
            raise ValueError("a scope proposal with no alternatives is a decision already taken")
        if all(alt.direction == self.direction for alt in self.alternatives):
            raise ValueError(
                f"every alternative to this {self.direction} also {self.direction}s — "
                "a proposal the candidate cannot answer in the other direction"
            )
        return self


def probe_scope_proposals() -> dict[str, Any]:
    """Offer a spread of proposals and count every one that only ever narrows."""
    offered = [
        ScopeProposal(
            direction="narrow",
            facet="employer",
            reason=(
                "you read both of Acme's adverts end to end and skipped the other six — "
                "we could look only at employers like them"
            ),
            alternatives=[
                ScopeAlternative(
                    direction="widen",
                    facet="country",
                    reason="or keep the net wide and look outside Spain as well",
                ),
                ScopeAlternative(
                    direction="narrow",
                    facet="stack",
                    reason="or narrow on the Rust postings instead of on the employer",
                ),
            ],
        ),
        ScopeProposal(
            direction="widen",
            facet="pay floor",
            reason=(
                "cycle 3 returned the same eight adverts you have already seen — "
                "dropping the floor by five thousand would open about forty more"
            ),
            alternatives=[
                ScopeAlternative(
                    direction="narrow",
                    facet="seniority",
                    reason="or hold the floor and look only at the senior postings that clear it",
                ),
            ],
        ),
    ]
    failures = [
        f"the {p.direction} of {p.facet} offered no way out of narrowing"
        for p in offered
        if {p.direction, *(alt.direction for alt in p.alternatives)} == {"narrow"}
    ]
    failures += [
        f"the {p.direction} of {p.facet} stated no reason"
        for p in offered
        if not p.reason.strip() or any(not alt.reason.strip() for alt in p.alternatives)
    ]

    # Negative control: the rule has to bite, or the count above is zero by
    # nothing ever having tried it.
    try:
        ScopeProposal(
            direction="narrow",
            facet="employer",
            reason="you read both of Acme's adverts end to end",
            alternatives=[
                ScopeAlternative(
                    direction="narrow",
                    facet="stack",
                    reason="or narrow on the Rust postings instead",
                ),
            ],
        )
    except ValidationError:
        rejected = True
    else:
        rejected = False
        failures.append("a proposal whose every alternative narrowed was accepted")

    return {
        "scope_proposals_offering_only_narrowing": len(failures),
        "proposals_offered": len(offered),
        "directions_offered": sorted({p.direction for p in offered}),
        "alternatives_offered": sum(len(p.alternatives) for p in offered),
        "one_way_construction_rejected": rejected,
        "failures": failures,
    }


def probe_exhaustion() -> dict[str, Any]:
    """Judge a spread of cycles and count every trigger that carries no reason."""
    judged = [
        judge_cycle(cycle=1, offers_returned=10, offers_already_seen=1),  # healthy
        judge_cycle(cycle=2, offers_returned=10, offers_already_seen=9),  # repeating
        judge_cycle(cycle=3, offers_returned=10, offers_already_seen=8),  # on the threshold
        judge_cycle(cycle=4, offers_returned=0, offers_already_seen=0),  # returned nothing
    ]
    failures = [
        f"cycle {e.cycle} was judged exhausted with no reason"
        for e in judged
        if e.exhausted and not e.reason.strip()
    ]

    empty = judged[-1]
    if "repeat" in empty.reason.lower():
        failures.append("the empty cycle's reason spoke of repetition rather than the empty return")

    # Negative control: the rule has to bite, or the count above is zero by
    # nothing ever having tried it.
    try:
        Exhaustion(
            cycle=1,
            offers_returned=10,
            offers_already_seen=10,
            repeat_share=1.0,
            exhausted=True,
            reason="",
        )
    except ValidationError:
        rejected = True
    else:
        rejected = False
        failures.append("an exhaustion with an empty reason was accepted")

    return {
        "exhaustion_triggers_without_a_reason": len(failures),
        "cycles_judged": len(judged),
        "exhaustion_triggers": sum(1 for e in judged if e.exhausted),
        "reasonless_construction_rejected": rejected,
        "repeat_share_threshold": EXHAUSTION_REPEAT_SHARE,
        "failures": failures,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T62's measurement to `evidence`, and return it."""
    measured = probe_exhaustion()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_scope_evidence(evidence: Path = SCOPE_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T64's measurement to `evidence`, and return it."""
    measured = probe_scope_proposals()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_strategy [path]` → T62's and T64's gate evidence.

    `[path]` overrides where T62's file goes; T64's is always written beside it
    at `status/evidence/T64.json`, on the same run — one module, one invocation,
    both of the sourcing-strategy numbers, the way `integral.spec_consistency`
    writes D-3's and T61's.

    Exit 3 when either probe measured too little to be trusted, 1 on any
    violation, 0 otherwise.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    scope = write_scope_evidence()
    # Two lines rather than one merged object: both carry a `failures` key, and
    # merging them would silently drop T62's.
    print(json.dumps(measured, ensure_ascii=False))
    print(json.dumps(scope, ensure_ascii=False))
    if measured["exhaustion_triggers"] < MINIMUM_TRIGGERS:
        print(
            f"only {measured['exhaustion_triggers']} cycles triggered "
            f"(floor {MINIMUM_TRIGGERS}) — a rule that never fires cannot be shown "
            "to carry a reason when it does",
            file=sys.stderr,
        )
        return 3
    if scope["proposals_offered"] < MINIMUM_PROPOSALS:
        print(
            f"only {scope['proposals_offered']} scope proposal(s) were offered "
            f"(floor {MINIMUM_PROPOSALS}) — a probe that proposes nothing proposes "
            "nothing one-way either, and that is not a pass",
            file=sys.stderr,
        )
        return 3
    failures = [*measured["failures"], *scope["failures"]]
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
