"""T203 — a topic the candidate ruled out is applied to every sourced offer.

T90's module was correct and tested and nothing on the serving path called it.
These tests drive `source()` itself: the producer records what was stated, the
round reads it back, and what was left out is counted rather than dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import exclusion_live_round as live
from integral import sourcing_exclusions as se
from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.connectors import ListRequest
from integral.identity import IdentityError, ProfileStore, create_profile
from integral.offers import load_offer
from integral.robots import Robots
from integral.sourcing import Response, flood_board, source
from integral.sourcing_exclusions import Exclusion, load_exclusions, record_exclusion

AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _platform() -> Exclusion:
    return Exclusion(about="role:platform", stated_at_cycle=1, words="platform work, no thanks")


def _constraints() -> CandidateConstraints:
    return CandidateConstraints(
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        reach=Reach(state="stated", modes=("remote",)),
    )


def _stored(store: ProfileStore) -> list[str]:
    return [
        load_offer(store, path.stem).text
        for path in Path(store.path("offers")).glob("*.json")
        if not path.name.startswith("_")
    ]


# --- the producer ---------------------------------------------------------


def test_no_recorded_exclusions_is_an_empty_tuple(store: ProfileStore) -> None:
    assert load_exclusions(store) == ()


def test_a_recorded_exclusion_round_trips_in_the_candidates_words(store: ProfileStore) -> None:
    record_exclusion(store, _platform())
    assert load_exclusions(store) == (_platform(),)


def test_saying_it_again_replaces_the_row_and_never_doubles_it(store: ProfileStore) -> None:
    record_exclusion(store, _platform())
    record_exclusion(
        store, Exclusion(about="role:platform", stated_at_cycle=2, words="still no platform")
    )
    (only,) = load_exclusions(store)
    assert only.words == "still no platform" and only.stated_at_cycle == 2


@pytest.mark.parametrize("payload", [{"about": "x:y"}, [{"about": "no-facet"}], "banking"])
def test_a_corrupt_file_is_refused_never_read_as_no_exclusions(
    store: ProfileStore, payload: object
) -> None:
    store.write_json(payload, *se.EXCLUSIONS_FILE)
    with pytest.raises(IdentityError):
        load_exclusions(store)


def test_the_record_command_writes_what_the_round_reads(tmp_path: Path) -> None:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    argv = ["x", "record", "--handle", "test", "--root", str(tmp_path)]
    assert se._main([*argv, "--about", "sector:banking", "--words", "no banking"]) == 0
    (kept,) = load_exclusions(ProfileStore(tmp_path, "test"))
    assert (kept.about, kept.words) == ("sector:banking", "no banking")


# --- the serving path -----------------------------------------------------


def _run(store: ProfileStore, tmp_path: Path) -> tuple[list[str], object]:
    pages = flood_board(tmp_path / "connectors", rows=4)

    def fetch(request: ListRequest) -> Response:
        return Response(200, pages[request.url].html)

    run = source(
        store,
        _constraints(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=2,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )
    return _stored(store), run


def test_without_a_recorded_exclusion_the_round_keeps_the_platform_adverts(
    store: ProfileStore, tmp_path: Path
) -> None:
    written, run = _run(store, tmp_path)
    assert sum("platform" in t for t in written) == 2, run.summary()  # type: ignore[attr-defined]


def test_a_stated_exclusion_removes_the_matching_offers_and_reports_them(
    store: ProfileStore, tmp_path: Path
) -> None:
    record_exclusion(store, _platform())
    written, run = _run(store, tmp_path)
    assert written and not any("platform" in t for t in written)
    assert any("Senior Python Engineer" in t for t in written)
    (outcome,) = run.outcomes  # type: ignore[attr-defined]
    assert outcome.excluded == 2
    assert all("role:platform" in why for why in outcome.excluded_because)
    summary = run.summary()  # type: ignore[attr-defined]
    assert "EXCLUDED flood_en: 2 of" in summary and "role:platform" in summary


# --- the gate -------------------------------------------------------------


def test_the_live_round_gate_measures_zero_over_real_adverts() -> None:
    measured = live.measure_live_round()
    assert measured["gate_status"] == "measured", measured["failures"]
    assert measured["stated_exclusions_not_applied_to_a_live_round"] == 0
    assert measured["unexcluded_offers_removed"] == 0
    assert measured["removals_not_reported"] == 0
    assert measured["exclusions_never_tripped"] == 0, measured["never_tripped"]


def test_the_live_round_removes_and_keeps_named_real_adverts() -> None:
    """Literal ids, chosen by reading the corpus, not by asking `matches`.

    manfred-8383 says e-commerce, manfred-8456 says fintech and the tecnoempleo
    one says "bancaria" — an *entidad bancaria* is a bank, so `banca` reaches it
    (the candidate's word, not the advert's). It is the ending, not the letters,
    that decides: none of the adverts served here says "bancarrota".
    """
    observed = live.measure_live_round()["_observed"]
    stored = {url.rsplit("/", 1)[1] for url in observed["stored_urls"]}
    assert {"manfred-8383", "manfred-8456", "tecnoempleo-17da1920025ad37df94f"}.isdisjoint(stored)
    assert observed["excluded_served"] >= live.MINIMUM_EXCLUDED_SERVED
    assert observed["stored"] == observed["unexcluded_served"]


def test_a_corpus_that_trips_nothing_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    tiny = tmp_path / "ads.jsonl"
    ads = [{"id": f"a{i}", "title": "Engineer", "text": "plain work"} for i in range(30)]
    tiny.write_text("\n".join(json.dumps(a) for a in ads) + "\n", encoding="utf-8")
    measured = live.measure_live_round(tiny)
    assert measured["gate_status"] == "unmeasured"
    assert measured["failures"]


def test_a_matcher_broken_for_one_row_turns_the_gate_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The gate pinned the wiring and not the matcher: with `matches` blind to
    hyphenated values (the e-commerce row) every metric stayed 0 and it exited 0."""
    real = se.matches
    monkeypatch.setattr(se, "matches", lambda c, e: False if "-" in e.value else real(c, e))
    measured = live.measure_live_round()
    assert measured["exclusions_never_tripped"] >= 1
    assert "sector:e-commerce" in measured["never_tripped"]
    assert live._main(["x", str(tmp_path / "T203.json")]) == 1  # red, not merely unmeasured


