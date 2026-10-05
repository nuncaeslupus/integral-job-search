"""T239 — a lesson learned in one candidate's session has a route to the process.

The gate is `candidate_session_corrections_left_untriaged == 0`: every lesson a
session recorded ends the session either seeded as a task or kept as
candidate-specific, with the decision on file. The second property is that the
task carries the rule and never the candidate's words.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.lesson_triage import (
    LessonError,
    LessonLedger,
    _main,
    render_session,
)
from integral.profile import EvidenceLog

AT = "2026-10-05T10:00:00+00:00"
SAID = "I never want my cover letter to mention the redundancy at my last employer"


def _store(tmp_path: Path, name: str = "Marta Quintana") -> ProfileStore:
    identity = create_profile(tmp_path, name)
    return ProfileStore(tmp_path, identity.handle)


def _say(store: ProfileStore, text: str) -> str:
    row = EvidenceLog(store).append(
        recorded_at=AT, step="step-11-application", kind="statement", text=text,
        source="conversation",
    )  # fmt: skip
    return row.id


def _ledger(tmp_path: Path) -> tuple[LessonLedger, ProfileStore]:
    store = _store(tmp_path)
    _say(store, SAID)
    return LessonLedger(store), store


RULE = "A cover letter never names why a previous role ended"


def test_a_session_lists_every_lesson_it_recorded_and_only_its_own(tmp_path: Path) -> None:
    ledger, _ = _ledger(tmp_path)
    a = ledger.record(RULE, session_id="s1", step="step-11-application", at=AT)
    ledger.record("Gap wording says dates and not reasons", session_id="s2", step="s", at=AT)
    assert [lesson.id for lesson in ledger.lessons("s1")] == [a.id]
    assert [lesson.id for lesson in ledger.untriaged("s1")] == [a.id]
    assert a.id in render_session(ledger, "s1") and "UNDECIDED" in render_session(ledger, "s1")
    assert "ls-0002" not in render_session(ledger, "s1")


def test_each_decision_clears_the_lesson_and_is_kept(tmp_path: Path) -> None:
    ledger, store = _ledger(tmp_path)
    one = ledger.record(RULE, session_id="s1", step="a", at=AT)
    two = ledger.record("Gap wording says dates and not reasons", session_id="s1", step="a", at=AT)
    ledger.decide(one.id, "seeded", at=AT, task_id="t-0123abcd")
    assert [lesson.id for lesson in ledger.untriaged("s1")] == [two.id]
    ledger.decide(two.id, "candidate_specific", at=AT, reason="turns on her own visa")
    assert ledger.untriaged("s1") == []
    # The decision survives a fresh reader: it is a file, not memory.
    again = LessonLedger(ProfileStore(store.root, store.handle))
    assert again.untriaged("s1") == []
    text = render_session(again, "s1")
    assert "seeded as t-0123abcd" in text and "candidate-specific (turns on her own visa)" in text


def test_a_decision_is_not_overwritable(tmp_path: Path) -> None:
    ledger, _ = _ledger(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step="a", at=AT)
    ledger.decide(lesson.id, "candidate_specific", at=AT, reason="her own case")
    with pytest.raises(LessonError, match="already has a decision"):
        ledger.decide(lesson.id, "seeded", at=AT, task_id="t-0123abcd")
    with pytest.raises(LessonError, match="not re-opened"):
        ledger.seed_spec(lesson.id)


def test_a_decision_needs_its_evidence(tmp_path: Path) -> None:
    ledger, _ = _ledger(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step="a", at=AT)
    for bad in (None, "", "TASK-1", "t-xyz"):
        with pytest.raises(LessonError):
            ledger.decide(lesson.id, "seeded", at=AT, task_id=bad)
    for reason in (None, "", "   "):
        with pytest.raises(LessonError):
            ledger.decide(lesson.id, "candidate_specific", at=AT, reason=reason)
    with pytest.raises(LessonError, match="no lesson"):
        ledger.decide("ls-9999", "candidate_specific", at=AT, reason="x")
    assert len(ledger.untriaged("s1")) == 1


def test_the_seeded_task_carries_the_rule_and_the_step_and_nothing_else(tmp_path: Path) -> None:
    ledger, store = _ledger(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step="step-11-application", at=AT)
    spec = ledger.seed_spec(lesson.id)
    blob = " ".join(spec.command())
    assert RULE in spec.body and "step-11-application" in spec.body
    for private in (SAID, store.handle, "Marta", "redundancy", "s1"):
        assert private not in blob


def test_a_rule_that_repeats_the_candidates_words_is_refused(tmp_path: Path) -> None:
    ledger, _ = _ledger(tmp_path)
    for leaky in (
        "Do not mention the redundancy at my last employer",  # a 4-word run
        "never mention THE REDUNDANCY AT my last employer, ever",  # case and punctuation differ
        "Remember: Marta Quintana wants no dates",  # the name
        "Handle marta-quintana's gaps gently",  # the handle, as a word run
    ):
        with pytest.raises(LessonError):
            ledger.record(leaky, session_id="s1", step="a", at=AT)
    assert ledger.lessons() == []


def test_a_retracted_row_is_still_the_candidates_and_still_guarded(tmp_path: Path) -> None:
    ledger, store = _ledger(tmp_path)
    secret = "my landlord evicted me from the flat in Girona"
    row_id = _say(store, secret)
    EvidenceLog(store).append(
        recorded_at=AT, step="x", kind="retraction", text="forget that",
        source="conversation", retracts=row_id,
    )  # fmt: skip
    with pytest.raises(LessonError):
        ledger.record(
            "A landlord evicted me from the flat is not a reason",
            session_id="s1", step="a", at=AT,
        )  # fmt: skip


def test_the_guard_is_rechecked_when_the_task_is_made(tmp_path: Path) -> None:
    ledger, store = _ledger(tmp_path)
    lesson = ledger.record(RULE, session_id="s1", step="a", at=AT)
    # The candidate later says the rule's own words; the lesson can no longer leave.
    _say(store, "honestly a cover letter never names why a previous role ended for me")
    with pytest.raises(LessonError, match="cannot leave"):
        ledger.seed_spec(lesson.id)


def test_legitimate_rules_are_not_refused(tmp_path: Path) -> None:
    ledger, _ = _ledger(tmp_path)
    # Shares only short phrases with the evidence ("cover letter", "my last") — a rule may.
    ledger.record("A cover letter states dates, never reasons", session_id="s1", step="a", at=AT)
    with pytest.raises(LessonError, match="at least"):
        ledger.record("no dates", session_id="s1", step="a", at=AT)


def test_a_malformed_ledger_is_an_error_not_an_empty_list(tmp_path: Path) -> None:
    ledger, store = _ledger(tmp_path)
    ledger.record(RULE, session_id="s1", step="a", at=AT)
    store.path("session", "lessons.jsonl").write_text('{"row": "lesson"}\n', encoding="utf-8")
    with pytest.raises(LessonError, match="not a ledger row"):
        ledger.untriaged("s1")


def test_the_end_of_session_check_fails_until_every_lesson_is_decided(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, store = _ledger(tmp_path)
    base = ["x", "--root", str(tmp_path), "--handle", store.handle]
    assert _main([*base, "check", "--session", "s1"]) == 0  # no lessons: nothing to triage
    assert _main([*base, "record", "--session", "s1", "--step", "a", "--rule", RULE]) == 0
    assert _main([*base, "check", "--session", "s1"]) == 1
    assert _main([*base, "decide", "ls-0001", "candidate_specific", "--reason", "visa"]) == 0
    assert _main([*base, "check", "--session", "s1"]) == 0
    assert _main([*base, "decide", "ls-0001", "seeded", "--task", "t-0123abcd"]) == 2
    assert "already has a decision" in capsys.readouterr().err


def test_a_handle_that_is_not_the_name_is_guarded_too(tmp_path: Path) -> None:
    identity = create_profile(tmp_path, "Marta Quintana", handle="mq-2026")
    ledger = LessonLedger(ProfileStore(tmp_path, identity.handle))
    with pytest.raises(LessonError, match="name or handle"):
        ledger.record("mq-2026 wants gaps worded gently", session_id="s1", step="a", at=AT)
    with pytest.raises(LessonError, match="name or handle"):
        ledger.record("Marta Quintana wants gaps worded gently", session_id="s1", step="a", at=AT)
