"""T36 — freshness triggers and proactive re-entry.

§5.2 is the requirement that separates this from a form: **if something could
have changed, ask.** Three trigger kinds — elapsed time, a life event in the
conversation, a gap — and one rule over all of them: *a trigger produces an
offer, never an action.*

That rule is checked the only way it can be believed — by comparing the profile
tree byte for byte before and after every trigger is evaluated. "It only
offered" is otherwise a claim about code somebody has to read.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from integral.decline import DeclineLedger
from integral.freshness import (
    DEFAULT_ELAPSED_DAYS,
    FreshnessError,
    Offer,
    decline,
    elapsed_offers,
    exhaustion_offers,
    gap_offers,
    life_event_offers,
    offers,
    probe_freshness,
    steps_for_event,
    tree_fingerprint,
    write_evidence,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, rebuild
from integral.session import SessionStore
from integral.sourcing_reentry import MINIMUM_TRIGGERS
from integral.sourcing_reentry import write_evidence as write_reentry_evidence
from integral.sourcing_strategy import judge_cycle

NOW = datetime.fromisoformat("2026-08-18T09:00:00+00:00")


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)
    SessionStore(store).record(
        at="2024-01-01T10:00:00Z", current_step="history", pending_steps=("traits",)
    )
    store.write_json(
        {"fields": {"salary_floor": {"state": "unknown"}}}, "profile", "constraints.json"
    )
    return store


# --- an offer, never an action ---------------------------------------------


def test_trigger_produces_an_offer_not_an_action(store: ProfileStore) -> None:
    before = tree_fingerprint(store)
    raised = offers(store, now=NOW, event="left_job", said="you left your job in March")
    assert raised
    assert tree_fingerprint(store) == before, "evaluating a trigger changed the profile"


def test_every_offer_says_something(store: ProfileStore) -> None:
    for offer in offers(store, now=NOW, event="left_job", said="you left in March"):
        assert offer.sentence().strip()
        assert offer.step
        assert offer.subject


def test_an_offer_is_a_conversation_not_an_audit(store: ProfileStore) -> None:
    """ "It has been eight months, let's update your file" is a form.

    "You said you left in March — how did that end up?" is the one that gets
    an answer, so the sentence quotes the candidate rather than naming a step.
    """
    raised = life_event_offers("left_job", said="you left your job in March")
    assert raised
    assert "you left your job in March" in raised[0].sentence()
    assert "step" not in raised[0].sentence().lower()


# --- the three kinds -------------------------------------------------------


def test_elapsed_time_reopens_history_and_constraints(store: ProfileStore) -> None:
    raised = elapsed_offers(store, now=NOW)
    assert {offer.step for offer in raised} == {"history", "constraints"}
    assert all(offer.kind == "elapsed" for offer in raised)


def test_a_recent_session_raises_nothing_on_elapsed_time(store: ProfileStore) -> None:
    SessionStore(store).record(at="2026-08-17T10:00:00Z", current_step="history")
    assert elapsed_offers(store, now=NOW) == []


def test_the_elapsed_threshold_is_a_parameter_not_a_constant(store: ProfileStore) -> None:
    """§5.2 puts the thresholds in each step's spec, so this must be overridable."""
    SessionStore(store).record(at="2026-08-01T10:00:00Z", current_step="history")
    assert elapsed_offers(store, now=NOW) == []
    assert elapsed_offers(store, now=NOW, elapsed_days=7) != []
    assert DEFAULT_ELAPSED_DAYS > 0


def test_life_event_reenters_the_step_the_spec_names(store: ProfileStore) -> None:
    """§3.5's three examples, each read from `reentry_events` rather than a table."""
    assert "history" in steps_for_event("left_job")
    assert "intake" in steps_for_event("cv_updated")
    assert "feedback" in steps_for_event("rejection_received")
    assert {offer.step for offer in life_event_offers("left_job")} == set(
        steps_for_event("left_job")
    )


def test_an_event_no_step_declares_is_an_error_not_a_silent_nothing(
    store: ProfileStore,
) -> None:
    """§3.5's three are examples, not the set — so an unknown one must be loud."""
    with pytest.raises(FreshnessError, match="no step declares"):
        life_event_offers("won_the_lottery")


def test_a_gap_names_the_step_that_owns_it(store: ProfileStore) -> None:
    raised = gap_offers(store)
    by_subject = {offer.subject: offer for offer in raised}
    assert by_subject["gap_salary_floor"].step == "constraints"
    assert by_subject["pending_traits"].step == "traits"


def test_a_stale_authored_artefact_is_offered_for_regeneration(
    store: ProfileStore,
) -> None:
    """T37 computes the staleness; this offers to do something about it."""
    log = EvidenceLog(store)
    log.append(
        recorded_at="2024-01-01T10:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="A while ago now.",
        source="conversation",
    )
    rebuild(store)
    store.write_json(
        {"profile_revision": log.revision().as_json(), "claims": []},
        "cv",
        "generated",
        "offer-1",
        "v1",
        "cv.json",
    )
    log.append(
        recorded_at="2026-08-18T08:00:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["remote_work"],
        text="Fully remote.",
        source="conversation",
    )
    subjects = {offer.subject for offer in gap_offers(store)}
    assert any(subject.startswith("stale_cv/generated") for subject in subjects)


