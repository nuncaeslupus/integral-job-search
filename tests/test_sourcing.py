"""T126 — the driver that joins the connector engine to a candidate's offers.

The gap it closes was structural rather than buggy: `build_list_urls` had no
production caller, `build_offer` was called only by two gates, and `collect_offer`
only by a step that is handed its offers. These tests pin the joins, and — more
importantly — the distinctions a naive loop would blur, every one of which turns
a failed run into a run that looks empty.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from integral.candidate import (
    Aim,
    CandidateConstraints,
    ConstraintState,
    Location,
    Reach,
    ReachMode,
)
from integral.connector_coverage import installed_packages
from integral.connectors import (
    ListRequest,
    accepts_query,
    build_list_requests,
    build_list_urls,
    load_connector,
)
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.sourcing import (
    FETCH_LOG,
    OFFER_CEILING,
    BoardOutcome,
    Fetch,
    Response,
    Run,
    browser_urls,
    flood_board,
    from_captures,
    matches_aim,
    measure_browser_route,
    measure_fixture,
    measure_flood,
    needs_browser,
    offers_without_a_recorded_fetch,
    packages_for,
    read_capture,
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

#: Every precondition `measure_flood`'s guard names. Listed once so the test
#: above can assert which are reported *and* which are not.
_EXERCISED = ("fill the ceiling", "cut rows at the ceiling", "meet the failing page")


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
    # Derived from the library's own declarations, not listed. Three names were
    # written out here until `talent_es` landed and made the list a census that
    # every future package would have to remember to update — `CLAUDE.md`'s
    # enumeration-has-no-last-element, in a test. What the run is being held to
    # is the partition: every package whose `url_pattern` takes a query and
    # whose capture answered is on the steered side, and nothing is on both.
    answered = set(_captures())
    steerable = set()
    for package in packages_for(_spain(), _CONNECTORS):
        if not package.site or package.site.removeprefix("www.") not in answered:
            continue
        connector = load_connector(_CONNECTORS / package.name)
        # A browser-only board (T173, `infojobs_es`) is steerable and has a
        # capture and still never reaches this `fetch` — it is routed to the
        # candidate's own browser instead. Found by this derivation rather than
        # reasoned about: the three hand-written names had it excluded silently.
        if accepts_query(connector) and not needs_browser(connector):
            steerable.add(package.name)
    assert steerable, "no steerable board answered — the assertion below is vacuous"
    assert set(run.steered) == steerable
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


@pytest.mark.parametrize("failure", ["error", "refused", "robots"])
def test_a_board_whose_later_page_fails_still_spends_the_ceiling(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Second reader round 2, N1: page one's offers are on disk, page two
    fails — the board must still report them, or the next board is handed the
    whole ceiling again and more than the ceiling lands."""
    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 100)
    d = tmp_path / "connectors"
    pages = flood_board(d, "deluge") | flood_board(d, "flood")  # deluge is selected first
    bad = "https://deluge.integral.local/jobs?page=2"

    def fetch(request: ListRequest) -> Response:
        if request.url == bad and failure == "error":
            return Response(None, "", error="timed out")
        if request.url == bad and failure == "refused":
            return Response(429, "Too Many Requests")
        return Response(200, pages[request.url].html)

    robots = (
        _robots("User-agent: *\nDisallow: /jobs?page=2\n") if failure == "robots" else _robots()
    )
    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=d,
        page_count=2,
        robots=robots,
    )
    assert len(_written(store)) <= 100, run.summary()
    assert run.added == len(_written(store)), run.summary()


@pytest.mark.parametrize(
    ("weaken", "unmet"),
    [
        # Pages too small to fill the ceiling: nothing to cut at it either.
        (("_FLOOD_GATE_ROWS", 4), ("fill the ceiling", "cut rows at the ceiling")),
        # The page that fails is one the run never asks for.
        (
            ("_FLOOD_FAILING", "https://nobody.integral.local/jobs?page=9"),
            ("meet the failing page",),
        ),
        # Round 4, R4-1: a ceiling that fills exactly at a page's end cuts no
        # row at it — the one construction that tells "fill" from "cut", and
        # without it either limb could carry the other's predicate.
        (("_FLOOD_GATE_ROWS", 50), ("cut rows at the ceiling",)),
    ],
)
def test_the_flood_gate_refuses_to_measure_a_run_that_did_not_exercise_it(
    monkeypatch: pytest.MonkeyPatch, weaken: tuple[str, object], unmet: tuple[str, ...]
) -> None:
    """Round 3, R1: the guard is the whole of N3's remedy, and nothing pinned
    it — deleting it left 124 tests green. Each precondition is named, so a
    guard that drops one goes red on the name rather than passing quietly."""
    monkeypatch.setattr(f"integral.sourcing.{weaken[0]}", weaken[1])
    measured = measure_flood()
    assert measured["gate_status"] == "unmeasured", measured
    (reason,) = measured["reasons"]
    assert [name for name in unmet if name in reason] == list(unmet), reason
    assert [name for name in _EXERCISED if name in reason] == list(unmet), reason


def test_the_flood_gate_reports_a_violation_even_when_the_run_fell_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 3, R1's other half: "unmeasured" must never swallow a finding. A
    run that both misbehaves and falls short of the ceiling is a failure, not
    an unmeasured one."""
    monkeypatch.setattr("integral.sourcing._FLOOD_GATE_ROWS", 4)
    monkeypatch.setattr("integral.sourcing.matches_aim", lambda item, phrases: True)
    measured = measure_flood()
    assert measured["offers_written_off_aim"] > 0, measured
    assert measured["gate_status"] == "measured", measured


def test_the_flood_gate_sees_a_board_that_read_rows_and_is_not_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 3, R3: the mirror component is the pin for the attribution half,
    so it needs a run where it fires. A report naming no board that handed over
    its list, over boards that plainly did, is the defect it watches for."""
    monkeypatch.setattr("integral.sourcing.Run.unsteered", property(lambda self: []))
    measured = measure_flood()
    assert measured["boards_that_read_rows_without_being_reported_asked"] > 0, measured
    assert measured["flood_violations"] > 0, measured


