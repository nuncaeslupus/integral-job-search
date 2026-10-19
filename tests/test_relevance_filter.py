"""T202 - a sourced offer that is not the candidate's role is left out, and said.

Cases are derived from the issue's live round (#552), not from the code: the
candidate's six terms, the five titles they found unprompted, and wording the
terms do not contain literally. The wiring is driven through `source()`: the
scoring module was never the problem, nothing on the serving path called it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import relevance as rel
from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.identity import IdentityError, ProfileStore, create_profile
from integral.offers import load_offer
from integral.robots import Robots
from integral.sourcing import _FLOOD_CONNECTOR, GLOBAL, Response, source

AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _rule(floor: float = 0.5, related: tuple[str, ...] = ()) -> rel.RelevanceRule:
    return rel.RelevanceRule(floor, rel.AIM, related)


# --- the score -------------------------------------------------------------


@pytest.mark.parametrize("title", rel.OFF_ROLE)
def test_a_different_job_is_below_the_floor(title: str) -> None:
    assert not _rule().judge(title).relevant


@pytest.mark.parametrize("title", rel.ON_AIM)
def test_the_aim_in_other_wording_is_kept(title: str) -> None:
    assert _rule().judge(title).relevant


def test_the_body_is_not_read() -> None:
    """The reported defect: an admin vacancy that mentions LLMs once matched."""
    # Only a title is judged: there is no argument through which a body could vote.
    assert not _rule().judge("Administrativo/a Comercial").relevant


def test_the_shared_family_word_alone_proves_nothing() -> None:
    verdict = _rule().judge("Senior Software Engineer - Mobile")
    assert not verdict.relevant and verdict.score < 0.5


def test_a_stem_needs_three_letters_so_ai_is_not_aerial() -> None:
    assert not rel.same_word("ai", "aerial") and not rel.same_word("ai", "air")
    assert rel.same_word("llm", "llmops") and rel.same_word("eval", "evals")


def test_genericness_comes_from_the_candidates_own_phrases() -> None:
    """No list of titles: another aim has other generic words."""
    data = rel.RelevanceRule(0.5, ("data analyst", "data engineer", "data scientist"))
    assert not data.judge("Data Platform Lead").relevant  # `data` is generic here, so alone...
    assert data.judge("Senior Analyst").relevant  # ...`analyst` is the distinctive word


def test_no_title_is_kept_never_dropped() -> None:
    assert _rule().judge(None).relevant and _rule().judge("  ").relevant


def test_the_floor_is_the_candidates_to_move() -> None:
    title = "Applied Machine Learning Engineer"
    assert _rule(0.5).judge(title).relevant and not _rule(0.9).judge(title).relevant
    assert _rule(0.0).judge("Data Entry Clerk").relevant


def test_the_reason_names_the_score_and_the_nearest_phrase() -> None:
    why = _rule().judge("Hardware Engineer").because
    assert "0.00" in why and "floor 0.50" in why and "«" in why


# --- the profile file ------------------------------------------------------


def test_no_file_is_no_filter(store: ProfileStore) -> None:
    assert rel.load_rule(store, rel.AIM) is None


def test_the_floor_and_wording_come_from_the_profile(store: ProfileStore) -> None:
    rel.record(store, 0.7, ("rag engineer",))
    rule = rel.load_rule(store, rel.AIM)
    assert rule is not None and rule.floor == 0.7 and rule.related == ("rag engineer",)


@pytest.mark.parametrize(
    "payload",
    [[], {"floor": "high"}, {"floor": 2}, {"floor": True}, {"floor": 0.5, "related": "rag"}, {}],
)
def test_a_corrupt_file_raises_never_reads_as_no_filter(
    store: ProfileStore, payload: object
) -> None:
    store.write_json(payload, *rel.RELEVANCE_FILE)
    with pytest.raises(IdentityError):
        rel.load_rule(store, rel.AIM)


def test_the_gate_measures_zero_in_both_directions() -> None:
    result = rel.measure()
    assert result["offers_presented_below_the_relevance_floor"] == 0
    assert result["off_role_offers_presented"] == 0
    assert result["on_aim_offers_rejected"] == 0
    assert result["offers_compared"] >= rel.MINIMUM_OFFERS_COMPARED


# --- the serving path ------------------------------------------------------


def _round(store: ProfileStore, tmp_path: Path):  # type: ignore[no-untyped-def]
    package = tmp_path / "connectors" / "roles_en"
    package.mkdir(parents=True)
    (package / "connector.yaml").write_text(
        _FLOOD_CONNECTOR.replace("SITE", "roles"), encoding="utf-8"
    )
    (package / "meta.yaml").write_text(
        f"site: roles.integral.local\ncountry: {GLOBAL}\nlanguage: en\n", encoding="utf-8"
    )
    titles = [*rel.OFF_ROLE, *rel.ON_AIM]
    # Every body names the aim, as the live round's did (an unsteered board's
    # `matches_aim` reads title and body, so this is what lets the row through):
    # the body must not decide.
    cards = "".join(
        f'<div class="job"><a href="/jobs/{i}">{t}</a><span class="title">{t}</span>'
        f'<span class="company">Employer {i}</span>'
        f'<span class="text">Our LLM engineer and prompt engineer teams. {t}, '
        "fully remote.</span></div>"
        for i, t in enumerate(titles)
    )
    html = f"<html><body>{cards}</body></html>"

    def fetch(request) -> Response:  # type: ignore[no-untyped-def]
        return Response(200, html)

    run = source(
        store,
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
            reach=Reach(state="stated", modes=("remote",)),
        ),
        Aim(state="stated", terms=rel.AIM),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=1,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )
    stored = sorted(
        load_offer(store, p.stem).title or ""
        for p in Path(store.path("offers")).glob("*.json")
        if not p.name.startswith("_")
    )
    return run, stored


def test_without_a_floor_every_offer_is_presented(store: ProfileStore, tmp_path: Path) -> None:
    run, stored = _round(store, tmp_path)
    assert len(stored) == len(rel.OFF_ROLE) + len(rel.ON_AIM)
    assert "OFF ROLE" not in run.summary()


def test_with_a_floor_only_the_role_is_stored_and_the_rest_is_said(
    store: ProfileStore, tmp_path: Path
) -> None:
    rel.record(store, 0.5, rel.RELATED)
    run, stored = _round(store, tmp_path)
    assert stored == sorted(rel.ON_AIM)
    (outcome,) = run.outcomes
    assert outcome.off_role == len(rel.OFF_ROLE)
    assert all("score 0.00" in why or "score 0." in why for why in outcome.off_role_because)
    assert any("Offensive Security Engineer" in why for why in outcome.off_role_because)
    assert f"OFF ROLE roles_en: {len(rel.OFF_ROLE)} of" in run.summary()


# --- the second reader's findings (#873) ------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "GenAI Engineer",
        "Gen-AI Engineer",
        "Large Language Model Engineer",
        "A.I. Engineer",
        "KI Engineer",
        "Ingeniero/a de IA",
        "Ingeniera de Inteligencia Artificial",
        "RAG Engineer",
        "LLMOps Engineer",
    ],
)
def test_other_spellings_and_languages_of_the_aim_are_kept_with_no_related_wording(
    title: str,
) -> None:
    assert _rule(related=()).judge(title).relevant


@pytest.mark.parametrize(
    ("aim", "kept", "dropped"),
    [
        (("data engineer",), "Ingeniero de Datos", "Ingeniero de Redes"),
        (("product manager",), "Produktmanager", "Production Manager"),
        (("java developer",), "Java Developer", "JavaScript Developer"),
    ],
)
def test_the_same_role_in_another_language_and_a_longer_word_is_not_the_role(
    aim: tuple[str, ...], kept: str, dropped: str
) -> None:
    rule = rel.RelevanceRule(0.6, aim)  # a shared role word alone is half a phrase
    assert rule.judge(kept).relevant and not rule.judge(dropped).relevant


def test_javascript_is_not_java_and_production_is_not_product() -> None:
    assert not rel.same_word("java", "javascript") and not rel.same_word("product", "production")


def test_related_wording_still_adds_what_the_table_cannot_know() -> None:
    title = "Retrieval Specialist"
    assert not _rule().judge(title).relevant
    assert _rule(related=("retrieval specialist",)).judge(title).relevant


# --- #865 follow-ups (R1, R3, R4, R5) ---------------------------------------


@pytest.mark.parametrize(
    ("title", "aim"),
    [
        ("Enfermero/a", "enfermera"),
        ("Abogada", "abogado"),
        ("Camarera", "camarero"),
        ("Programadora", "programador"),
        ("Auditora", "auditor"),
        ("Back-end Engineer", "backend engineer"),
        ("Back End Engineer", "backend engineer"),
        ("Front-end Developer", "frontend developer"),
        ("Full-Stack Developer", "fullstack developer"),
        ("Gerente de Producto", "product manager"),
    ],
)
def test_gender_endings_and_split_compounds_match(title: str, aim: str) -> None:
    # floor 1.0: every word of the aim has to be found, not just the shared `engineer`
    assert rel.RelevanceRule(1.0, (aim,)).judge(title).relevant


def test_the_ending_rule_needs_a_stem_and_stays_a_whole_word() -> None:
    assert not rel.same_word("javascript", "java")
    assert not rel.same_word("production", "product")
    assert not rel.same_word("data", "date")  # stem of three letters
    assert rel.same_word("producto", "product")
    rule = rel.RelevanceRule(0.9, ("java developer",))
    assert not rule.judge("JavaScript Developer").relevant


def test_a_family_noun_beside_a_shared_subject_is_not_the_job() -> None:
    rule = rel.RelevanceRule(0.5, ("java developer", "java engineer"))
    assert not rule.judge("Python Developer").relevant
    assert rule.judge("Java Architect").relevant
    assert rule.judge("Java Engineer").relevant


@pytest.mark.parametrize(
    "title", ["Next-Gen Sales Engineer", "Gen Z Marketing Lead", "Rag Trade Buyer"]
)
def test_gen_and_rag_in_other_trades_are_dropped(title: str) -> None:
    assert not _rule().judge(title).relevant


@pytest.mark.parametrize("title", ["GenAI Engineer", "Gen-AI Engineer", "RAG Engineer"])
def test_gen_ai_and_rag_engineer_are_kept(title: str) -> None:
    assert _rule().judge(title).relevant


@pytest.mark.parametrize(
    "title",
    [
        "Agents Engineer",
        "Ingénieur Intelligence Artificielle",
        "Ingegnere Intelligenza Artificiale",
    ],
)
def test_minor_misses_are_kept(title: str) -> None:
    assert _rule().judge(title).relevant


def test_a_german_compound_is_its_parts() -> None:
    assert rel.RelevanceRule(0.5, ("data analyst",)).judge("Datenanalyst").relevant


def test_gen_ai_and_rag_need_the_ai_sense_when_every_word_of_the_aim_is_required() -> None:
    generative = rel.RelevanceRule(1.0, ("generative ai",))
    assert generative.judge("Gen-AI Engineer").relevant
    assert generative.judge("GenAI Engineer").relevant
    assert not generative.judge("Gen Z Marketing Lead").relevant
    llm = rel.RelevanceRule(1.0, ("llm engineer",))
    assert llm.judge("RAG Engineer").relevant
    assert not llm.judge("Rag Trade Buyer").relevant


@pytest.mark.parametrize(
    "title",
    [
        "RAG Lead",
        "Head of RAG",
        "RAG & Retrieval Engineer",
        "Engineer - RAG",
        "Tech Lead (RAG)",
        "RAG Engineer",
    ],
)
def test_a_standalone_upper_case_rag_is_the_ai_term_wherever_it_stands(title: str) -> None:
    assert rel.RelevanceRule(1.0, ("RAG",)).judge(title).relevant
    assert rel.RelevanceRule(0.5, ("rag engineer", "llm engineer")).judge(title).relevant


def test_a_capitalised_or_all_caps_rag_in_another_trade_is_not_the_ai_term() -> None:
    rule = rel.RelevanceRule(1.0, ("RAG",))
    assert not rule.judge("Rag Trade Buyer").relevant
    assert not rule.judge("RAG TRADE BUYER").relevant
