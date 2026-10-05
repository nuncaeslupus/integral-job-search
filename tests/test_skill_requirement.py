"""T229 — a skill the candidate lacks rules out the adverts that *require* it.

"Nunca he usado Go, así que fuera." A word match on `golang` held 128 stored
adverts, many of which offer Go as one option among several, and 299 more say
bare `Go`. Text cannot tell required from mentioned — two regex readers each
failed a second reader's cases in every round — so the step-8 model reads each
advert and records, per skill, whether it is `required`
(`extraction.OfferExtraction.skills`), and the `skill:<tech>` exclusion consumes
that: it holds an advert only on a `required` reading, and shows (marks pending)
one with no reading yet.

These tests pin the **consuming path** and the extraction's schema. They cannot
pin the model's reading — the cases' `extracted` field is what the reading of
each advert should be, taken from the second reader's verdicts.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from integral import extraction as ex
from integral import skill_requirement as sr
from integral import sourcing_exclusions as se
from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import collect_offer
from integral.offers import Offer, compute_offer_id, load_offer
from integral.presentation_log import (
    partition,
    pending_skill_counts,
    pending_skill_line,
    presented_pending_skill_counts,
    shown_notes,
)
from integral.robots import Robots
from integral.sourcing import Response, flood_board, source
from integral.sourcing_exclusions import Exclusion, record_exclusion

AT = "2026-01-01T00:00:00+00:00"
FIXTURE = Path(__file__).parent / "fixtures" / "skill_requirement" / "cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
GO = Exclusion(about="skill:go", stated_at_cycle=1, words="w", terms=("golang",))


#: An advert that contains every spelling the tests cite, so each reading can carry a
#: real span of it.
TEXT = (
    "Go golang GOLANG Golang Python Rust elixír cobol Elixir-ish tooling "
    "Go (Golang) Golang/Go Go language Go 1.21 Go lang"
)


def candidate(readings: list[dict[str, Any]] | None, text: str = TEXT) -> se.Candidate:
    """An advert whose extraction carries `readings` (`None` = not read yet)."""
    skills = None if readings is None else sr.required_skills({"skills": readings}, text)
    return se.Candidate(offer_id="x", text=text, required_skills=skills)


def reading(skill: str, role: str, quote: str | None = None) -> dict[str, Any]:
    """A reading citing `quote` (default: the skill's own spelling) in `TEXT`."""
    quote = quote or ("Go" if skill == "go" else skill)
    start = TEXT.index(quote)
    return {
        "skill": skill,
        "role": role,
        "span": {"start": start, "end": start + len(quote), "quote": quote},
    }


# --- the consuming path ---------------------------------------------------------


def test_a_required_reading_holds_the_advert() -> None:
    assert se.matches(candidate([reading("Go", "required")]), GO)


@pytest.mark.parametrize("role", ["optional", "alternative", "plus"])
def test_any_other_role_shows_the_advert(role: str) -> None:
    assert not se.matches(candidate([reading("Go", role)]), GO)


def test_an_advert_with_no_reading_yet_is_shown_whatever_it_says() -> None:
    """Pending: the text is never the deciding evidence."""
    assert not se.matches(candidate(None, "Requirements:\n- 5 years of Go. Go required."), GO)


def test_a_read_advert_naming_no_skill_is_shown_and_not_pending() -> None:
    assert not se.matches(candidate([]), GO)
    assert se.pending_skill_checks(candidate([]), [GO]) == ()


def test_pending_names_the_exclusion_that_could_not_be_checked() -> None:
    assert se.pending_skill_checks(candidate(None), [GO]) == ("skill:go",)
    other = Exclusion(about="sector:banca", stated_at_cycle=1, words="w")
    assert se.pending_skill_checks(candidate(None), [other]) == ()


def test_one_required_skill_among_other_roles_holds() -> None:
    readings = [reading("Python", "plus"), reading("Go", "required"), reading("Rust", "plus")]
    assert se.matches(candidate(readings), GO)


def test_a_required_other_skill_does_not_hold_a_go_exclusion() -> None:
    assert not se.matches(candidate([reading("Python", "required"), reading("Go", "plus")]), GO)


@pytest.mark.parametrize("spelling", ["Go", "go", "Golang", "golang", "GOLANG"])
def test_the_skill_is_matched_by_its_technology_not_its_spelling(spelling: str) -> None:
    assert se.matches(candidate([reading(spelling, "required")]), GO)


def test_a_term_names_the_same_skill_in_another_spelling() -> None:
    cobol = Exclusion(about="skill:cobol-ish", stated_at_cycle=1, words="w", terms=("COBOL",))
    assert se.matches(candidate([reading("cobol", "required")]), cobol)


def test_a_skill_outside_the_vocabulary_matches_as_a_whole_folded_word() -> None:
    elixir = Exclusion(about="skill:Elixir", stated_at_cycle=1, words="w")
    assert se.matches(candidate([reading("elixír", "required")]), elixir)
    # a phrase of several words is not one literal word: the record is pending, never held
    assert candidate([reading("Elixir-ish tooling", "required")]).required_skills is None
    assert not se.matches(candidate([reading("cobol", "required")]), elixir)


def test_other_facets_are_untouched() -> None:
    topic = Exclusion(about="topic:go", stated_at_cycle=1, words="w")
    assert se.matches(se.Candidate(offer_id="x", text="we play go on weekends"), topic)


@pytest.mark.parametrize(
    "payload",
    [None, [], "x", {}, {"skills": None}, {"skills": "go"}, {"skills": {"skill": "Go"}}],
)
def test_a_payload_without_a_list_of_readings_is_pending(payload: object) -> None:
    assert sr.required_skills(payload, TEXT) is None


def _one(**changes: Any) -> dict[str, Any]:
    return reading("Go", "required") | changes


@pytest.mark.parametrize(
    "bad",
    [
        _one(role="Required"),
        _one(role="requerido"),
        _one(role=None),
        _one(span=None),
        {"skill": "Go", "role": "required"},  # no span at all
        _one(span={"start": 0, "end": 15, "quote": "Go is mandatory"}),  # not in the advert
        _one(span={"start": 5, "end": 7, "quote": "Go"}),  # offsets elsewhere
        _one(skill="   "),
        _one(unexpected=1),
        "Go",
        3,
        None,
    ],
)
def test_a_reading_that_does_not_validate_makes_the_whole_record_pending(bad: object) -> None:
    """B1, B2 and the malformed ones: pending (shown, noted), never held, never "requires none"."""
    for extra in ([], [reading("Python", "plus")]):
        payload = {"skills": [*extra, bad]}
        assert sr.required_skills(payload, TEXT) is None
        assert not se.matches(
            se.Candidate(
                offer_id="x", text=TEXT, required_skills=sr.required_skills(payload, TEXT)
            ),
            GO,
        )
    pending = se.Candidate(offer_id="x", text=TEXT, required_skills=None)
    assert se.pending_skill_checks(pending, [GO]) == ("skill:go",)


def test_a_valid_span_in_another_advert_does_not_hold_this_one() -> None:
    """Changing the text under a stored reading turns it pending: the span is checked on read."""
    payload = {"skills": [reading("Go", "required")]}
    assert sr.required_skills(payload, TEXT) == ("Go",)
    assert sr.required_skills(payload, "x") is None
    assert sr.required_skills(payload, "") is None
    assert sr.required_skills(payload, "Python only, nothing else here") is None


def test_the_span_is_checked_on_the_advert_as_the_extraction_saw_it() -> None:
    """Extraction cites NFC text; a decomposed copy of the same advert still validates."""
    import unicodedata

    text = "Requisitos: Go y café"
    payload = {"skills": [reading_of(text, "Go", "required")]}
    assert sr.required_skills(payload, unicodedata.normalize("NFD", text)) == ("Go",)


def reading_of(
    text: str, quote: str, role: str, skill: str = "Go", title: str = ""
) -> dict[str, Any]:
    """A reading citing `quote` in the advert as extraction sees it (title, newline, text)."""
    start = ex.citable_text(title, text).index(quote)
    return {
        "skill": skill,
        "role": role,
        "span": {"start": start, "end": start + len(quote), "quote": quote},
    }


@pytest.mark.parametrize(
    "variant",
    ["Go (Golang)", "Golang/Go", "Go language", "Go 1.21", "Go lang", " Go ", "go", "GOLANG"],
)
def test_the_obvious_spelling_variants_of_a_required_skill_still_hold(variant: str) -> None:
    assert se.matches(candidate([reading(variant, "required")]), GO), variant


@pytest.mark.parametrize("other", ["Google Cloud", "Django", "MongoDB", "Gopher", "Gone"])
def test_a_different_word_that_starts_like_the_skill_does_not_hold(other: str) -> None:
    text = f"{other} is what we use"
    cand = se.Candidate(
        offer_id="x",
        text=text,
        required_skills=sr.required_skills(
            {"skills": [reading_of(text, other, "required", skill=other)]}, text
        ),
    )
    assert not se.matches(cand, GO)


# --- the reviewer's cases, read as extractions ----------------------------------


def test_the_reviewer_corpus_is_all_there() -> None:
    assert len(CASES) >= 130
    assert any(c["id"].startswith("corpus:") for c in CASES)
    assert {c["requires"] for c in CASES} == {True, False}
    assert all("extracted" in c for c in CASES)


def test_every_case_extraction_is_consistent_with_its_verdict() -> None:
    """`requires` is exactly "the extraction lists Go as required" — nothing else."""
    for case in CASES:
        listed = any(r["role"] == "required" for r in case["extracted"])
        assert listed == case["requires"], case["id"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_reviewers_case_through_the_extraction(case: dict[str, Any]) -> None:
    advert = sr.advert_of(case)
    as_read = se.Candidate(
        offer_id=str(case["id"]),
        title=str(case["title"]),
        text=advert,
        required_skills=sr.required_skills({"skills": case["extracted"]}, advert),
    )
    assert se.matches(as_read, GO) == case["requires"], case["note"]
    unread = as_read.model_copy(update={"required_skills": None})
    assert not se.matches(unread, GO), "an advert nobody has read is never held"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_reading_is_cited_from_its_cases_own_text(case: dict[str, Any]) -> None:
    """The readings carry spans of the case's advert, and only that advert validates them.

    Replace the text with "x" and every reading is refused (pending), so no case holds
    and the required ones fail `test_the_reviewers_case_through_the_extraction`.
    """
    advert = sr.advert_of(case)
    for r in case["extracted"]:
        span = r["span"]
        assert advert[span["start"] : span["end"]] == span["quote"], case["id"]
    if case["extracted"]:
        assert sr.required_skills({"skills": case["extracted"]}, advert) is not None
        assert sr.required_skills({"skills": case["extracted"]}, "x") is None


# --- the schema the model fills -------------------------------------------------


def _ad(text: str = "Requirements: Go and Python.") -> ex.NormalisedAd:
    return ex.NormalisedAd(offer_id="o1", language="en", text=text)


def _span(text: str, quote: str) -> ex.EvidenceSpan:
    start = text.index(quote)
    return ex.EvidenceSpan(start=start, end=start + len(quote), quote=quote)


def test_a_role_outside_the_four_is_refused() -> None:
    span = _span("Go", "Go")
    with pytest.raises(ValidationError):
        ex.SkillReading(skill="Go", role="mandatory", span=span)  # type: ignore[arg-type]


def test_every_role_the_skill_text_names_is_a_role_of_the_schema() -> None:
    text = (
        Path(__file__).parents[1] / ".claude" / "skills" / "step-08-understanding" / "SKILL.md"
    ).read_text(encoding="utf-8")
    for role in ex.SKILL_ROLES:
        assert f"`{role}`" in text


def test_a_reading_must_name_a_skill() -> None:
    with pytest.raises(ValidationError):
        ex.SkillReading(skill="   ", role="required", span=_span("Go", "Go"))


def test_a_reading_must_cite_the_advert() -> None:
    ad = _ad()
    invented = ex.SkillReading(
        skill="Go",
        role="required",
        span=ex.EvidenceSpan(start=0, end=5, quote="Go is"),
    )
    with pytest.raises(ex.ExtractionError, match="not what the advert says"):
        ex.accept_skill_readings(ad, [invented])


def test_a_technology_read_in_two_roles_is_refused_whatever_its_spelling() -> None:
    ad = _ad("Requirements: Go. Golang a plus.")
    required = ex.SkillReading(skill="Go", role="required", span=_span(ad.text, "Go."[:2]))
    plus = ex.SkillReading(skill="Golang", role="plus", span=_span(ad.text, "Golang"))
    assert ex.accept_skill_readings(ad, [required, required]) == [required, required]
    for other in ("Golang", "GOLANG", "Go (Golang)", "go"):
        clash = plus.model_copy(update={"skill": other})
        with pytest.raises(ex.ExtractionError, match="both"):
            ex.accept_skill_readings(ad, [required, clash])
        with pytest.raises(ex.ExtractionError, match="both"):
            ex.accept_skill_readings(ad, [clash, required])


@pytest.mark.parametrize(
    "skill",
    ["Java/Go", "Go, Python o Java", "Kotlin or Java", "Python and Go", "", "a b"],
)
def test_a_reading_names_exactly_one_technology(skill: str) -> None:
    ad = _ad("Java/Go, Python and Go, Kotlin or Java, Java Script. a b")
    quote = "Go" if "Go" in skill else "Java"
    reading_ = ex.SkillReading.model_construct(
        skill=skill, role="required", span=_span(ad.text, quote)
    )
    with pytest.raises(ex.ExtractionError, match="exactly one technology"):
        ex.accept_skill_readings(ad, [reading_])


def test_java_script_is_javascript_not_java() -> None:
    """F4."""
    assert sr.identity("Java Script") == "javascript"
    assert not sr.names("Java Script", sr.target_of("java"))
    assert sr.names("Java Script", sr.target_of("javascript"))


@pytest.mark.parametrize("skill", ["Go (Golang)", "Go 1.21", "Go language", "Golang/Go", "Java"])
def test_a_variant_that_resolves_to_one_technology_is_accepted(skill: str) -> None:
    text = "Go (Golang) Go 1.21 Go language Golang/Go Java"
    ad = _ad(text)
    quote = "Java" if skill == "Java" else skill
    ex.accept_skill_readings(
        ad, [ex.SkillReading(skill=skill, role="required", span=_span(text, quote))]
    )


def test_the_span_must_name_the_readings_own_technology() -> None:
    """F1: a real quote about another skill does not ground this reading."""
    text = "Requirements: 5 years of Python required. Go is a plus."
    ad = _ad(text)
    about_python = ex.SkillReading(skill="Go", role="required", span=_span(text, "Python required"))
    with pytest.raises(ex.ExtractionError, match="does not name it"):
        ex.accept_skill_readings(ad, [about_python])
    ok = ex.SkillReading(skill="Go", role="plus", span=_span(text, "Go is a plus"))
    assert ex.accept_skill_readings(ad, [ok]) == [ok]
    payload = {"skills": [about_python.model_dump()]}
    assert sr.required_skills(payload, text) is None


def test_a_literal_skill_is_one_word_and_c_is_not_c_sharp() -> None:
    """F5: `#`, `+` and a `-` suffix/prefix belong to the word."""
    exclusion = Exclusion(about="skill:Zed", stated_at_cycle=1, words="w")
    for other in ("Zed#", "Zed++", "Objective-Zed", "Zedd", "Zed-lang"):
        text = f"We write {other}"
        payload = {"skills": [reading_of(text, other, "required", skill=other)]}
        cand = se.Candidate(
            offer_id="x", text=text, required_skills=sr.required_skills(payload, text)
        )
        assert not se.matches(cand, exclusion), other
    # and the quote of a plain `Zed` skill may not be `Zed++`: it names a different word
    text = "We write Zed++"
    payload = {"skills": [reading_of(text, "Zed++", "required", skill="Zed")]}
    assert sr.required_skills(payload, text) is None
    ok_text = "We write Zed daily"
    payload = {"skills": [reading_of(ok_text, "Zed", "required", skill="Zed")]}
    cand = se.Candidate(
        offer_id="x", text=ok_text, required_skills=sr.required_skills(payload, ok_text)
    )
    assert se.matches(cand, exclusion)
    # the reviewer's literal-`c` case, whichever way `C` resolves
    c_text = "We write C# and C++ and Objective-C"
    for other in ("C#", "C++", "Objective-C"):
        payload = {"skills": [reading_of(c_text, other, "required", skill=other)]}
        cand = se.Candidate(
            offer_id="x", text=c_text, required_skills=sr.required_skills(payload, c_text)
        )
        assert not se.matches(cand, Exclusion(about="skill:c", stated_at_cycle=1, words="w"))


def test_a_title_cited_reading_validates_the_same_in_production() -> None:
    """F6: the fixtures' text is production's: title, newline, text."""
    title, text = "Golang Developer", "You will build microservices."
    payload = {"skills": [reading_of(text, "Golang", "required", title=title)]}
    assert sr.required_skills(payload, text, title) == ("Go",)
    assert sr.required_skills(payload, text) is None  # no title passed: not the advert it cites


def _offer(text: str, title: str = "Backend") -> Offer:
    return Offer(id=compute_offer_id(text), source="test", text=text, title=title)


def test_extract_leaves_skills_pending_until_the_model_reads_them() -> None:
    offer = _offer("Requirements: Go and Python.")
    assert ex.extract(offer, []).skills is None
    assert ex.extract(offer, [], model_skills=[]).skills == []
    read = ex.SkillReading(
        skill="Go",
        role="required",
        span=_span(ex.citable_text(offer.title, offer.text), "Go and"),
    )
    assert ex.extract(offer, [], model_skills=[read]).skills == [read]


def test_extract_refuses_a_reading_the_advert_does_not_back() -> None:
    offer = _offer("Requirements: Python.")
    fabricated = ex.SkillReading(
        skill="Go", role="required", span=ex.EvidenceSpan(start=0, end=2, quote="Go")
    )
    with pytest.raises(ex.ExtractionError):
        ex.extract(offer, [], model_skills=[fabricated])


def test_the_model_request_asks_for_skills_and_still_has_no_profile() -> None:
    request = ex.model_request(_ad(), [])
    assert request.read_skills is True
    assert "profile" not in ex.ModelRequest.model_fields


def test_an_extraction_stored_before_the_field_existed_still_loads_as_pending() -> None:
    old = {
        "offer_id": "o1",
        "language": "en",
        "scores": [],
        "unsettled": [],
        "unmapped_concepts": [],
    }
    loaded = ex.OfferExtraction.model_validate(old)
    assert loaded.skills is None


# --- applied where adverts reach the candidate ----------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "tester")
    return ProfileStore(tmp_path, "tester")


def _store_offer(store: ProfileStore, text: str, title: str) -> str:
    offer = _offer(text, title)
    collect_offer(store, offer, at=AT)
    return offer.id


def _read(store: ProfileStore, offer_id: str, readings: list[dict[str, Any]] | None) -> None:
    payload = ex.OfferExtraction(offer_id=offer_id, language="en").model_dump()
    payload["offer_id"] = offer_id
    payload["skills"] = readings
    store.write_json(payload, "extractions", f"{offer_id}.json")


def _rule_out_go(store: ProfileStore) -> None:
    record_exclusion(
        store,
        Exclusion(
            about="skill:go",
            stated_at_cycle=1,
            words="Nunca he usado Go, así que fuera.",
            terms=("golang",),
        ),
    )


def _span_of(text: str, quote: str) -> dict[str, object]:
    start = text.index(quote)
    return {"start": start, "end": start + len(quote), "quote": quote}


def test_partition_holds_back_only_the_adverts_that_the_extraction_says_require_the_skill(
    store: ProfileStore,
) -> None:
    requires_text = "Requisitos:\n- Go\n- SQL"
    requires = _store_offer(store, requires_text, "Backend A")
    option = _store_offer(store, "Experiencia con Java, Go o Python.", "Backend B")
    unread = _store_offer(store, "Requisitos:\n- Go\n- SQL y más", "Backend C")
    bare = _store_offer(store, "Python, SQL y AWS.", "Backend D")
    ids = [requires, option, unread, bare]
    assert len(partition(store, ids)[0]) == 4
    _rule_out_go(store)
    option_text = "Experiencia con Java, Go o Python."
    _read(store, requires, [reading_of(requires_text, "Go", "required", title="Backend A")])
    _read(store, option, [reading_of(option_text, "Go", "alternative", title="Backend B")])
    _read(store, bare, [])
    show, hold = partition(store, ids)
    assert [h.offer_id for h in hold] == [requires]
    assert set(show) == {option, unread, bare}
    assert "skill:go" in hold[0].reason


def test_the_advert_that_says_go_is_required_is_shown_while_unread(store: ProfileStore) -> None:
    text = "Requisitos:\n- Go\n- SQL"
    offer_id = _store_offer(store, text, "Backend A")
    _rule_out_go(store)
    show, hold = partition(store, [offer_id])
    assert (show, hold) == ([offer_id], [])
    assert "skill:go" in pending_skill_line(store, [offer_id])
    assert "1" in pending_skill_line(store, [offer_id])


def test_nothing_is_pending_once_read_or_when_no_skill_is_ruled_out(store: ProfileStore) -> None:
    offer_id = _store_offer(store, "Python", "Backend A")
    assert pending_skill_line(store, [offer_id]) == ""
    _rule_out_go(store)
    assert pending_skill_line(store, [offer_id]) != ""
    _read(store, offer_id, [])
    assert pending_skill_line(store, [offer_id]) == ""


def test_an_unreadable_extraction_is_pending_not_held(store: ProfileStore) -> None:
    offer_id = _store_offer(store, "Requisitos:\n- Go", "Backend A")
    _rule_out_go(store)
    store.path("extractions").mkdir(parents=True, exist_ok=True)
    store.path("extractions", f"{offer_id}.json").write_text("{not json", encoding="utf-8")
    assert partition(store, [offer_id])[0] == [offer_id]


def _source_round(store: ProfileStore, tmp_path: Path) -> object:
    pages = flood_board(tmp_path / "connectors", rows=4)

    def fetch(request: ListRequest) -> Response:
        return Response(200, pages[request.url].html)

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


def _stored_ids(store: ProfileStore) -> set[str]:
    return {p.stem for p in Path(store.path("offers")).glob("*.json") if not p.name.startswith("_")}


def test_source_applies_a_required_reading_and_shows_what_is_unread(
    store: ProfileStore, tmp_path: Path
) -> None:
    root = tmp_path / "baseline"
    root.mkdir()
    create_profile(root, "Test", handle="test", language="es", fiction=True)
    base = ProfileStore(root, "test")
    _source_round(base, root)
    baseline = _stored_ids(base)
    assert len(baseline) >= 2
    victim = sorted(baseline)[0]
    offer = load_offer(base, victim)
    advert = ex.citable_text(offer.title, offer.text)
    word = next(w for w in re.findall(r"[A-Za-z]{4,}", advert) if w.lower() != "python")
    start = advert.index(word)
    cited = {
        "skill": word,
        "role": "required",
        "span": {"start": start, "end": start + len(word), "quote": word},
    }
    rule = Exclusion(about=f"skill:{word}", stated_at_cycle=1, words="w")

    record_exclusion(store, rule)
    # Nothing read yet: every advert is shown, none is held on a guess.
    _source_round(store, tmp_path)
    assert _stored_ids(store) == baseline

    # Once step 8 has read one advert as requiring it, a fresh round leaves it out and says so.
    other = tmp_path / "second"
    other.mkdir()
    create_profile(other, "Test", handle="test", language="es", fiction=True)
    second = ProfileStore(other, "test")
    record_exclusion(second, rule)
    _read(second, victim, [cited])
    run = _source_round(second, other)
    assert _stored_ids(second) == baseline - {victim}
    (outcome,) = run.outcomes  # type: ignore[attr-defined]
    assert outcome.excluded == 1
    assert f"skill:{word}" in outcome.excluded_because[0]


def test_a_stored_reading_with_a_span_not_in_the_advert_is_shown_with_a_note(
    store: ProfileStore,
) -> None:
    """B1 through the real path: create, collect, extraction on disk, partition."""
    text = "We use Python. Experience with Go is a plus."
    offer_id = _store_offer(store, text, "Backend")
    _rule_out_go(store)
    forged = {
        "skill": "Go",
        "role": "required",
        "span": {"start": 0, "end": 15, "quote": "Go is mandatory"},
    }
    _read(store, offer_id, [forged])
    assert partition(store, [offer_id]) == ([offer_id], [])
    assert pending_skill_counts(store, [offer_id]) == {"skill:go": 1}
    _read(store, offer_id, [{"skill": "Go", "role": "required"}])  # B2: no span
    assert partition(store, [offer_id]) == ([offer_id], [])
    assert pending_skill_counts(store, [offer_id]) == {"skill:go": 1}


def test_step_9_emits_the_pending_note_next_to_the_other_notes(store: ProfileStore) -> None:
    offer_id = _store_offer(store, "Requisitos:\n- Go", "Backend")
    assert not [n for n in shown_notes(store, [offer_id]) if "skill:go" in n]
    _rule_out_go(store)
    notes = [n for n in shown_notes(store, [offer_id]) if "skill:go" in n]
    assert len(notes) == 1
    _read(store, offer_id, [reading_of("Requisitos:\n- Go", "Go", "required", title="Backend")])
    assert not [n for n in shown_notes(store, [offer_id]) if "skill:go" in n]


def test_the_step_9_skill_calls_what_the_code_provides() -> None:
    text = (
        Path(__file__).parents[1] / ".claude" / "skills" / "step-09-ranking" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "shown_notes(store, show)" in text
    imported = text.split("from integral.presentation_log import ", 1)[1].split("\n", 1)[0]
    import integral.presentation_log as pl

    for name in (n.strip() for n in imported.split(",")):
        assert hasattr(pl, name), name


def test_the_step_9_checkpoint_reports_the_shown_adverts_still_unread(store: ProfileStore) -> None:
    offer_id = _store_offer(store, "Requisitos:\n- Go", "Backend")
    _rule_out_go(store)
    from integral.presentation_log import present

    present(store, [offer_id], at=AT)
    assert presented_pending_skill_counts(store) == {"skill:go": 1}
    script = (
        Path(__file__).parents[1]
        / ".claude"
        / "skills"
        / "step-09-ranking"
        / "scripts"
        / "run_checkpoint.py"
    ).read_text(encoding="utf-8")
    assert '"skill_checks_pending_on_presented": presented_pending_skill_counts(store)' in script


def test_the_live_round_says_a_skill_exclusion_was_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integral import exclusion_live_round as live

    assert live.measure_live_round()["skill_exclusions_not_applied"] == []
    monkeypatch.setattr(
        live,
        "LIVE_ROUND_EXCLUSIONS",
        (*live.LIVE_ROUND_EXCLUSIONS, ("skill:go", "nunca he usado Go", ("golang",))),
    )
    measured = live.measure_live_round()
    assert measured["skill_exclusions_not_applied"] == ["skill:go"]
    assert "skill:go" in measured["never_tripped"]


# --- how a reading gets stored ---------------------------------------------------


def test_the_step_8_write_path_stores_validated_readings(store: ProfileStore) -> None:
    text = "Requisitos:\n- Go\n- SQL"
    offer_id = _store_offer(store, text, "Backend")
    _rule_out_go(store)
    path = sr.store_readings(store, offer_id, [reading_of(text, "Go", "required", title="Backend")])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["skills"][0]["role"] == "required" and stored["offer_id"] == offer_id
    assert partition(store, [offer_id])[1][0].offer_id == offer_id


def test_the_write_path_keeps_the_rest_of_an_existing_extraction(store: ProfileStore) -> None:
    text = "Requisitos:\n- Go"
    offer_id = _store_offer(store, text, "Backend")
    store.write_json(
        {
            "offer_id": offer_id,
            "language": "es",
            "scores": [],
            "unsettled": ["pay"],
            "unmapped_concepts": ["x"],
            "skills": None,
        },
        "extractions",
        f"{offer_id}.json",
    )
    path = sr.store_readings(store, offer_id, [])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["unsettled"] == ["pay"] and stored["unmapped_concepts"] == ["x"]
    assert stored["skills"] == []


@pytest.mark.parametrize(
    "bad",
    [
        {"skill": "Go", "role": "required"},
        {"skill": "Go", "role": "mandatory", "span": {"start": 0, "end": 2, "quote": "Re"}},
        {"skill": "Go", "role": "required", "span": {"start": 0, "end": 2, "quote": "Xx"}},
    ],
)
def test_the_write_path_refuses_a_bad_reading_and_writes_nothing(
    store: ProfileStore, bad: dict[str, Any]
) -> None:
    offer_id = _store_offer(store, "Requisitos:\n- Go", "Backend")
    with pytest.raises(ex.ExtractionError):
        sr.store_readings(store, offer_id, [bad])
    assert not store.path("extractions", f"{offer_id}.json").exists()


def test_the_write_path_refuses_an_offer_that_is_not_stored(store: ProfileStore) -> None:
    with pytest.raises(ex.ExtractionError):
        sr.store_readings(store, "sha256:nope", [])


def test_the_command_line_stores_and_exits_two_on_a_refusal(
    store: ProfileStore, tmp_path: Path
) -> None:
    text = "Requisitos:\n- Go"
    offer_id = _store_offer(store, text, "Backend")
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps([reading_of(text, "Go", "required", title="Backend")]), encoding="utf-8"
    )
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"skill": "Go", "role": "required"}]), encoding="utf-8")
    base = ["--handle", store.home.name, "--offer", offer_id, "--root", str(store.home.parent)]
    assert sr._store_main([*base, "--readings", str(bad)]) == 2
    assert not store.path("extractions", f"{offer_id}.json").exists()
    assert sr._store_main([*base, "--readings", str(good)]) == 0
    assert store.path("extractions", f"{offer_id}.json").exists()


