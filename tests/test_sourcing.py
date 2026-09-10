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

from integral.candidate import Aim, CandidateConstraints, Location, Reach, ReachMode
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.sourcing import (
    OFFER_CEILING,
    Fetch,
    Response,
    flood_board,
    matches_aim,
    measure_fixture,
    measure_flood,
    offers_without_a_recorded_fetch,
    packages_for,
    source,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONNECTORS = _REPO_ROOT / "connectors"

ALLOW_ALL = "User-agent: *\nAllow: /\n"
AT = "2026-01-01T00:00:00+00:00"

#: An unsteered board keeps only rows matching a phrase (T167), and no
#: unsteered Spanish capture carries a Python row — so the advert-page tests
#: need a phrase those rows do carry.
_TERMS = ("python", "developer", "engineer")


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


def test_an_unsteered_board_without_terms_is_skipped(store: ProfileStore) -> None:
    """T167, the owner's decision: a board that searches is not searched for
    nothing, and one that does not search does not hand over its whole list for
    a search nobody stated. Both say what is missing, and nothing is fetched."""
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(200, "")

    run = source(
        store,
        _spain(),
        Aim(state="unknown"),
        fetch=fetch,
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert {o.steered for o in run.outcomes} == {True, False}, run.summary()
    assert all(o.skipped and "say what you are looking for" in o.skipped for o in run.outcomes)
    assert asked == [] and run.added == 0


# ---------------------------------------------------------------------------
# T167 — worldwide boards, the aim filter, and the per-run ceiling


def _remote_spain() -> CandidateConstraints:
    return _spain().model_copy(update={"reach": Reach(state="stated", modes=("remote",))})


@pytest.mark.parametrize(
    ("modes", "selected"),
    [
        (("remote",), True),
        (("cross_border_remote_employer",), True),
        (("commute", "relocate"), False),
    ],
)
def test_a_global_package_is_selected_by_reach(
    tmp_path: Path, modes: tuple[ReachMode, ...], selected: bool
) -> None:
    flood_board(tmp_path)
    constraints = _spain().model_copy(update={"reach": Reach(state="stated", modes=modes)})
    assert ("flood_en" in {p.name for p in packages_for(constraints, tmp_path)}) is selected


def test_a_global_package_is_not_selected_when_reach_is_unknown(
    tmp_path: Path, store: ProfileStore
) -> None:
    """And the summary names what was left out, so a quiet run is not read as a
    quiet world."""
    flood_board(tmp_path / "connectors")
    assert packages_for(_spain(), tmp_path / "connectors") == []
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python",)),
        fetch=lambda request: Response(200, ""),
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert run.unreached == ("flood_en",)
    assert "flood_en" in run.summary()


def test_the_installed_global_boards_are_selected_after_the_country_s_own() -> None:
    names = [p.name for p in packages_for(_remote_spain(), _CONNECTORS)]
    spanish = [p.name for p in packages_for(_spain(), _CONNECTORS)]
    assert names[: len(spanish)] == spanish
    assert "foorilla_en" in names[len(spanish) :], names


def _flood_run(store: ProfileStore, tmp_path: Path, page_count: int = 1) -> Any:
    """One constructed worldwide board. Returns the run, the matching and
    off-aim advert texts of the pages actually served, and the URLs asked."""
    pages = flood_board(tmp_path / "connectors")
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(200, pages[request.url].html)

    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=page_count,
        robots=_robots(),
    )
    matching = set().union(*(pages[url].matching for url in asked))
    off_aim = set().union(*(pages[url].off_aim for url in asked))
    return run, matching, off_aim, asked


def _written(store: ProfileStore) -> list[str]:
    from integral.offers import load_offer

    return [
        load_offer(store, path.stem).text
        for path in Path(store.path("offers")).glob("*.json")
        if not path.name.startswith("_")
    ]


def test_an_unsteered_board_keeps_only_rows_matching_a_phrase(
    store: ProfileStore, tmp_path: Path
) -> None:
    run, matching, off_aim, _ = _flood_run(store, tmp_path)
    written = _written(store)
    assert written and set(written) <= matching, run.summary()
    assert not set(written) & off_aim
    (outcome,) = run.outcomes
    assert outcome.off_aim == len(off_aim)
    assert f"FILTERED flood_en: {len(off_aim)} of {outcome.items}" in run.summary()


def test_the_run_stops_at_the_offer_ceiling_and_says_so(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Step 7's stop rule. The owner set 50 on 2026-09-10; pinned as a literal
    so raising it is a visible decision, not a drift."""
    assert OFFER_CEILING == 50
    run, matching, _, _ = _flood_run(store, tmp_path)
    assert len(matching) > OFFER_CEILING, "the ceiling was never reached, so this proves nothing"
    assert len(_written(store)) == OFFER_CEILING == run.added
    (outcome,) = run.outcomes
    assert outcome.over_ceiling == len(matching) - OFFER_CEILING
    assert "CEILING  flood_en" in run.summary()


def test_boards_after_the_ceiling_are_not_asked(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A phrase after the ceiling is another request to every steerable board;
    none may go out, and the summary names the boards left unasked."""
    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 1)
    answer: Fetch = _answer_with_detail()
    late: list[str] = []

    def fetch(request: ListRequest) -> Response:
        if _written(store):
            late.append(request.url)
        return answer(request)

    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=_TERMS),
        fetch=fetch,
        at=AT,
        directory=_CONNECTORS,
        page_count=2,
        robots=_robots(),
    )
    assert run.added == 1, run.summary()
    assert late == [], "a request went out after the ceiling's offer was written"
    assert [o for o in run.outcomes if o.skipped and "ceiling" in o.skipped], run.summary()
    # Second reader, F3: `_spain()`'s unknown reach prints its own "NOT asked"
    # line about worldwide boards, so the bare substring never reached this one.
    assert "NOT asked, after the ceiling: " in run.summary()


