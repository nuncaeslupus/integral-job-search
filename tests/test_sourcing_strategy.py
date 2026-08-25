"""T62 — exhaustion as a measurement: a cycle that keeps finding the same jobs.

`status/specs/iterative-sourcing.md` §5.2. Two things are checked here that a
reading of the code would otherwise have to be trusted on: that a cycle which
returned *nothing* is exhausted for its own stated reason rather than for a
repeat share of zero, and that an exhaustion carrying no reason cannot be
constructed at all — it is a violation, not a trigger.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.sourcing_cycles import (
    MINIMUM_NON_IMPROVING,
    Cycle,
    cycles_neither_improving_nor_proposing,
    improved,
    write_cycle_evidence,
)
from integral.sourcing_market import (
    HARD_CONSTRAINT_TERMS,
    MINIMUM_EMPTY_MARKETS,
    RETRY_TIMES,
    EmptyMarketReport,
    market_is_empty,
    report_empty_market,
    write_market_evidence,
)
from integral.sourcing_strategy import (
    EXHAUSTION_REPEAT_SHARE,
    MINIMUM_PROPOSALS,
    MINIMUM_SCOPE_CHANGES,
    ConsentError,
    EvidenceRow,
    Exhaustion,
    ScopeAlternative,
    ScopeDecision,
    ScopeProposal,
    apply_scope_change,
    judge_cycle,
    probe_consent,
    probe_exhaustion,
    probe_scope_proposals,
    refusal_forbidding,
    write_consent_evidence,
    write_evidence,
    write_scope_evidence,
)


def test_a_cycle_repeating_known_offers_is_exhausted() -> None:
    judged = judge_cycle(cycle=2, offers_returned=10, offers_already_seen=9)
    assert judged.repeat_share > EXHAUSTION_REPEAT_SHARE
    assert judged.exhausted
    assert judged.reason.strip()


def test_a_cycle_finding_new_work_is_not_exhausted() -> None:
    judged = judge_cycle(cycle=1, offers_returned=10, offers_already_seen=1)
    assert not judged.exhausted
    assert judged.reason == ""


def test_the_threshold_is_the_boundary_and_not_beyond_it() -> None:
    judged = judge_cycle(cycle=3, offers_returned=10, offers_already_seen=8)
    assert judged.repeat_share == pytest.approx(EXHAUSTION_REPEAT_SHARE)
    assert judged.exhausted


def test_a_cycle_that_returned_nothing_is_exhausted_for_its_own_reason() -> None:
    judged = judge_cycle(cycle=4, offers_returned=0, offers_already_seen=0)
    assert judged.repeat_share == 0.0
    assert judged.exhausted
    # A zero share must not read as "nothing was repeated, so all is well": the
    # reason has to name the empty return, not the repetition that did not happen.
    assert "repeat" not in judged.reason.lower()
    assert "no offers" in judged.reason.lower()


def test_no_exhaustion_is_recorded_without_a_reason() -> None:
    with pytest.raises(ValidationError):
        Exhaustion(
            cycle=1,
            offers_returned=10,
            offers_already_seen=10,
            repeat_share=1.0,
            exhausted=True,
            reason="   ",
        )


def test_a_repeat_share_that_contradicts_the_counts_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Exhaustion(
            cycle=1,
            offers_returned=10,
            offers_already_seen=2,
            repeat_share=0.9,
            exhausted=True,
            reason="claims a repeat share the counts do not support",
        )


def test_more_seen_than_returned_is_rejected() -> None:
    with pytest.raises(ValidationError):
        judge_cycle(cycle=1, offers_returned=2, offers_already_seen=3)


def test_the_probe_finds_no_reasonless_trigger_and_is_not_vacuous() -> None:
    measured = probe_exhaustion()
    assert measured["exhaustion_triggers_without_a_reason"] == 0
    assert measured["failures"] == []
    # A probe that never triggered would pass by not measuring anything.
    assert measured["exhaustion_triggers"] >= 2
    assert measured["reasonless_construction_rejected"] is True


def test_the_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T62.json"
    measured = write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["exhaustion_triggers_without_a_reason"] == 0


# --- T64: symmetric scope proposals — §5.4 ---------------------------------


def _narrowing_to_one_employer(alternatives: tuple[ScopeAlternative, ...]) -> ScopeProposal:
    return ScopeProposal(
        direction="narrow",
        facet="employer",
        reason="you read two of Acme's adverts end to end and skipped the rest",
        alternatives=alternatives,
    )


def test_a_proposal_offering_only_narrowing_is_rejected() -> None:
    # Alternatives that all narrow are not alternatives: they are the same
    # suggestion three times, and the candidate has nothing to say no to.
    with pytest.raises(ValidationError):
        _narrowing_to_one_employer(
            (
                ScopeAlternative(
                    direction="narrow",
                    facet="stack",
                    reason="every advert you lingered on mentioned Rust",
                ),
                ScopeAlternative(
                    direction="narrow",
                    facet="seniority",
                    reason="you skipped both junior postings",
                ),
            )
        )
    # …and offering nothing at all is not an improvement on offering one direction.
    with pytest.raises(ValidationError):
        _narrowing_to_one_employer(())


def test_a_widening_is_proposable_when_the_search_is_too_focused() -> None:
    proposal = ScopeProposal(
        direction="widen",
        facet="country",
        reason=(
            "cycle 3 returned the same eight Madrid adverts you have already seen — "
            "the search has run out of road where it is looking"
        ),
        alternatives=(
            ScopeAlternative(
                direction="narrow",
                facet="employer",
                reason="or stay here and read only the two employers you opened in full",
            ),
        ),
    )
    assert proposal.direction == "widen"
    assert [alt.direction for alt in proposal.alternatives] == ["narrow"]


def test_every_proposal_states_its_reason_in_candidate_terms() -> None:
    measured = probe_scope_proposals()
    assert measured["scope_proposals_offering_only_narrowing"] == 0
    assert measured["failures"] == []
    # A probe that offered nothing would pass by never having proposed.
    assert measured["proposals_offered"] >= MINIMUM_PROPOSALS
    assert measured["directions_offered"] == ["narrow", "widen"]
    assert measured["one_way_construction_rejected"] is True
    # The reason is the proposal's whole justification to the candidate, so a
    # blank one is a violation on both halves of the pair, not a missing field.
    with pytest.raises(ValidationError):
        ScopeAlternative(direction="widen", facet="country", reason="   ")
    with pytest.raises(ValidationError):
        ScopeProposal(
            direction="narrow",
            facet="employer",
            reason="  ",
            alternatives=(
                ScopeAlternative(
                    direction="widen", facet="country", reason="or look further out"
                ),
            ),
        )


def test_an_alternative_cannot_carry_alternatives_of_its_own() -> None:
    # The base case is a distinct type, so the nesting stops at depth one by
    # construction — no depth counter, and no proposal that can never be built.
    assert "alternatives" not in ScopeAlternative.model_fields
    with pytest.raises(ValidationError):
        ScopeAlternative.model_validate(
            {"direction": "widen", "facet": "country", "reason": "further out", "alternatives": []}
        )


def test_the_alternatives_cannot_be_emptied_after_validation() -> None:
    # `Strict` is frozen, which stops rebinding the field but not mutating what it
    # holds. A list would let the opposite direction be stripped back off once the
    # validator had passed, which is the whole invariant — so it is a tuple.
    proposal = ScopeProposal(
        direction="narrow",
        facet="employer",
        reason="you read both of their adverts end to end",
        alternatives=(
            ScopeAlternative(
                direction="widen",
                facet="country",
                reason="or look outside Spain as well",
            ),
        ),
    )
    assert isinstance(proposal.alternatives, tuple)
    with pytest.raises(AttributeError):
        proposal.alternatives.clear()  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        ScopeProposal.model_validate(
            {**proposal.model_dump(), "alternatives": []},
        )


def test_the_scope_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T64.json"
    measured = write_scope_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["scope_proposals_offering_only_narrowing"] == 0


# --- T65: consent — a narrowing is licensed by a recorded decision (§5.5) --


_SESSION = "cse_5b1e"
_TRIGGER = judge_cycle(cycle=3, offers_returned=10, offers_already_seen=9).reason
_NARROW_TO_ACME = ScopeProposal(
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
_WIDEN_COUNTRY = ScopeProposal(
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


def _decision(**overrides: object) -> ScopeDecision:
    """A recorded decision, with only what a test is about spelled out."""
    fields: dict[str, object] = {
        "session": _SESSION,
        "about": "employer:acme",
        "decision": "narrow",
        "accepted": True,
        "cycle": 3,
        "reason": "what the candidate said when they were asked",
        "proposed_alternatives": ("widen:country", "narrow:stack"),
        "trigger": _TRIGGER,
    }
    fields.update(overrides)
    return ScopeDecision.model_validate(fields)


def test_a_narrowing_without_a_recorded_decision_is_refused() -> None:
    # An empty log licenses nothing: the scope change cannot apply without the row.
    with pytest.raises(ConsentError):
        apply_scope_change(_NARROW_TO_ACME, log=())
    # Nor does a decision about another facet, or one pointing the other way.
    elsewhere = _decision(about="stack:rust")
    other_way = _decision(decision="widen")
    with pytest.raises(ConsentError):
        apply_scope_change(_NARROW_TO_ACME, log=(elsewhere, other_way))
    # The recorded decision is what licenses it, and it is what comes back.
    said_yes = _decision()
    assert apply_scope_change(_NARROW_TO_ACME, log=(elsewhere, said_yes)) is said_yes


def test_a_refusal_is_recorded_as_evidence_not_as_a_veto() -> None:
    refusal = _decision(about="country:spain", decision="widen", accepted=False)
    # Evidence: it is a row of `evidence.jsonl` like any other, and says so.
    assert isinstance(refusal, EvidenceRow)
    assert refusal.kind == "scope_decision"
    assert refusal.step == "sourcing"
    assert refusal.facet == "country"
    # Not a licence: a refusal never licenses the change it refused.
    with pytest.raises(ConsentError):
        apply_scope_change(_WIDEN_COUNTRY, log=(refusal,))
    # Not a veto either, and not permanent. A new session may ask again…
    assert (
        refusal_forbidding(
            _WIDEN_COUNTRY, session="cse_later", trigger=_TRIGGER, log=(refusal,)
        )
        is None
    )
    # …so may a changed trigger…
    assert (
        refusal_forbidding(
            _WIDEN_COUNTRY, session=_SESSION, trigger="the market went quiet", log=(refusal,)
        )
        is None
    )
    # …and so does new evidence about the candidate arriving in between.
    reaction = EvidenceRow(kind="reaction", step="reactions", session=_SESSION)
    assert (
        refusal_forbidding(
            _WIDEN_COUNTRY, session=_SESSION, trigger=_TRIGGER, log=(refusal, reaction)
        )
        is None
    )
    # And when they change their mind, the later row licenses the same change.
    said_yes = _decision(about="country:spain", decision="widen", cycle=5)
    assert apply_scope_change(_WIDEN_COUNTRY, log=(refusal, said_yes)) is said_yes


def test_a_refused_proposal_is_not_reasked_on_the_next_cycle() -> None:
    refusal = _decision(about="country:spain", decision="widen", accepted=False)
    # Same facet, same direction, same session, same trigger, nothing learned in
    # between — asking again next cycle in different words is the violation.
    assert (
        refusal_forbidding(_WIDEN_COUNTRY, session=_SESSION, trigger=_TRIGGER, log=(refusal,))
        is refusal
    )
    # Another scope question asked in between is not news about the candidate:
    # the tool cannot license its own re-ask by asking something else first.
    asked_elsewhere = _decision(cycle=4)
    assert (
        refusal_forbidding(
            _WIDEN_COUNTRY, session=_SESSION, trigger=_TRIGGER, log=(refusal, asked_elsewhere)
        )
        is refusal
    )
    # A question that was never refused is not forbidden by someone else's refusal.
    assert (
        refusal_forbidding(_NARROW_TO_ACME, session=_SESSION, trigger=_TRIGGER, log=(refusal,))
        is None
    )


def test_a_decision_nobody_could_review_is_rejected() -> None:
    # IS-4: consent nobody can review is not consent. A row naming no facet, no
    # reason, or nothing that was on the table cannot be reviewed on return (§5.7).
    with pytest.raises(ValidationError):
        _decision(about="acme")
    with pytest.raises(ValidationError):
        _decision(reason="  ")
    with pytest.raises(ValidationError):
        _decision(proposed_alternatives=())
    # The alternatives are a tuple, so they cannot be emptied after validation.
    assert isinstance(_decision().proposed_alternatives, tuple)


def test_the_consent_probe_finds_no_unlicensed_narrowing_and_is_not_vacuous() -> None:
    measured = probe_consent()
    assert measured["narrowings_without_a_recorded_decision"] == 0
    assert measured["failures"] == []
    # A probe that applied nothing would pass by never having narrowed.
    assert measured["scope_changes_applied"] >= MINIMUM_SCOPE_CHANGES
    assert measured["refusals_recorded"] >= 1
    assert measured["unconsented_narrowing_rejected"] is True
    assert measured["reask_after_refusal_rejected"] is True
    assert measured["reask_licensed_by"] == ["changed trigger", "new evidence", "new session"]


def test_the_consent_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T65.json"
    measured = write_consent_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["narrowings_without_a_recorded_decision"] == 0
# --- T68: the cycle improves, or it says why ------------------------------
#
# `status/specs/iterative-sourcing.md` §1, the `cycle_rejection_rate` row:
# strictly decreasing across a candidate's cycles, or the cycle proposes a
# scope change. The metric and §5.2's exhaustion trigger are the same
# measurement read twice, so what is checked here is the *second* reading:
# where the search did not get better, the tool has to say something.


def _widening() -> ScopeProposal:
    return ScopeProposal(
        direction="widen",
        facet="country",
        reason="cycle 3 rejected more than cycle 2 did — we could look outside Spain",
        alternatives=(
            ScopeAlternative(
                direction="narrow",
                facet="employer",
                reason="or hold the country and look only at the two employers you read",
            ),
        ),
    )


def test_a_cycle_that_did_not_improve_proposes_a_scope_change() -> None:
    first = Cycle(cycle=1, offers_returned=20, offers_rejected=12)
    worse = Cycle(cycle=2, offers_returned=20, offers_rejected=18)
    assert not improved(worse, first)
    # Silent, it is exactly the failure the gate counts.
    assert cycles_neither_improving_nor_proposing([first, worse])
    # Carrying a proposal, it is not — the search got worse and the tool said so.
    spoke = worse.model_copy(update={"proposal": _widening()})
    assert cycles_neither_improving_nor_proposing([first, spoke]) == []


def test_an_improving_cycle_is_left_alone() -> None:
    """The tool does not speak when the search is working."""
    first = Cycle(cycle=1, offers_returned=20, offers_rejected=19)
    better = Cycle(cycle=2, offers_returned=20, offers_rejected=12)
    assert improved(better, first)
    assert better.proposal is None
    assert cycles_neither_improving_nor_proposing([first, better]) == []
    # The first cycle has nothing to be better than, so it is never counted.
    assert cycles_neither_improving_nor_proposing([first]) == []
    # Flat is not improving: "strictly decreasing" is strict.
    flat = Cycle(cycle=2, offers_returned=20, offers_rejected=19)
    assert not improved(flat, first)


def test_cycles_out_of_order_or_with_a_gap_are_refused() -> None:
    """`pairwise` reads its left element as "the last search" — so order is the claim."""
    first = Cycle(cycle=1, offers_returned=20, offers_rejected=2)
    third = Cycle(cycle=3, offers_returned=20, offers_rejected=18)
    # Reordered, the regression reads as an improvement and the gate passes on it.
    with pytest.raises(ValueError, match="consecutively"):
        cycles_neither_improving_nor_proposing([third, first])
    # A gap compares cycle 3 with cycle 1 as though cycle 2 had not happened.
    with pytest.raises(ValueError, match="consecutively"):
        cycles_neither_improving_nor_proposing([first, third])


def test_a_later_window_of_one_candidates_cycles_is_still_judgeable() -> None:
    """Only adjacency is load-bearing — starting at 1 is not required."""
    second = Cycle(cycle=2, offers_returned=20, offers_rejected=2)
    third = Cycle(cycle=3, offers_returned=20, offers_rejected=18)
    assert cycles_neither_improving_nor_proposing([second, third])


def test_the_rate_is_measured_within_subject_only() -> None:
    """No cross-candidate comparison exists to make."""
    import inspect

    mine = [
        Cycle(cycle=1, offers_returned=20, offers_rejected=12),
        Cycle(cycle=2, offers_returned=20, offers_rejected=18),
    ]
    somebody_else = [
        Cycle(cycle=1, offers_returned=20, offers_rejected=18),
        Cycle(cycle=2, offers_returned=20, offers_rejected=2),
    ]
    before = cycles_neither_improving_nor_proposing(mine)
    cycles_neither_improving_nor_proposing(somebody_else)
    # Judging another candidate in between changes nothing: there is no store
    # their cycles could have landed in.
    assert cycles_neither_improving_nor_proposing(mine) == before
    assert len(before) == 1
    # And the signature cannot express a second subject — one sequence in, one
    # candidate's own cycles, and no identifier for whose they are.
    assert list(inspect.signature(cycles_neither_improving_nor_proposing).parameters) == ["cycles"]


def test_a_cycle_that_returned_nothing_has_no_rate_to_improve_on() -> None:
    # 0/0 is not a rejection rate of zero, the way T62's repeat share is not a
    # repeat share of zero. An empty return improved on nothing.
    empty = Cycle(cycle=2, offers_returned=0, offers_rejected=0)
    assert empty.rejection_rate is None
    assert not improved(empty, Cycle(cycle=1, offers_returned=20, offers_rejected=12))


def test_the_cycle_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T68.json"
    measured = write_cycle_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["cycles_neither_improving_nor_proposing"] == 0
    # A probe whose cycles all improved has not tested the rule.
    assert measured["non_improving_cycles"] >= MINIMUM_NON_IMPROVING
    assert measured["unproposed_regression_detected"] is True


# --- T66: the empty market — a time, never a relaxed constraint (§5.6) -------


def _steered(cycle: int, direction: str, facet: str) -> ScopeDecision:
    """A recorded, accepted decision — the licence T65 says a scope change needs."""
    return ScopeDecision(
        session="cse_t66",
        about=f"{facet}:madrid",
        decision=direction,  # type: ignore[arg-type]
        accepted=True,
        cycle=cycle,
        reason="the candidate agreed to try the search this way",
        proposed_alternatives=("narrow:employer", "widen:country"),
        trigger="cycle 1 returned the same adverts it returned before",
    )


def _both_directions_tried() -> list[Cycle]:
    """Widened, then narrowed, and neither one helped."""
    return [
        Cycle(cycle=1, offers_returned=20, offers_rejected=18),
        Cycle(
            cycle=2,
            offers_returned=20,
            offers_rejected=19,
            steered_by=_steered(2, "widen", "country"),
        ),
        Cycle(
            cycle=3,
            offers_returned=20,
            offers_rejected=19,
            steered_by=_steered(3, "narrow", "employer"),
        ),
    ]


def test_an_empty_market_is_reported_as_a_time_not_a_compromise() -> None:
    report = report_empty_market(_both_directions_tried())
    # What is offered is when to come back, and nothing else.
    assert report.retry_options == RETRY_TIMES
    assert all(when in ("tomorrow", "next week") for when in report.retry_options)
    said = json.dumps(report.model_dump(), ensure_ascii=False).lower()
    assert not [term for term in HARD_CONSTRAINT_TERMS if term in said]
    # And nothing may be reported when the market is not the problem.
    with pytest.raises(ValueError, match="not empty"):
        report_empty_market([Cycle(cycle=1, offers_returned=20, offers_rejected=18)])


def test_the_empty_market_needs_exhaustion_in_both_directions() -> None:
    both = _both_directions_tried()
    assert market_is_empty(both)

    # One stale cycle is not a market. Nor are two, unsteered.
    assert not market_is_empty(both[:1])
    assert not market_is_empty([both[0], Cycle(cycle=2, offers_returned=20, offers_rejected=19)])

    # Widened only: the other remedy has not been tried, so the diagnosis is unreached.
    assert not market_is_empty(both[:2])

    # Both tried, and the narrowing worked — a search problem after all.
    it_worked = [
        *both[:2],
        Cycle(
            cycle=3,
            offers_returned=20,
            offers_rejected=4,
            steered_by=_steered(3, "narrow", "employer"),
        ),
    ]
    assert not market_is_empty(it_worked)

    # Order is a claim (T68's lesson): out of order, the comparison inverts.
    with pytest.raises(ValueError, match="consecutively"):
        market_is_empty([both[2], both[1], both[0]])


def test_no_hard_constraint_is_proposed_for_relaxation_on_an_empty_result() -> None:
    reason = "it looks like it is not a good day to find jobs"
    # A relaxed constraint dressed as an option is not a time.
    with pytest.raises(ValidationError):
        EmptyMarketReport(reason=reason, retry_options=("or we could lower your salary floor",))
    with pytest.raises(ValidationError):
        EmptyMarketReport(reason="we could look at relocation instead", retry_options=RETRY_TIMES)
    # Nor can the report carry a scope change at all: there is no field for one.
    with pytest.raises(ValidationError):
        EmptyMarketReport(
            reason=reason,
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


def test_the_market_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T66.json"
    measured = write_market_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["exhausted_searches_reported_as_a_scope_change"] == 0
    # A probe where the market was never empty has not tested the rule.
    assert measured["empty_markets_reported"] >= MINIMUM_EMPTY_MARKETS
    assert measured["relaxed_constraint_rejected"] is True
    assert measured["scope_change_field_rejected"] is True
