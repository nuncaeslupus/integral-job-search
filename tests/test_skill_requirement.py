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

import json
from pathlib import Path

import pytest

from integral import skill_requirement as sr
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


def req(text: str) -> str:
    """`text` placed under a requirements heading, where a mention can hold."""
    return f"Requirements:\n{text}"


REQUIRED = [
    "We need 3 years of Go experience.",
    "Go experience is required.",
    "Imprescindible: Golang",
    "Requisitos:\n- Python\n- Go\n- Docker",
    "Requirements: Go and Python.",
    "Python and Go are required.",
    "Requirements:\nGo, Python",
    "Nice to have:\n- Docker\nRequirements:\n- Go",
    "Se valora:\n- Docker\nRequisitos:\n- Go",
    "Python required, but Go is also required.",
    "Go required, Python a plus.",
    "Go is a plus for others; for this role Go is a must.",
    "Go is not a plus, it is required.",
    "Go no es opcional: es imprescindible.",
    "Requirements: Golang backend work.",
    "## Requirements\n- Go\n## Nice to have\n- Rust",
    "Requirements: Strong Go. Docker is a plus.",
    "Docker and Kubernetes (a plus); Go is required.",
    "Go is required and Python is a plus.",
    "Se valorará Kafka. Imprescindible Go.",
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
    # and the same words where a mention *can* hold: the cue, not the missing heading, shows it
    assert not held("go", req(text), terms=("golang",))


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
    text = req("Python required, but Go is a plus.")
    assert held("python", text)
    assert not held("go", text)


def test_a_parenthetical_plus_softens_only_the_item_before_it() -> None:
    text = req("Python, Go (nice to have), Docker")
    assert held("python", text)
    assert held("docker", text)
    assert not held("go", text)


def test_a_cue_inside_a_parenthesis_does_not_soften_the_main_clause() -> None:
    assert held("python", req("Python experience (Go a plus)."))
    assert held("go", req("Python (Go)."))


def test_a_plus_in_the_next_sentence_does_not_soften_this_one() -> None:
    assert held("go", req("Strong Go. Docker is a plus."))
    assert not held("docker", req("Strong Go. Docker is a plus."))


def test_a_list_of_needs_is_not_a_list_of_alternatives() -> None:
    text = req("Python, Go and Docker.")
    assert all(held(skill, text) for skill in ("python", "go", "docker"))


# --- other values --------------------------------------------------------------


def test_a_skill_outside_the_vocabulary_is_read_the_same_way() -> None:
    assert held("cobol", "COBOL required.")
    assert held("cobol", req("Mainframe COBOL, JCL and CICS."))
    assert not held("cobol", req("COBOL is a plus."))
    assert not held("cobol", req("COBOL or RPG."))
    assert not held("cobol", req("RPG or COBOL."))
    assert not held("cobol", req("RPG/COBOL."))


def test_a_term_names_the_same_skill_in_another_spelling() -> None:
    assert held("go", req("Golang developer."), terms=("golang",))
    assert held("golang", req("Golang developer."))
    assert held("kubernetes", req("K8s in production."))


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


# --- T229 second reader: the polarity is "shown unless a requirement context" ---
#
# 105 cases written from the spec before the implementation was read, plus the one
# stored advert the first version held although it says outright it does not expect
# Go. `requires` is the verdict [SPEC-1] gives: does the advert hold the candidate
# to Go. One reviewer case is deliberately absent: all-caps `GO` is not named at
# all (`stack_fit` R3, exact case), so `REQUIREMENTS:\n- GO` is shown — fail-closed,
# and true before this task.

FIXTURE = Path(__file__).parent / "fixtures" / "skill_requirement" / "cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_reviewer_corpus_is_all_there() -> None:
    assert len(CASES) >= 100
    assert any(c["id"].startswith("corpus:") for c in CASES)
    assert {c["requires"] for c in CASES} == {True, False}


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_reviewers_case(case: dict[str, object]) -> None:
    got = sr.requires(case["title"], case["text"], sr.target_of("go", ("golang",)))  # type: ignore[arg-type]
    assert got is case["requires"], case["note"]


# --- the four closed rules, each pinned where it alone decides ------------------


@pytest.mark.parametrize(
    "text",
    [
        "Experience with Go.",  # rule 1: plain prose names Go, requires nothing
        "About us: our platform is built in Go.\nRequirements:\n- Python",
        "Benefits:\n- Go conference budget",
        "Our stack: Go, Kafka, AWS.",
        "Ofrecemos:\n- Proyectos en Go",
    ],
)
def test_rule_1_a_mention_outside_a_requirement_context_is_shown(text: str) -> None:
    assert not held("go", text)


def test_rule_1_a_heading_the_module_does_not_know_still_resets_the_section() -> None:
    assert not held("go", "Requirements:\n- Python\nSome Brand New Heading\n- Go")


@pytest.mark.parametrize(
    "text",
    [
        "Requirements:\n- No prior Go experience needed",
        "Requisitos:\n- No se requiere experiencia en Go",
        "Requirements:\n- You don't need to know Go",
        "Requirements:\n- Without Go experience, apply anyway",
        "Requisitos:\n- Sin experiencia en Go, no pasa nada",
        "Requirements:\n- While we use Go, we don't expect you to be an expert",
        "Requirements:\n- Go knowledge is not mandatory",
    ],
)
def test_rule_2_a_negated_need_never_holds(text: str) -> None:
    assert not held("go", text)


def test_rule_2_a_negation_does_not_leak_across_punctuation() -> None:
    assert held("go", req("Go is not a plus, it is required."))
    assert held("go", req("Python is not required. Go is required."))


@pytest.mark.parametrize(
    "text",
    [
        "Requirements:\n- Willingness to learn Go",
        "Requisitos:\n- Aprenderás Go con nosotros",
        "Requirements:\n- Go (we will teach you)",
        "Requirements:\n- Mentoring in Go",
    ],
)
def test_rule_3_learning_wording_never_holds(text: str) -> None:
    assert not held("go", text)


@pytest.mark.parametrize(
    "text",
    [
        "Requirements:\n- Go above and beyond for our customers",
        "Requirements:\n- Go big on quality",
        "Requirements:\n- Python\n\nGo make an impact every day.",
        "Requirements: Ready to Go? Apply now!",
        "Requirements:\n- Be ready to Go.",
    ],
)
def test_rule_4_the_verb_go_is_not_the_skill(text: str) -> None:
    assert not held("go", text)


@pytest.mark.parametrize(
    "text",
    [
        "Requirements:\n- Go",
        "Requirements:\n- Go, Python and Docker",
        "Requirements:\n- Go (Golang)",
        "Requirements:\n- Go experience",
        "Requirements:\n- Go is the language of our backend",
    ],
)
def test_rule_4_a_bullet_that_is_the_skill_still_holds(text: str) -> None:
    assert held("go", text)


def test_rule_5_a_conditional_is_an_invitation() -> None:
    assert not held("go", "Requisitos:\n- Python\nSi además conoces Go, ¡genial!")
    assert not held("go", "Even better if you have:\n- Go")
    assert held("go", "Go is required if you join the platform team.")


def test_rule_1_a_heading_with_its_text_on_the_same_line_resets_the_section() -> None:
    assert not held("go", "Requirements:\n- Python\nOur stack: Go, Kafka.")
    assert held("go", "Qualifications: Go and Python.")


def test_rule_4_go_with_an_exclamation_is_the_verb() -> None:
    assert not held("go", "Requirements:\n- Python\n- Let's Go!")


def test_an_alternative_cue_alone_shows_a_single_mention() -> None:
    assert not held("go", req("Experience in at least one of Go."))
    assert not held("go", req("Experiencia en alguno de Go."))
