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