def test_a_phrase_stopped_by_the_ceiling_is_not_reported_as_searched(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second reader, F1: the ceiling filled on the first phrase of a steerable
    board; the second was never sent, so it is not "searched", and the summary
    names the board **and** the phrase left unasked."""
    import shutil

    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 1)
    shutil.copytree(_CONNECTORS / "tecnoempleo_es", tmp_path / "tecnoempleo_es")
    run = source(
        store,
        _spain(),
        Aim(state="stated", terms=("python", "rust")),
        fetch=_answer_with_detail(),
        at=AT,
        directory=tmp_path,
        robots=_robots(),
    )
    assert run.added == 1, run.summary()
    assert run.searched == ["python"], run.summary()
    assert "NOT asked, after the ceiling: tecnoempleo_es (rust)" in run.summary()


def test_a_ceiling_that_fills_at_a_page_end_is_still_reported(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second reader, F2: page one fills the ceiling exactly, so no row is over
    it and page two is rightly never asked — and the run must still not read as
    a complete pass."""
    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 60)
    run, matching, _, asked = _flood_run(store, tmp_path, page_count=2)
    assert len(matching) == 60 and len(asked) == 1, (len(matching), asked)
    assert run.added == 60 and not any(o.over_ceiling for o in run.outcomes)
    assert "STOPPED at the 60-offer ceiling" in run.summary()


