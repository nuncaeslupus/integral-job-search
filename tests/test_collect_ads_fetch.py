"""Every hop of a fetch is checked, not just the URL we started from.

`requests` follows redirects itself, which would check the first URL and fetch
the last. A board that redirects a permitted path onto a disallowed one — or
onto a different host whose robots.txt was never read — would walk straight
through the gate `get()` exists to be. These drive the loop with a fake session
so the failure is reproducible without a board.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("requests", reason="the optional `collect` extra is not installed here")

REPO_ROOT = Path(__file__).resolve().parents[1]


def _collect_ads() -> Any:
    spec = importlib.util.spec_from_file_location(
        "collect_ads", REPO_ROOT / "tools" / "collect_ads.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["collect_ads"] = module
    spec.loader.exec_module(module)
    return module


COLLECT = _collect_ads()

ALLOWED = "https://board.test/ofertas"
DISALLOWED = "https://board.test/privado"
OTHER_HOST = "https://otro.test/ofertas"


class FakeResponse:
    def __init__(self, location: str | None = None) -> None:
        self.headers = {"Location": location} if location else {}
        self.is_redirect = location is not None
        self.raised = False

    def raise_for_status(self) -> None:
        self.raised = True


class FakeSession:
    """Records what was actually requested — the point of most of these."""

    def __init__(self, script: dict[str, FakeResponse]) -> None:
        self.script = script
        self.fetched: list[str] = []

    def get(self, url: str, **kw: Any) -> FakeResponse:
        assert kw["allow_redirects"] is False, "redirects must be followed by hand"
        self.fetched.append(url)
        return self.script[url]


class FakeRobots:
    def __init__(self, disallowed: set[str]) -> None:
        self.disallowed = disallowed
        self.asked: list[str] = []

    def allows(self, url: str) -> bool:
        self.asked.append(url)
        return url not in self.disallowed

    def delay(self, url: str, floor: float) -> float:
        return floor


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(COLLECT.time, "sleep", lambda _seconds: None)


def _run(monkeypatch: pytest.MonkeyPatch, robots: FakeRobots, session: FakeSession) -> Any:
    monkeypatch.setattr(COLLECT, "ROBOTS", robots)
    # `board.test` and `otro.test` are boards for the purposes of these fixtures: every
    # hop is put through the policy ledger, and a host `SOURCE_HOSTS` does not record is
    # refused before robots.txt is ever asked.
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "board", "board.test")
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "otro", "otro.test")
    return COLLECT.get(session, ALLOWED)


def test_a_plain_response_is_returned_and_status_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession({ALLOWED: FakeResponse()})
    response = _run(monkeypatch, FakeRobots(set()), session)
    assert response.raised
    assert session.fetched == [ALLOWED]


def test_a_redirect_onto_a_disallowed_path_is_refused_before_it_is_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole finding: the first URL is allowed, the one we would land on is not."""
    session = FakeSession({ALLOWED: FakeResponse(location=DISALLOWED)})
    robots = FakeRobots({DISALLOWED})
    with pytest.raises(PermissionError):
        _run(monkeypatch, robots, session)
    assert session.fetched == [ALLOWED], "the disallowed target was fetched anyway"
    assert DISALLOWED in robots.asked


def test_a_cross_origin_redirect_asks_the_new_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession({ALLOWED: FakeResponse(location=OTHER_HOST), OTHER_HOST: FakeResponse()})
    robots = FakeRobots(set())
    _run(monkeypatch, robots, session)
    assert robots.asked == [ALLOWED, OTHER_HOST]
    assert session.fetched == [ALLOWED, OTHER_HOST]


def test_a_relative_location_is_resolved_against_the_url_it_came_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession(
        {ALLOWED: FakeResponse(location="/otra"), "https://board.test/otra": FakeResponse()}
    )
    robots = FakeRobots(set())
    _run(monkeypatch, robots, session)
    assert session.fetched == [ALLOWED, "https://board.test/otra"]


