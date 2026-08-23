"""S6 — step 12: what an interview taught, and where it landed.

The gate is `interview_lesson_linkage == 1.0`, and the way it could be wrong is
that the writer guarantees it: `log_interview` refuses a linkless record, so a
check that trusted the writer would report 1.0 for a measurement that never
looked. `test_the_linkage_check_would_notice_a_record_written_by_hand` puts a
record on disk with no evidence behind it and requires the fraction to drop and
name it. A gate that cannot fail is not a gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.interview_log import (
    InterviewLogError,
    Lesson,
    Question,
    _write_once,
    lesson_linkage,
    log_interview,
    logged_interviews,
    prepare,
    read_held,
    read_outcome,
    record_outcome,
    rehearsal_lines,
    render_story,
    subject,
)
from integral.lifecycle import (
    PURGE_HORIZON_DAYS,
    has_case_record,
    is_purge_eligible,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import connect_manual
from integral.profile import EvidenceLog, EvidenceRow

NOW = datetime(2026, 8, 18, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


@pytest.fixture
def log(store: ProfileStore) -> EvidenceLog:
    return EvidenceLog(store)


@pytest.fixture
def bank(log: EvidenceLog) -> list[EvidenceRow]:
    """Two episodes, so a lesson has something real to cite."""
    return [
        log.append(
            recorded_at="2026-01-04T09:00:00Z",
            occurred_at="2025-11",
            occurred_precision="month",
            step="history",
            kind="episode",
            dimensions=("on_call_load",),
            text="Rebuilt the on-call rota after a quarter of 2am pages",
            source="conversation",
        ),
        log.append(
            recorded_at="2026-01-04T09:05:00Z",
            step="history",
            kind="episode",
            dimensions=("team_autonomy",),
            text="Ran the migration with nobody reviewing the plan",
            source="conversation",
        ),
    ]


LESSON = Lesson(
    text="they pushed hard on on-call and I had no answer", dimensions=("on_call_load",)
)


def test_every_logged_interview_produces_a_linked_evidence_row(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """The gate itself: the record on disk, against the log on disk."""
    held = log_interview(
        store,
        log,
        offer_id="girona-1",
        held_on="2026-02-10",
        questions=(Question(text="How often were you paged?", dimensions=("on_call_load",)),),
        lessons=(LESSON,),
    )

    measured = lesson_linkage(store, log)
    assert measured["interview_lesson_linkage"] == 1.0
    assert measured["interviews_logged"] == 1
    assert measured["interviews_unlinked"] == []

    (row,) = [r for r in log.effective_rows() if r.id in held.evidence_ids]
    assert row.dimensions == ("on_call_load",)
    assert row.source == "interview"
    assert row.about is not None
    assert row.about.id == f"girona-1/{held.interview_id}"


def test_an_interview_that_taught_nothing_is_refused(store: ProfileStore, log: EvidenceLog) -> None:
    """The refusal is what makes the gate structural rather than aspirational."""
    with pytest.raises(InterviewLogError, match="diary entry"):
        log_interview(
            store,
            log,
            offer_id="girona-1",
            held_on="2026-02-10",
            lessons=(Lesson(text="it went fine I think"),),
        )
    assert logged_interviews(store) == []
    assert log.effective_rows() == []


def test_the_linkage_check_would_notice_a_record_written_by_hand(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """A second record on disk with nothing behind it must drop the fraction.

    The measurement reads files, not the objects that wrote them — which is the
    only reason it can see an interview `log_interview` never wrote.
    """
    log_interview(store, log, offer_id="girona-1", held_on="2026-02-10", lessons=(LESSON,))
    planted = store.path("interviews", "girona-2", "iv-001")
    planted.mkdir(parents=True)
    (planted / "held.json").write_text(
        read_held(store, "girona-1", "iv-001")
        .model_copy(update={"offer_id": "girona-2"})
        .model_dump_json(),
        encoding="utf-8",
    )

    measured = lesson_linkage(store, log)
    assert measured["interview_lesson_linkage"] == 0.5
    assert measured["interviews_unlinked"] == ["girona-2/iv-001"]


def test_no_interviews_at_all_does_not_score_one(store: ProfileStore, log: EvidenceLog) -> None:
    """Null, never 1.0 — D-2's third outcome. A step that recorded nothing has
    not met a gate about what recording teaches."""
    measured = lesson_linkage(store, log)
    assert measured["interview_lesson_linkage"] is None
    assert measured["interviews_logged"] == 0


def test_a_cited_episode_lends_its_dimensions(
    store: ProfileStore, log: EvidenceLog, bank: list[EvidenceRow]
) -> None:
    """ "That story landed badly" is a link too, resolved through the log."""
    held = log_interview(
        store,
        log,
        offer_id="girona-1",
        held_on="2026-02-10",
        lessons=(Lesson(text="the rota story landed badly", stories=(bank[0].id,)),),
    )
    (row,) = [r for r in log.effective_rows() if r.id in held.evidence_ids]
    assert row.dimensions == ("on_call_load",)
    assert lesson_linkage(store, log)["interview_lesson_linkage"] == 1.0


def test_a_lesson_citing_an_episode_nobody_told_us_is_refused(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """A citation that resolves to nothing is the story-bank equivalent of an
    invented claim, and it must not reach the log."""
    with pytest.raises(InterviewLogError, match="not an episode"):
        log_interview(
            store,
            log,
            offer_id="girona-1",
            held_on="2026-02-10",
            lessons=(Lesson(text="that one went well", stories=("ev-999999",)),),
        )
    assert logged_interviews(store) == []


def test_interview_record_is_immutable(store: ProfileStore, log: EvidenceLog) -> None:
    """§3.4: historical. Never revised — a second round takes the next id."""
    first = log_interview(store, log, offer_id="girona-1", held_on="2026-02-10", lessons=(LESSON,))
    second = log_interview(store, log, offer_id="girona-1", held_on="2026-03-02", lessons=(LESSON,))
    assert (first.interview_id, second.interview_id) == ("iv-001", "iv-002")
    assert read_held(store, "girona-1", "iv-001").held_on == "2026-02-10"

    # And a write aimed straight at the file is refused, not merged: `"x"` is
    # the whole of immutability here, so there is no path that rewrites one.
    held_path = store.path("interviews", "girona-1", "iv-001", "held.json")
    before = held_path.read_bytes()
    with pytest.raises(InterviewLogError, match="never revised"):
        _write_once(held_path, read_held(store, "girona-1", "iv-001"))
    assert held_path.read_bytes() == before


def test_outcome_arriving_days_later_resumes_the_record(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """The reply is an append, not an edit: what was recorded on the day stays."""
    held = log_interview(store, log, offer_id="girona-1", held_on="2026-02-10", lessons=(LESSON,))
    assert read_outcome(store, "girona-1", held.interview_id) is None

    outcome = record_outcome(
        store,
        log,
        offer_id="girona-1",
        interview_id=held.interview_id,
        recorded_at="2026-02-14",
        result="rejected",
        note="they went with someone who had run a rota before",
    )
    assert read_outcome(store, "girona-1", held.interview_id) == outcome
    assert read_held(store, "girona-1", held.interview_id) == held

    with pytest.raises(InterviewLogError, match="never revised"):
        record_outcome(
            store,
            log,
            offer_id="girona-1",
            interview_id=held.interview_id,
            recorded_at="2026-02-20",
            result="offer",
        )


def test_an_outcome_for_an_interview_nobody_logged_is_refused(
    store: ProfileStore, log: EvidenceLog
) -> None:
    with pytest.raises(InterviewLogError, match="no record"):
        record_outcome(
            store,
            log,
            offer_id="girona-1",
            interview_id="iv-001",
            recorded_at="2026-02-14",
            result="offer",
        )


def test_an_interview_record_is_never_purged_with_its_offer(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """§7.3's fourth condition, reached through the writer rather than by hand.

    The offer is screened out and older than the horizon, so every other
    condition for purging holds — logging an interview against it is the only
    thing standing between it and deletion.
    """
    old = (NOW - timedelta(days=PURGE_HORIZON_DAYS + 5)).isoformat()
    offer = connect_manual("Night Security Guard, on site. On-call rotation.")
    record = track_new_offer(offer, at=old)
    offer, record = transition(offer, record, "screened_out", at=old)
    save_lifecycle_offer(store, offer, record)
    assert is_purge_eligible(store, offer, record, now=NOW)

    log_interview(store, log, offer_id=offer.id, held_on="2026-02-10", lessons=(LESSON,))

    assert has_case_record(store, offer.id)
    assert not is_purge_eligible(store, offer, record, now=NOW)


def test_preparation_draws_only_from_the_story_bank(
    store: ProfileStore, log: EvidenceLog, bank: list[EvidenceRow]
) -> None:
    """The invent-nothing rule the generated CV is held to (S4/T45).

    Every rehearsal line must be `render_story` over an episode in the bank. A
    dimension the advert presses on that the bank cannot answer is *named as a
    gap*, never filled with a plausible sentence.
    """
    note = prepare(store, log, offer_id="girona-1", presses=("on_call_load", "english_demand"))
    text = note.read_text(encoding="utf-8")

    assert rehearsal_lines(text) == [render_story(bank[0])]
    assert "nothing in the story bank yet" in text
    assert "english_demand" in text
    # The unpressed episode is not rehearsed: preparation is for this employer.
    assert bank[1].text not in text


def test_preparation_is_authored_and_the_record_is_historical(
    store: ProfileStore, log: EvidenceLog, bank: list[EvidenceRow]
) -> None:
    """§3.4's split, asserted where the paths are chosen rather than described."""
    from integral.revision import classify

    note = prepare(store, log, offer_id="girona-1", presses=("on_call_load",))
    held = log_interview(store, log, offer_id="girona-1", held_on="2026-02-10", lessons=(LESSON,))
    held_path = store.path("interviews", "girona-1", held.interview_id, "held.json")

    assert classify(note.relative_to(store.home)) == "authored"
    assert classify(held_path.relative_to(store.home)) == "historical"