# --- declining -------------------------------------------------------------


def test_declined_trigger_is_not_raised_again(store: ProfileStore) -> None:
    raised = offers(store, now=NOW)
    target = next(offer for offer in raised if offer.subject == "gap_salary_floor")
    decline(store, target, at="2026-08-18T09:05:00Z")

    again = offers(store, now=NOW)
    assert all(offer.subject != "gap_salary_floor" for offer in again)


def test_a_decline_goes_through_the_same_ledger_as_every_other_question(
    store: ProfileStore,
) -> None:
    """Waving away a suggestion twice says the same thing as declining a question.

    §5.4's non-insistence rule and §5.2's "declining is recorded" are the same
    mechanism, so a second decline silences it everywhere.
    """
    raised = offers(store, now=NOW)
    target = next(offer for offer in raised if offer.subject == "gap_salary_floor")
    ledger = DeclineLedger(store)
    decline(store, target, at="2026-08-18T09:05:00Z")
    ledger.decline(target.subject, step="anywhere", at="2026-08-18T09:06:00Z")
    assert target.subject in ledger.silenced()


def test_declining_one_offer_leaves_the_others_standing(store: ProfileStore) -> None:
    raised = offers(store, now=NOW)
    target = next(offer for offer in raised if offer.subject == "gap_salary_floor")
    decline(store, target, at="2026-08-18T09:05:00Z")
    remaining = offers(store, now=NOW)
    assert remaining
    assert {offer.kind for offer in remaining} >= {"elapsed"}


def test_declining_is_the_only_thing_this_module_writes(store: ProfileStore) -> None:
    before = tree_fingerprint(store)
    raised = offers(store, now=NOW)
    assert tree_fingerprint(store) == before
    decline(store, raised[0], at="2026-08-18T09:05:00Z")
    assert tree_fingerprint(store) != before


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T36.json"
    measured = write_evidence(evidence)
    assert measured["unoffered_reentries"] == 0
    assert measured["offers_raised"] >= 3
    assert measured["trigger_kinds"] == ["elapsed", "gap", "life_event"]
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_probe_fires_all_three_kinds(tmp_path: Path) -> None:
    result = probe_freshness(tmp_path / "profiles")
    assert result["failures"] == []
    assert set(result["trigger_kinds"]) == {"elapsed", "life_event", "gap"}


# --- T63: exhaustion, a kind beside staleness ------------------------------


STUCK = judge_cycle(cycle=3, offers_returned=10, offers_already_seen=9)
HEALTHY = judge_cycle(cycle=1, offers_returned=10, offers_already_seen=1)
PROPOSAL = "widen: drop the country filter, or narrow to the two employers you read"


def test_an_exhausted_step_seven_is_offered_again(store: ProfileStore) -> None:
    """§5.3 — a finished sourcing step re-enters on an `exhausted` trigger."""
    SessionStore(store).record(at="2026-08-17T10:00:00Z", current_step="ranking")
    raised = offers(store, now=NOW, exhaustion=STUCK, proposal=PROPOSAL)
    entered = [offer for offer in raised if offer.kind == "exhausted"]
    assert [offer.step for offer in entered] == ["sourcing"]
    # the reason names the repeat share, the cycle number, and what was repeated
    assert "90%" in entered[0].reason
    assert "cycle 3" in entered[0].reason
    assert "already seen" in entered[0].reason


def test_staleness_behaviour_is_unchanged_by_the_new_kind(store: ProfileStore) -> None:
    """The new kind is added beside the old one, never a change to it."""
    stale = offers(store, now=NOW)
    assert {offer.kind for offer in stale} == {"elapsed", "gap"}
    with_new = offers(store, now=NOW, exhaustion=STUCK, proposal=PROPOSAL)
    assert [offer for offer in with_new if offer.kind != "exhausted"] == stale
    # and a cycle that is not exhausted raises nothing new at all
    assert offers(store, now=NOW, exhaustion=HEALTHY) == stale


def test_an_exhausted_cycle_never_reruns_the_same_search_silently(
    store: ProfileStore,
) -> None:
    """Re-entry carries a proposal — that is `stuck_cycles_without_a_proposal`."""
    with pytest.raises(FreshnessError, match="proposal"):
        exhaustion_offers(STUCK, proposal=None)
    with pytest.raises(FreshnessError, match="proposal"):
        offers(store, now=NOW, exhaustion=STUCK, proposal="   ")
    with pytest.raises(FreshnessError, match="reason"):
        Offer(kind="exhausted", step="sourcing", subject="s", says="?", proposal=PROPOSAL)
    assert exhaustion_offers(STUCK, proposal=PROPOSAL)[0].proposal == PROPOSAL


def test_the_reentry_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T63.json"
    measured = write_reentry_evidence(evidence)
    assert measured["stuck_cycles_without_a_proposal"] == 0
    assert measured["reentry_offers"] >= MINIMUM_TRIGGERS
    assert measured["proposalless_reentry_rejected"] is True
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured
