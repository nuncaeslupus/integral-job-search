"""T229 — a skill the candidate lacks rules out the adverts that *require* it.

"Nunca he usado Go, así que fuera." A word match on `golang` held 128 stored
adverts, many of which offer Go as one option among several, and 299 more say
bare `Go`. The `skill:<technology>` facet holds an advert only where a mention
of the technology is a requirement.

Every case is derived from that statement, not from the implementation: what a
person means by "required", "a plus" and "one of". The cases that matter most are
the fail-open ones — an advert that **does** require the skill and is let through
— so each softening cue is paired with a sentence where the same words soften
something *else*, or are denied.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import sourcing_exclusions as se
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import collect_offer
from integral.offers import Offer, compute_offer_id
from integral.presentation_log import partition
from integral.sourcing_exclusions import Exclusion, record_exclusion

AT = "2026-01-01T00:00:00+00:00"


def held(value: str, text: str, *, title: str | None = None, terms: tuple[str, ...] = ()) -> bool:
    exclusion = Exclusion(about=f"skill:{value}", stated_at_cycle=1, words="w", terms=terms)
    return se.matches(se.Candidate(offer_id="x", title=title, text=text), exclusion)


# --- required: the advert holds the candidate to it (fail-open if let through) ---

REQUIRED = [
    "We need 3 years of Go experience.",
    "Experiencia sólida en Go.",
    "Requisitos:\n- Python\n- Go\n- Docker",
    "Python and Go are required.",
    "Python, Go and Docker.",
    "We use Go, Python and Docker in production.",
    "Requirements:\nGo, Python",
    "Nice to have:\n- Docker\nRequirements:\n- Go",
    "Se valora:\n- Docker\nRequisitos:\n- Go",
    "Python required, but Go too.",
    "Go required, Python a plus.",
    "Go is a plus for others; for this role Go is a must.",
    "Go is not a plus, it is required.",
    "Go no es opcional: es imprescindible.",
    "Golang backend work.",
    "Desarrollador backend (Go)",
    "## Requirements\n- Go\n## Nice to have\n- Rust",
    "Strong Go. Docker is a plus.",
    "Docker and Kubernetes (a plus); Go is required.",
]


@pytest.mark.parametrize("text", REQUIRED)
def test_an_advert_requiring_the_skill_is_held(text: str) -> None:
    assert held("go", text, terms=("golang",))


def test_a_title_naming_the_skill_requires_it() -> None:
    assert held("go", "Join our team.", title="Senior Go Developer")
    assert held("go", "Join our team.", title="Backend Engineer (Golang)")


def test_one_required_mention_among_optional_ones_holds_the_advert() -> None:
    assert held("go", "Go is a plus.\nRequisitos:\n- Go")


# --- not required: an option, a plus, an example (fail-closed if held) ----------

NOT_REQUIRED = [
    "Experience with Java, Go or Python.",
    "Java, Python, Go or Rust.",
    "Experiencia con Java, Go o Python.",
    "Experiencia en Go/Java/Python.",
    "Go and/or Java.",
    "Go o similar.",
    "Go (or equivalent).",
    "Go or any other language.",
    "Experience with one of: Go, Java.",
    "Experience with one of the following:\n- Go\n- Java",
    "Experiencia en alguno de estos:\n- Go\n- Java",
    "Languages such as Go or Rust.",
    "Lenguajes como Go o Rust.",
    "Languages, e.g. Go.",
    "Go is a plus.",
    "Go would be nice to have.",
    "Python required. Go is a nice-to-have.",
    "Se valora Go.",
    "Go es un plus.",
    "Deseable Go.",
    "Es valorarà Go.",
    "Python, Go (nice to have), Docker",
    "Python, Go (se valora), Docker",
    "Python experience (Go a plus).",
    "Backend developer (Go preferred)",
    "Nice to have:\n- Go\n- Docker",
    "Se valorará:\n- Go",
    "## Nice to have\nGo",
    "Go not required.",
    "Go no es imprescindible.",
    "Go preferred, Python required.",
    "Ideally Go.",
]


@pytest.mark.parametrize("text", NOT_REQUIRED)
def test_an_advert_naming_the_skill_only_as_an_option_is_shown(text: str) -> None:
    assert not held("go", text, terms=("golang",))


def test_an_advert_that_does_not_name_it_is_shown() -> None:
    assert not held("go", "Python engineer, Docker, AWS.")


@pytest.mark.parametrize(
    "text",
    [
        "Let's go build things together.",
        "We go to market in spring.",
        "Ready to go ahead? Go further!",
        "Go-to-market strategy lead.",
        "Go live in Q3.",
    ],
)
def test_the_verb_is_not_the_skill(text: str) -> None:
    assert not held("go", text)


# --- the cue binds to its own mention, not to a neighbour -----------------------


def test_a_plus_for_one_skill_does_not_soften_another() -> None:
    text = "Python required, but Go is a plus."
    assert held("python", text)
    assert not held("go", text)


def test_a_parenthetical_plus_softens_only_the_item_before_it() -> None:
    text = "Python, Go (nice to have), Docker"
    assert held("python", text)
    assert held("docker", text)
    assert not held("go", text)


def test_a_cue_inside_a_parenthesis_does_not_soften_the_main_clause() -> None:
    assert held("python", "Python experience (Go a plus).")
    assert held("go", "Python (Go).")


def test_a_plus_in_the_next_sentence_does_not_soften_this_one() -> None:
    assert held("go", "Strong Go. Docker is a plus.")
    assert not held("docker", "Strong Go. Docker is a plus.")


def test_a_list_of_needs_is_not_a_list_of_alternatives() -> None:
    text = "Python, Go and Docker."
    assert all(held(skill, text) for skill in ("python", "go", "docker"))


# --- other values --------------------------------------------------------------


def test_a_skill_outside_the_vocabulary_is_read_the_same_way() -> None:
    assert held("cobol", "COBOL required.")
    assert held("cobol", "Mainframe COBOL, JCL and CICS.")
    assert not held("cobol", "COBOL is a plus.")
    assert not held("cobol", "COBOL or RPG.")
    assert not held("cobol", "RPG or COBOL.")
    assert not held("cobol", "RPG/COBOL.")


def test_a_term_names_the_same_skill_in_another_spelling() -> None:
    assert held("go", "Golang developer.", terms=("golang",))
    assert held("golang", "Golang developer.")
    assert held("kubernetes", "K8s in production.")


def test_a_skill_with_no_value_is_not_an_exclusion() -> None:
    with pytest.raises(ValueError):
        Exclusion(about="skill:", stated_at_cycle=1, words="w")


def test_other_facets_are_untouched() -> None:
    exclusion = Exclusion(about="sector:banca", stated_at_cycle=1, words="w")
    assert se.matches(se.Candidate(offer_id="x", text="Go is a plus. Trabajo en banca."), exclusion)


# --- applied where adverts reach the candidate ---------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _store_offer(store: ProfileStore, text: str, title: str) -> str:
    offer = Offer(id=compute_offer_id(text), source="test", text=text, title=title)
    collect_offer(store, offer, at=AT)
    return offer.id


def test_partition_holds_back_only_the_adverts_that_require_the_skill(
    store: ProfileStore,
) -> None:
    requires = _store_offer(store, "Requisitos:\n- Go\n- SQL", "Backend A")
    option = _store_offer(store, "Experiencia con Java, Go o Python.", "Backend B")
    plus = _store_offer(store, "Python. Se valora Go.", "Backend C")
    bare = _store_offer(store, "Python, SQL y AWS.", "Backend D")
    ids = [requires, option, plus, bare]
    assert len(partition(store, ids)[0]) == 4
    record_exclusion(
        store,
        Exclusion(
            about="skill:go",
            stated_at_cycle=1,
            words="Nunca he usado Go, así que fuera.",
            terms=("golang",),
        ),
    )
    show, hold = partition(store, ids)
    assert [h.offer_id for h in hold] == [requires]
    assert set(show) == {option, plus, bare}
    assert "skill:go" in hold[0].reason
