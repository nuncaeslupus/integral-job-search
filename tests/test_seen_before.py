"""T250 — an advert the candidate has seen, shortlisted, applied to or rejected is
not presented as new because another board worded it differently.

Verdicts are derived from the task text (each offer is compared by employer and
title similarity against every offer previously shown, shortlisted, applied to
or rejected, across boards; what was shown is recorded; matches are withheld and
counted) and from `same_vacancy`'s stated rule, never from running the code.
Every withhold case has a control that must stay shown: hiding an advert the
candidate never saw costs as much as re-showing one they did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.feedback import record_decision
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import record_application_status, save_lifecycle_offer, track_new_offer
from integral.offers import Offer, OfferStatus, compute_offer_id
from integral.presentation_log import (
    REASON_APPLIED,
    REASON_SHORTLISTED,
    REASON_SHOWN,
    partition,
    present,
    rule_out,
    unchecked_line,
    withheld_line,
)
from integral.same_vacancy import TITLE_THRESHOLD, employer_key, same_vacancy, title_similarity

_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    return ProfileStore(root, "fixture")


def _save(
    store: ProfileStore,
    text: str,
    *,
    title: str | None,
    company: str | None,
    url: str | None = None,
    source: str = "board-a",
) -> str:
    offer = Offer(
        id=compute_offer_id(text),
        source=source,
        url=url or f"https://{source}.example/{abs(hash(text))}",
        title=title,
        company=company,
        text=text,
    )
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    return offer.id


# --- the rule, pinned by pairs ------------------------------------------------

# Same role, worded differently by two boards. (title on board A, title on board B)
SAME_ROLE = [
    ("Backend Engineer", "Backend Developer"),
    ("Software Engineer, Backend", "Backend Software Engineer"),
    ("Data Engineer (m/w/d)", "Data Engineer - Remote"),
    ("Desarrollador Backend", "Back-end Developer"),
    ("Sr. Backend Engineer", "Senior Backend Engineer"),
    ("Full Stack Developer", "Fullstack Developer"),
    ("Product Manager", "Product Manager (Hybrid)"),
    ("Frontend Engineer React", "React Front-end Engineer"),
    ("Senior Python Developer", "Python Engineer (Senior) (m/f/d)"),
    ("Senior Data Engineer Spark", "Data Engineer Senior Spark Scala"),  # the boundary: 3/4
]

# Same employer, different role: a never-seen advert that must be shown.
DIFFERENT_ROLE = [
    ("Backend Engineer", "Frontend Engineer"),
    ("Data Engineer", "Data Scientist"),
    ("Data Analyst", "Data Engineer"),
    ("Backend Engineer", "Backend Engineering Manager"),
    ("Junior Backend Engineer", "Senior Backend Engineer"),
    ("Backend Engineer", "Senior Backend Engineer"),
    ("Engineer II", "Engineer III"),
    ("Product Manager", "Product Designer"),
    ("Python Developer", "Java Developer"),
    ("Sales Engineer", "Software Engineer"),
    ("Machine Learning Engineer", "Machine Learning Researcher"),
    ("Backend Engineer", "Backend Engineer Platform Infrastructure"),  # the boundary: 2/4
]

# A number on one side only is a salary, a year or a percentage: same role.
NUMBER_ON_ONE_SIDE = [
    ("Backend Engineer \u2013 60.000\u20ac", "Backend Engineer"),
    ("Backend Engineer (2026)", "Backend Engineer"),
    ("Backend Engineer 100% remote", "Backend Engineer"),
    ("Backend Engineer II", "Backend Engineer"),
]
# A number on both sides that disagrees is a grade or a different posting.
NUMBERS_DISAGREE = [
    ("Engineer II", "Engineer III"),
    ("Engineer 2", "Engineer 3"),
    ("Backend Engineer (2025)", "Backend Engineer (2026)"),
]


@pytest.mark.parametrize(("a", "b"), SAME_ROLE)
def test_the_same_role_in_another_boards_words_is_the_same_vacancy(a: str, b: str) -> None:
    assert same_vacancy("Haddock", a, "Haddock", b)
    assert same_vacancy("Haddock", b, "Haddock", a)  # symmetric


@pytest.mark.parametrize(("a", "b"), DIFFERENT_ROLE)
def test_a_different_role_at_the_same_employer_is_not(a: str, b: str) -> None:
    assert not same_vacancy("Haddock", a, "Haddock", b)


def test_the_threshold_sits_inside_the_gap_between_the_two_populations() -> None:
    """The threshold is justified by the data and pinned against it: the lowest
    same-role score is the threshold itself and the highest different-role score
    is strictly below it, so moving the constant either way breaks a pair above."""
    same = [title_similarity(a, b) for a, b in SAME_ROLE]
    different = [title_similarity(a, b) for a, b in DIFFERENT_ROLE]
    assert min(same) == TITLE_THRESHOLD == 0.75
    assert max(different) == 0.5 < TITLE_THRESHOLD


@pytest.mark.parametrize(("a", "b"), NUMBER_ON_ONE_SIDE)
def test_a_number_on_one_title_only_is_ignored(a: str, b: str) -> None:
    assert same_vacancy("Cala", a, "Cala", b)
    assert same_vacancy("Cala", b, "Cala", a)


@pytest.mark.parametrize(("a", "b"), NUMBERS_DISAGREE)
def test_numbers_on_both_titles_must_agree(a: str, b: str) -> None:
    assert not same_vacancy("Cala", a, "Cala", b)
    assert same_vacancy("Cala", a, "Cala", a)


@pytest.mark.parametrize(
    "title",
    ["Backend Engineer (all genders)", "Backend Engineer (m/w/divers)", "Backend Engineer (m/f/d)"],
)
def test_gender_markers_are_dropped(title: str) -> None:
    assert same_vacancy("Cala", title, "Cala", "Backend Engineer")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Cala", "Cala S. L."),
        ("Foo", "Foo GmbH & Co. KG"),
        ("Foo", "Foo SAS"),
        ("Foo", "Foo S.L.L."),
        ("Foo", "Foo Pty Ltd"),
    ],
)
def test_trailing_legal_forms_are_stripped(a: str, b: str) -> None:
    assert same_vacancy(a, "Backend Engineer", b, "Backend Engineer")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Spa Resort Group", "Resort Group"),
        ("SA Power Networks", "Power Networks"),
        ("AB Foods", "Foods"),
        ("Co-op", "Op"),
    ],
)
def test_a_legal_form_word_inside_a_name_is_part_of_the_name(a: str, b: str) -> None:
    assert not same_vacancy(a, "Backend Engineer", b, "Backend Engineer")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Haddock", "Haddock S.L."),
        ("Valeria HR", "VALERIA  HR, S.L.U."),
        ("Cala", "cala"),
        ("\uff21\uff23\uff2d\uff25", "ACME GmbH"),  # fullwidth, NFKC
        ("Ac\u200bme", "Acme"),  # zero-width space (Cf)
        ("Café", "Cafe Ltd"),
    ],
)
def test_one_employer_under_different_decoration(a: str, b: str) -> None:
    assert same_vacancy(a, "Backend Engineer", b, "Backend Engineer")


@pytest.mark.parametrize(
    ("a", "b"),
    [("Cala", "Cala Health"), ("Haddock", "Haddock Labs"), ("Acme", "Acne")],
)
def test_two_employers_with_similar_names_are_two_employers(a: str, b: str) -> None:
    assert not same_vacancy(a, "Backend Engineer", b, "Backend Engineer")


@pytest.mark.parametrize("blank", [None, "", "   ", "​", "S.L."])
def test_a_blank_employer_matches_nothing_not_even_another_blank(blank: str | None) -> None:
    assert employer_key(blank) is None
    assert not same_vacancy(blank, "Backend Engineer", blank, "Backend Engineer")
    assert not same_vacancy(blank, "Backend Engineer", "Acme", "Backend Engineer")
    assert not same_vacancy("Acme", "Backend Engineer", blank, "Backend Engineer")


@pytest.mark.parametrize("title", [None, "", "  ", "(m/f/d)", "Remote"])
def test_a_title_with_no_significant_word_matches_nothing(title: str | None) -> None:
    assert not same_vacancy("Acme", title, "Acme", title)


# --- the round: across boards, every kind of prior record withholds -----------


def _prior(store: ProfileStore, how: str) -> str:
    """One offer from board A in each state the task names."""
    prior = _save(store, f"prior {how}", title="Python Developer", company="Haddock S.L.")
    if how == "shown":
        present(store, [prior], at=_AT)
    elif how == "shortlisted":
        record_decision(store, prior, "shortlisted", at=_AT, reason=None)
    elif how == "applied":
        record_decision(store, prior, "shortlisted", at=_AT, reason=None)
        record_decision(store, prior, "applied", at=_AT, reason=None)
    elif how == "rejected":
        record_decision(store, prior, "screened_out", at=_AT, reason="no me interesa")
    elif how == "application record only":
        record_application_status(store, prior, status="applied", at=_AT)
    return prior


_EXPECTED_REASON = {
    "shown": REASON_SHOWN,
    "shortlisted": REASON_SHORTLISTED,
    "applied": REASON_APPLIED,
    "rejected": "no me interesa",
    "application record only": REASON_APPLIED,
}


@pytest.mark.parametrize("how", list(_EXPECTED_REASON))
def test_the_same_vacancy_from_another_board_is_withheld(store: ProfileStore, how: str) -> None:
    prior = _prior(store, how)
    again = _save(
        store,
        "same vacancy, other board",
        title="Python Software Engineer (m/f/d)",
        company="HADDOCK",
        source="board-b",
    )
    show, held = partition(store, [again])
    assert show == []
    assert [(h.offer_id, h.reason, h.sibling) for h in held] == [
        (again, _EXPECTED_REASON[how], prior)
    ]


@pytest.mark.parametrize("how", list(_EXPECTED_REASON))
def test_a_never_seen_role_at_a_seen_employer_is_shown(store: ProfileStore, how: str) -> None:
    _prior(store, how)
    other_role = _save(
        store, "other role", title="Sales Engineer", company="Haddock", source="board-b"
    )
    assert partition(store, [other_role]) == ([other_role], [])


@pytest.mark.parametrize("how", list(_EXPECTED_REASON))
def test_the_same_title_at_another_employer_is_shown(store: ProfileStore, how: str) -> None:
    _prior(store, how)
    elsewhere = _save(
        store, "elsewhere", title="Python Developer", company="Cala", source="board-b"
    )
    assert partition(store, [elsewhere]) == ([elsewhere], [])


@pytest.mark.parametrize(
    "path",
    [
        ("shortlisted", "applied", "archived"),
        ("shortlisted", "expired"),
        ("shortlisted", "archived"),
        ("screened_out", "archived"),
        ("screened_out", "expired"),
    ],
)
def test_a_prior_state_survives_the_copy_moving_on(
    store: ProfileStore, path: tuple[OfferStatus, ...]
) -> None:
    """Lifecycle 7.2: "ever, not currently". Applied then archived is still applied to."""
    prior = _save(store, "prior", title="Python Developer", company="Haddock")
    for status in path:
        record_decision(
            store, prior, status, at=_AT, reason="no" if status == "screened_out" else None
        )
    again = _save(store, "again", title="Python Engineer", company="Haddock", source="board-b")
    show, held = partition(store, [again])
    assert show == []
    assert [h.sibling for h in held] == [prior]


def test_an_archived_copy_that_was_only_new_withholds_nothing(store: ProfileStore) -> None:
    prior = _save(store, "prior", title="Python Developer", company="Haddock")
    record_decision(store, prior, "archived", at=_AT, reason=None)
    again = _save(store, "again", title="Python Engineer", company="Haddock", source="board-b")
    assert partition(store, [again]) == ([again], [])


def test_a_drafted_application_is_not_an_application(store: ProfileStore) -> None:
    prior = _save(store, "draft", title="Python Developer", company="Haddock")
    record_application_status(store, prior, status="drafted", at=_AT)
    again = _save(store, "again", title="Python Developer", company="Haddock", source="board-b")
    assert partition(store, [again]) == ([again], [])


def test_a_blank_employer_never_withholds_and_is_reported(store: ProfileStore) -> None:
    _save(store, "prior no employer", title="Python Developer", company=None)
    prior = _save(store, "prior blank", title="Python Developer", company="   ")
    record_decision(store, prior, "shortlisted", at=_AT, reason=None)
    present(store, [prior], at=_AT)
    again = _save(store, "again no employer", title="Python Developer", company=None, source="b")
    again2 = _save(store, "again blank", title="Python Developer", company="  ", source="c")
    show, held = partition(store, [again, again2])
    assert (show, held) == ([again, again2], [])
    assert unchecked_line(store, show).startswith("2 sin empresa")
    assert unchecked_line(store, []) == ""


def test_two_matches_in_one_round_are_shown_once(store: ProfileStore) -> None:
    one = _save(store, "one", title="Backend Engineer", company="Cala", source="board-a")
    two = _save(store, "two", title="Backend Developer", company="Cala", source="board-b")
    show, held = partition(store, [one, two])
    assert show == [one]
    assert [(h.offer_id, h.sibling) for h in held] == [(two, one)]


# --- recorded as shown, so the next round can tell ----------------------------


def test_recording_a_round_as_shown_makes_the_next_round_withhold_it(store: ProfileStore) -> None:
    round_one = _save(store, "round one", title="Backend Engineer", company="Cala")
    again = _save(store, "round two copy", title="Backend Developer", company="Cala", source="b")
    show, held = partition(store, [round_one])
    assert (show, held) == ([round_one], [])
    # Not yet recorded as shown: the other board's copy is still new to the candidate.
    assert partition(store, [again]) == ([again], [])
    present(store, show, at=_AT)
    show2, held2 = partition(store, [again])
    assert show2 == []
    assert [(h.reason, h.sibling) for h in held2] == [(REASON_SHOWN, round_one)]


# --- counted in the round's summary, recoverable ------------------------------


def test_withheld_offers_are_counted_per_reason_and_stay_stored(store: ProfileStore) -> None:
    applied = _prior(store, "applied")
    rejected = _save(store, "rej", title="Data Engineer", company="Cala")
    rule_out(store, rejected, "demasiado junior", at=_AT)
    copies = [
        _save(store, "a1", title="Python Engineer", company="Haddock", source="b"),
        _save(store, "a2", title="Python Developer (m/f/d)", company="Haddock", source="c"),
        _save(store, "r1", title="Data Engineer - Remote", company="Cala", source="b"),
        _save(store, "n1", title="Data Scientist", company="Cala", source="b"),
    ]
    show, held = partition(store, copies)
    assert show == [copies[3]]
    line = withheld_line(held)
    assert line.startswith("3 descartada(s)")
    assert f"2 porque «{REASON_APPLIED}»" in line
    assert "1 porque «demasiado junior»" in line
    # Withheld is not deleted: every offer is still on disk and loadable.
    from integral.lifecycle import load_lifecycle_offer

    for offer_id in [applied, rejected, *copies]:
        load_lifecycle_offer(store, offer_id)
