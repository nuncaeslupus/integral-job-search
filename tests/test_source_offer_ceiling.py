"""T253 - the offer ceiling is counted per board and after the candidate's reach.

Everything is driven through `source` / `source_every_phrase` and read back from
the run's `summary()` and outcomes. Boards are installed under a temporary
directory, every one in the candidate's own country so that `packages_for` asks
all of them whatever the reach, and every row is labelled **by construction**
(`country`, remote or not) rather than by asking the code under test which rows
are reachable.

Candidate: lives in ES, reach `remote` + `commute`. So an on-site row in `US`
needs `relocate` and is out of reach; a row with `remote` text, or on site in
`ES`, is inside it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.connector_coverage import installed_packages
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.sourcing import (
    OFFER_CEILING,
    PHRASE_CEILING,
    Response,
    board_share,
    source,
    source_every_phrase,
)

AT = "2026-01-01T00:00:00+00:00"

#: One row: (country, remote text). `("US", "")` is on site abroad - out of reach.
Row = tuple[str, str]
IN_REACH: Row = ("ES", "remote")
OUT_OF_REACH: Row = ("US", "")

_STEERABLE = """\
site: SITE
locale: en
version: "1.0.0"
last_verified: "2026-09-10"
auth: none
list:
  url_pattern: "https://SITE.integral.local/jobs?q={query}&page={page}"
  pagination: {mode: query_param, param: page, start: 1, max_pages: 3}
  item: ".job"
  fields:
    detail_url: {css: "a", attr: href}
    title: {css: ".title"}
    company: {css: ".company"}
    text: {css: ".text"}
    location_country: {css: ".country"}
    location_remote: {css: ".remote"}
"""
_UNSTEERED = _STEERABLE.replace("?q={query}&page={page}", "?page={page}")


def _install(directory: Path, site: str, *, steerable: bool = True) -> None:
    package = directory / f"{site}_en"
    package.mkdir(parents=True)
    body = _STEERABLE if steerable else _UNSTEERED
    (package / "connector.yaml").write_text(body.replace("SITE", site), encoding="utf-8")
    (package / "meta.yaml").write_text(
        f"site: {site}.integral.local\ncountry: ES\nlanguage: en\n", encoding="utf-8"
    )


def _page(site: str, term: str, rows: list[Row], page: str = "1") -> str:
    cards = []
    for i, (country, remote) in enumerate(rows):
        title = f"Role {site}-{term}-p{page}-{i}"
        cards.append(
            f'<div class="job"><a href="/jobs/{term}-{i}">{title}</a>'
            f'<span class="title">{title}</span><span class="company">Employer {i}</span>'
            f'<span class="text">{title} about {term}</span>'
            f'<span class="country">{country}</span><span class="remote">{remote}</span></div>'
        )
    return "<html><body>" + "".join(cards) + "</body></html>"


class World:
    """Boards installed, what each returns per term, and every request made."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.rows: dict[str, Callable[[str], list[Row]]] = {}
        self.asked: list[tuple[str, str]] = []

    def board(self, site: str, rows: Callable[[str], list[Row]], *, steerable: bool = True) -> None:
        _install(self.directory, site, steerable=steerable)
        self.rows[site] = rows
        # a board `packages_for` would not ask makes every test below pass for
        # the wrong reason (a one-letter site name did exactly that)
        assert [p.name for p in installed_packages(self.directory) if p.name == f"{site}_en"]
        assert all(p.usable for p in installed_packages(self.directory)), installed_packages(
            self.directory
        )

    def fetch(self, request: object) -> Response:
        url = request.url  # type: ignore[attr-defined]
        parts = urlsplit(url)
        site = (parts.hostname or "").split(".")[0]
        term = parse_qs(parts.query).get("q", [""])[0]
        self.asked.append((site, term))
        page = parse_qs(parts.query).get("page", ["1"])[0]
        return Response(200, _page(site, term, self.rows[site](term), page))


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="en", fiction=True)
    return ProfileStore(tmp_path, "test")


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path / "connectors")


def _candidate(reach: Reach | None = None) -> CandidateConstraints:
    return CandidateConstraints(
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
        reach=reach or Reach(state="stated", modes=("remote", "commute")),
    )


def _terms(n: int) -> tuple[str, ...]:
    return tuple(f"term{i}" for i in range(n))


def _walk(store: ProfileStore, world: World, aim: Aim, constraints=None, **kw):  # type: ignore[no-untyped-def]
    return source_every_phrase(
        store,
        constraints or _candidate(),
        aim,
        fetch=world.fetch,
        at=AT,
        directory=world.directory,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        **kw,
    )


def _added(run, board: str) -> int:  # type: ignore[no-untyped-def]
    return sum(o.added for o in run.outcomes if o.connector == f"{board}_en")


# --- the share ---------------------------------------------------------------


@pytest.mark.parametrize("boards", range(1, OFFER_CEILING + 3))
def test_the_shares_never_add_up_to_more_than_the_ceiling(boards: int) -> None:
    """The closed rule behind the number: no board is owed more than it can have
    without taking the room of a board not yet asked."""
    share = board_share(boards)
    assert share >= 1
    if boards <= OFFER_CEILING:
        assert boards * share <= OFFER_CEILING


# --- a flood board no longer starves another board or later terms -------------


def test_a_flood_board_cannot_starve_another_board_or_the_later_terms(
    store: ProfileStore, world: World
) -> None:
    flood_rows = [OUT_OF_REACH] * 150 + [IN_REACH] * 45  # 195, most out of reach
    world.board("flood", lambda term: flood_rows)  # first in board order
    world.board("small", lambda term: [IN_REACH] * 3)
    terms = _terms(PHRASE_CEILING + 2)  # two windows
    run = _walk(store, world, Aim(state="stated", terms=terms))

    share = board_share(2)
    assert _added(run, "flood") == share
    # the other board is asked every term, and keeps what each of them gave it
    assert {t for s, t in world.asked if s == "small"} == set(terms)
    assert _added(run, "small") == 3 * len(terms)
    # the walk was not ended early: nothing unsearched, nothing to resume
    assert run.unsearched == () and run.next_offset is None
    assert run.added == share + 3 * len(terms) <= OFFER_CEILING


# --- out-of-reach rows are not counted ---------------------------------------


def test_rows_outside_reach_do_not_spend_the_ceiling(store: ProfileStore, world: World) -> None:
    # the unreachable rows come FIRST, so a count taken before the reach
    # constraint would have used the whole ceiling on them
    rows = [OUT_OF_REACH] * 150 + [IN_REACH] * 40
    world.board("flood", lambda term: rows)
    run = _walk(store, world, Aim(state="stated", terms=("term0",)))
    outcome = run.outcomes[0]
    assert (outcome.added, outcome.out_of_reach, outcome.over_ceiling) == (40, 150, 0)
    assert outcome.over_board_cap == 0
    assert "OUT OF REACH flood_en: 150 of 190 row(s)" in run.summary()
    assert "STOPPED at the" not in run.summary()


def test_out_of_reach_rows_are_not_collected(store: ProfileStore, world: World) -> None:
    from integral.offers import load_offer

    world.board("flood", lambda term: [OUT_OF_REACH] * 5 + [IN_REACH] * 2)
    _walk(store, world, Aim(state="stated", terms=("term0",)))
    countries = sorted(
        (load_offer(store, p.stem).location.country or "")  # type: ignore[union-attr]
        for p in Path(store.path("offers")).glob("*.json")
        if not p.name.startswith("_")
    )
    assert countries == ["ES", "ES"]


def test_reachable_rows_still_stop_at_the_ceiling(store: ProfileStore, world: World) -> None:
    rows = [OUT_OF_REACH] * 150 + [IN_REACH] * 60
    world.board("flood", lambda term: rows)
    run = _walk(store, world, Aim(state="stated", terms=("term0",)))
    outcome = run.outcomes[0]
    assert (outcome.added, outcome.over_ceiling, outcome.out_of_reach) == (50, 10, 150)


def test_an_unstated_reach_filters_nothing(store: ProfileStore, world: World) -> None:
    """Fail-open for the count: with no stated reach nothing can be ruled out."""
    world.board("flood", lambda term: [OUT_OF_REACH] * 10)
    unstated = CandidateConstraints(
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
    )
    run = _walk(store, world, Aim(state="stated", terms=("term0",)), unstated)
    assert run.outcomes[0].added == 10 and run.outcomes[0].out_of_reach == 0