def test_a_board_that_answered_with_no_advert_is_not_a_board_with_no_jobs(
    store: ProfileStore, tmp_path: Path
) -> None:
    """`landingjobs_en` serves a JavaScript shell that parses to zero anchors —
    `connectors/ruled-out.yaml` has said so since August — and it read as
    "returned their whole list", which is what a board with nothing to offer
    reads as. A refusal and a stale connector were already told apart; this is
    the third way to answer and mean nothing."""
    flood_board(tmp_path / "connectors")
    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=lambda request: Response(200, "<html><body><div id='app'></div></body></html>"),
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert run.added == 0
    assert run.parsed_nothing == ["flood_en"], run.summary()
    assert run.unsteered == [], run.summary()
    assert "NOTHING PARSED" in run.summary()
    assert "returned their whole list" not in run.summary()


@pytest.mark.parametrize("terms", [("welder",), ("python engineer", "welder")])
def test_a_searching_board_with_no_hits_answered_rather_than_failed_to_parse(
    store: ProfileStore, tmp_path: Path, terms: tuple[str, ...]
) -> None:
    """Round 4, R4-4: a `{query}` board answering a query with no row has said
    there are no jobs for that query. Calling that "no advert on the page"
    spends the signal — a real parse failure would then arrive beside every
    board that merely had nothing — and with two phrases it named one board in
    both lines at once."""
    pages = flood_board(tmp_path / "connectors", "steerable")
    package = tmp_path / "connectors" / "steerable_en"
    connector = (package / "connector.yaml").read_text()
    (package / "connector.yaml").write_text(
        connector.replace("/jobs?page={page}", "/jobs?q={query}&page={page}")
    )

    def fetch(request: ListRequest) -> Response:
        if "welder" in request.url:
            return Response(200, "<html><body></body></html>")
        number = request.url.rsplit("page=", 1)[1]
        page = pages[f"https://steerable.integral.local/jobs?page={number}"]
        return Response(200, page.html)

    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=terms),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert run.steered == ["steerable_en"], run.summary()
    assert run.parsed_nothing == [], run.summary()
    assert "NOTHING PARSED" not in run.summary(), run.summary()


@pytest.mark.parametrize("status", [403, 429, 503])
def test_a_board_that_refused_is_not_a_board_that_parsed_nothing(
    store: ProfileStore, tmp_path: Path, status: int
) -> None:
    """A refusal already has its own line and its own meaning. Folding it into
    "answered with no advert on the page" would say the board let us look and
    had nothing, which is the opposite of what it did."""
    flood_board(tmp_path / "connectors")
    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=lambda request: Response(status, "<html><body>Forbidden</body></html>"),
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert run.refused == ["flood_en"], run.summary()
    assert run.parsed_nothing == [], run.summary()
    assert "NOTHING PARSED" not in run.summary()
    # Round 4, R4-5: and it must not read as a board that handed over its list
    # either — the line the whole distinction was written to correct.
    assert run.unsteered == [], run.summary()
    assert "returned their whole list" not in run.summary(), run.summary()


