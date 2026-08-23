"""T47 — step 12: the mock interview stays in character until it ends.

The gate is `mock_interview_character_breaks == 0`, and the way it could be
wrong is that the writer guarantees it: `Rehearsal` cannot emit a coaching turn
in character, so a check that trusted the writer would report 0 for a
measurement that never looked.
`test_the_gate_would_notice_a_coaching_turn_planted_in_a_transcript` writes one
into a recorded transcript on disk and requires the count to rise and name the
turn. A gate that cannot fail is not a gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.interview_log import Question
from integral.mock_interview import (
    IN_CHARACTER,
    MAX_QUESTIONS,
    MockInterviewError,
    Rehearsal,
    character_breaks,
    measure,
    next_rehearsal_id,
    rehearsal_questions,
    transcript_paths,
)

QUESTIONS = (
    Question(
        text="Walk me through a time on-call load decided the work.", dimensions=("on_call_load",)
    ),
    Question(
        text="Walk me through a time autonomy decided the work.", dimensions=("team_autonomy",)
    ),
)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def scripted(store: ProfileStore, offer_id: str = "girona-1") -> Path:
    """One complete role-play, recorded — announce, ask, answer, press, wait, close."""
    session = Rehearsal(offer_id, QUESTIONS)
    session.announce()
    while session.ask() is not None:
        session.answer("I did the thing.")
        session.press()
        session.wait()
    session.close()
    session.feedback(("The second answer had no story behind it.",))
    return session.save(store)


# ---------------------------------------------------------------------------
# the three the task names


def test_no_coaching_turn_occurs_inside_the_roleplay(store: ProfileStore) -> None:
    """The gate itself, read off the transcript on disk."""
    scripted(store)

    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 0
    assert measured["sessions_rehearsed"] == 1
    assert measured["character_breaks"] == []

    recorded = json.loads(transcript_paths(store)[0].read_text(encoding="utf-8"))
    inside = recorded["turns"][1:-2]  # between the announcement and the closing
    assert inside, "the scripted session rehearsed nothing"
    for turn in inside:
        assert turn["kind"] in IN_CHARACTER[turn["speaker"]]


def test_roleplay_is_announced_before_it_begins(store: ProfileStore) -> None:
    """Nothing in character can be produced until the announcement has been made."""
    session = Rehearsal("girona-1", QUESTIONS)
    with pytest.raises(MockInterviewError, match="cannot ask while the rehearsal is 'opening'"):
        session.ask()

    turn = session.announce()
    assert "I am the interviewer" in turn.text
    assert "dictate" in turn.text, "step 12 requires dictation to be offered"
    assert session.ask() is not None

    scripted(store, "girona-2")
    recorded = json.loads(transcript_paths(store)[0].read_text(encoding="utf-8"))
    assert recorded["turns"][0]["kind"] == "announcement"
    assert character_breaks(store)["sessions_not_announced"] == []


def test_feedback_is_given_only_after_it_ends(store: ProfileStore) -> None:
    """Feedback has no phase to happen in until the role-play is closed."""
    session = Rehearsal("girona-1", QUESTIONS)
    session.announce()
    session.ask()
    with pytest.raises(MockInterviewError, match="cannot give feedback"):
        session.feedback(("You rambled there.",))

    session.answer("I did the thing.")
    session.close()
    assert session.feedback(("You rambled there.",))[0].kind == "feedback"

    path = session.save(store)
    kinds = [turn["kind"] for turn in json.loads(path.read_text(encoding="utf-8"))["turns"]]
    assert kinds.index("closing") < kinds.index("feedback")
    assert character_breaks(store)["mock_interview_character_breaks"] == 0


# ---------------------------------------------------------------------------
# teeth


def test_the_gate_would_notice_a_coaching_turn_planted_in_a_transcript(
    store: ProfileStore,
) -> None:
    """Plant what `Rehearsal` cannot emit, and require the gate to name it.

    Written as raw JSON precisely because the schema would refuse it: a gate
    that could only see turns its own writer produced would be checking nothing.
    """
    path = scripted(store)
    recorded = json.loads(path.read_text(encoding="utf-8"))
    recorded["turns"].insert(
        3,
        {
            "kind": "coaching",
            "speaker": "interviewer",
            "text": "Good start — try leading with the outcome next time.",
        },
    )
    path.write_text(json.dumps(recorded), encoding="utf-8")

    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 1
    assert measured["character_breaks"] == [
        "girona-1/rh-001: turn 3 is 'coaching' from the interviewer"
    ]


def test_a_transcript_that_never_ends_is_a_defect(store: ProfileStore) -> None:
    """Never closing keeps the tool in character for ever — the mirror failure."""
    path = scripted(store)
    recorded = json.loads(path.read_text(encoding="utf-8"))
    recorded["turns"] = [turn for turn in recorded["turns"] if turn["kind"] != "closing"]
    path.write_text(json.dumps(recorded), encoding="utf-8")

    measured = character_breaks(store)
    assert measured["sessions_never_closed"] == [
        "girona-1/rh-001: the role-play never ends, so nothing is ever out of character"
    ]
    # The feedback now falls inside the role-play, which is exactly a break.
    assert measured["mock_interview_character_breaks"] == 1


def test_an_unannounced_transcript_is_named(store: ProfileStore) -> None:
    path = scripted(store)
    recorded = json.loads(path.read_text(encoding="utf-8"))
    recorded["turns"] = recorded["turns"][1:]
    path.write_text(json.dumps(recorded), encoding="utf-8")

    assert character_breaks(store)["sessions_not_announced"] == [
        "girona-1/rh-001: the role-play is not announced before it begins"
    ]


# ---------------------------------------------------------------------------
# the cap, the ids, and D-2


def test_ten_questions_is_a_hard_cap(store: ProfileStore) -> None:
    """`rehearsal_questions` truncates; building a longer session is refused."""
    many = tuple(
        Question(text=f"question {index}", dimensions=("on_call_load",))
        for index in range(MAX_QUESTIONS + 3)
    )
    with pytest.raises(MockInterviewError, match="caps a rehearsal at 10"):
        Rehearsal("girona-1", many)


def test_questions_come_from_what_the_advert_presses_on() -> None:
    from integral.dimensions import load_dimensions

    dimensions = load_dimensions()
    presses = tuple(dimension.id for dimension in dimensions)[: MAX_QUESTIONS + 5]
    questions = rehearsal_questions(presses, dimensions)

    assert len(questions) <= MAX_QUESTIONS
    assert all(question.dimensions[0] in presses for question in questions)


def test_rehearsal_ids_do_not_collide(store: ProfileStore) -> None:
    scripted(store)
    assert next_rehearsal_id(store, "girona-1") == "rh-002"
    scripted(store)
    assert [path.stem for path in transcript_paths(store)] == ["rh-001", "rh-002"]


def test_no_rehearsal_scores_none_not_zero(store: ProfileStore) -> None:
    """D-2: a profile that never entered character has not stayed in it."""
    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] is None
    assert measured["sessions_rehearsed"] == 0


def test_the_measurement_runs_over_the_corpus() -> None:
    """The gate as `_main` computes it — real adverts, fixture candidate."""
    measured = measure()
    assert measured["mock_interview_character_breaks"] == 0
    assert measured["sessions_rehearsed"] > 0
    assert measured["sessions_over_the_question_cap"] == []
