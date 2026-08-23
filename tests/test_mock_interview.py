"""T47 — step 12: the mock interview stays in character until it ends.

The gate is `mock_interview_character_breaks == 0`, and the way it could be
wrong is that the writer guarantees it: `Rehearsal` cannot emit a coaching turn
in character, so a check that trusted the writer would report 0 for a
measurement that never looked.

The teeth are therefore all plants — turns written into a recorded transcript
as raw JSON, which is what a hand edit, a later feature or a second writer
would look like. Each one must move the number *and* name the turn:

* a coaching `question` (the first version scored this 0, because it checked
  the turn's kind and never its words);
* a `silence` that is not silent;
* a `closing` planted early, which used to end the scan and hide everything
  after it;
* an offer id containing a separator, which used to file a transcript where
  the walk never looked.

`test_the_interviewer_vocabulary_is_closed` pins the wording itself, which is
the one thing re-rendering cannot catch: edit a probe into a tip and writer and
reader agree again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.dimensions import load_dimensions
from integral.identity import ProfileStore, create_profile
from integral.mock_interview import (
    ANNOUNCEMENT,
    CLOSING,
    IN_CHARACTER,
    MAX_QUESTIONS,
    VOCABULARY,
    MockInterviewError,
    Rehearsal,
    character_breaks,
    dimension_labels,
    measure,
    next_rehearsal_id,
    rehearsal_subjects,
    render,
    transcript_paths,
)

SUBJECTS = ("on_call_load", "team_autonomy")


@pytest.fixture(scope="session")
def labels() -> dict[str, str]:
    return dimension_labels(load_dimensions())


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def scripted(store: ProfileStore, labels: dict[str, str], offer_id: str = "girona-1") -> Path:
    """One complete role-play, recorded — announce, ask, answer, press, wait, close."""
    session = Rehearsal(offer_id, SUBJECTS, labels)
    session.announce()
    while session.ask() is not None:
        session.answer("I did the thing.")
        session.press()
        session.wait()
    session.close()
    session.feedback(("The second answer had no story behind it.",))
    return session.save(store)


def edit(path: Path, turns: list[dict[str, object]]) -> None:
    """Write turns back as raw JSON — what a hand edit or a second writer does."""
    recorded = json.loads(path.read_text(encoding="utf-8"))
    recorded["turns"] = turns
    path.write_text(json.dumps(recorded), encoding="utf-8")


def turns_of(path: Path) -> list[dict[str, object]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["turns"])


# ---------------------------------------------------------------------------
# the three the task names


def test_no_coaching_turn_occurs_inside_the_roleplay(
    store: ProfileStore, labels: dict[str, str]
) -> None:
    """The gate itself, read off the transcript on disk."""
    scripted(store, labels)

    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 0
    assert measured["sessions_rehearsed"] == 1
    assert measured["character_breaks"] == []

    turns = turns_of(transcript_paths(store)[0])
    inside = turns[1 : [turn["kind"] for turn in turns].index("closing")]
    assert inside, "the scripted session rehearsed nothing"
    for turn in inside:
        assert turn["kind"] in IN_CHARACTER[str(turn["speaker"])]
        if turn["speaker"] == "interviewer":
            assert turn["text"] == render(str(turn["kind"]), str(turn["form"]), labels)


def test_roleplay_is_announced_before_it_begins(
    store: ProfileStore, labels: dict[str, str]
) -> None:
    """Nothing in character can be produced until the announcement has been made."""
    session = Rehearsal("girona-1", SUBJECTS, labels)
    with pytest.raises(MockInterviewError, match="cannot ask while the rehearsal is 'opening'"):
        session.ask()

    turn = session.announce()
    assert "I am the interviewer" in turn.text
    assert "dictate" in turn.text, "step 12 requires dictation to be offered"
    assert session.ask() is not None

    scripted(store, labels, "girona-2")
    assert turns_of(transcript_paths(store)[0])[0]["kind"] == "announcement"
    assert character_breaks(store)["sessions_not_announced"] == []


def test_feedback_is_given_only_after_it_ends(store: ProfileStore, labels: dict[str, str]) -> None:
    """Feedback has no phase to happen in until the role-play is closed."""
    session = Rehearsal("girona-1", SUBJECTS, labels)
    session.announce()
    session.ask()
    with pytest.raises(MockInterviewError, match="cannot give feedback"):
        session.feedback(("You rambled there.",))

    session.answer("I did the thing.")
    session.close()
    assert session.feedback(("You rambled there.",))[0].kind == "feedback"

    path = session.save(store)
    kinds = [turn["kind"] for turn in turns_of(path)]
    assert kinds.index("closing") < kinds.index("feedback")
    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 0
    assert measured["turns_after_the_end_that_are_not_feedback"] == []


# ---------------------------------------------------------------------------
# teeth — each plant must move the number and name the turn


def test_a_planted_coaching_turn_is_named(store: ProfileStore, labels: dict[str, str]) -> None:
    """A kind this module cannot produce at all."""
    path = scripted(store, labels)
    turns = turns_of(path)
    turns.insert(
        3,
        {
            "kind": "coaching",
            "speaker": "interviewer",
            "form": "",
            "text": "Good start — try leading with the outcome next time.",
        },
    )
    edit(path, turns)

    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 1
    assert measured["character_breaks"] == [
        "girona-1/rh-001: turn 3 is 'coaching' from the interviewer"
    ]


def test_a_coaching_question_is_named_even_though_its_kind_is_a_question(
    store: ProfileStore, labels: dict[str, str]
) -> None:
    """F1(a): the turn kind was never the thing worth constraining.

    A `question` whose wording is a STAR tip plus encouragement has an entirely
    legitimate kind, an entirely legitimate speaker, and is not a question this
    module can ask. The first version of the gate scored it 0.
    """
    path = scripted(store, labels)
    turns = turns_of(path)
    turns[1]["text"] = (
        "Great start! Tell me about on-call — remember to use STAR, and lead with the outcome."
    )
    edit(path, turns)

    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 1
    assert measured["character_breaks"] == [
        "girona-1/rh-001: turn 1 is 'question' from the interviewer, "
        "and not in the interviewer's words"
    ]


def test_the_interviewer_cannot_be_handed_words_to_say(labels: dict[str, str]) -> None:
    """F1(a) at the source: a subject is a dimension id, so prose has no way in."""
    with pytest.raises(MockInterviewError, match="cannot ask about"):
        Rehearsal("girona-1", ("Remember to use STAR — strong start!",), labels)


def test_a_silence_that_is_not_silent_is_named(store: ProfileStore, labels: dict[str, str]) -> None:
    """F1(b): the silence after an answer is the exercise, so it is pinned to empty."""
    path = scripted(store, labels)
    turns = turns_of(path)
    silence = next(i for i, turn in enumerate(turns) if turn["kind"] == "silence")
    turns[silence]["text"] = "Take your time — that was a strong start. Remember to use STAR."
    edit(path, turns)

    measured = character_breaks(store)
    assert measured["mock_interview_character_breaks"] == 1
    assert "not in the interviewer's words" in measured["character_breaks"][0]


def test_the_interviewer_vocabulary_is_closed() -> None:
    """F1(b): what re-rendering cannot catch is the wording itself being rewritten.

    Editing a probe into a tip makes writer and reader agree again, so the only
    defence is that the whole vocabulary is finite and written down here. This
    test failing means somebody changed what the interviewer can say — which is
    allowed, and has to be a decision rather than a slip.
    """
    assert VOCABULARY == (
        "From here I am the interviewer and nothing else: no coaching, no encouragement, "
        "no stepping out to explain a question. It ends when it ends, and the feedback "
        "comes then. You can dictate your answers out loud instead of typing them — "
        "speaking one is much closer to the real thing.",
        "That is the end of the interview. Thank you for your time.",
        "Walk me through a time {label} was what decided how the work went.",
        "When was that, and over how long?",
        "Who else was in the room when that was decided?",
        "What would you do differently now?",
        "",
    )
    assert VOCABULARY[0] == ANNOUNCEMENT
    assert VOCABULARY[1] == CLOSING


def test_a_closing_planted_early_does_not_blind_the_scan(
    store: ProfileStore, labels: dict[str, str]
) -> None:
    """F3: the whole array is examined, not the prefix before the first closing.

    Ending the scan at `kinds.index("closing")` made one planted turn at index 1
    hide every turn after it — a blind spot exactly where a smuggler would aim.
    """
    path = scripted(store, labels)
    turns = turns_of(path)
    turns.insert(1, {"kind": "closing", "speaker": "interviewer", "form": "", "text": CLOSING})
    turns.insert(
        2,
        {
            "kind": "coaching",
            "speaker": "interviewer",
            "form": "",
            "text": "Between us — lead with the outcome.",
        },
    )
    edit(path, turns)

    measured = character_breaks(store)
    out_of_place = measured["turns_after_the_end_that_are_not_feedback"]
    # Everything from the planted closing to the end, bar the one real feedback
    # turn: the announcement, the planted closing and the feedback are the three
    # not named, and the coaching turn plus every original turn is.
    assert len(out_of_place) == len(turns) - 3
    assert "girona-1/rh-001: turn 2 is 'coaching' from the interviewer" in out_of_place
    assert f"girona-1/rh-001: turn {len(turns) - 2} is 'closing' from the interviewer" in (
        out_of_place
    ), "the scan reached the far end of the transcript, not just past the plant"
    assert measured["sessions_never_closed"] == []


def test_an_announcement_the_interviewer_did_not_make_is_named(
    store: ProfileStore, labels: dict[str, str]
) -> None:
    """The boundary turn is itself scanned, speaker included.

    A forged first turn carrying `kind="announcement"` and the exact wording,
    but spoken by the *candidate*, used to satisfy the check and advance the
    scan past itself — so a role-play the interviewer never announced measured
    clean. Same shape as the planted `closing`: a turn that decides how much
    gets read must not be the one thing nobody reads.
    """
    path = scripted(store, labels)
    turns = turns_of(path)
    turns[0] = {
        "kind": "announcement",
        "speaker": "candidate",
        "form": "",
        "text": ANNOUNCEMENT,
    }
    edit(path, turns)

    measured = character_breaks(store)
    assert measured["sessions_not_announced"] == [
        "girona-1/rh-001: the role-play is not announced before it begins"
    ]
    # And, because `start` no longer advances past it, the forged turn is held
    # to the in-character vocabulary like every other turn.
    assert measured["character_breaks"] == [
        "girona-1/rh-001: turn 0 is 'announcement' from the candidate"
    ]


def test_an_offer_id_with_a_separator_is_refused(labels: dict[str, str]) -> None:
    """F4: a transcript the walk cannot find is a rehearsal that cannot fail."""
    for offer_id in ("infojobs/1234", "..", "a/.."):
        with pytest.raises(MockInterviewError, match="not a usable offer id"):
            Rehearsal(offer_id, SUBJECTS, labels)


def test_an_over_cap_transcript_is_named(store: ProfileStore, labels: dict[str, str]) -> None:
    """F5: no advert in the corpus presses on eleven, so the cap is planted here."""
    path = scripted(store, labels)
    turns = turns_of(path)
    question = next(turn for turn in turns if turn["kind"] == "question")
    edit(path, turns + [dict(question) for _ in range(MAX_QUESTIONS)])

    assert character_breaks(store)["sessions_over_the_question_cap"] == [
        f"girona-1/rh-001: {MAX_QUESTIONS + 2} questions rehearsed, and the cap is {MAX_QUESTIONS}"
    ]


def test_a_transcript_that_never_ends_is_a_defect(
    store: ProfileStore, labels: dict[str, str]
) -> None:
    """Never closing keeps the tool in character for ever — the mirror failure."""
    path = scripted(store, labels)
    edit(path, [turn for turn in turns_of(path) if turn["kind"] != "closing"])

    measured = character_breaks(store)
    assert measured["sessions_never_closed"] == [
        "girona-1/rh-001: the role-play never ends, so nothing is ever out of character"
    ]
    # The feedback now falls inside the role-play, which is exactly a break.
    assert measured["mock_interview_character_breaks"] == 1


def test_an_unannounced_transcript_is_named(store: ProfileStore, labels: dict[str, str]) -> None:
    path = scripted(store, labels)
    edit(path, turns_of(path)[1:])

    assert character_breaks(store)["sessions_not_announced"] == [
        "girona-1/rh-001: the role-play is not announced before it begins"
    ]


def test_an_edited_announcement_is_a_break(store: ProfileStore, labels: dict[str, str]) -> None:
    """F6's replacement for a `dictation_offered` flag nothing read.

    Whether dictation was offered is a property of the announcement's wording,
    and the wording is re-rendered — so dropping the offer is a finding rather
    than a boolean somebody can set either way.
    """
    path = scripted(store, labels)
    turns = turns_of(path)
    turns[0]["text"] = ANNOUNCEMENT.replace(
        " You can dictate your answers out loud instead of typing them —"
        " speaking one is much closer to the real thing.",
        "",
    )
    edit(path, turns)

    assert character_breaks(store)["sessions_not_announced"] == [
        "girona-1/rh-001: the announcement is not the one this module makes"
    ]


# ---------------------------------------------------------------------------
# the cap, the ids, and D-2


def test_ten_questions_is_a_hard_cap(labels: dict[str, str]) -> None:
    """`rehearsal_subjects` truncates; building a longer session is refused."""
    many = tuple(labels)[: MAX_QUESTIONS + 3]
    assert len(many) == MAX_QUESTIONS + 3, "the model has enough dimensions to overrun the cap"
    with pytest.raises(MockInterviewError, match="caps a rehearsal at 10"):
        Rehearsal("girona-1", many, labels)
    assert len(rehearsal_subjects(many, labels)) == MAX_QUESTIONS


def test_questions_come_from_what_the_advert_presses_on(labels: dict[str, str]) -> None:
    presses = ("on_call_load", "not_a_dimension", "team_autonomy")
    assert rehearsal_subjects(presses, labels) == ("on_call_load", "team_autonomy")


def test_rehearsal_ids_do_not_collide(store: ProfileStore, labels: dict[str, str]) -> None:
    scripted(store, labels)
    assert next_rehearsal_id(store, "girona-1") == "rh-002"
    scripted(store, labels)
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
    assert measured["turns_after_the_end_that_are_not_feedback"] == []