def test_a_stale_board_is_neither_empty_handed_nor_a_board_that_handed_its_list_over(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Round 4, R4-5: a stale connector's emptiness proves nothing, so it is
    not "no advert on the page" and not "returned their whole list" either."""
    from integral.sourcing import _one_board

    flood_board(tmp_path / "connectors")
    package = next(p for p in installed_packages(tmp_path / "connectors") if p.name == "flood_en")
    outcome = _one_board(
        store,
        package,
        None,
        fetch=lambda request: Response(200, "<html><body></body></html>"),
        at=AT,
        directory=tmp_path / "connectors",
        page_count=1,
        robots=_robots(),
        phrases=("python engineer",),
    )
    run = Run(outcomes=[replace(outcome, stale=True)])
    assert run.untrusted == ["flood_en"], run.summary()
    assert run.parsed_nothing == [], run.summary()
    assert run.unsteered == [], run.summary()
    assert "returned their whole list" not in run.summary(), run.summary()


def test_a_stale_board_with_rows_is_still_named_in_unsteered(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Round 5, F1: R4-5's own fixture above only ever fed `_one_board` an
    empty page, so the fix it pinned (`refused or stale` excludes
    unconditionally) could not be told apart from the narrower one this
    needs (excludes only when there is nothing to attribute). A stale
    connector that still parses its page has handed over real rows — that
    is exactly what "its emptiness proves nothing" is supposed to leave
    open — and those rows must land in `unsteered` like any other board's,
    not disappear because the connector happens to be past `last_verified`.
    """
    from integral.sourcing import _one_board

    pages = flood_board(tmp_path / "connectors")
    package = next(p for p in installed_packages(tmp_path / "connectors") if p.name == "flood_en")
    outcome = _one_board(
        store,
        package,
        None,
        fetch=lambda request: Response(200, pages[request.url].html),
        at=AT,
        directory=tmp_path / "connectors",
        page_count=1,
        robots=_robots(),
        phrases=("python engineer",),
    )
    assert outcome.items > 0 and outcome.added > 0, outcome
    run = Run(outcomes=[replace(outcome, stale=True)])
    assert run.untrusted == ["flood_en"], run.summary()
    assert run.unsteered == ["flood_en"], run.summary()
    assert "returned their whole list: flood_en" in run.summary(), run.summary()


def test_a_stale_board_whose_rows_were_all_re_sighted_is_still_named_in_unsteered(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Round 6, F1(a): the fixture above only ever tests `added > 0`, so the
    stale limb's fix (`_answered` gating on `added`, not `items`) could not
    be told apart from the narrower one this needs. A page that parsed real
    rows but re-sighted every one of them (`items > 0`, `added == 0` — a
    board whose whole page is already on disk from an earlier run) used to
    read exactly like a connector that parsed nothing: excluded from
    `unsteered`, with the only line about it reading "its emptiness proves
    nothing" over rows that were, in fact, parsed. `run.unaccounted_for`
    (the mirror `measure_flood` checks) must agree that nothing was lost.

    Gating on `items` instead of `added` closes it: staleness is about
    whether the connector parsed anything at all, never about whether what
    it parsed survived dedup — the stance `employer_boards`'s own docstring
    already took for the identical `added == 0` signal (#462 rounds 2 and
    3, G3/H1-H2); `_answered` used to disagree with it.
    """
    from integral.sourcing import _one_board

    pages = flood_board(tmp_path / "connectors")
    package = next(p for p in installed_packages(tmp_path / "connectors") if p.name == "flood_en")
    outcome = _one_board(
        store,
        package,
        None,
        fetch=lambda request: Response(200, pages[request.url].html),
        at=AT,
        directory=tmp_path / "connectors",
        page_count=1,
        robots=_robots(),
        phrases=("python engineer",),
    )
    assert outcome.items > 0, outcome
    resighted = replace(outcome, stale=True, added=0)
    run = Run(outcomes=[resighted])
    assert run.untrusted == ["flood_en"], run.summary()
    assert run.unsteered == ["flood_en"], run.summary()
    assert run.unaccounted_for == [], run.summary()
    assert "returned their whole list: flood_en" in run.summary(), run.summary()
    assert "STALE   flood_en: its emptiness proves nothing" in run.summary(), run.summary()


def test_a_board_refused_after_rows_is_still_named_in_unsteered(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 5, F1: page one's rows, and the offers built from them, are
    already on disk before a 429 ends the board on page two. `_answered`
    used to exclude every refused outcome unconditionally (round 4, R4-5),
    which reintroduced round 3's R3 for this failure route — the offers
    end up attributed to neither `steered` nor `unsteered`, and the only
    line the summary prints about the board (REFUSED) never says where
    they came from.
    """
    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 100)
    pages = flood_board(tmp_path / "connectors", "deluge")
    bad = "https://deluge.integral.local/jobs?page=2"

    def fetch(request: ListRequest) -> Response:
        if request.url == bad:
            return Response(429, "Too Many Requests")
        return Response(200, pages[request.url].html)

    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=2,
        robots=_robots(),
    )
    assert run.refused == ["deluge_en"], run.summary()
    assert run.unsteered == ["deluge_en"], run.summary()
    assert run.steered == [], run.summary()
    assert run.added == len(_written(store)) > 0, run.summary()
    assert "returned their whole list: deluge_en" in run.summary(), run.summary()
    assert "REFUSED deluge_en" in run.summary(), run.summary()


