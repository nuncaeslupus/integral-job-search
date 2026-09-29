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


def test_the_live_round_removes_and_keeps_named_real_adverts() -> None:
    """Literal ids, chosen by reading the corpus, not by asking `matches`.

    manfred-8383 says e-commerce and manfred-8456 says fintech; the tecnoempleo
    one says "bancaria" (banking-related) but never the word "banca".
    """
    observed = live.measure_live_round()["_observed"]
    stored = {url.rsplit("/", 1)[1] for url in observed["stored_urls"]}
    assert {"manfred-8383", "manfred-8456"}.isdisjoint(stored)
    assert "tecnoempleo-17da1920025ad37df94f" in stored
    assert observed["excluded_served"] >= live.MINIMUM_EXCLUDED_SERVED
    assert observed["stored"] == observed["unexcluded_served"]


def test_a_corpus_that_trips_nothing_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    tiny = tmp_path / "ads.jsonl"
    ads = [{"id": f"a{i}", "title": "Engineer", "text": "plain work"} for i in range(30)]
    tiny.write_text("\n".join(json.dumps(a) for a in ads) + "\n", encoding="utf-8")
    measured = live.measure_live_round(tiny)
    assert measured["gate_status"] == "unmeasured"
    assert measured["failures"]
