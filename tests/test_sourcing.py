"""T126 — the driver that joins the connector engine to a candidate's offers.

The gap it closes was structural rather than buggy: `build_list_urls` had no
production caller, `build_offer` was called only by two gates, and `collect_offer`
only by a step that is handed its offers. These tests pin the joins, and — more
importantly — the distinctions a naive loop would blur, every one of which turns
a failed run into a run that looks empty.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from integral.candidate import Aim, CandidateConstraints, Location
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.sourcing import (
    Response,
    measure_fixture,
    offers_without_a_recorded_fetch,
    packages_for,
    source,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONNECTORS = _REPO_ROOT / "connectors"

ALLOW_ALL = "User-agent: *\nAllow: /\n"
AT = "2026-01-01T00:00:00+00:00"


def _robots(text: str = ALLOW_ALL) -> Robots:
    return Robots(fetch=lambda url: text)


def _spain() -> CandidateConstraints:
    return CandidateConstraints(
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        )
    )


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _captures() -> dict[str, str]:
    out = {}
    for package in packages_for(_spain(), _CONNECTORS):
        capture = _CONNECTORS / package.name / "fixture" / "list.html"
        if capture.is_file() and package.site:
            out[package.site.removeprefix("www.")] = capture.read_text(encoding="utf-8")
    return out


def _answer_with_captures() -> Any:
    from urllib.parse import urlsplit

    captures = _captures()

    def answer(request: ListRequest) -> Response:
        host = (urlsplit(request.url).hostname or "").removeprefix("www.")
        return Response(
            200, captures.get(host, ""), error=None if host in captures else "no capture"
        )

    return answer


# ---------------------------------------------------------------------------
# the join itself


def test_a_run_collects_offers_and_records_how_each_arrived(store: ProfileStore) -> None:
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=_answer_with_captures(),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert run.added > 0, run.summary()
    assert offers_without_a_recorded_fetch(store) == []


def test_an_offer_placed_by_hand_is_found(store: ProfileStore) -> None:
    """Every offer in the tree before this task arrived this way. The metric
    must see them, or its zero over a driven run means nothing."""
    from integral.lifecycle import save_lifecycle_offer, track_new_offer
    from integral.offers import Offer, compute_offer_id

    planted = Offer(id=compute_offer_id("never fetched"), source="by-hand", text="never fetched")
    save_lifecycle_offer(store, planted, track_new_offer(planted, at=AT))
    assert offers_without_a_recorded_fetch(store) == [planted.id]


# ---------------------------------------------------------------------------
# the three distinctions a naive loop blurs


def test_searched_and_handed_everything_are_reported_apart(store: ProfileStore) -> None:
    """ "We searched for your terms" and "the board gave us its whole list" are
    different results, and a caller that cannot tell them apart will describe
    the second as the first."""
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=_answer_with_captures(),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert set(run.steered) == {"tecnoempleo_es", "jobfluent_es"}
    assert "getmanfred_es" in run.unsteered
    assert not set(run.steered) & set(run.unsteered)


def test_a_refusal_is_not_an_empty_market(store: ProfileStore) -> None:
    """A 429 with no rows is a board refusing us. Counting it as "no jobs
    matched" is the silent wrong answer this whole module exists to avoid."""
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=lambda request: Response(429, "Too Many Requests"),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert run.added == 0
    assert run.refused, run.summary()
    assert all("429" in o.refused for o in run.outcomes if o.refused)


def test_a_challenge_page_is_a_refusal_not_a_listing(store: ProfileStore) -> None:
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=lambda request: Response(200, "<html>Just a moment... checking your browser</html>"),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert run.refused, run.summary()


# ---------------------------------------------------------------------------
# refusals that must not fail open


def test_robots_is_consulted_before_the_request_is_made(store: ProfileStore) -> None:
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(200, "")

    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=fetch,
        at=AT,
        directory=_CONNECTORS,
        robots=_robots("User-agent: *\nDisallow: /\n"),
    )
    assert asked == [], "a disallowed URL was fetched"
    assert run.added == 0
    assert all(o.skipped and "robots" in o.skipped for o in run.outcomes), run.summary()


def test_an_unreadable_robots_refuses_rather_than_permits(store: ProfileStore) -> None:
    """Failing open here would fetch exactly the paths nobody could confirm we
    may — the one direction this check must never fail in."""

    def broken(url: str) -> str:
        raise OSError("the network is down")

    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(200, "")

    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=fetch,
        at=AT,
        directory=_CONNECTORS,
        robots=Robots(fetch=broken),
    )
    assert asked == []
    assert all(o.skipped for o in run.outcomes), run.summary()


def test_a_board_that_searches_is_skipped_rather_than_searched_for_nothing(
    store: ProfileStore,
) -> None:
    """And the other boards still run — one un-aimed board must not end a run."""
    run = source(
        store,
        _spain(),
        Aim(state="unknown"),
        fetch=_answer_with_captures(),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    steerable = [o for o in run.outcomes if o.steered]
    assert steerable and all(o.skipped for o in steerable), run.summary()
    assert any(o.added for o in run.outcomes if not o.steered), run.summary()


def test_an_unstated_location_sources_nothing(store: ProfileStore) -> None:
    """Sourcing the whole world for somebody who has not said where they are is
    not a generous default; it is a search nobody asked for."""
    assert packages_for(CandidateConstraints(), _CONNECTORS) == []


def test_a_row_the_schema_refuses_is_dropped_with_its_reason(store: ProfileStore) -> None:
    """Measured live 2026-09-05: `getmanfred_es` parsed 22 rows and produced 0
    offers because its list page carries no ad body. A count alone leaves the
    next reader guessing which field went missing."""
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=_answer_with_captures(),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    dropped = [o for o in run.outcomes if o.dropped]
    if dropped:
        assert all(o.drop_reason for o in dropped), run.summary()


# ---------------------------------------------------------------------------
# the gate


def test_the_gate_measures_a_real_run_and_its_control() -> None:
    measured = measure_fixture()
    assert measured["gate_status"] == "measured", measured
    assert measured["sourced_offers_without_a_recorded_fetch"] == 0
    assert measured["sourced_offers_evaluated"] > 0
    assert measured["unrecorded_offers_detected_by_the_control"] == 1
