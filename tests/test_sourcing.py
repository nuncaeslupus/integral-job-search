"""T126 — the driver that joins the connector engine to a candidate's offers.

The gap it closes was structural rather than buggy: `build_list_urls` had no
production caller, `build_offer` was called only by two gates, and `collect_offer`
only by a step that is handed its offers. These tests pin the joins, and — more
importantly — the distinctions a naive loop would blur, every one of which turns
a failed run into a run that looks empty.
"""

from __future__ import annotations

from collections.abc import Callable
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


def test_a_second_pass_over_the_same_boards_adds_nothing(store: ProfileStore) -> None:
    """T168: `added` is what survived dedup. The same adverts sighted again are
    a real result that adds no offer — counting them re-reports yesterday's run."""
    first = _run(store, _answer_with_captures())
    assert first.added > 0, first.summary()

    second = _run(store, _answer_with_captures())
    assert sum(o.items for o in second.outcomes) > 0, second.summary()
    assert second.added == 0, second.summary()


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
    assert measured["advert_requests_after_a_refusal"] == 0
    assert measured["refused_boards_listed_as_reached"] == 0
    assert measured["boards_with_a_second_advert_to_refuse"] > 0


# ---------------------------------------------------------------------------
# T130 — the advert's own page


def _answer_with_detail(*, detail_status: int = 200, seen: list[str] | None = None) -> Any:
    """List pages from each package's `fixture/list.html`, everything else from
    its `fixture/detail.html`. A board's detail URLs are its own host, so the
    two are told apart by whether the path is one `build_list_urls` produced."""
    from urllib.parse import urlsplit

    from integral.connectors import build_list_urls, load_connector

    captures = _captures()
    details: dict[str, str] = {}
    list_paths: set[str] = set()
    for package in packages_for(_spain(), _CONNECTORS):
        capture = _CONNECTORS / package.name / "fixture" / "detail.html"
        if capture.is_file() and package.site:
            details[package.site.removeprefix("www.")] = capture.read_text(encoding="utf-8")
        connector = load_connector(_CONNECTORS / package.name)
        for url in build_list_urls(connector, query="python"):
            list_paths.add(urlsplit(url).path)

    def answer(request: ListRequest) -> Response:
        host = (urlsplit(request.url).hostname or "").removeprefix("www.")
        if urlsplit(request.url).path in list_paths:
            return Response(
                200, captures.get(host, ""), error=None if host in captures else "no capture"
            )
        if seen is not None:
            seen.append(request.url)
        if host not in details:
            return Response(404, "", error="no detail capture")
        # The body is the real advert whatever the status: a helper that
        # blanked it on an error status would make "the status is read" and
        # "the body was empty" indistinguishable.
        return Response(detail_status, details[host])

    return answer


def _run(store: ProfileStore, fetch: Any, robots: Robots | None = None) -> Any:
    return source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=fetch,
        at=AT,
        directory=_CONNECTORS,
        robots=robots or _robots(),
    )


def test_a_list_row_with_no_body_is_completed_from_the_adverts_own_page(
    store: ProfileStore,
) -> None:
    """The defect: six installed connectors declare `text` only under `detail:`
    — correctly, their list rows carry no teaser — and produced zero offers for
    as long as nothing fetched it. Measured live 2026-09-06: getmanfred_es 22
    rows / 0 offers, arbeitnow_en 35 / 0, wellfound_en 20 / 0, remotive_en 18 / 0.
    """
    without = _run(store, _answer_with_captures())
    starved = {o.connector for o in without.outcomes if o.items and not o.added}
    assert starved, without.summary()

    with_detail = _run(store, _answer_with_detail())
    recovered = {o.connector for o in with_detail.outcomes if o.added}
    assert starved & recovered, with_detail.summary()


def test_the_detail_page_is_fetched_only_for_a_row_that_needs_it(
    store: ProfileStore,
) -> None:
    """A listing whose rows already carry a body must not double the requests."""
    seen: list[str] = []
    run = _run(store, _answer_with_detail(seen=seen))
    needed = sum(o.detail_needed for o in run.outcomes)
    assert len(seen) <= needed, run.summary()
    complete = [o for o in run.outcomes if o.items and not o.detail_needed]
    assert complete, "no board completed a row from its list page alone"


def test_robots_is_consulted_for_the_detail_page_too(store: ProfileStore) -> None:
    """The list URL and the advert URL are different paths, and a board may
    allow one and refuse the other — `getmanfred_es` lists under `/api/` and
    advertises under `/ofertas-empleo/`. Failing open here would fetch exactly
    the pages nobody confirmed we may, which is why the robots text below
    permits the listing: a rule that blocks both proves nothing about the
    second."""
    from integral.connector_coverage import installed_packages
    from integral.sourcing import _one_board

    package = next(p for p in installed_packages(_CONNECTORS) if p.name == "getmanfred_es")

    def _outcome(robots_text: str, seen: list[str]) -> Any:
        return _one_board(
            store,
            package,
            "python",
            fetch=_answer_with_detail(seen=seen),
            at=AT,
            directory=_CONNECTORS,
            page_count=1,
            robots=Robots(fetch=lambda url: robots_text),
        )

    permitted: list[str] = []
    allowed = _outcome(ALLOW_ALL, permitted)
    assert permitted, f"nothing fetched a detail page, so a refusal proves nothing: {allowed}"

    refused: list[str] = []
    outcome = _outcome("User-agent: *\nDisallow: /ofertas-empleo/\n", refused)
    assert outcome.items, "the listing itself was refused, so this tests the wrong rule"
    assert refused == [], outcome
    assert outcome.detail_needed > outcome.detail_fetched, outcome


