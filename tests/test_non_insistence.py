"""T40 — the decline ledger.

§5.4 puts the non-insistence rule above every coverage target: a subject
declined once is not raised again *in that step*; declined twice, not raised
again at all unless the candidate reopens it. "It is better to find a worse job
than to make someone feel bad about the questions."

The two thresholds are different rules, and the difference is the point. One
decline is about this conversation; two are about the subject. Collapsing them
either nags or gives up too early.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.decline import (
    Ask,
    DeclineError,
    DeclineLedger,
    count_repeat_asks,
    probe_declines,
    write_evidence,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog


@pytest.fixture
def ledger(tmp_path: Path) -> DeclineLedger:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    return DeclineLedger(ProfileStore(root, identity.handle))


# --- the two thresholds ----------------------------------------------------


def test_subject_declined_once_is_not_raised_again_in_that_step(
    ledger: DeclineLedger,
) -> None:
    assert ledger.may_ask("salary_floor", step="constraints")
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    verdict = ledger.may_ask("salary_floor", step="constraints")
    assert not verdict
    assert "already declined in constraints" in verdict.reason


def test_one_decline_does_not_silence_a_subject_everywhere(ledger: DeclineLedger) -> None:
    """§2.5 guarantees a path forward without any given answer.

    A constraint the candidate would not discuss during the interview may still
    be worth one gentle ask when it turns out to decide a shortlist. What it
    must never become is the same question twice in the same conversation.
    """
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    assert ledger.may_ask("salary_floor", step="ranking")


def test_subject_declined_twice_is_never_asked_again(ledger: DeclineLedger) -> None:
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    for step in ("constraints", "ranking", "feedback", "application", "a-step-invented-later"):
        assert not ledger.may_ask("salary_floor", step=step)
    assert ledger.silenced() == ["salary_floor"]


def test_two_declines_in_the_same_step_still_count_as_two(ledger: DeclineLedger) -> None:
    """Asked twice, declined twice — the rule is about the person, not the step."""
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:30:00Z")
    assert not ledger.may_ask("salary_floor", step="history")


def test_declining_one_subject_says_nothing_about_another(ledger: DeclineLedger) -> None:
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    assert ledger.may_ask("relocation", step="constraints")


# --- reopening -------------------------------------------------------------


def test_candidate_reopening_a_subject_clears_the_ledger(ledger: DeclineLedger) -> None:
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    assert not ledger.may_ask("salary_floor", step="constraints")

    ledger.reopen("salary_floor", at="2026-08-18T09:00:00Z")
    assert ledger.may_ask("salary_floor", step="constraints")
    assert ledger.silenced() == []


def test_only_reopening_clears_it(ledger: DeclineLedger) -> None:
    """A new step is not permission, and neither is a later timestamp.

    §5.4 says "unless the candidate reopens it", and raising it themselves is
    the only thing that counts as raising it.
    """
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    assert not ledger.may_ask("salary_floor", step="a-completely-new-step")
    assert not ledger.may_ask("salary_floor", step="constraints")


def test_declines_after_a_reopening_count_again(ledger: DeclineLedger) -> None:
    """Reopening is a fresh start, not an exemption."""
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    ledger.reopen("salary_floor", at="2026-08-18T09:00:00Z")
    ledger.decline("salary_floor", step="constraints", at="2026-08-18T09:05:00Z")
    ledger.decline("salary_floor", step="history", at="2026-08-18T09:06:00Z")
    assert not ledger.may_ask("salary_floor", step="traits")


def test_the_ledger_is_append_only(ledger: DeclineLedger) -> None:
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    before = ledger.path.read_bytes()
    ledger.reopen("salary_floor", at="2026-08-18T09:00:00Z")
    assert ledger.path.read_bytes().startswith(before)
    assert len(ledger.entries()) == 2


# --- where it lives --------------------------------------------------------


def test_a_decline_is_not_filed_as_evidence_about_the_candidate(
    ledger: DeclineLedger,
) -> None:
    """ "What do you know about me?" must not come back as a list of refusals.

    §5.4 guarantees that question is answerable at any point; answering it with
    what somebody would not discuss is the opposite of what it is for.
    """
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    log = EvidenceLog(ledger.store)
    assert log.rows() == []
    assert ledger.path.parts[-2] == "session"


def test_one_candidates_ledger_is_not_another_s(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    first = create_profile(root, "Ada Lovelace", language="en")
    second = create_profile(root, "Grace Hopper", language="en")
    DeclineLedger(ProfileStore(root, first.handle)).decline(
        "salary_floor", step="constraints", at="2026-08-17T10:00:00Z"
    )
    assert DeclineLedger(ProfileStore(root, second.handle)).entries() == []
    assert DeclineLedger(ProfileStore(root, second.handle)).may_ask(
        "salary_floor", step="constraints"
    )


# --- shape -----------------------------------------------------------------


def test_a_subject_that_is_not_a_subject_is_refused(ledger: DeclineLedger) -> None:
    with pytest.raises(DeclineError):
        ledger.decline("Salary Floor", step="constraints", at="2026-08-17T10:00:00Z")
    with pytest.raises(DeclineError):
        ledger.may_ask("", step="constraints")


def test_a_malformed_ledger_line_is_reported_with_its_number(
    ledger: DeclineLedger,
) -> None:
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.path.write_text(
        ledger.path.read_text(encoding="utf-8") + '{"subject": "x"}\n', encoding="utf-8"
    )
    with pytest.raises(DeclineError, match=r"declines\.jsonl:2"):
        ledger.entries()


def test_a_missing_ledger_is_an_empty_one_not_an_error(ledger: DeclineLedger) -> None:
    assert ledger.entries() == []
    assert ledger.may_ask("anything", step="constraints")


# --- the gate --------------------------------------------------------------


def test_the_measurement_is_over_attempted_asks(ledger: DeclineLedger) -> None:
    """A ledger that records perfectly and is never consulted still asks.

    So the count is over questions a step tried to put, not over the ledger's
    own state.
    """
    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    offences = count_repeat_asks(
        ledger, [Ask("salary_floor", "traits"), Ask("relocation", "constraints")]
    )
    assert len(offences) == 1
    assert "salary_floor" in offences[0]


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T40.json"
    measured = write_evidence(evidence)
    assert measured["repeat_asks_after_decline"] == 0
    assert measured["asks_evaluated"] >= 8
    assert measured["failures"] == []
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_probe_exercises_both_thresholds_and_the_reopening(tmp_path: Path) -> None:
    result = probe_declines(tmp_path / "profiles")
    assert result["failures"] == []
    assert result["forbidden_asks_detected"] > 0, "the replay must actually catch something"