def test_the_command_line_exits_two_on_an_invalid_handle(tmp_path: Path) -> None:
    readings = tmp_path / "r.json"
    readings.write_text("[]", encoding="utf-8")
    code = sr._store_main(
        [
            "--handle",
            "../x",
            "--offer",
            "sha256:a",
            "--readings",
            str(readings),
            "--root",
            str(tmp_path),
        ]
    )
    assert code == 2


def test_the_step_8_skill_names_the_command_the_code_provides() -> None:
    text = (
        Path(__file__).parents[1] / ".claude" / "skills" / "step-08-understanding" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "uv run python -m integral.skill_requirement store --handle" in text
    assert "integral.stack_fit.VOCABULARY" in text


# --- the measurement ------------------------------------------------------------


def test_the_measurement_over_the_reviewers_cases_is_zero_on_both_sides() -> None:
    measured = sr.measure()
    assert measured["status"] == "measured"
    assert measured["requiring_cases"] >= sr.FEWEST_REQUIRING_CASES
    assert measured["adverts_requiring_a_ruled_out_skill_presented"] == 0
    assert measured["adverts_not_requiring_a_ruled_out_skill_held"] == 0
    assert measured["pending_adverts_held"] == 0
    assert measured["stored_corpus_status"] == "unmeasured"
    assert measured["stored_corpus_adverts_requiring_a_ruled_out_skill_presented"] == -1


def test_an_empty_population_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    empty = tmp_path / "cases.json"
    empty.write_text("[]", encoding="utf-8")
    measured = sr.measure(empty)
    assert measured["status"] == "unmeasured"
    assert measured["adverts_requiring_a_ruled_out_skill_presented"] == -1
    assert measured["pending_adverts_held"] == -1


def test_a_population_with_only_one_side_is_unmeasured(tmp_path: Path) -> None:
    only_required = [c for c in CASES if c["requires"]]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(only_required), encoding="utf-8")
    assert sr.measure(path)["status"] == "unmeasured"