def test_a_steered_board_refused_after_rows_is_still_named_in_steered(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Round 5, F1 (second reader's steered extension): the unsteered fixture
    above is only half of what R4-5's blanket exclusion broke. A `{query}`
    board answers page one with rows that match the candidate's phrase and
    writes offers for them, then a 429 ends it on page two. `run.searched`
    already (correctly) names the phrase as sent — `_answered` used to
    disagree with its own run and drop the board from `steered` anyway,
    which is the sharper version of the same defect: the summary would say
    the phrase was searched for and simultaneously deny that any board
    searched it.
    """
    pages = flood_board(tmp_path / "connectors", "steerable", rows=20)
    package = tmp_path / "connectors" / "steerable_en"
    connector = (package / "connector.yaml").read_text()
    (package / "connector.yaml").write_text(
        connector.replace("/jobs?page={page}", "/jobs?q={query}&page={page}")
    )

    def fetch(request: ListRequest) -> Response:
        number = request.url.rsplit("page=", 1)[1]
        if number == "2":
            return Response(429, "Too Many Requests")
        page = pages[f"https://steerable.integral.local/jobs?page={number}"]
        return Response(200, page.html)

    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=2,
        robots=_robots(),
    )
    assert run.searched == ["python engineer"], run.summary()
    assert run.refused == ["steerable_en"], run.summary()
    assert run.steered == ["steerable_en"], run.summary()
    assert run.unsteered == [], run.summary()
    assert run.added == len(_written(store)) > 0, run.summary()
    assert "searched for your terms: steerable_en" in run.summary(), run.summary()
    assert "REFUSED steerable_en" in run.summary(), run.summary()


def test_the_headline_counts_only_the_boards_that_answered(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Round 3, minor: deluge fills the ceiling on its own page one, so flood
    is never asked. "from 2 board(s)" would credit the run with a board it did
    not touch."""
    pages = flood_board(tmp_path / "connectors", "deluge") | flood_board(
        tmp_path / "connectors", "flood"
    )
    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=lambda request: Response(200, pages[request.url].html),
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert run.summary().startswith(f"{OFFER_CEILING} offer(s) added from 1 board(s)"), (
        run.summary()
    )
    assert "NOT asked, after the ceiling: flood_en" in run.summary()


@pytest.mark.parametrize(
    ("state", "phrase", "not_said"),
    [
        # Round 4, R4-2: "where you are" is shared by both wordings, so
        # asserting it pinned nothing about the branch this varies. Telling
        # somebody who said "prefer not to say" that they have not said
        # attributes a silence they did not choose (round 1, F8).
        ("unknown", "you have not said where you are", "preferred not to say"),
        ("declined", "you preferred not to say where you are", "have not said"),
    ],
)
@pytest.mark.parametrize(
    "reach", [Reach(state="unknown"), Reach(state="stated", modes=("remote",))]
)
def test_a_run_blocked_by_an_unstated_location_says_so(
    store: ProfileStore,
    tmp_path: Path,
    state: ConstraintState,
    phrase: str,
    not_said: str,
    reach: Reach,
) -> None:
    """Round 3, R2: without a stated country `packages_for` selects nothing at
    all, so a silent run reads as a world with no jobs — and naming the reach
    instead hands the candidate a question whose answer changes nothing."""
    flood_board(tmp_path / "connectors")
    constraints = CandidateConstraints(location=Location(state=state), reach=reach)
    run = source(
        store,
        constraints,
        Aim(state="stated", terms=("python",)),
        fetch=lambda request: Response(200, ""),
        at=AT,
        directory=tmp_path / "connectors",
        robots=_robots(),
    )
    assert run.unreached == ("flood_en",), run.summary()
    assert phrase in run.summary(), run.summary()
    assert not_said not in run.summary(), run.summary()
    assert "work remotely" not in run.summary(), run.summary()


def test_a_board_that_answered_before_failing_is_reported_as_read(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Round 3, R3: deluge served page one and failed on page two. It supplied
    offers, so the line naming which boards handed over their list must name
    it — the terminal reason is not what decides whether a board was read."""
    # 40-row pages carry 20 matches, so page one cannot fill the ceiling and
    # page two is actually reached.
    pages = flood_board(tmp_path / "connectors", "deluge", 40)
    bad = "https://deluge.integral.local/jobs?page=2"

    def fetch(request: ListRequest) -> Response:
        if request.url == bad:
            return Response(None, "", error="timed out")
        return Response(200, pages[request.url].html)

    run = source(
        store,
        _remote_spain(),
        Aim(state="stated", terms=("python engineer",)),
        fetch=fetch,
        at=AT,
        directory=tmp_path / "connectors",
        page_count=2,
        robots=_robots(),
    )
    assert run.added > 0, run.summary()
    assert run.unsteered == ["deluge_en"], run.summary()
    assert "ERROR   deluge_en" in run.summary()


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
        # Round 2, N2: a version after `c++`/`c#` is a digit, not a letter.
        ({"title": "Desarrollador C++17"}, ("c++",), True),
        ({"title": "C++20 Developer"}, ("c++ developer",), True),
        ({"title": "C#10 developer"}, ("c# developer",), True),
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
    assert measured["advert_requests_after_a_refusal"] == 0
    assert measured["refused_boards_listed_as_reached"] == 0
    assert measured["boards_with_a_second_advert_to_refuse"] > 0


def test_the_population_counts_adverts_the_budget_could_ask_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#466 N3: with a one-advert budget, no board can make a second advert
    request, so `advert_requests_after_a_refusal` can observe nothing and its
    zero means nothing. Counting rows the budget would never reach would leave
    the population at 2 and the gate `measured` over a metric that is blind."""
    monkeypatch.setattr("integral.sourcing.DETAIL_FETCH_CEILING", 1)
    measured = measure_fixture()
    assert measured["boards_with_a_second_advert_to_refuse"] == 0, measured
    assert measured["gate_status"] == "unmeasured", measured


def test_the_flood_gate_measures_and_reads_clean() -> None:
    measured = measure_flood()
    assert measured["gate_status"] == "measured", measured
    assert measured["flood_violations"] == 0, measured
    assert measured["rows_reported_off_aim"] > 0
    assert measured["rows_reported_over_the_ceiling"] > 0


# ---------------------------------------------------------------------------
# T172/T167 — `Run.employer_boards`'s partition, and the fields it is derived from


def test_the_unrealized_row_fields_are_derived_not_hand_listed() -> None:
    """Round 6, F2: `employer_boards` and `measure_flood`'s
    `rows_not_accounted_for` each hand-listed the same four `BoardOutcome`
    field names, separately. `_fields_outside` is the idiom
    `tests/test_review_reader.py`'s `_twin_varying_every_non_input_field`
    already uses for the identical shape (its `_INPUT_FIELDS`): a field is
    included by default, so a bucket added to the dataclass later needs no
    matching addition at either call site — only a name in the exclusion set
    would leave one out, and this proves the function reads
    `dataclasses.fields`, not a private, hand-typed tuple of its own."""
    from dataclasses import dataclass as make_dataclass
    from dataclasses import fields as dc_fields

    from integral.sourcing import _fields_outside

    @make_dataclass
    class Sample:
        kept_out: int = 0
        also_kept_out: int = 0
        picked_up: int = 0
        picked_up_too: int = 0

    result = _fields_outside(Sample, frozenset({"kept_out", "also_kept_out"}))
    assert result == ("picked_up", "picked_up_too")
    assert set(result) == {f.name for f in dc_fields(Sample)} - {"kept_out", "also_kept_out"}


def test_the_board_outcome_unrealized_row_fields_are_todays_five_terms() -> None:
    """Pins what `_UNREALIZED_ROW_FIELDS` resolves to today — `dropped`,
    `off_aim`, `unopened`, `over_ceiling`, `refused_rows` — so a change to
    `BoardOutcome` or to the exclusion set it is derived against is visible
    here, not only in `employer_boards`'s or `rows_not_accounted_for`'s
    behaviour. `refused_rows` (T174, #466 review round 1 F6) is the fifth: a
    row whose advert host had already refused before it was read, counted in
    none of the original four."""
    from integral.sourcing import _UNREALIZED_ROW_FIELDS

    assert set(_UNREALIZED_ROW_FIELDS) == {
        "dropped",
        "off_aim",
        "unopened",
        "over_ceiling",
        "refused_rows",
    }


@pytest.mark.parametrize(
    "bucket", ["dropped", "off_aim", "unopened", "over_ceiling", "refused_rows"]
)
def test_employer_boards_excludes_a_board_whose_rows_are_all_one_bucket(bucket: str) -> None:
    """Round 6, F2: T172's partition (`items > dropped+off_aim+unopened+
    over_ceiling`) hand-listed four terms, and dropping either `unopened` or
    `over_ceiling` from it left every test and every evidence key unmoved —
    nothing exercised an employer board whose rows were consumed by exactly
    one of those two buckets alone (the `ATTRIBUTION_BOARDS` matrix that
    incidentally pins `off_aim` and `dropped` has no construction that
    produces either). Each bucket now gets its own board, in isolation, so
    dropping any one of them — or a bucket landing outside the derived set —
    is caught here directly. `refused_rows` (T174, #466 review round 1 F6) is
    the fifth, added after this test was written; parametrizing it here,
    rather than leaving it to the derived-set mechanism alone, is what
    actually exercises it end to end through `employer_boards`."""
    outcome = replace(
        BoardOutcome(
            connector="acme_en",
            url=None,
            steered=False,
            source_kind="employer",
            items=10,
        ),
        **{bucket: 10},  # type: ignore[arg-type]
    )
    run = Run(outcomes=[outcome])
    assert run.employer_boards == [], (bucket, run.summary())


def test_employer_boards_includes_a_board_none_of_whose_rows_are_fully_accounted_for() -> None:
    """The control for the parametrized exclusion above: a board whose rows
    are not entirely consumed by the four buckets still names as an
    employer board — the subtraction excludes boards, it does not exclude
    all of them."""
    outcome = BoardOutcome(
        connector="acme_en",
        url=None,
        steered=False,
        source_kind="employer",
        items=10,
        added=10,
    )
    run = Run(outcomes=[outcome])
    assert run.employer_boards == ["acme_en"], run.summary()


# ---------------------------------------------------------------------------
# T130 — the advert's own page


def _answer_with_detail(
    *, detail_status: int = 200, seen: list[str] | None = None, detail_error: str | None = None
) -> Any:
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
        return Response(detail_status, details[host], error=detail_error)

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


# ---------------------------------------------------------------------------
# T174 — a refusal on the advert page stops the host, and is reported as one


def _hosts(urls: list[str]) -> dict[str, int]:
    from collections import Counter
    from urllib.parse import urlsplit

    return dict(Counter(urlsplit(url).netloc for url in urls))


@pytest.mark.parametrize("error", [None, "HTTP error"], ids=["body", "transport-error"])
@pytest.mark.parametrize("status", [403, 429, 503])
def test_a_refused_advert_page_is_the_last_one_asked_of_that_host(
    store: ProfileStore, status: int, error: str | None
) -> None:
    """#445 R3-3. The list rule stopped on a 429; the advert page's did not, so
    one refusal was followed by 39 more requests to the host that refused, and
    the rows were reported as "no text" — a connector defect — rather than as
    the board saying stop."""
    seen: list[str] = []
    run = _run(store, _answer_with_detail(detail_status=status, seen=seen, detail_error=error))
    needing = [o for o in run.outcomes if o.detail_needed]
    assert needing, "no board needed an advert page, so this proves nothing"
    assert any(o.detail_needed > 1 for o in needing), "one row cannot show a second fetch"
    assert all(n == 1 for n in _hosts(seen).values()), _hosts(seen)
    for outcome in needing:
        assert outcome.refused and str(status) in outcome.refused, outcome
        assert outcome.dropped == 0, outcome
        assert outcome.connector in run.refused, run.summary()
    assert "no 'text'" not in run.summary(), run.summary()


def test_one_host_is_one_origin_however_its_links_spell_it() -> None:
    """#466 F1: `usajobs_en` lists at `https://www.usajobs.gov/…` and links its
    adverts as `https://www.usajobs.gov:443/…`. Two spellings of one origin
    (RFC 6454) must not be two keys, or a refusal on one leaves the other free."""
    from integral.sourcing import _origin

    same = _origin("https://www.usajobs.gov/Search/ExecuteSearch")
    assert _origin("https://www.usajobs.gov:443/job/856726500") == same
    assert _origin("HTTPS://WWW.USAJOBS.GOV/job/1") == same
    assert _origin("http://example.test/a") == _origin("http://example.test:80/b")
    assert _origin("https://www.usajobs.gov:8443/") != same
    assert _origin("http://www.usajobs.gov/") != same
    assert _origin("https://usajobs.gov/") != same
    # The malformed-port branch: a port that is not a number cannot be parsed,
    # so it is kept as written — and folded, like every other part (#466 N2).
    assert _origin("https://host.test:abc/a") == _origin("https://HOST.TEST:ABC/b")
    assert _origin("https://host.test:abc/a").endswith(":abc")
    assert _origin("https://host.test:abc/a") != _origin("https://host.test:def/b")


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
    # A board served only to a real browser (#455) is skipped before any
    # request, so it has nothing to be refused about.
    asked_boards = [o for o in run.outcomes if o.skipped is None]
    assert asked_boards, run.summary()
    assert all(o.refused and "429" in o.refused for o in asked_boards), run.summary()
    # T174's own task file left this the obligation of "whichever PR lands
    # second" (#458). Nothing reached disk from any board, so nothing was
    # searched — a phrase whose every board was refused before answering
    # must not be listed as one this run actually asked.
    assert run.searched == [], run.summary()


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

    def board(page_count: int = 1) -> Any:
        return _one_board(
            store,
            package,
            "python",
            fetch=fetch,
            at=AT,
            directory=_CONNECTORS,
            page_count=page_count,
            robots=_robots(),
            phrases=_TERMS,
            refused_origins=refused,
        )

    # Two pages: `mode: none` clamps only when `page_count is None`, so a
    # second list request IS made here (#466 N7) — and page one's advert
    # refusal must stop it, with the board keeping its OWN reason rather than
    # the carry-over wording written for a board that asked for nothing.
    first = board(page_count=2)
    assert first.refused and len(seen) == 2, (first, seen)  # the list, then one advert
    assert "not asked again" not in first.refused, first.refused

    second = board()
    assert len(seen) == 2, seen
    assert second.refused and "429" in second.refused, second
    assert second.refused.startswith("not asked again"), second.refused


def test_a_refused_board_is_not_listed_as_reached(store: ProfileStore) -> None:
    """#445 R3-4, refined by round 5's F1 (T167): "searched for your terms"
    and "returned their whole list" say the board answered. One that refused
    with nothing to show for it did not — but one that refused only after
    real offers were already on disk is not "unreached" either; excluding it
    unconditionally would attribute those offers to no disposition at all
    (round 5, F1)."""
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
    # getmanfred_es needs the advert page for every row it kept, and every one
    # of those was refused: nothing reached disk, so it stays unreached.
    getmanfred = next(o for o in advert.outcomes if o.connector == "getmanfred_es")
    assert getmanfred.refused and not getmanfred.added, getmanfred
    assert "getmanfred_es" not in advert.steered + advert.unsteered, advert.summary()
    # trabajos_es built real offers straight from its list rows before one
    # row's own detail fetch was refused (round 5, F1, from a real connector
    # fixture rather than a constructed one): those offers are on disk, so
    # the board — a `{query}` board — is reached, under `steered`.
    trabajos = next(o for o in advert.outcomes if o.connector == "trabajos_es")
    assert trabajos.refused and trabajos.added > 0, trabajos
    assert "trabajos_es" in advert.steered, advert.summary()


def test_unaccounted_for_agrees_with_a_refused_boards_own_disposition(
    store: ProfileStore,
) -> None:
    """Round 6, F1(b): the mirror `measure_flood` checks used to be built
    from `{o.connector for o in outcomes if o.items or o.added}`, unscoped
    by `reached_the_board`. On this exact fixture (`getmanfred_es`, real ES
    captures, `items == 3, added == 0`, refused before any offer was ever
    built) that population flagged the board as "read rows without being
    reported asked" in the very run `test_a_refused_board_is_not_listed_
    as_reached` (above) asserts, forty lines apart, must not list it as
    reached — one test file asserting an invariant and its own negation.

    Scoping the population by `reached_the_board` — the same predicate
    `_answered` already requires before naming a board anywhere — makes
    `Run.unaccounted_for` and `steered`/`unsteered`'s own exclusion agree.
    """
    advert = _run(store, _answer_with_detail(detail_status=429))
    getmanfred = next(o for o in advert.outcomes if o.connector == "getmanfred_es")
    assert getmanfred.items > 0 and not getmanfred.added and getmanfred.refused, getmanfred
    assert "getmanfred_es" not in advert.steered + advert.unsteered, advert.summary()
    assert advert.unaccounted_for == [], advert.summary()


def test_the_flood_gate_catches_a_reinstated_refused_or_stale_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 5's own report closed with: "the `boards_that_read_rows_
    without_being_reported_asked` component and `_answered` must agree …
    otherwise the next round re-discovers this through the gate." That is
    what round 6 found: the shipped fix generalized only for the one
    429-with-`added>0` case actually re-run, and reinstating round 4's own
    blanket exclusion (`not (refused or stale)`, unconditional) left
    `flood_violations` at a clean 0 — the gate could not catch its own named
    defect. `_FLOOD_FAILING` (deluge, page two) now answers with a real
    refusal rather than a transport error, so deluge — which already has
    page-one's offers on disk — is exactly F1's shape, and this mutation
    must move the gate rather than pass silently.
    """

    def blanket(outcome: Any) -> bool:
        return outcome.reached_the_board and not (outcome.refused or outcome.stale)

    monkeypatch.setattr(Run, "_answered", staticmethod(blanket))
    measured = measure_flood()
    assert measured["flood_violations"] > 0, measured
    assert measured["boards_that_read_rows_without_being_reported_asked"] > 0, measured


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


# ---------------------------------------------------------------------------
# T173 — a board served only to a real browser


_INFOJOBS_SEARCH = "https://www.infojobs.net/ofertas-trabajo/farmaceutico/barcelona"


def _pharmacy() -> Aim:
    return Aim(state="stated", terms=("farmaceutico",))


def _saved_page(tmp_path: Path, url: str) -> Path:
    """What the step-7 snippet writes: the URL line, then the rendered page."""
    html = (_CONNECTORS / "infojobs_es" / "fixture" / "list.html").read_text(encoding="utf-8")
    path = tmp_path / "integral-capture-1.html"
    path.write_text(f"<!-- integral-capture: {url} -->\n{html}", encoding="utf-8")
    return path


def _plain_recording(asked: list[str]) -> Any:
    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(None, "", error="offline")

    return fetch


def _infojobs(run: Any) -> Any:
    return next(o for o in run.outcomes if o.connector == "infojobs_es")


def test_a_browser_board_is_never_sent_to_the_plain_fetch(store: ProfileStore) -> None:
    """InfoJobs answers every plain request with its edge check page (measured
    2026-09-10). Sending it anyway is a certain refusal, and the only ways to
    make one pass are evasion — so with no browser page it is skipped, and
    says what would answer it."""
    asked: list[str] = []
    run = source(
        store,
        _spain(),
        _pharmacy(),
        fetch=_plain_recording(asked),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert not [u for u in asked if "infojobs" in u], asked
    assert asked, "the plain boards must still be fetched, or this proves nothing"
    outcome = _infojobs(run)
    assert outcome.skipped and "real browser" in outcome.skipped, run.summary()
    assert outcome.url == _INFOJOBS_SEARCH


def test_a_page_the_candidates_browser_saved_becomes_offers(
    store: ProfileStore, tmp_path: Path
) -> None:
    asked: list[str] = []
    run = source(
        store,
        _spain(),
        _pharmacy(),
        fetch=_plain_recording(asked),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
        browser=from_captures([_saved_page(tmp_path, _INFOJOBS_SEARCH)]),
    )
    assert not [u for u in asked if "infojobs" in u], asked
    assert _infojobs(run).added == 3, run.summary()
    rows = [
        json.loads(line)
        for line in Path(store.path("offers", FETCH_LOG)).read_text(encoding="utf-8").splitlines()
    ]
    [row] = [r for r in rows if r["connector"] == "infojobs_es"]
    assert row["via"] == "candidate_browser"
    assert row["url"] == _INFOJOBS_SEARCH
    assert all("via" not in r for r in rows if r["connector"] != "infojobs_es")
    assert offers_without_a_recorded_fetch(store) == []


def test_a_saved_page_that_does_not_name_its_url_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text("<html><body>a listing</body></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="integral-capture"):
        from_captures([path])
    assert read_capture(_saved_page(tmp_path, _INFOJOBS_SEARCH))[0] == _INFOJOBS_SEARCH


def test_the_browser_is_sent_only_where_robots_allows() -> None:
    assert browser_urls(_spain(), _pharmacy(), directory=_CONNECTORS, robots=_robots()) == [
        _INFOJOBS_SEARCH
    ]
    refused = _robots("User-agent: *\nDisallow: /\n")
    assert browser_urls(_spain(), _pharmacy(), directory=_CONNECTORS, robots=refused) == []
    # The engine's own spelling of a phrase — what the browser must be sent to,
    # and what it measured as keeping the Barcelona scope.
    [url] = browser_urls(
        _spain(),
        Aim(state="stated", terms=("auxiliar de farmacia",)),
        directory=_CONNECTORS,
        robots=_robots(),
    )
    assert url == "https://www.infojobs.net/ofertas-trabajo/auxiliar%20de%20farmacia/barcelona"


def test_the_browser_route_gate_measures_a_real_run() -> None:
    measured = measure_browser_route()
    assert measured["gate_status"] == "measured", measured
    assert measured["browser_boards_fetched_over_plain_http"] == 0
    assert measured["offers_collected_from_a_capture_of_another_search"] == 0
    assert measured["offers_collected_through_the_browser"] > 0


# Second reader on #455 — each accepted finding, committed as a fixture.


def _browser_variant(tmp_path: Path, side: str) -> Any:
    """foorilla_en with `client: browser` on its list page or its advert page.

    The only installed browser board has no advert page, so the advert half of
    the rule needs a board that has one (#455, F2).
    """
    import shutil

    from integral.connector_coverage import installed_packages

    root = tmp_path / "connectors"
    shutil.copytree(_CONNECTORS / "foorilla_en", root / "foorilla_en")
    path = root / "foorilla_en" / "connector.yaml"
    target = '"mc_1"' if side == "list" else '"mc_2"'
    old = f"  client: htmx\n  client_target: {target}\n"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, "  client: browser\n"), encoding="utf-8")
    [package] = [p for p in installed_packages(root) if p.name == "foorilla_en"]
    return package, root


def test_a_browser_board_s_adverts_never_reach_the_plain_fetch(
    store: ProfileStore, tmp_path: Path
) -> None:
    """F2: list page in the browser, advert pages still sent to the plain fetch."""
    from integral.sourcing import _one_board

    package, root = _browser_variant(tmp_path, "list")
    connector = load_connector(root / "foorilla_en")
    [url] = build_list_urls(connector, query="agentic")
    listing = (root / "foorilla_en" / "fixture" / "list.html").read_text(encoding="utf-8")
    saved = tmp_path / "list-capture.html"
    saved.write_text(f"<!-- integral-capture: {url} -->\n{listing}", encoding="utf-8")
    asked: list[str] = []
    outcome = _one_board(
        store,
        package,
        "agentic",
        fetch=_plain_recording(asked),
        at=AT,
        directory=root,
        page_count=1,
        robots=_robots(),
        browser=from_captures([saved]),
    )
    assert outcome.detail_fetched, "the advert path was never exercised"
    assert asked == [], asked


def test_a_board_whose_adverts_need_a_browser_is_a_browser_board(
    store: ProfileStore, tmp_path: Path
) -> None:
    """F2: `needs_browser` reading only `list.client` sends this board's
    listing — and then its adverts — to the plain fetch."""
    from integral.sourcing import _one_board

    package, root = _browser_variant(tmp_path, "detail")
    asked: list[str] = []
    outcome = _one_board(
        store,
        package,
        "agentic",
        fetch=_plain_recording(asked),
        at=AT,
        directory=root,
        page_count=1,
        robots=_robots(),
    )
    assert asked == [], asked
    assert outcome.skipped and "real browser" in outcome.skipped, outcome


def _twins(url: str) -> list[str]:
    """`url` altered in exactly one component, for every component that names a
    different resource — derived from `SplitResult`, not listed, so no
    component is forgotten (#455 round 2, N2). The fragment is left out: it is
    never sent to a server, so it cannot name another search."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    altered = {
        "scheme": "http",
        "netloc": "jobs.example.org",
        "path": "/ofertas-trabajo/enfermera/barcelona",
        "query": "keyword=enfermera",
    }
    assert set(altered) == set(parts._fields) - {"fragment"}
    return [urlunsplit(parts._replace(**{field: value})) for field, value in altered.items()]


@pytest.mark.parametrize("named", _twins(_INFOJOBS_SEARCH))
def test_a_saved_page_answers_no_search_but_its_own(
    store: ProfileStore, tmp_path: Path, named: str
) -> None:
    run = source(
        store,
        _spain(),
        _pharmacy(),
        fetch=_plain_recording([]),
        at=AT,
        directory=_CONNECTORS,
        robots=_robots(),
        browser=from_captures([_saved_page(tmp_path, named)]),
    )
    assert _infojobs(run).added == 0, run.summary()


def test_a_saved_page_never_answers_a_post(tmp_path: Path) -> None:
    """F4: every page of a POST search shares one URL, so one capture would
    answer them all. Refused at load, and again where the page is served."""
    import yaml

    from integral.connectors import ConnectorError, parse_connector

    fetch = from_captures([_saved_page(tmp_path, _INFOJOBS_SEARCH)])
    post = ListRequest(url=_INFOJOBS_SEARCH, method="POST", headers={}, body=b'{"q": 1}')
    assert fetch(post).error is not None
    document = yaml.safe_load((_CONNECTORS / "usajobs_en" / "connector.yaml").read_text())
    document["list"]["client"] = "browser"
    with pytest.raises(ConnectorError, match="only a GET"):
        parse_connector(yaml.safe_dump(document))


def test_a_phrase_the_board_cannot_take_does_not_end_the_list(tmp_path: Path) -> None:
    """F6: `source` reports such a phrase and carries on; so does this."""
    aim = Aim(state="stated", terms=("   ", "farmaceutico"))
    assert browser_urls(_spain(), aim, directory=_CONNECTORS, robots=_robots()) == [
        _INFOJOBS_SEARCH
    ]


@pytest.mark.parametrize(
    ("fixture_gate", "browser_gate", "expected"),
    [
        ("unmeasured", "misfiled", 1),
        ("failed", "unmeasured", 1),
        ("unmeasured", "clean", 3),
        ("clean", "clean", 0),
    ],
)
def test_one_gate_failing_is_never_hidden_by_the_other_being_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixture_gate: str,
    browser_gate: str,
    expected: int,
) -> None:
    """F1: the exits are combined by `gate_exit.worst`, so a failure outranks
    an `unmeasured` from either side."""
    import integral.sourcing as sourcing

    def reading(key: str, state: str) -> dict[str, Any]:
        return {
            key: 1 if state == "failed" else 0,
            # T174's two keys ride on the fixture gate's reading. `_main`
            # indexes rather than `.get`s them, deliberately: a key that
            # stopped being measured must raise, not read as a clean pass.
            "advert_requests_after_a_refusal": 0,
            "refused_boards_listed_as_reached": 0,
            "offers_collected_from_a_capture_of_another_search": 3 if state == "misfiled" else 0,
            "gate_status": "unmeasured" if state == "unmeasured" else "measured",
        }

    fixture_key = "sourced_offers_without_a_recorded_fetch"
    browser_key = "browser_boards_fetched_over_plain_http"
    monkeypatch.setattr(sourcing, "measure_fixture", lambda: reading(fixture_key, fixture_gate))
    monkeypatch.setattr(
        sourcing, "measure_browser_route", lambda: reading(browser_key, browser_gate)
    )
    monkeypatch.setattr(sourcing, "DEFAULT_EVIDENCE_PATH", tmp_path / "a.json")
    monkeypatch.setattr(sourcing, "DEFAULT_BROWSER_EVIDENCE_PATH", tmp_path / "b.json")
    assert sourcing._main([]) == expected


# #455 round 4, N4 — the rule over every installed board, not over InfoJobs alone.


def _installed_get_packages() -> list[str]:
    from integral.connector_coverage import installed_packages

    return [
        p.name
        for p in installed_packages(_CONNECTORS)
        if p.usable and load_connector(_CONNECTORS / p.name).list.method == "GET"
    ]


def _browser_twin(tmp_path: Path, name: str) -> Any:
    """An installed package with `client: browser` switched on, whatever else
    it is — steerable, paginated, an ATS host with employers, a detail page."""
    import shutil

    import yaml

    from integral.connector_coverage import installed_packages

    root = tmp_path / "connectors"
    shutil.copytree(_CONNECTORS / name, root / name)
    path = root / name / "connector.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["list"]["client"] = "browser"
    document["list"].pop("client_target", None)
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    [package] = [p for p in installed_packages(root) if p.name == name]
    return package, root, load_connector(root / name)


@pytest.mark.parametrize("name", _installed_get_packages())
def test_no_installed_board_as_a_browser_board_reaches_the_plain_fetch(
    store: ProfileStore, tmp_path: Path, name: str
) -> None:
    """Every request of every board, once it declares `client: browser` —
    per employer, per phrase, per page, for adverts — goes to the browser or
    nowhere, and every fetch-log row it writes says it came through the
    browser. Derived from the installed packages, so a board added later is
    twinned without anyone remembering to."""
    from integral.connectors import accepts_query
    from integral.sourcing import _one_board

    package, root, connector = _browser_twin(tmp_path, name)
    query = "python" if accepts_query(connector) else None
    asked: list[str] = []
    for browser in (None, from_captures([])):
        outcome = _one_board(
            store,
            package,
            query,
            fetch=_plain_recording(asked),
            at=AT,
            directory=root,
            page_count=2,
            robots=_robots(),
            phrases=("python",),
            browser=browser,
        )
        assert asked == [], (name, asked)
        if browser is None:
            assert outcome.skipped and "real browser" in outcome.skipped, outcome
    log = Path(store.path("offers", FETCH_LOG))
    rows = (
        [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        if log.exists()
        else []
    )
    assert all(row.get("via") == "candidate_browser" for row in rows), rows
    if connector.list.employers:
        # Each employer's unanswered page is its own row, so `via` is exercised.
        assert rows, "an ATS host's per-employer rows were never written"


def test_a_browser_board_skipped_mid_host_keeps_the_employers_it_already_lost(
    store: ProfileStore, tmp_path: Path
) -> None:
    """The skip on an ATS host reports the employers robots had already
    refused, as T144's `ended()` does for every other exit."""
    from urllib.parse import urlsplit

    from integral.sourcing import _one_board

    package, root, connector = _browser_twin(tmp_path, "lever_en")
    [first, *_] = build_list_requests(connector, page_count=1)
    parts = urlsplit(first.url)
    refused_path = f"{parts.path}?{parts.query}" if parts.query else parts.path
    outcome = _one_board(
        store,
        package,
        None,
        fetch=_plain_recording([]),
        at=AT,
        directory=root,
        page_count=1,
        robots=_robots(f"User-agent: *\nDisallow: {refused_path}$\n"),
        phrases=("python",),
    )
    assert outcome.skipped and "real browser" in outcome.skipped, outcome
    assert first.employer is not None, first
    assert any(first.employer in e for e in outcome.employers_failed), outcome
