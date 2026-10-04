"""T228 — a candidate can rule out an employer, not only a topic.

A sector exclusion is text-matched, and one restaurant-sector employer had 41
stored adverts of which the sector held 9: the other 32 never say what the
company sells. `employer:<name>` is matched against who published the advert.

Cases are derived from the stated requirement, not from the code: the same
employer spelled differently must be out (fail-open otherwise), and a different
employer whose name merely contains the excluded one must stay in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import sourcing_exclusions as se
from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.offers import load_offer
from integral.presentation_log import partition
from integral.robots import Robots
from integral.sourcing import Response, flood_board, source
from integral.sourcing_exclusions import Exclusion, record_exclusion

AT = "2026-01-01T00:00:00+00:00"


def _constraints() -> CandidateConstraints:
    return CandidateConstraints(
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        reach=Reach(state="stated", modes=("remote",)),
    )


def _out(
    value: str,
    *,
    company: str | None = None,
    title: str | None = None,
    text: str = "plain work",
    terms: tuple[str, ...] = (),
) -> bool:
    exclusion = Exclusion(about=f"employer:{value}", stated_at_cycle=1, words="w", terms=terms)
    candidate = se.Candidate(offer_id="x", title=title, text=text, employer=company)
    return se.matches(candidate, exclusion)


@pytest.mark.parametrize(
    "company",
    [
        "Foo Restauración",
        "FOO RESTAURACIÓN",
        "foo restauracion",
        "Foo Restauración logo",
        "Foo Restauración S.L.",
        "Foo Restauración, S.L.U. logo",
        "  Foo   Restauración  ",
    ],
)
def test_the_same_employer_spelled_differently_is_ruled_out(company: str) -> None:
    assert _out("Foo Restauración", company=company)


def test_the_stated_value_is_normalised_too() -> None:
    assert _out("FOO restauracion s.l.", company="Foo Restauración logo")


@pytest.mark.parametrize(
    "title",
    [
        "Camarero en Foo Restauración",
        "Camarero en Foo Restauración logo",
        "Jefe de sala EN FOO RESTAURACION S.L.",
        "Cocinero en turno de noche en Foo Restauración",
    ],
)
def test_a_title_naming_the_employer_rules_out_an_advert_with_no_company(title: str) -> None:
    assert _out("Foo Restauración", title=title, company=None)


def test_the_employer_is_ruled_out_though_the_text_never_names_its_sector() -> None:
    assert _out("Foo", company="Foo logo", text="Software engineer, fully remote")


@pytest.mark.parametrize(
    ("value", "company"),
    [
        ("Bar", "Barclays"),
        ("Bar", "Barclays logo"),
        ("Bar", "Bar Mitzvah Events"),
        ("Bar", "Foo Bar"),
        ("Foo", "Foobar S.L."),
        ("Foo Restauración", "Foo Restauración Group"),
    ],
)
def test_a_different_employer_containing_the_name_is_not_ruled_out(
    value: str, company: str
) -> None:
    assert not _out(value, company=company)


@pytest.mark.parametrize(
    "title",
    ["Camarero en Barclays", "Engineer en Barcelona", "Barista en Bar Central"],
)
def test_a_title_naming_another_employer_is_not_ruled_out(title: str) -> None:
    assert not _out("Bar", title=title, company=None)


@pytest.mark.parametrize("company", [None, "", "   ", "\u200b"])
def test_an_advert_that_names_no_employer_is_undecidable_not_satisfied(
    company: str | None,
) -> None:
    """A board that publishes no employer cannot show the advert is another's."""
    assert _out("Foo", company=company, title="Camarero de sala")
    assert _out("Foo", company=company, title=None)


def test_an_advert_with_a_named_employer_is_decided_by_it() -> None:
    assert not _out("Foo", company="Other", title="Camarero de sala")


def test_an_employer_exclusion_is_not_a_text_match() -> None:
    """The text says the name; the company is someone else — not ruled out."""
    assert not _out("Foo", company="Other", text="We compete with Foo and Foo logo daily")


def test_a_sector_exclusion_still_reads_the_text() -> None:
    exclusion = Exclusion(about="sector:banca", stated_at_cycle=1, words="w")
    candidate = se.Candidate(offer_id="x", text="trabajo en banca", employer="Other")
    assert se.matches(candidate, exclusion)


def test_a_name_that_normalises_to_nothing_rules_out_nothing() -> None:
    assert not _out("...", company="Anyone", title="Camarero en Anyone")


# --- applied by source() and partition, like any other exclusion -------------


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _run(store: ProfileStore, tmp_path: Path) -> object:
    pages = flood_board(tmp_path / "connectors", rows=4)

    def fetch(request: ListRequest) -> Response:
        return Response(200, pages[request.url].html)

    return source(
        store,
        _constraints(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=2,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )


def _companies(store: ProfileStore) -> list[str | None]:
    return [
        load_offer(store, p.stem).company
        for p in Path(store.path("offers")).glob("*.json")
        if not p.name.startswith("_")
    ]


def _baseline(tmp_path: Path) -> set[str | None]:
    """The employers stored by the same round with nothing ruled out."""
    root = tmp_path / "baseline"
    root.mkdir()
    create_profile(root, "Test", handle="test", language="es", fiction=True)
    base = ProfileStore(root, "test")
    _run(base, root)
    return set(_companies(base))


def test_source_leaves_out_the_employer_and_says_so(store: ProfileStore, tmp_path: Path) -> None:
    baseline = _baseline(tmp_path)
    assert {"Employer 0", "Employer 2"} <= baseline
    record_exclusion(
        store, Exclusion(about="employer:EMPLOYER 2 logo", stated_at_cycle=1, words="no Employer 2")
    )
    run = _run(store, tmp_path)
    assert set(_companies(store)) == baseline - {"Employer 2"}
    (outcome,) = run.outcomes  # type: ignore[attr-defined]
    assert outcome.excluded >= 1
    assert all("employer:EMPLOYER 2 logo" in why for why in outcome.excluded_because)


def test_source_keeps_an_employer_whose_name_only_contains_the_excluded_one(
    store: ProfileStore, tmp_path: Path
) -> None:
    baseline = _baseline(tmp_path)
    record_exclusion(store, Exclusion(about="employer:Employer", stated_at_cycle=1, words="no"))
    run = _run(store, tmp_path)
    assert set(_companies(store)) == baseline
    (outcome,) = run.outcomes  # type: ignore[attr-defined]
    assert outcome.excluded == 0


def test_partition_holds_back_stored_offers_of_a_newly_ruled_out_employer(
    store: ProfileStore, tmp_path: Path
) -> None:
    _run(store, tmp_path)
    ids = [p.stem for p in Path(store.path("offers")).glob("*.json") if not p.name.startswith("_")]
    before = {load_offer(store, i).company for i in partition(store, ids)[0]}
    assert "Employer 2" in before
    assert partition(store, ids)[1] == []
    record_exclusion(store, Exclusion(about="employer:employer 2", stated_at_cycle=1, words="no"))
    show, held = partition(store, ids)
    assert held and all("employer:employer 2" in h.reason for h in held)
    assert {load_offer(store, i).company for i in show} == before - {"Employer 2"}