def test_a_row_with_no_country_is_counted_not_refused(store: ProfileStore, world: World) -> None:
    world.board("flood", lambda term: [("", ""), ("Spain", ""), IN_REACH])
    run = _walk(store, world, Aim(state="stated", terms=("term0",)))
    assert run.outcomes[0].added == 3 and run.outcomes[0].out_of_reach == 0


# --- the summary names the capped boards, with counts --------------------------


def test_the_summary_names_a_capped_board_and_what_it_lost(
    store: ProfileStore, world: World
) -> None:
    world.board("flood", lambda term: [IN_REACH] * 45)
    world.board("small", lambda term: [IN_REACH] * 2)
    terms = _terms(3)
    run = _walk(store, world, Aim(state="stated", terms=terms))
    share = board_share(2)
    # term0 fills the share; the 45 - share rows left are counted; terms 1 and 2
    # are never sent to the board that is already full
    assert run.capped == {"flood_en": (45 - share, 0, ("term1", "term2"))}
    line = (
        f"CAPPED  flood_en: held to its {share}-offer share of the {OFFER_CEILING}-offer "
        f"ceiling — {45 - share} matching row(s) not collected, 0 further request(s) of "
        "this term not made; never searched for: term1, term2"
    )
    assert line in run.summary()
    assert "small_en" not in "".join(x for x in run.summary().splitlines() if "CAPPED" in x)
    assert [t for s, t in world.asked if s == "flood"] == ["term0"]


def test_a_board_under_its_share_is_not_reported_capped(store: ProfileStore, world: World) -> None:
    world.board("alpha", lambda term: [IN_REACH] * 2)
    world.board("beta", lambda term: [IN_REACH] * 2)
    run = _walk(store, world, Aim(state="stated", terms=("term0",)))
    assert run.capped == {} and "CAPPED" not in run.summary()


# --- unsearched / next_offset stay coherent when a cap bites ------------------


def test_a_cap_does_not_move_unsearched_or_next_offset(
    store: ProfileStore, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Board `a` hits its share on term0; the run ceiling then fills on `b` in the
    middle of window 0. The cut is named by the run's ceiling alone, and resumes
    at this window - the board's share contributes nothing to it."""
    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 4)
    world.board("alpha", lambda term: [IN_REACH] * 9)  # share 2
    world.board("beta", lambda term: [IN_REACH] * 9)
    terms = _terms(PHRASE_CEILING + 1)
    run = _walk(store, world, Aim(state="stated", terms=terms))
    # `alpha` lost 7 of its 9 rows to its own share; `beta` stopped at the same
    # row count because the run's ceiling filled - said as the ceiling, not a cap
    assert run.capped == {"alpha_en": (7, 0, ("term1", "term2", "term3", "term4", "term5"))}
    beta = next(o for o in run.outcomes if o.connector == "beta_en" and o.items)
    assert beta.over_ceiling == 7 and beta.over_board_cap == 0
    assert run.added == 4
    assert run.next_offset == 0
    assert run.unsearched == terms[1:]  # term0 reached both boards; b's term1 onward did not
    assert "offset=0" in run.summary()


def test_a_cap_alone_leaves_nothing_to_resume(store: ProfileStore, world: World) -> None:
    world.board("alpha", lambda term: [IN_REACH] * 40)
    world.board("beta", lambda term: [IN_REACH] * 1)
    run = _walk(store, world, Aim(state="stated", terms=_terms(PHRASE_CEILING + 1)))
    assert "alpha_en" in run.capped
    assert run.unsearched == () and run.next_offset is None
    assert "NOT searched" not in run.summary()


# --- #709's edge: a board that takes no query, last, behind a full ceiling -----


