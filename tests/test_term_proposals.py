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
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import save_lifecycle_offer, track_new_offer
from integral.offers import Offer, compute_offer_id
from integral.search_terms import AIM_FILE, save_aim
from integral.sourcing import FETCH_LOG
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


def _advert(store: ProfileStore, title: str, company: str | None, board: str = "a") -> str:
    text = f"{title} at {company} on {board} " + "x" * 20
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


def test_adverts_with_no_employer_each_count(store: ProfileStore) -> None:
    _advert(store, "Generative AI Engineer", None, "a")
    _advert(store, "Generative AI Engineer", None, "b")
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


def test_a_title_the_aim_already_covers_is_not_proposed(store: ProfileStore) -> None:
    # "python developer" searches python AND developer; engineer is a synonym.
    _advert(store, "Python Engineer", "Acme")
    _advert(store, "Senior Python Developer", "Globex")
    _advert(store, "Python Developer Platform", "Initech")
    assert _terms(store) == []


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
    _advert(store, "Developer Tools Developer", "Initech")
    _advert(store, "Developer Tools Developer", "Umbrella")
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


def test_declining_the_same_title_in_another_wording_stores_it_once(store: ProfileStore) -> None:
    decline(store, "developer tools")
    assert decline(store, "Tools Engineer Developer") == ["developer tools"]