def test_a_redirect_loop_stops_rather_than_spinning(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession({ALLOWED: FakeResponse(location=ALLOWED)})
    with pytest.raises(RuntimeError, match="redirects"):
        _run(monkeypatch, FakeRobots(set()), session)
    assert len(session.fetched) == COLLECT.MAX_REDIRECTS + 1


def test_a_redirect_off_https_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession({ALLOWED: FakeResponse(location="http://board.test/ofertas")})
    with pytest.raises(PermissionError, match="https only"):
        _run(monkeypatch, FakeRobots(set()), session)


def test_the_declared_agent_is_sent_on_every_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    class Recording(FakeSession):
        def get(self, url: str, **kw: Any) -> FakeResponse:
            sent.append(kw["headers"]["User-Agent"])
            return super().get(url, **kw)

    session = Recording({ALLOWED: FakeResponse(location=OTHER_HOST), OTHER_HOST: FakeResponse()})
    _run(monkeypatch, FakeRobots(set()), session)
    assert sent == [COLLECT.USER_AGENT, COLLECT.USER_AGENT]
    assert "Mozilla" not in COLLECT.USER_AGENT


# T98 — the collector cannot write a row nothing can account for.


def _fetched() -> Any:
    return COLLECT.record(
        "board-1",
        "exampleboard",
        "https://example.invalid/1",
        "Programador/a",
        "Example S.L.",
        "Buscamos una persona para trabajar en Python. " * 20,
        "programming",
    )


def test_collecting_without_a_draw_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--draw` is required and validated against the registry, but the guard lives on
    `record` as well: an import-time default of `""` must not silently produce a corpus
    whose rows name nothing."""
    monkeypatch.setattr(COLLECT, "DRAW", "")
    with pytest.raises(RuntimeError, match="no draw set"):
        _fetched()


def test_a_collected_row_carries_the_draw_it_was_collected_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(COLLECT, "DRAW", "t4b-programming")
    assert _fetched()["draw"] == "t4b-programming"


# ---------------------------------------------------------------------------
# T98 — a board the policy ledger refuses is never planned.


_LEDGER = """
policy_refused:
  - site: refusedboard.test
    refuses: volume
    robots_verdict: allowed
    rule_cited: "Disallow: /*?action=get_jobs"
    decided_by: owner
    decided_on: 2026-01-01
    decision: "Bulk ingestion of this board is not ours to do."
"""


def _ledger(tmp_path: Path, document: str = _LEDGER) -> Path:
    path = tmp_path / "ruled-out.yaml"
    path.write_text(document, encoding="utf-8")
    return path


def test_a_policy_refused_board_is_refused_by_the_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this exists for: the collector named a board `ruled-out.yaml` refuses,
    stamped its rows with the selected draw, and the draw did not list it as a source.

    Adding it to the draw would have made the two agree by writing a refusal into a
    specification. The plan is what was wrong, so the plan is what is checked — and by
    reading the ledger rather than by deleting one name, so the next refused board is
    caught the day it is added.
    """
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "refusedboard", "refusedboard.test")
    refused = COLLECT.plan_refusals(["refusedboard", "manfred"], _ledger(tmp_path))
    assert list(refused) == ["refusedboard"]
    assert "policy_refused" in refused["refusedboard"]


def test_a_volume_refusal_binds_the_collector_the_same_as_an_access_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`refuses: volume` is the owner's line between a candidate reading a handful of
    adverts and a tool ingesting a board. A corpus draw is the second by construction,
    so both kinds bind here — reading `volume` as "collect anyway" is the fail-open
    version of this check."""
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "refusedboard", "refusedboard.test")
    for kind in ("volume", "access"):
        ledger = _ledger(tmp_path, _LEDGER.replace("refuses: volume", f"refuses: {kind}"))
        assert list(COLLECT.plan_refusals(["refusedboard"], ledger)) == ["refusedboard"], kind


def test_a_subdomain_of_a_refused_site_is_refused_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal names a board, not a hostname spelling. `jobs.refusedboard.test` is the
    same board, and an exact-match check would wave it through."""
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "refusedboard", "jobs.refusedboard.test")
    assert list(COLLECT.plan_refusals(["refusedboard"], _ledger(tmp_path))) == ["refusedboard"]


def test_a_source_with_no_recorded_host_cannot_be_checked_and_is_refused(
    tmp_path: Path,
) -> None:
    """Fail-closed on the unknown. A source added to the plan without a host in
    `SOURCE_HOSTS` cannot be put through the ledger at all, and "not checkable" reading
    as "allowed" is exactly how the refused board got planned in the first place."""
    refused = COLLECT.plan_refusals(["brand_new_board"], _ledger(tmp_path))
    assert "no host recorded" in refused["brand_new_board"]


def test_an_empty_ledger_refuses_nothing(tmp_path: Path) -> None:
    """The negative control. Without it a check that refuses everything would pass every
    assertion above."""
    ledger = _ledger(tmp_path, "policy_refused: []\n")
    assert COLLECT.plan_refusals(["manfred", "tecnoempleo", "feinaactiva"], ledger) == {}


# ---------------------------------------------------------------------------
# T98 — and a URL handed in on the command line is bound by the same ledger.
#
# `plan_refusals` covered the fixed plan only. `--ca-urls` reached `from_urls`
# without passing the ledger at all, so a refused board's URL in that file was
# fetched — the refusal routed around by the one input a person types by hand.


def test_a_supplied_url_on_a_refused_board_is_never_fetched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hole: the ledger refuses the board, and `--ca-urls` fetched it anyway.

    Asserted over the session rather than over the return value — "refused" has to mean
    no request left the process, not that the record was discarded after the fetch.
    """
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "refusedboard", "refusedboard.test")
    urls = ["https://refusedboard.test/oferta/1"]
    session = FakeSession({})

    allowed = COLLECT.permitted_urls(urls, _ledger(tmp_path))
    assert allowed == []
    assert list(COLLECT.from_urls(session, allowed, "ca")) == []
    assert session.fetched == []


def test_a_supplied_url_on_an_unrecorded_host_is_refused_too(
    tmp_path: Path,
) -> None:
    """Fail-closed on the unknown, the same rule `SOURCE_HOSTS` already gives the plan.

    A host nothing recorded cannot be put through the ledger, and "not checkable"
    reading as "allowed" would leave the whole check bypassable by typing a URL.
    """
    urls = ["https://never-surveyed.invalid/oferta/1"]
    session = FakeSession({})

    refused = COLLECT.url_refusals(urls, _ledger(tmp_path))
    assert "not recorded in SOURCE_HOSTS" in refused[urls[0]]
    assert COLLECT.permitted_urls(urls, _ledger(tmp_path)) == []
    assert list(COLLECT.from_urls(session, [], "ca")) == []
    assert session.fetched == []


def test_a_supplied_url_on_a_permitted_board_still_passes(tmp_path: Path) -> None:
    """The negative control. A guard that refuses everything passes both tests above
    and silently disables `--ca-urls`."""
    url = "https://feinaactiva.gencat.cat/oferta/1"
    assert COLLECT.permitted_urls([url], _ledger(tmp_path)) == [url]


def test_a_subdomain_of_a_recorded_board_is_checked_not_waved_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`jobs.refusedboard.test` is the same board under a longer name, in the URL path
    exactly as in the plan path."""
    monkeypatch.setitem(COLLECT.SOURCE_HOSTS, "refusedboard", "refusedboard.test")
    assert COLLECT.permitted_urls(["https://jobs.refusedboard.test/x"], _ledger(tmp_path)) == []


def test_the_committed_ledger_refuses_a_remoteok_url_handed_in_by_hand() -> None:
    """The live reading, over the real ledger: the board the owner refused on
    2026-08-31 is refused whichever input names it."""
    assert COLLECT.url_refusals(["https://remoteok.com/remote-jobs/1"])
    assert COLLECT.permitted_urls(["https://remoteok.com/remote-jobs/1"]) == []


# ---------------------------------------------------------------------------
# T98 — and every redirect hop is bound by the same ledger.
#
# The plan is filtered before it is walked and `--ca-urls` before it is read, and
# neither reaches a redirect: `get()` follows hops by hand and asked only robots.txt
# about each one. A first hop the ledger allows may land on a board it refuses, and a
# redirect target is the one URL nobody typed and nobody checked — the refusal routed
# around by the board itself.

REFUSED_HOP = "https://remoteok.com/remote-jobs/1"
UNKNOWN_HOP = "https://never-surveyed.invalid/oferta/1"


def test_a_redirect_onto_a_ledger_refused_board_is_never_fetched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live reading, over the real ledger: `remoteok.com` carries `refuses: volume`,
    decided by the owner, and arriving there through a `302` is the same violation as
    naming it in the plan.

    Asserted over the session rather than over the return value — "refused" has to mean
    no request left the process.
    """
    session = FakeSession({ALLOWED: FakeResponse(location=REFUSED_HOP)})
    robots = FakeRobots(set())

    with pytest.raises(PermissionError, match="policy ledger"):
        _run(monkeypatch, robots, session)

    assert session.fetched == [ALLOWED], "the refused board was fetched anyway"
    assert REFUSED_HOP not in robots.asked, "the ledger is asked before robots.txt, not after"


def test_a_redirect_onto_an_unrecorded_host_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed on the unknown, the rule the plan path and `--ca-urls` already follow.
    A board nothing surveyed cannot be put through the ledger, and "not checkable"
    reading as "allowed" would leave the whole check bypassable by a `Location` header."""
    session = FakeSession({ALLOWED: FakeResponse(location=UNKNOWN_HOP)})
    robots = FakeRobots(set())

    with pytest.raises(PermissionError, match="not recorded in SOURCE_HOSTS"):
        _run(monkeypatch, robots, session)

    assert session.fetched == [ALLOWED], "the unrecorded host was fetched anyway"
    assert UNKNOWN_HOP not in robots.asked


def test_a_redirect_between_two_permitted_boards_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control, over two boards the committed ledger permits. Without it a
    hop check that refuses everything passes both tests above and silently breaks every
    board that redirects."""
    first = "https://feinaactiva.gencat.cat/search/offers/detail/1"
    second = "https://www.tecnoempleo.com/ofertas-trabajo/rf-abc"
    session = FakeSession({first: FakeResponse(location=second), second: FakeResponse()})
    monkeypatch.setattr(COLLECT, "ROBOTS", FakeRobots(set()))

    response = COLLECT.get(session, first)

    assert response.raised
    assert session.fetched == [first, second]


def test_the_committed_plan_is_clean_against_the_committed_ledger() -> None:
    """The live reading, over the real ledger. Every source the collector can plan is
    one the ledger does not refuse — and `remoteok`, which it does refuse, is named in
    `SOURCE_HOSTS` so that the refusal is found rather than missed."""
    assert "remoteok" in COLLECT.SOURCE_HOSTS
    refused = COLLECT.plan_refusals(COLLECT.SOURCE_HOSTS)
    assert list(refused) == ["remoteok"], refused
    survivors = [name for name in COLLECT.SOURCE_HOSTS if name not in refused]
    assert len(survivors) >= 5, survivors


# ---------------------------------------------------------------------------
# T98 — a draw's specification narrows what is fetched, not only what is stamped.


def _plan() -> list[tuple[str, str, Any, int]]:
    """The collector's fixed plan, shaped as `main` builds it."""
    return [
        ("es", "manfred", None, 60),
        ("es", "tecnoempleo", None, 60),
        ("en", "weworkremotely", None, 25),
        ("en", "remotive", None, 25),
        ("ca", "feinaactiva", None, 15),
    ]


def test_a_draw_that_names_one_board_puts_no_other_board_on_the_wire() -> None:
    """`t25-families` declares Feina Activa alone. Before this bound the plan, a run
    against it contacted three remote boards the specification never asked for —
    real requests to real boards, which is the rule the ledger enforces elsewhere."""
    spec = COLLECT.load_draws()["t25-families"]
    plan, _ = COLLECT.draw_scoped(spec, _plan())
    assert [row[1] for row in plan] == ["feinaactiva"], plan


def test_a_programming_draw_issues_no_search_for_a_family_it_does_not_name() -> None:
    """`t4b-programming` declares `job_families: [programming]`, and no
    `FAMILY_KEYWORDS` entry is programming — so it searches for none of them."""
    spec = COLLECT.load_draws()["t4b-programming"]
    _, families = COLLECT.draw_scoped(spec, _plan())
    assert families == [], families


def test_the_breadth_draw_still_asks_for_every_family_it_declares() -> None:
    """The negative control: narrowing that refuses everything would pass both tests
    above. `t25-families` names six families and every one is a keyword set here."""
    spec = COLLECT.load_draws()["t25-families"]
    _, families = COLLECT.draw_scoped(spec, _plan())
    assert sorted(families) == sorted(spec["job_families"]), families


def test_every_declared_draw_asks_only_for_boards_the_collector_can_reach() -> None:
    """The live reading over the committed registry: a draw naming a source the
    collector has no fetcher for would silently collect nothing for it."""
    for name, spec in COLLECT.load_draws().items():
        unreachable = set(spec["sources"]) - set(COLLECT.SOURCE_HOSTS)
        assert not unreachable, f"draw {name!r} names {sorted(unreachable)}"