def test_an_unsteered_board_behind_a_full_ceiling_is_said_not_resumable(
    store: ProfileStore, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("integral.sourcing.OFFER_CEILING", 2)
    world.board("alpha", lambda term: [IN_REACH] * 3)
    world.board("beta", lambda term: [IN_REACH] * 3)
    world.board("gamma", lambda term: [IN_REACH] * 3, steerable=False)  # last in board order
    terms = _terms(PHRASE_CEILING + 1)  # a continuation exists and cannot ask `c`
    run = _walk(store, world, Aim(state="stated", terms=terms))
    assert run.unsteered_after_ceiling == ["gamma_en"]
    summary = run.summary()
    line = next(x for x in summary.splitlines() if "NOT asked, after the ceiling:" in x)
    assert line.endswith(", gamma_en")
    assert "ask again with offset=0: gamma_en" in summary
    # and a continuation really does not ask it - the claim the line makes
    world.asked.clear()
    source(
        store,
        _candidate(),
        Aim(state="stated", terms=terms),
        fetch=world.fetch,
        at=AT,
        directory=world.directory,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        offset=PHRASE_CEILING,
    )
    assert "gamma" not in {s for s, _ in world.asked}


def test_no_such_line_when_every_board_was_asked(store: ProfileStore, world: World) -> None:
    world.board("alpha", lambda term: [IN_REACH])
    world.board("gamma", lambda term: [IN_REACH], steerable=False)
    run = _walk(store, world, Aim(state="stated", terms=("term0",)))
    assert run.unsteered_after_ceiling == [] and "NOT resumable" not in run.summary()


# --- #709's other loose end: `already_added`, through the public path ----------


def test_already_added_leaves_only_the_rest_of_the_ceiling(
    store: ProfileStore, world: World
) -> None:
    world.board("alpha", lambda term: [IN_REACH] * 5)
    run = source(
        store,
        _candidate(),
        Aim(state="stated", terms=("term0",)),
        fetch=world.fetch,
        at=AT,
        directory=world.directory,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        already_added=OFFER_CEILING - 1,
    )
    assert run.added == 1
    assert run.outcomes[0].over_ceiling == 4 and run.outcomes[0].over_board_cap == 0


# --- B1: a share filled at a page boundary is still a capped board -----------


def test_a_share_filled_at_a_page_boundary_is_reported(store: ProfileStore, world: World) -> None:
    world.board("alpha", lambda term: [IN_REACH] * 25)  # three pages of 25
    world.board("beta", lambda term: [IN_REACH])
    run = _walk(store, world, Aim(state="stated", terms=("term0",)), page_count=3)
    share = board_share(2)
    assert share == 25
    assert [t for s, t in world.asked if s == "alpha"] == ["term0"]  # one page only
    assert run.capped == {"alpha_en": (0, 2, ())}
    assert "CAPPED  alpha_en" in run.summary()
    assert "2 further request(s) of this term not made" in run.summary()


def test_a_share_filled_by_the_last_request_is_not_capped(
    store: ProfileStore, world: World
) -> None:
    """Nothing was left unread, so there is nothing to report."""
    world.board("alpha", lambda term: [IN_REACH] * 25)
    world.board("beta", lambda term: [IN_REACH])
    run = _walk(store, world, Aim(state="stated", terms=("term0",)), page_count=1)
    assert run.capped == {} and "CAPPED" not in run.summary()


# --- B2: free remote text is undecidable, never a reason to rule a row out ---


@pytest.mark.parametrize("text", ["En sede", "En remoto", "hybrid", "híbrido"])
def test_a_row_with_free_remote_text_is_counted_not_ruled_out(
    store: ProfileStore, world: World, text: str
) -> None:
    world.board("alpha", lambda term: [("ES", text), ("US", text)])
    commuter = _candidate(Reach(state="stated", modes=("commute", "relocate")))
    run = _walk(store, world, Aim(state="stated", terms=("term0",)), commuter)
    assert (run.outcomes[0].added, run.outcomes[0].out_of_reach) == (2, 0)


# --- O1: once the share is full, a row out of reach is still out of reach ----


def test_out_of_reach_rows_after_the_share_are_still_out_of_reach(
    store: ProfileStore, world: World
) -> None:
    share = board_share(2)
    world.board("alpha", lambda term: [IN_REACH] * (share + 3) + [OUT_OF_REACH] * 4)
    world.board("beta", lambda term: [IN_REACH])
    run = _walk(store, world, Aim(state="stated", terms=("term0",)))
    first = run.outcomes[0]
    assert (first.added, first.over_board_cap, first.out_of_reach) == (share, 3, 4)
