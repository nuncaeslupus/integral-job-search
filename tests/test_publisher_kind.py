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
        "Puesto para empresa cliente en Madrid",
        "Incorporación a cliente final",
        "Buscamos para nuestro cliente un analista",
    ],
    "en": [
        "Hiring for our client in retail",
        "Working for a client in banking",
        "Our client is a leading insurer",
        "Placed with the end client",
        "Working at our client's site",
    ],
    "ca": [
        "Per a un client del sector bancari",
        "Lloc per a una empresa client a Barcelona",
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


# One sample per language for every concept in the module's table, in its order.
CONCEPT_SAMPLES = [
    (
        "Para un importante cliente del sector bancario",
        "For an important client in banking",
        "Per a un important client del sector bancari",
    ),
    (
        "Incorporarte a nuestro cliente en Madrid",
        "Join our client in Madrid",
        "Incorporar-te al nostre client a Barcelona",
    ),
    (
        "Nuestro cliente busca un analista",
        "Our client is a leading insurer",
        "El nostre client busca un analista",
    ),
    ("Somos una consultora", "We are a consultancy", "Som una consultora"),
    ("Trabajarás en cliente final", "Working at the end client", "Treballaràs a client final"),
    ("En nombre de nuestro cliente", "On behalf of our client", "En nom del nostre client"),
]
AGENCY_SAMPLES = [
    ("Oferta de ETT", "Temporary staffing role", "Oferta d'ETT"),
    ("Agencia de selección", "Recruitment agency", "Agència de selecció"),
]
OWN_CUSTOMERS = [
    "Nuestra app mejora la experiencia del cliente final.",
    "We build software that delights the end client.",
    "La nostra app millora l'experiència del client final.",
    "Orientación al cliente final y atención al cliente final.",
    "Cada empresa cliente usa nuestra plataforma SaaS.",
    "Each client company is onboarded onto our platform.",
    "Cada empresa client fa servir la nostra plataforma.",
    "Serás el account manager de un importante cliente de nuestra cartera.",
]
NEGATED = [
    "Contratación directa, sin ETT ni intermediarios.",
    "No somos una ETT: trabajarás en producto propio.",
    "Contractació directa, sense ETT.",
    "Direct hire, not through a staffing agency.",
    "Producto propio, no trabajarás en cliente final.",
    "Som producte propi, mai treballaràs a client final.",
    "We are not a recruitment agency; we never place you at a client.",
]


def test_the_concept_tables_cover_all_three_languages_alike() -> None:
    assert len(CONCEPT_SAMPLES) == len(pk._CONSULTANCY_CONCEPTS)
    assert len(AGENCY_SAMPLES) == len(pk._AGENCY_CONCEPTS)
    for concept in (*pk._CONSULTANCY_CONCEPTS, *pk._AGENCY_CONCEPTS):
        assert len(concept) == 3


@pytest.mark.parametrize("text", [t for row in CONCEPT_SAMPLES for t in row])
def test_every_concept_is_a_consultancy_in_every_language(text: str) -> None:
    assert pk.publisher_kind(text) == "consultancy"


@pytest.mark.parametrize("text", [t for row in AGENCY_SAMPLES for t in row])
def test_every_agency_concept_is_an_agency_in_every_language(text: str) -> None:
    assert pk.publisher_kind(text) == "agency"


@pytest.mark.parametrize("text", OWN_CUSTOMERS)
def test_a_bare_client_noun_phrase_is_not_a_placement(text: str) -> None:
    assert pk.publisher_kind(text) == "unknown"


@pytest.mark.parametrize("text", NEGATED)
def test_a_negated_cue_is_not_a_cue(text: str) -> None:
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


# --- leftovers from #965 (t-92dfe902) --------------------------------------

# "client" as a modifier or half of a hyphenated word is not a placement.
CLIENT_MODIFIER = [
    "We are looking for a client-facing Solutions Engineer",
    "You will join a client-facing team",
    "Join our Client Success team!",
    "Work with our client success managers",
    "We are hiring for our Client Services team.",
    "Buscamos para nuestro cliente-facing un ingeniero",
    "Incorporarte a nuestro cliente-facing equipo",
    "Per al nostre client-facing busquem un enginyer",
    "Treballaràs a client-success",
]
# Customer-first slogans, support wording and past work are not a placement.
CLIENT_SINGULAR = [
    "Our client is at the heart of everything",
    "Nuestro cliente es lo primero",
    "El nostre client és el centre de tot",
    "Darás soporte a un cliente",
    "Dóna suport a un client",
    "You will support a client every day",
    "Built X for a client in 2019",
    "Construimos X para un cliente en 2019",
    "Vam construir X per a un client en 2019",
]
SELF_DESCRIBED = ["Somos una consultora", "We are a consultancy", "Som una consultora"]
EARLIER_CLAUSE_NEGATOR = [
    "No es necesario inglés, trabajarás en cliente final",
    "No English needed, you will be working at the end client",
    "No cal anglès, treballaràs a client final",
]


@pytest.mark.parametrize("text", CLIENT_MODIFIER)
def test_client_as_a_modifier_is_not_a_placement(text: str) -> None:
    assert pk.publisher_kind(text) == "unknown"


@pytest.mark.parametrize("text", CLIENT_SINGULAR)
def test_a_singular_client_slogan_or_support_wording_is_not_a_placement(text: str) -> None:
    assert pk.publisher_kind(text) == "unknown"


@pytest.mark.parametrize("text", SELF_DESCRIBED)
def test_a_self_described_consultancy_is_a_consultancy(text: str) -> None:
    assert pk.publisher_kind(text) == "consultancy"


@pytest.mark.parametrize("text", EARLIER_CLAUSE_NEGATOR)
def test_a_negator_in_an_earlier_clause_does_not_cancel_a_cue(text: str) -> None:
    assert pk.publisher_kind(text) == "consultancy"


@pytest.mark.parametrize("about", ["publisher:consultora", "publisher:unknown"])
def test_the_recorder_refuses_a_publisher_value_that_would_exclude_nothing_or_all(
    tmp_path: Path, about: str
) -> None:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path, "test")
    with pytest.raises(ValueError, match="publisher takes one of"):
        record_exclusion(store, Exclusion(about=about, stated_at_cycle=1, words="w"))