def test_earlier_questions_reach_the_next_preparation(
    store: ProfileStore, log: EvidenceLog, bank: list[EvidenceRow]
) -> None:
    """ "What they asked last time" is the whole reason the log exists."""
    log_interview(
        store,
        log,
        offer_id="girona-1",
        held_on="2026-02-10",
        questions=(Question(text="How often were you paged?"),),
        lessons=(LESSON,),
    )
    text = prepare(store, log, offer_id="girona-1", presses=("on_call_load",)).read_text(
        encoding="utf-8"
    )
    assert "How often were you paged?" in text
    assert rehearsal_lines(text) == [render_story(bank[0])]


def test_a_row_about_an_interview_nobody_logged_is_named(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """The mirror of the planted record: a lesson with no interview behind it.

    `interview_lesson_linkage` cannot see this and should not — every record
    that exists still traces. It is a different property, and it matters because
    a row like this would feed step 10's weights from an event with no record.
    """
    log_interview(store, log, offer_id="girona-1", held_on="2026-02-10", lessons=(LESSON,))
    log.append(
        recorded_at="2026-02-11",
        step="interview_log",
        kind="outcome",
        dimensions=("on_call_load",),
        text="something I learned at an interview I never wrote down",
        source="interview",
        about=subject("girona-9", "iv-001"),
    )

    measured = lesson_linkage(store, log)
    assert measured["interview_lesson_linkage"] == 1.0
    assert measured["rows_about_an_interview_with_no_record"] == ["girona-9/iv-001"]


def test_a_record_naming_a_row_that_is_not_its_own_is_named(
    store: ProfileStore, log: EvidenceLog
) -> None:
    """`evidence_ids` is a convenience copy, and it must not be able to lie."""
    held = log_interview(store, log, offer_id="girona-1", held_on="2026-02-10", lessons=(LESSON,))
    held_path = store.path("interviews", "girona-1", held.interview_id, "held.json")
    held_path.write_text(
        held.model_copy(update={"evidence_ids": ("ev-999999",)}).model_dump_json(), encoding="utf-8"
    )

    measured = lesson_linkage(store, log)
    assert measured["records_naming_a_row_that_is_not_theirs"] == [
        f"girona-1/{held.interview_id}: ev-999999"
    ]
