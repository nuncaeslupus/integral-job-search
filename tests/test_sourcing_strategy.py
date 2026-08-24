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

from integral.sourcing_strategy import (
    EXHAUSTION_REPEAT_SHARE,
    MINIMUM_PROPOSALS,
    Exhaustion,
    ScopeAlternative,
    ScopeProposal,
    judge_cycle,
    probe_exhaustion,
    probe_scope_proposals,
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


def _narrowing_to_one_employer(alternatives: list[ScopeAlternative]) -> ScopeProposal:
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
            [
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
            ]
        )
    # …and offering nothing at all is not an improvement on offering one direction.
    with pytest.raises(ValidationError):
        _narrowing_to_one_employer([])


def test_a_widening_is_proposable_when_the_search_is_too_focused() -> None:
    proposal = ScopeProposal(
        direction="widen",
        facet="country",
        reason=(
            "cycle 3 returned the same eight Madrid adverts you have already seen — "
            "the search has run out of road where it is looking"
        ),
        alternatives=[
            ScopeAlternative(
                direction="narrow",
                facet="employer",
                reason="or stay here and read only the two employers you opened in full",
            )
        ],
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
            alternatives=[
                ScopeAlternative(
                    direction="widen", facet="country", reason="or look further out"
                )
            ],
        )


def test_an_alternative_cannot_carry_alternatives_of_its_own() -> None:
    # The base case is a distinct type, so the nesting stops at depth one by
    # construction — no depth counter, and no proposal that can never be built.
    assert "alternatives" not in ScopeAlternative.model_fields
    with pytest.raises(ValidationError):
        ScopeAlternative.model_validate(
            {"direction": "widen", "facet": "country", "reason": "further out", "alternatives": []}
        )


def test_the_scope_evidence_file_carries_the_gate_key(tmp_path: Path) -> None:
    target = tmp_path / "T64.json"
    measured = write_scope_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["scope_proposals_offering_only_narrowing"] == 0
