"""T248 - titles recurring in found adverts are proposed as search terms; only a yes adds one.

Verdicts come from the task text (recurring off-aim titles proposed, single
occurrences and covered titles not, accept appends exactly that term, decline is
remembered, nothing is written without an accept) and from the rule stated in
`term_proposals`' docstring, never from running the code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.candidate import Aim
from integral.extraction import citable_text
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import save_lifecycle_offer, track_new_offer
from integral.offers import Offer, compute_offer_id, load_offer
from integral.search_terms import AIM_FILE, save_aim
from integral.sourcing import FETCH_LOG
from integral.sourcing_exclusions import Exclusion, record_exclusion
from integral.term_proposals import (
    DECLINED_FILE,
    TermError,
    accept,
    clean_title,
    decline,
    propose,
    recurs,
)
from integral.term_proposals import _main as cli

_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    s = ProfileStore(root, "fixture")
    save_aim(s, Aim(state="stated", terms=("python developer",), evidence=("e1",)))
    return s


def _advert(
    store: ProfileStore, title: str, company: str | None, board: str = "a", extra: str = ""
) -> str:
    text = f"{title} at {company} on {board} {extra} " + "x" * 20
    offer = Offer(
        id=compute_offer_id(text),
        source=board,
        url=f"https://{board}.example/{abs(hash(text))}",
        title=title,
        company=company,
        text=text,
    )
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    store.append_jsonl(
        {"connector": board, "query": "python developer", "at": _AT, "offer_ids": [offer.id]},
        "offers",
        FETCH_LOG,
    )
    return offer.id


def _terms(store: ProfileStore) -> list[str]:
    return [p.term for p in propose(store)]


def _aim_bytes(store: ProfileStore) -> bytes:
    return store.path(*AIM_FILE).read_bytes()


def test_a_title_recurring_across_employers_and_boards_is_proposed(store: ProfileStore) -> None:
    _advert(store, "Applied AI Engineer", "Acme", "a")
    _advert(store, "Applied AI Engineer (m/f/d)", "Globex", "b")
    [p] = propose(store)
    assert (p.term, p.vacancies, p.boards) == ("applied ai engineer", 2, ["a", "b"])


def test_the_threshold_is_the_boundary(store: ProfileStore) -> None:
    assert (recurs(1), recurs(2)) == (False, True)
    _advert(store, "Developer Platform Lead", "Acme")
    assert _terms(store) == []
    _advert(store, "Senior Developer Platform Lead - Barcelona", "Globex")
    assert _terms(store) == ["developer platform"]


def test_one_vacancy_cross_posted_is_still_one_vacancy(store: ProfileStore) -> None:
    _advert(store, "AI Platform Engineer", "Acme S.L.", "a")
    _advert(store, "AI Platform Engineer", "ACME SL", "b")
    assert _terms(store) == []


def test_adverts_with_no_employer_count_once_between_them(store: ProfileStore) -> None:
    _advert(store, "Generative AI Engineer", None, "a")
    _advert(store, "Generative AI Engineer", None, "b")
    assert _terms(store) == []
    _advert(store, "Generative AI Engineer", "Acme", "b")
    assert _terms(store) == ["generative ai engineer"]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Senior Data Scientist (m/w/d)", "data scientist"),
        ("Data Scientist - Madrid", "data scientist"),
        ("Data Scientist, Remote", "data scientist"),
        ("Sr. Data Scientist | Hybrid", "data scientist"),
        ("Junior Data Scientist [Barcelona]", "data scientist"),
    ],
)
def test_noise_is_stripped_from_a_title(raw: str, clean: str) -> None:
    assert clean_title(raw) == clean


SPEC_TITLES = [
    "Applied AI Engineer",
    "Developer Platform",
    "AI Platform Engineer",
    "Generative AI Engineer",
    "Developer Tools",
]


@pytest.mark.parametrize(
    "aim_term",
    [
        "software engineer",
        "software developer",
        "desarrollador de software",
        "ingeniero de software",
        "remote developer",
    ],
)
def test_a_broad_aim_term_does_not_swallow_the_spec_titles(
    store: ProfileStore, aim_term: str
) -> None:
    save_aim(store, Aim(state="stated", terms=(aim_term,), evidence=("e1",)))
    for title in SPEC_TITLES:
        _advert(store, title, "Acme")
        _advert(store, title, "Globex")
    assert sorted(_terms(store)) == sorted(t.lower() for t in SPEC_TITLES)


def test_coverage_is_what_a_boards_and_query_would_match(store: ProfileStore) -> None:
    # every word of the aim term is a word of the title -> a search already finds it
    save_aim(store, Aim(state="stated", terms=("python developer",), evidence=("e1",)))
    for title in ("Senior Python Developer Platform", "Python Developer Tools"):
        _advert(store, title, "Acme")
        _advert(store, title, "Globex")
    # a synonym is a different word to a board: not covered
    _advert(store, "Python Engineer", "Acme")
    _advert(store, "Python Engineer", "Globex")
    assert _terms(store) == ["python engineer"]


def test_a_decline_silences_only_the_same_set_of_significant_words(
    store: ProfileStore,
) -> None:
    decline(store, "platform engineer")
    for title in ("Developer Platform", "Platform Engineer Lead Tools", "Engineer, Platform II"):
        _advert(store, title, "Acme")
        _advert(store, title, "Globex")
    # same words in another order (and a grade) are declined; a superset is not
    assert _terms(store) == ["developer platform", "platform engineer tools"]


def test_declining_ai_engineer_does_not_hide_applied_ai_engineer(store: ProfileStore) -> None:
    decline(store, "ai engineer")
    _advert(store, "Applied AI Engineer", "Acme")
    _advert(store, "Applied AI Engineer", "Globex")
    assert _terms(store) == ["applied ai engineer"]


@pytest.mark.parametrize(
    "title",
    ["Head of Data", "Engineer III", "Engineer 2", "Software Engineer II", "Data de la"],
)
def test_function_words_and_grades_are_not_significant_words(
    store: ProfileStore, title: str
) -> None:
    # "head of data" -> one word; "engineer iii/2" -> one; "software engineer ii" is
    # the two-word "software engineer", which the aim (python developer) does not cover.
    _advert(store, title, "Acme")
    _advert(store, title, "Globex")
    expected = ["software engineer"] if title == "Software Engineer II" else []
    assert _terms(store) == expected


def test_a_slash_gender_form_is_one_word_in_the_proposal(store: ProfileStore) -> None:
    _advert(store, "Ingeniero/a de datos", "Acme")
    _advert(store, "Ingeniero/a de Datos", "Globex")
    assert _terms(store) == ["ingeniero datos"]
    assert clean_title("Ingeniera/o de datos") == "ingeniera datos"


def test_a_declined_term_typed_with_a_grade_or_function_word_still_matches(
    store: ProfileStore,
) -> None:
    decline(store, "Platform of Engineer II")
    assert decline(store, "engineer platform") == ["Platform of Engineer II"]
    _advert(store, "Platform Engineer", "Acme")
    _advert(store, "Platform Engineer", "Globex")
    assert _terms(store) == []


def test_adverts_on_a_ruled_out_topic_propose_nothing(store: ProfileStore) -> None:
    record_exclusion(
        store,
        Exclusion(about="sector:banking", stated_at_cycle=1, words="no banks", terms=("banking",)),
    )
    _advert(store, "Applied AI Engineer", "Acme", extra="a banking group")
    _advert(store, "Applied AI Engineer", "Globex", extra="retail banking")
    assert _terms(store) == []
    _advert(store, "Applied AI Engineer", "Initech")
    assert _terms(store) == []  # one surviving vacancy is below the threshold
    _advert(store, "Applied AI Engineer", "Umbrella")
    assert _terms(store) == ["applied ai engineer"]


def test_adverts_whose_extraction_requires_a_ruled_out_skill_propose_nothing(
    store: ProfileStore,
) -> None:
    """T229: `propose` reads the stored extraction, so a `skill:` exclusion holds there too."""
    from integral.skill_requirement import store_readings

    record_exclusion(
        store,
        Exclusion(
            about="skill:go", stated_at_cycle=1, words="nunca he usado Go", terms=("golang",)
        ),
    )
    ids = [
        _advert(store, "Applied AI Engineer", company, extra="Go required")
        for company in ("Acme", "Globex")
    ]
    assert _terms(store) == ["applied ai engineer"]  # unread: shown, so still proposed
    for offer_id in ids:
        offer = load_offer(store, offer_id)
        start = citable_text(offer.title, offer.text).index("Go")
        span = {"start": start, "end": start + 2, "quote": "Go"}
        store_readings(store, offer_id, [{"skill": "Go", "role": "required", "span": span}])
    assert _terms(store) == []


def test_a_title_seen_across_boards_sorts_before_a_busier_single_board_one(
    store: ProfileStore,
) -> None:
    for company in ("A1", "A2", "A3"):
        _advert(store, "Developer Tools", company, "a")
    _advert(store, "Applied AI Engineer", "B1", "a")
    _advert(store, "Applied AI Engineer", "B2", "b")
    assert _terms(store) == ["applied ai engineer", "developer tools"]


def test_the_duplicate_check_ignores_case_and_spacing_in_the_stored_aim(
    store: ProfileStore,
) -> None:
    store.write_json(
        {"state": "stated", "terms": ["Python   Developer"], "evidence": []}, *AIM_FILE
    )
    with pytest.raises(TermError):
        accept(store, "python developer")


def test_declining_the_same_words_in_another_order_stores_it_once(store: ProfileStore) -> None:
    decline(store, "developer tools")
    assert decline(store, "Tools  Developer") == ["developer tools"]


def test_a_single_word_title_is_never_proposed(store: ProfileStore) -> None:
    _advert(store, "Architect", "Acme")
    _advert(store, "Architect", "Globex")
    assert _terms(store) == []


def test_declined_is_not_proposed_again_even_reworded(store: ProfileStore) -> None:
    _advert(store, "Developer Tools Engineer", "Acme")
    _advert(store, "Developer Tools Engineer", "Globex")
    assert _terms(store) == ["developer tools engineer"]
    decline(store, "developer tools engineer")
    assert _terms(store) == []
    _advert(store, "Senior Tools Developer Engineer - Madrid", "Initech")
    _advert(store, "Developer Tools Engineer (m/f/d)", "Umbrella")
    assert _terms(store) == []
    declined = json.loads(store.path(*DECLINED_FILE).read_text())["terms"]
    assert declined == ["developer tools engineer"]


def test_accept_appends_exactly_that_term_and_keeps_the_rest(store: ProfileStore) -> None:
    store.write_json(
        {"state": "stated", "terms": ["python developer"], "evidence": ["e1"], "note": "keep"},
        *AIM_FILE,
    )
    assert accept(store, "applied ai engineer") == ["python developer", "applied ai engineer"]
    assert json.loads(_aim_bytes(store)) == {
        "state": "stated",
        "terms": ["python developer", "applied ai engineer"],
        "evidence": ["e1"],
        "note": "keep",
    }


def test_an_accepted_term_stops_being_proposed(store: ProfileStore) -> None:
    _advert(store, "Applied AI Engineer", "Acme")
    _advert(store, "Applied AI Engineer", "Globex")
    accept(store, "applied ai engineer")
    assert _terms(store) == []


def test_accepting_what_was_declined_lifts_the_decline(store: ProfileStore) -> None:
    decline(store, "platform engineer")
    accept(store, "platform engineer")
    assert json.loads(store.path(*DECLINED_FILE).read_text())["terms"] == []


def test_accept_refuses_a_duplicate_a_blank_and_an_absent_aim(
    store: ProfileStore, tmp_path: Path
) -> None:
    before = _aim_bytes(store)
    with pytest.raises(TermError):
        accept(store, "Python  Developer")
    with pytest.raises(TermError):
        accept(store, "  ")
    assert _aim_bytes(store) == before
    create_profile(tmp_path / "profiles", "Other", handle="other", language="es", fiction=True)
    with pytest.raises(TermError):
        accept(ProfileStore(tmp_path / "profiles", "other"), "applied ai engineer")


def test_proposing_never_writes_and_declining_never_touches_the_aim(store: ProfileStore) -> None:
    before = _aim_bytes(store)
    _advert(store, "Applied AI Engineer", "Acme")
    _advert(store, "Applied AI Engineer", "Globex")
    propose(store)
    assert _aim_bytes(store) == before
    assert not store.exists(*DECLINED_FILE)
    decline(store, "applied ai engineer")
    assert _aim_bytes(store) == before


def test_no_proposal_without_a_stated_aim(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    s = ProfileStore(root, "fixture")
    _advert(s, "Applied AI Engineer", "Acme")
    _advert(s, "Applied AI Engineer", "Globex")
    assert propose(s) == []


def test_the_command_line_proposes_then_writes_only_on_accept(
    store: ProfileStore, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _advert(store, "Applied AI Engineer", "Acme")
    _advert(store, "Applied AI Engineer", "Globex")
    base = ["--handle", "fixture", "--root", str(tmp_path / "profiles")]
    before = _aim_bytes(store)
    assert cli(["propose", *base]) == 0
    assert json.loads(capsys.readouterr().out)[0]["term"] == "applied ai engineer"
    assert _aim_bytes(store) == before
    assert cli(["accept", *base, "--term", "applied ai engineer"]) == 0
    assert "applied ai engineer" in json.loads(_aim_bytes(store))["terms"]
    assert cli(["accept", *base, "--term", "applied ai engineer"]) == 2