# --- F1: offers stored before the topic was ruled out -----------------------


def test_offers_stored_in_round_one_are_not_presented_after_the_topic_is_ruled_out(
    store: ProfileStore, tmp_path: Path
) -> None:
    from integral.presentation_log import partition, withheld_line

    written, _ = _run(store, tmp_path)  # round 1: nothing ruled out, so 2 are stored
    assert sum("platform" in t for t in written) == 2
    ids = [path.stem for path in Path(store.path("offers")).glob("*.json")]
    assert partition(store, ids)[1] == []

    record_exclusion(store, _platform())  # the candidate rules the topic out, round 2

    show, held = partition(store, ids)
    shown_text = [load_offer(store, i).text for i in show]
    assert shown_text and not any("platform" in t for t in shown_text)
    assert len(held) == 2 and "role:platform" in held[0].reason
    assert "descartada" in withheld_line(held)  # and the candidate is told


# --- F2: the closed inflection rule, its cases derived from the rule ---------


def _says(
    value: str, text: str, *, terms: tuple[str, ...] = (), employer: str | None = None
) -> bool:
    exclusion = Exclusion(about=f"sector:{value}", stated_at_cycle=1, words="w", terms=terms)
    return se.matches(se.Candidate(offer_id="x", text=text, employer=employer), exclusion)


_ENDINGS = sorted({e for group in se.SUFFIXES.values() for e in group})


@pytest.mark.parametrize("ending", _ENDINGS)
def test_every_declared_ending_is_the_same_topic(ending: str) -> None:
    assert _says("fintech", f"a leading fintech{ending} in Spain")  # the value plus the ending
    assert _says("banca", f"trabajamos en el sector banc{ending} de Madrid")  # the stem plus it