def test_the_measurement_counts_a_required_advert_that_is_let_through(tmp_path: Path) -> None:
    """The metric moves when the fixture says required and the path lets it by."""
    broken = [dict(c) for c in CASES]
    for case in broken:
        if case["id"] == "E1":
            case["extracted"] = [{**case["extracted"][0], "skill": "Rust"}]  # not Go
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert sr.measure(path)["adverts_requiring_a_ruled_out_skill_presented"] == 1


def test_the_measurement_counts_a_non_required_advert_that_is_held(tmp_path: Path) -> None:
    broken = [dict(c) for c in CASES]
    for case in broken:
        if case["id"] == "E3":
            case["extracted"] = [{**case["extracted"][0], "role": "required"}]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    assert sr.measure(path)["adverts_not_requiring_a_ruled_out_skill_held"] == 1


def test_the_committed_evidence_matches_the_measurement() -> None:
    committed = json.loads(sr.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == sr.record(sr.measure())


def test_the_regex_reader_is_gone() -> None:
    """No text reading decides a hold: the module has no function that reads an advert's prose."""
    public = {n for n in dir(sr) if not n.startswith("_")}
    assert not public & {"requires", "read_mentions", "Reading"}


def test_the_module_reads_in_a_fresh_process() -> None:
    """The evidence entry point runs and exits 0 in its own interpreter."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            "from integral import skill_requirement as s; print(s.measure()['status'])",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout.strip() == "measured"