@pytest.mark.parametrize(
    ("reach", "says"),
    [
        (Reach(state="unknown"), "have not said whether you would work remotely"),
        (Reach(state="declined"), "preferred not to say"),
        (Reach(state="stated", modes=("commute",)), "your reach does not include remote work"),
    ],
)
def test_why_worldwide_boards_were_left_out_follows_the_reach_state(
    store: ProfileStore, tmp_path: Path, reach: Reach, says: str
) -> None:
    """Second reader, F8: "does not include remote work" is an answer, and an
    unknown reach is a question step 7 still owes the candidate."""
    flood_board(tmp_path / "connectors")
    run = source(
        store,
        _spain().model_copy(update={"reach": reach}),
        Aim(state="stated", terms=("python",)),
        fetch=lambda request: Response(200, ""),
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert says in run.summary(), run.summary()


def test_off_aim_rows_are_never_fetched(store: ProfileStore) -> None:
    """The filter runs before the advert page is opened — otherwise it saves
    storage and spends every request it was meant to save."""
    seen: list[str] = []
    source(
        store,
        _spain(),
        Aim(state="stated", terms=("scala developer",)),
        fetch=_answer_with_detail(seen=seen),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert len([url for url in seen if "getmanfred" in url]) == 1, seen


def test_rows_past_the_detail_budget_are_unopened_not_dropped(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is wrong with an advert nobody opened; calling it "no text" sends
    the next reader to debug a connector that works."""
    monkeypatch.setattr("integral.sourcing.DETAIL_FETCH_CEILING", 0)
    run = _run(store, _answer_with_detail())
    unopened = [o for o in run.outcomes if o.unopened]
    assert unopened, run.summary()
    assert all(o.dropped == 0 for o in unopened), run.summary()
    assert "UNOPENED" in run.summary()


@pytest.mark.parametrize(
    ("row", "phrases", "matches"),
    [
        ({"title": "Senior Python Engineer"}, ("python engineer",), True),
        ({"title": "Engineer, Python"}, ("python engineer",), True),
        ({"title": "Python Developer"}, ("python engineer",), False),
        ({"title": "Ingeniería de datos"}, ("ingenieria de datos",), True),
        ({"title": "Account Manager", "text": "Python tooling"}, ("python",), True),
        ({"title": "JavaScript Developer"}, ("java",), False),
        ({"title": "C# Developer"}, ("c++",), False),
        ({"title": "Anything at all"}, ("  ", "--"), False),
        ({"title": "Anything at all"}, (), False),
        # Second reader, F5 — ES/CA parity: `I+D+i` is three words, as `R&D&I` is.
        ({"title": "Técnico de I+D+i"}, ("técnico i+d",), True),
        ({"title": "Tècnic R+D+I"}, ("tecnic r+d",), True),
        ({"title": "R&D&I Technician"}, ("r&d technician",), True),
        ({"title": "Técnico I+D"}, ("tecnico i + d",), True),
        ({"title": "Python+Django Developer"}, ("python developer",), True),
        ({"title": "React+TypeScript Developer"}, ("react developer",), True),
        ({"title": "C++ Developer"}, ("c++",), True),
        ({"title": "C Developer"}, ("c++",), False),
        # F6 — NFKD, not NFD: Catalan `ŀ` (U+0140) and fullwidth letters fold.
        ({"title": "Coŀlaborador comercial"}, ("col·laborador",), True),
        ({"title": "\uff30\uff39\uff34\uff28\uff2f\uff2e Engineer"}, ("python engineer",), True),
        # casefold, not lower.
        ({"title": "STRASSE Engineer"}, ("straße engineer",), True),
        # F7, accepted: a leading `.` is not part of a word, because boards
        # write `.NET` as `NET` (infojobs_es's capture: "Arquitecto NET").
        ({"title": "Arquitecto NET"}, (".net",), True),
        ({"title": "Sales rep, net salary 40k, developer tools"}, (".net developer",), True),
    ],
)
def test_the_aim_match(row: dict[str, str], phrases: tuple[str, ...], matches: bool) -> None:
    assert matches_aim(row, phrases) is matches


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


def test_the_flood_gate_measures_and_reads_clean() -> None:
    measured = measure_flood()
    assert measured["gate_status"] == "measured", measured
    assert measured["flood_violations"] == 0, measured
    assert measured["rows_reported_off_aim"] > 0
    assert measured["rows_reported_over_the_ceiling"] > 0


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
        for phrase in _TERMS:
            for url in build_list_urls(connector, query=phrase):
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
        Aim(state="stated", terms=_TERMS),
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
            phrases=_TERMS,
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
