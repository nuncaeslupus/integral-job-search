"""T276 — one posting listed under several offices is stored once.

The cases are derived from the task (#551), not from the code: greenhouse /
anthropic listed the same role under several offices (different `location`,
different URL query) and every copy was stored. The counter-case is two
genuinely different openings of one role at one employer (two teams), which
must both survive: a wrong merge hides a vacancy the candidate never sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.lifecycle import collect_offer, same_board_twin
from integral.offers import Location, Offer, compute_offer_id

NOW = "2026-01-01T00:00:00+00:00"

ABOUT = (
    "About Anthropic. Anthropic's mission is to create reliable, interpretable and steerable "
    "AI systems. We want AI to be safe and beneficial for our users and for society as a whole. "
    "Our team is a quickly growing group of committed researchers, engineers, policy experts "
    "and business leaders working together to build beneficial AI systems."
)
PARTNERSHIPS = (
    "As an Applied AI Architect on the Partnerships team you will work with strategic "
    "technology partners to design joint reference architectures, advise their engineering "
    "teams on building Claude into their platforms, and write the integration guides that "
    "partner developers follow. You will travel to partner sites a few times each quarter."
)
INDUSTRIES = (
    "As an Applied AI Architect on the Industries team you will embed with customers in "
    "regulated sectors such as banking and healthcare, translate their compliance needs into "
    "deployment patterns, and prototype agents for their back offices. You will lead "
    "discovery workshops and own the technical relationship through production launch."
)


def _offer(
    text: str,
    *,
    url: str,
    location: str,
    title: str = "Applied AI Architect",
    company: str | None = "Anthropic",
    source: str = "greenhouse",
) -> Offer:
    return Offer(
        id=compute_offer_id(text + url + location),
        source=source,
        url=url,
        title=title,
        company=company,
        location=Location(raw=location),
        text=text,
    )


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    return ProfileStore(root, "fixture")


def _stored(store: ProfileStore) -> set[str]:
    return {p.stem for p in Path(store.path("offers")).glob("*.json") if not p.name.startswith("_")}


def test_one_posting_under_four_offices_is_stored_once(store: ProfileStore) -> None:
    body = f"{PARTNERSHIPS} {ABOUT}"
    offices = ["London", "Dublin", "Paris", "San Francisco, CA"]
    copies = [
        _offer(
            body,
            url=f"https://boards.greenhouse.io/anthropic/jobs/{4000 + n}?gh_src=o{n}",
            location=place,
        )
        for n, place in enumerate(offices)
    ]
    outcomes = [collect_offer(store, c, at=NOW) for c in copies]
    assert [o.added_as_new for o in outcomes] == [True, False, False, False]
    assert {o.duplicate_of for o in outcomes[1:]} == {copies[0].id}
    assert _stored(store) == {copies[0].id}


def test_the_office_written_into_the_body_does_not_split_the_copies(store: ProfileStore) -> None:
    first = _offer(
        f"{PARTNERSHIPS} {ABOUT} Location: London", url="https://g.test/a", location="London"
    )
    second = _offer(
        f"{PARTNERSHIPS} {ABOUT} Location: Dublin", url="https://g.test/b", location="Dublin"
    )
    assert collect_offer(store, first, at=NOW).added_as_new
    assert collect_offer(store, second, at=NOW).duplicate_of == first.id


def test_two_teams_hiring_the_same_title_are_both_stored(store: ProfileStore) -> None:
    partnerships = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    industries = _offer(f"{INDUSTRIES} {ABOUT}", url="https://g.test/2", location="London")
    assert collect_offer(store, partnerships, at=NOW).added_as_new
    outcome = collect_offer(store, industries, at=NOW)
    assert outcome.added_as_new and outcome.duplicate_of is None
    assert _stored(store) == {partnerships.id, industries.id}


def test_two_teams_are_not_a_twin_even_with_the_same_office() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(f"{INDUSTRIES} {ABOUT}", url="https://g.test/2", location="London")
    assert not same_board_twin(a, b)


def test_the_same_words_on_another_board_are_not_merged_here() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://l.test/1", location="London", source="lever")
    assert not same_board_twin(a, b)


def test_another_employer_with_the_same_title_and_body_is_not_a_twin() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/2", location="London", company="Acme")
    assert not same_board_twin(a, b)


def test_a_different_level_of_the_same_role_is_not_a_twin() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(
        f"{PARTNERSHIPS} {ABOUT}",
        url="https://g.test/2",
        location="London",
        title="Senior Applied AI Architect",
    )
    assert not same_board_twin(a, b)


def test_an_advert_naming_no_employer_is_never_a_twin(store: ProfileStore) -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London", company=None)
    b = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/2", location="Dublin", company=None)
    assert not same_board_twin(a, b)
    assert collect_offer(store, a, at=NOW).added_as_new
    assert collect_offer(store, b, at=NOW).added_as_new