def test_the_detail_budget_is_capped_and_the_shortfall_is_reported(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One listing must not turn into one request per row without a ceiling —
    and a truncated pass must be legible as truncated, not as an empty board."""
    monkeypatch.setattr("integral.sourcing.DETAIL_FETCH_CEILING", 1)
    seen: list[str] = []
    run = _run(store, _answer_with_detail(seen=seen))
    for outcome in run.outcomes:
        assert outcome.detail_fetched <= 1, outcome
        assert outcome.detail_fetched <= outcome.detail_needed, outcome
    starved = [o for o in run.outcomes if o.detail_needed > o.detail_fetched]
    assert starved, "the ceiling stopped nothing, so this proves nothing"


def test_a_relative_detail_url_is_made_absolute(store: ProfileStore) -> None:
    """`builtin_en` yields `/job/<slug>`. A relative URL is not fetchable, and
    it is not a usable `Offer.url` either — it reached a candidate's tree as
    one before this."""
    seen: list[str] = []
    _run(store, _answer_with_detail(seen=seen))
    assert seen, "no detail page was fetched, so this asserts nothing"
    assert all(url.startswith("http") for url in seen), seen[:5]


def test_a_relative_detail_url_is_resolved_against_the_page_it_came_from() -> None:
    """`jobfluent_es` yields `/es/empleos/<slug>`, `infojobs_es` the
    protocol-relative `//www.infojobs.net/...`, and `builtin_en` `/job/<slug>`.
    None is fetchable, and none is a usable `Offer.url` — one reached a
    candidate's tree as `/job/...` before this."""
    from integral.sourcing import _absolute

    page = "https://www.jobfluent.com/es/empleos-barcelona"
    assert _absolute("/es/empleos/data-scientist-cc3854", page) == (
        "https://www.jobfluent.com/es/empleos/data-scientist-cc3854"
    )
    assert _absolute("//www.infojobs.net/barcelona/of-i7f3", page) == (
        "https://www.infojobs.net/barcelona/of-i7f3"
    )
    absolute = "https://www.tecnoempleo.com/rf-f0eb18"
    assert _absolute(absolute, page) == absolute
    assert _absolute(None, page) is None
    assert _absolute("", page) is None


def test_an_unreadable_robots_refuses_the_advert_rather_than_permitting_it() -> None:
    """Fail-open is the expensive direction: it fetches pages nobody could
    confirm we may. The listing already takes this posture; the advert's own
    page takes the same one. Asserted on `_may_fetch` directly because `Robots`
    caches per host, and a board's adverts share its listing's host — so a run
    can never reach this branch, and a mutation flipping it was invisible.
    """
    from integral.robots import RobotsError
    from integral.sourcing import _may_fetch

    url = "https://www.getmanfred.com/ofertas-empleo/8389/scala-developer"

    def unreadable(_: str) -> str:
        raise RobotsError("robots.txt could not be read")

    assert _may_fetch(Robots(fetch=unreadable), url) is False
    assert _may_fetch(Robots(fetch=lambda _: ALLOW_ALL), url) is True
    assert _may_fetch(Robots(fetch=lambda _: "User-agent: *\nDisallow: /\n"), url) is False


def test_an_advert_page_that_answered_with_an_error_is_not_read_as_an_advert(
    store: ProfileStore,
) -> None:
    """A 404 or 403 still has a body, and boards serve a rendered page with it.
    Parsing that would put "page not found" into an offer a candidate reads —
    and the row's real defect, that its body is missing, would be hidden behind
    a body that is present and wrong."""
    run = _run(store, _answer_with_detail(detail_status=404))
    starved = [o for o in run.outcomes if o.detail_needed]
    assert starved, "no board needed a detail page, so this proves nothing"
    for outcome in starved:
        assert outcome.detail_needed == outcome.dropped, outcome


# ---------------------------------------------------------------------------
# T174 — a refusal on the advert page stops the host, and is reported as one


def _hosts(urls: list[str]) -> dict[str, int]:
    from collections import Counter
    from urllib.parse import urlsplit

    return dict(Counter(urlsplit(url).netloc for url in urls))


@pytest.mark.parametrize("status", [403, 429, 503])
def test_a_refused_advert_page_is_the_last_one_asked_of_that_host(
    store: ProfileStore, status: int
) -> None:
    """#445 R3-3. The list rule stopped on a 429; the advert page's did not, so
    one refusal was followed by 39 more requests to the host that refused, and
    the rows were reported as "no text" — a connector defect — rather than as
    the board saying stop."""
    seen: list[str] = []
    run = _run(store, _answer_with_detail(detail_status=status, seen=seen))
    needing = [o for o in run.outcomes if o.detail_needed]
    assert needing, "no board needed an advert page, so this proves nothing"
    assert any(o.detail_needed > 1 for o in needing), "one row cannot show a second fetch"
    assert all(n == 1 for n in _hosts(seen).values()), _hosts(seen)
    for outcome in needing:
        assert outcome.refused and str(status) in outcome.refused, outcome
        assert outcome.dropped == 0, outcome
        assert outcome.connector in run.refused, run.summary()
    assert "no 'text'" not in run.summary(), run.summary()


@pytest.mark.parametrize(
    "refusal",
    [Response(429, "Too Many Requests"), Response(429, "", error="HTTP 429")],
    ids=["body", "transport-error"],
)
def test_a_host_that_refused_is_not_asked_again_by_the_next_phrase(
    store: ProfileStore, refusal: Response
) -> None:
    """A run asks a steerable board once per phrase. "Stop" from the host on the
    first is the answer for the rest of the run, list page or advert page —
    whichever way the fetcher shaped the 429."""
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return refusal

    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python", "java", "go")),
        fetch=fetch,
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert len(run.outcomes) > len(_hosts(asked)), "no host had a second phrase to refuse"
    assert all(n == 1 for n in _hosts(asked).values()), _hosts(asked)
    assert all(o.refused and "429" in o.refused for o in run.outcomes), run.summary()


def test_a_refused_advert_page_stops_the_next_phrases_list_too(store: ProfileStore) -> None:
    """The advert page and the list share a host on every ES board, and the
    next phrase's list request is still a request to the host that said stop."""
    from integral.connector_coverage import installed_packages
    from integral.sourcing import _one_board

    package = next(p for p in installed_packages(_CONNECTORS) if p.name == "getmanfred_es")
    refused: dict[str, str] = {}
    seen: list[str] = []
    answer: Callable[[ListRequest], Response] = _answer_with_detail(detail_status=429)

    def fetch(request: ListRequest) -> Response:
        seen.append(request.url)
        return answer(request)

    def board() -> Any:
        return _one_board(
            store,
            package,
            "python",
            fetch=fetch,
            at=AT,
            directory=_CONNECTORS,
            page_count=1,
            robots=_robots(),
            refused_origins=refused,
        )

    first = board()
    assert first.refused and len(seen) == 2, (first, seen)  # the list, then one advert
    second = board()
    assert len(seen) == 2, seen
    assert second.refused and "429" in second.refused, second


def test_a_refused_board_is_not_listed_as_reached(store: ProfileStore) -> None:
    """#445 R3-4. "Searched for your terms" and "returned their whole list" say
    the board answered. One that refused did not, list page or advert page."""
    listed = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=lambda request: Response(429, "Too Many Requests"),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert listed.refused, listed.summary()
    assert listed.steered == [] and listed.unsteered == [], listed.summary()
    assert "searched for your terms" not in listed.summary(), listed.summary()
    assert "returned their whole list" not in listed.summary(), listed.summary()

    advert = _run(store, _answer_with_detail(detail_status=429))
    assert advert.refused, advert.summary()
    assert not set(advert.refused) & set(advert.steered + advert.unsteered), advert.summary()


def test_the_advert_page_gets_its_own_clients_headers(store: ProfileStore) -> None:
    """T133 wired into T130's fetch. A board serving both surfaces behind htmx
    targets a different element for each — foorilla.com uses `mc_1` for the
    list and `mc_2` for the advert — so the detail request's headers come from
    `connector.detail`, not from the listing's declaration.

    Sending none was silent in the worst way: the fetch answers **200** with
    the site's shell, the detail selectors match nothing, and every row is
    dropped for "no text" over a board that returned all of them. Measured
    live 2026-09-06: 50 rows in, 40 detail pages fetched, 0 offers.
    """
    from integral.connector_coverage import installed_packages
    from integral.sourcing import _one_board

    package = next(p for p in installed_packages(_CONNECTORS) if p.name == "foorilla_en")
    seen: list[dict[str, str]] = []
    fixture = (_CONNECTORS / "foorilla_en" / "fixture" / "list.html").read_text(encoding="utf-8")
    detail = (_CONNECTORS / "foorilla_en" / "fixture" / "detail.html").read_text(encoding="utf-8")

    def answer(request: ListRequest) -> Response:
        seen.append(dict(request.headers))
        return Response(200, fixture if "job_search" in request.url else detail)

    outcome = _one_board(
        store,
        package,
        "agentic",
        fetch=answer,
        at=AT,
        directory=_CONNECTORS,
        page_count=1,
        robots=_robots(),
    )
    assert outcome.added, outcome
    assert seen[0] == {"HX-Request": "true", "HX-Target": "mc_1"}, seen[0]
    assert seen[1] == {"HX-Request": "true", "HX-Target": "mc_2"}, seen[1]
