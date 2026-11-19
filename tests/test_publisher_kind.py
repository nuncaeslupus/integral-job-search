"""Who publishes an advert is read from cue phrases, in three languages alike."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import publisher_kind as pk
from integral import sourcing_exclusions as se
from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.relevance import record as record_relevance
from integral.robots import Robots
from integral.sourcing import Response, flood_board, source
from integral.sourcing_exclusions import Exclusion, record_exclusion

CONSULTANCY = {
    "es": [
        "Para importante cliente del sector banca",
        "Empresa cliente en Madrid",
        "Incorporación a cliente final",
        "Buscamos para nuestro cliente un analista",
    ],
    "en": [
        "Hiring for our client in retail",
        "Working for a client in banking",
        "Our client is a leading insurer",
        "Placed with the end client",
    ],
    "ca": [
        "Per a un client del sector bancari",
        "Empresa client a Barcelona",
        "Incorporació a client final",
        "Per al nostre client busquem un analista",
    ],
}
AGENCY = {
    "es": ["Oferta de ETT en Valencia", "Somos una empresa de trabajo temporal"],
    "en": ["We are a temporary staffing agency", "Leading staffing agency hiring"],
    "ca": ["Oferta d'ETT a Girona", "Som una empresa de treball temporal"],
}
OWN_CLIENTS = {
    "es": "Nuestros clientes usan la app. Una app hecha para nuestros clientes.",
    "en": "Our clients use the app. An app built for our clients.",
    "ca": "Els nostres clients fan servir l'app cada dia i el nostre equip la construeix.",
}


@pytest.mark.parametrize("text", [t for ts in CONSULTANCY.values() for t in ts])
def test_every_consultancy_cue_is_a_consultancy(text: str) -> None:
    assert pk.publisher_kind(text) == "consultancy"


@pytest.mark.parametrize("text", [t for ts in AGENCY.values() for t in ts])
def test_every_agency_cue_is_an_agency(text: str) -> None:
    assert pk.publisher_kind(text) == "agency"


def test_an_agency_that_also_names_a_client_is_an_agency() -> None:
    assert pk.publisher_kind("ETT. Para importante cliente de logística") == "agency"


@pytest.mark.parametrize("text", ["", "We build a payments app in Python.", "Ingeniero en Madrid"])
def test_an_advert_with_no_cue_is_unknown_never_direct(text: str) -> None:
    assert pk.publisher_kind(text) == "unknown"


@pytest.mark.parametrize("text", OWN_CLIENTS.values(), ids=OWN_CLIENTS.keys())
def test_a_product_company_describing_its_own_clients_is_not_a_consultancy(text: str) -> None:
    assert pk.publisher_kind(text) == "unknown"


# --- the run line ----------------------------------------------------------

AT = "2026-01-01T00:00:00+00:00"


def _run(tmp_path: Path, rule: str) -> object:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path, "test")
    record_relevance(store, 0.0)
    record_exclusion(store, Exclusion(about=rule, stated_at_cycle=1, words="no thanks"))
    pages = flood_board(tmp_path / "connectors", rows=4)
    marked = {"Advert flood-1-0:": "For our client. ", "Advert flood-1-2:": "Somos una ETT. "}

    def fetch(request: ListRequest) -> Response:
        html = pages[request.url].html
        for advert, cue in marked.items():
            html = html.replace(advert, cue + advert)
        return Response(200, html)

    return source(
        store,
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
            reach=Reach(state="stated", modes=("remote",)),
        ),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=2,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )


@pytest.mark.parametrize("kind", ["consultancy", "agency"])
def test_a_ruled_out_publisher_is_counted_and_named_in_the_run_line(
    tmp_path: Path, kind: str
) -> None:
    run = _run(tmp_path, f"publisher:{kind}")
    (outcome,) = run.outcomes  # type: ignore[attr-defined]
    assert outcome.excluded == 1
    assert f"publisher:{kind}" in outcome.excluded_because[0]
    assert "EXCLUDED flood_en: 1 of" in run.summary()  # type: ignore[attr-defined]


def test_without_the_rule_nothing_is_excluded_for_its_publisher(tmp_path: Path) -> None:
    run = _run(tmp_path, "role:nothing-matches-this")
    assert run.outcomes[0].excluded == 0  # type: ignore[attr-defined]


def test_the_facet_is_only_a_publisher_rule_for_its_own_value() -> None:
    ad = se.Candidate(offer_id="x", title=None, text="For our client, a bank.")
    assert se.matches(ad, Exclusion(about="publisher:consultancy", stated_at_cycle=1, words="w"))
    assert not se.matches(ad, Exclusion(about="publisher:agency", stated_at_cycle=1, words="w"))
