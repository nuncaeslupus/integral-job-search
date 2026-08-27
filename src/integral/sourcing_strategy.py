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

## T65 — consent: a narrowing is licensed by a recorded decision

§5.5. A scope change is candidate evidence like any other, so the licence for
one is a `scope_decision` row of `evidence.jsonl` and nothing else:
`apply_scope_change` hands back the row that licensed the change, or refuses.
That is why the gate counts recorded decisions and **not employer share** — a
cycle collapsing onto one employer is exactly right when the candidate chose it,
and the discriminator is entirely whether they were asked.

**A refusal is evidence, not a veto**, which is one type doing two jobs.
`ScopeDecision` is a subclass of `EvidenceRow` — a refused proposal is a row,
readable on return like the rest of §5.7's standing scope — and `accepted:
False` licenses nothing while forbidding nothing permanently. What it forbids is
narrow: re-asking *the same facet and direction, in the same session, under the
same trigger, with nothing new learned in between*. `refusal_forbidding` is that
sentence and no more, so the three things §5.5 says re-open the question — a
changed trigger, new evidence, a new session — re-open it by the predicate
simply not matching.

The one judgement call is what counts as "new evidence": a later
`scope_decision` does not. Otherwise the tool could license its own re-ask by
asking something else first, and asking again in different words next cycle is
precisely the failure the rule is named after.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T62.json"
SCOPE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T64.json"
CONSENT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T65.json"

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

#: The consent probe has to *apply* something, not merely fail to apply an
#: unlicensed thing — a run that changed no scope would report zero unlicensed
#: narrowings by never having narrowed. Two, so both directions are exercised.
MINIMUM_SCOPE_CHANGES = 2


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
    # A tuple, not a list: `Strict` is frozen, but a frozen model still hands out a
    # mutable list, so `proposal.alternatives.clear()` could strip the opposite
    # direction back off after validation had passed. The invariant is meant to be
    # unbreakable in the type rather than merely checked once.
    alternatives: tuple[ScopeAlternative, ...]  # never empty, never all one direction

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


class EvidenceRow(Strict):
    """One row of `profile/evidence.jsonl`, in the little of it §5.5 reads.

    The re-ask rule needs to know only whether *something else* about the
    candidate was recorded after a refusal, so nothing here models what any
    other kind of row carries.
    """

    kind: str
    step: str
    session: str  # not in §5.5's example row, and load-bearing: "in the same
    # session" is half of the re-ask rule, and a rule nothing can evaluate is prose.


class ScopeDecision(EvidenceRow):
    """§5.5's row: what the candidate answered when one scope change was offered."""

    kind: Literal["scope_decision"] = "scope_decision"
    step: Literal["sourcing"] = "sourcing"
    about: str  # "<facet>:<value>" — the employer, country or stack that would change
    decision: Literal["widen", "narrow"]
    accepted: bool  # False is a refusal: evidence, and not permanent
    cycle: int = Field(ge=1)
    reason: str  # in the candidate's own terms — this is what they review later
    # A tuple for the same reason `ScopeProposal.alternatives` is one: frozen stops
    # the field being rebound, not the list being emptied afterwards.
    proposed_alternatives: tuple[str, ...]  # "widen:country" — what else was on the table
    trigger: str  # the exhaustion reason that prompted the question; "the trigger
    # changed" is the other half of the re-ask rule

    @property
    def facet(self) -> str:
        """What this decision was about — `about` without its value."""
        return self.about.partition(":")[0]

    @model_validator(mode="after")
    def _the_decision_can_be_reviewed(self) -> ScopeDecision:
        facet, sep, value = self.about.partition(":")
        if not (facet.strip() and sep and value.strip()):
            raise ValueError(f"about {self.about!r} is not the <facet>:<value> §5.5 records")
        if not self.reason.strip():
            raise ValueError("a scope decision with no reason is not consent anyone can review")
        if not self.proposed_alternatives:
            raise ValueError("a decision recording no alternatives cannot show what was offered")
        if not self.trigger.strip():
            raise ValueError("a scope decision with no trigger can never be re-asked under another")
        return self


class ConsentError(ValueError):
    """A scope change no recorded decision licenses."""


def apply_scope_change(proposal: ScopeProposal, *, log: Sequence[EvidenceRow]) -> ScopeDecision:
    """The recorded decision licensing `proposal`, or `ConsentError`.

    The candidate's latest word on this facet and direction wins, so a refusal
    followed by a yes applies and a yes followed by a refusal does not.

    ponytail: there is no scope object to mutate yet — step 7 still sources from
    `constraints.json` alone — so this returns the licence rather than applying
    it. It is the one call an applier makes, and the gate counts the narrowings
    that reached a scope without coming through here.
    """
    for row in reversed(list(log)):
        if (
            isinstance(row, ScopeDecision)
            and row.facet == proposal.facet
            and row.decision == proposal.direction
        ):
            if row.accepted:
                return row
            raise ConsentError(
                f"the candidate refused to {proposal.direction} {proposal.facet} "
                f"in cycle {row.cycle}, and a refusal licenses nothing"
            )
    raise ConsentError(
        f"no recorded decision licenses {proposal.direction}ing {proposal.facet} — "
        "a scope change nobody was asked about"
    )


def refusal_forbidding(
    proposal: ScopeProposal,
    *,
    session: str,
    trigger: str,
    log: Sequence[EvidenceRow],
) -> ScopeDecision | None:
    """The refusal that forbids asking `proposal` again now, if there is one.

    §5.5: a refused proposal may be made again when the trigger changed, when new
    evidence about the candidate arrived, or in a new session — never simply on
    the next cycle. All three re-open the question by this predicate not matching;
    the cycle number is deliberately not consulted, since moving to the next cycle
    is the one thing that must *not* be enough.
    """
    rows = list(log)
    for i, row in enumerate(rows):
        if (
            isinstance(row, ScopeDecision)
            and not row.accepted
            and row.session == session
            and row.trigger == trigger
            and row.facet == proposal.facet
            and row.decision == proposal.direction
            # A later scope_decision is not news about the candidate: the tool
            # would otherwise license its own re-ask by asking something else first.
            and not any(later.kind != "scope_decision" for later in rows[i + 1 :])
        ):
            return row
    return None


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
            alternatives=(
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
            ),
        ),
        ScopeProposal(
            direction="widen",
            facet="pay floor",
            reason=(
                "cycle 3 returned the same eight adverts you have already seen — "
                "dropping the floor by five thousand would open about forty more"
            ),
            alternatives=(
                ScopeAlternative(
                    direction="narrow",
                    facet="seniority",
                    reason="or hold the floor and look only at the senior postings that clear it",
                ),
            ),
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
            alternatives=(
                ScopeAlternative(
                    direction="narrow",
                    facet="stack",
                    reason="or narrow on the Rust postings instead",
                ),
            ),
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


def probe_consent() -> dict[str, Any]:
    """Walk one session's scope decisions and count every narrowing nobody licensed."""
    session = "cse_5b1e"
    trigger = judge_cycle(cycle=3, offers_returned=10, offers_already_seen=9).reason
    narrowing = ScopeProposal(
        direction="narrow",
        facet="employer",
        reason="you read both of Acme's adverts end to end and skipped the other six",
        alternatives=(
            ScopeAlternative(
                direction="widen",
                facet="country",
                reason="or keep the net wide and look outside Spain as well",
            ),
        ),
    )
    widening = ScopeProposal(
        direction="widen",
        facet="country",
        reason="cycle 3 returned the same eight Madrid adverts you have already seen",
        alternatives=(
            ScopeAlternative(
                direction="narrow",
                facet="employer",
                reason="or stay here and read only the two employers you opened in full",
            ),
        ),
    )
    pay_floor = ScopeProposal(
        direction="widen",
        facet="pay floor",
        reason="dropping the floor by five thousand would open about forty more adverts",
        alternatives=(
            ScopeAlternative(
                direction="narrow",
                facet="seniority",
                reason="or hold the floor and look only at the senior postings that clear it",
            ),
        ),
    )

    refusal = ScopeDecision(
        session=session,
        about="country:spain",
        decision="widen",
        accepted=False,
        cycle=3,
        reason="the candidate will not relocate and does not want to read foreign adverts",
        proposed_alternatives=("narrow:employer", "narrow:stack"),
        trigger=trigger,
    )
    consented = [
        ScopeDecision(
            session=session,
            about="employer:acme",
            decision="narrow",
            accepted=True,
            cycle=3,
            reason="the candidate asked to focus here after reading two of their adverts",
            proposed_alternatives=("widen:country", "widen:seniority"),
            trigger=trigger,
        ),
        ScopeDecision(
            session=session,
            about="pay floor:55000",
            decision="widen",
            accepted=True,
            cycle=4,
            reason="the candidate said five thousand less is worth it for the right team",
            proposed_alternatives=("narrow:seniority", "narrow:stack"),
            trigger=trigger,
        ),
    ]
    log: list[EvidenceRow] = [refusal, *consented]

    applied: list[ScopeDecision] = []
    failures: list[str] = []
    for proposal in (narrowing, pay_floor):
        try:
            applied.append(apply_scope_change(proposal, log=log))
        except ConsentError as refused:
            failures.append(f"a decision the candidate recorded was not honoured: {refused}")

    # Negative control 1: a narrowing nobody was asked about must not apply, or
    # the count above is zero by nothing unlicensed ever having been attempted.
    try:
        apply_scope_change(
            ScopeProposal(
                direction="narrow",
                facet="stack",
                reason="every advert you lingered on mentioned Rust",
                alternatives=(
                    ScopeAlternative(
                        direction="widen",
                        facet="country",
                        reason="or look for the same stack further out",
                    ),
                ),
            ),
            log=log,
        )
    except ConsentError:
        unconsented_rejected = True
    else:
        unconsented_rejected = False
        failures.append("a narrowing with no recorded decision was applied")

    # Negative control 2: the refused widening, asked again on the next cycle in
    # different words — the failure §5.5 is named after.
    reask_rejected = (
        refusal_forbidding(widening, session=session, trigger=trigger, log=log) is refusal
    )
    if not reask_rejected:
        failures.append("a proposal refused this session was re-asked with nothing changed")

    # …and the three things that do re-open it, so "not permanent" is measured too.
    reopened = {
        "changed trigger": refusal_forbidding(
            widening,
            session=session,
            trigger=judge_cycle(cycle=6, offers_returned=0, offers_already_seen=0).reason,
            log=log,
        ),
        "new session": refusal_forbidding(widening, session="cse_c40f", trigger=trigger, log=log),
        "new evidence": refusal_forbidding(
            widening,
            session=session,
            trigger=trigger,
            log=[*log, EvidenceRow(kind="reaction", step="reactions", session=session)],
        ),
    }
    licensed = sorted(why for why, blocked in reopened.items() if blocked is None)
    failures += [
        f"a refusal outlived {why} — a refusal is evidence, not a veto"
        for why, blocked in reopened.items()
        if blocked is not None
    ]

    return {
        "narrowings_without_a_recorded_decision": len(failures),
        "scope_changes_applied": len(applied),
        "decisions_recorded": len([row for row in log if isinstance(row, ScopeDecision)]),
        "refusals_recorded": len(
            [row for row in log if isinstance(row, ScopeDecision) and not row.accepted]
        ),
        "unconsented_narrowing_rejected": unconsented_rejected,
        "reask_after_refusal_rejected": reask_rejected,
        "reask_licensed_by": licensed,
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


def write_consent_evidence(evidence: Path = CONSENT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T65's measurement to `evidence`, and return it."""
    measured = probe_consent()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_strategy [path]` → T62's, T64's and T65's evidence.

    `[path]` overrides where T62's file goes; T64's and T65's are always written
    beside it at `status/evidence/`, on the same run — one module, one
    invocation, all three of the sourcing-strategy numbers, the way
    `integral.spec_consistency` writes D-3's and T61's.

    Exit 3 when any probe measured too little to be trusted, 1 on any violation,
    0 otherwise.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    scope = write_scope_evidence()
    consent = write_consent_evidence()
    # Three lines rather than one merged object: each carries a `failures` key,
    # and merging them would silently drop the earlier ones'.
    print(json.dumps(measured, ensure_ascii=False))
    print(json.dumps(scope, ensure_ascii=False))
    print(json.dumps(consent, ensure_ascii=False))
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
    if consent["scope_changes_applied"] < MINIMUM_SCOPE_CHANGES:
        print(
            f"only {consent['scope_changes_applied']} scope change(s) were applied "
            f"(floor {MINIMUM_SCOPE_CHANGES}) — a probe that narrows nothing narrows "
            "nothing unlicensed either, and that is not a pass",
            file=sys.stderr,
        )
        return 3
    failures = [*measured["failures"], *scope["failures"], *consent["failures"]]
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