@pytest.mark.parametrize("language", sorted(se.SUFFIXES))
def test_the_three_languages_are_treated_the_same(language: str) -> None:
    for ending in se.SUFFIXES[language]:
        assert _says("fintech", f"fintech{ending}"), (language, ending)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("cloud", "Backend Engineer at Cloudflare"),  # T90's pinned over-reach case
        ("cloud", "soundcloud-adjacent"),  # mid-word on the left
        ("banca", "quiebra y bancarrota"),  # `banc` + `arrota`
        ("fintech", "fintechnology"),
        ("fintech", "xfintech"),
        ("defensa", "defensivo"),
    ],
)
def test_a_continuation_outside_the_declared_endings_is_not_the_topic(
    value: str, text: str
) -> None:
    assert not _says(value, text)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("banca", "Cliente del sector bancario"),
        ("banca", "una entidad bancaria líder"),
        ("banca", "Banco Santander busca"),
        ("banca", "Experiència en el sector bancari"),
        ("bancos", "trabajamos para la banca"),  # the candidate's own plural
        ("fintechs", "a FinTech startup"),
        ("fintech", "one of Europe's fastest-growing fintechs"),
        ("publicidad", "agencia publicitaria"),  # abstract noun -> its adjective
        ("publicidad", "creatividad publicitario"),
    ],
)
def test_the_reported_wordings_are_now_the_topic(value: str, text: str) -> None:
    assert _says(value, text)


def test_a_term_carries_the_other_languages_the_recording_session_supplies() -> None:
    terms = ("ciberseguretat", "cybersecurity")
    assert not _says("ciberseguridad", "cybersecurity team")
    assert _says("ciberseguridad", "cybersecurity team", terms=terms)
    assert _says("ciberseguridad", "ciberseguretat i xarxes", terms=terms)
    assert _says("banca", "a leading bank", terms=("bank",))
    assert not _says(
        "banca", "a leading bankruptcy firm", terms=("bank",)
    )  # same rule as the value


def test_a_row_written_before_terms_existed_still_loads(store: ProfileStore) -> None:
    store.write_json(
        [{"about": "sector:banca", "stated_at_cycle": 1, "words": "banca no"}], *se.EXCLUSIONS_FILE
    )
    (row,) = load_exclusions(store)
    assert row.terms == ()


def test_the_record_command_takes_repeatable_terms(tmp_path: Path) -> None:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    argv = ["x", "record", "--handle", "test", "--root", str(tmp_path)]
    args = ["--about", "sector:banca", "--words", "banca no"]
    assert se._main([*argv, *args, "--term", "banking", "--term", "bancari"]) == 0
    (kept,) = load_exclusions(ProfileStore(tmp_path, "test"))
    assert kept.terms == ("banking", "bancari")


# --- F4: the employer ---------------------------------------------------------


def test_the_employer_is_read_when_the_advert_never_says_the_topic() -> None:
    text = "Buscamos ingeniero de datos para nuestro equipo."
    assert not _says("banca", text)
    assert _says("banca", text, employer="Banco Sabadell")


def test_a_stored_offers_employer_reaches_the_matcher() -> None:
    from integral.offers import Offer, compute_offer_id

    text = "Buscamos ingeniero de datos."
    offer = Offer(id=compute_offer_id(text), source="f", text=text, company="Banco Sabadell")
    banca = Exclusion(about="sector:banca", stated_at_cycle=1, words="w")
    assert se.ruled_out_by(se.candidate_of(offer), [banca]) == ("sector:banca",)


def test_a_reaction_stimulus_on_a_ruled_out_topic_is_withheld_before_step_five_shows_it(
    store: ProfileStore,
) -> None:
    """Stimuli become ordinary `new` offers, so `partition` is the guard for them too."""
    from integral.offers import Offer, compute_offer_id
    from integral.presentation_log import partition
    from integral.reaction_elicit import collect_stimuli

    record_exclusion(store, _platform())
    ids = []
    for text in ("Platform engineering for a payments team. " * 3, "Logistics data team. " * 3):
        offer = Offer(
            id=compute_offer_id(text),
            source="remotive",
            url="https://remotive.com/ad/1",
            fetched_at=AT,
            text=text,
            status="new",
        )
        ids += collect_stimuli(store, [offer], at=AT)
    show, held = partition(store, ids)
    assert len(show) == 1 and len(held) == 1 and "role:platform" in held[0].reason


_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("skill", ["step-02-constraints", "step-05-reactions", "step-10-feedback"])
def test_every_step_that_hears_a_ruled_out_topic_tells_the_session_to_record_it(
    skill: str,
) -> None:
    """Nothing else turns a spoken "not banking" into a row: the instruction is the producer."""
    text = (_ROOT / ".claude" / "skills" / skill / "SKILL.md").read_text()
    assert "integral.sourcing_exclusions record" in text
    assert "--term" in text


def test_step_05_shows_stimuli_only_through_the_presentation_guard() -> None:
    text = (_ROOT / ".claude" / "skills" / "step-05-reactions" / "SKILL.md").read_text()
    assert "partition(store, stored_ids)" in text
