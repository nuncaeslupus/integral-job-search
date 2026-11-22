"""Every former HTTP entry point refuses the same three things, through one layer (#929).

The socket is replaced at its lowest level (`transport._OPENER`), so the size cap,
the redirect handling and every check above it are the real code. "Refused" is
asserted over what reached the socket, not over a return value: a private address
or a disallowed path must never be requested at all.
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from integral import canonical_ad, connector_exchange, transport
from integral.robots import Robots, RobotsError

REPO = Path(__file__).resolve().parents[1]
RULES = "User-agent: *\nDisallow: /private\n"
ALLOWED = "https://jobs.example.com/ofertas"
PRIVATE = "https://127.0.0.1/ofertas"
DISALLOWED = "https://jobs.example.com/private/1"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Reply:
    def __init__(self, url: str, body: bytes) -> None:
        self.url, self.status, self._body = url, 200, body
        self.headers = Message()

    def read(self, limit: int = -1) -> bytes:
        return self._body[:limit] if limit >= 0 else self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


class _Socket:
    """Answers each URL from a script; a `str` value is a redirect to it."""

    def __init__(self, script: dict[str, bytes | str]) -> None:
        self.script = script
        self.asked: list[str] = []

    def open(self, request: Any, timeout: float = 0) -> _Reply:
        url = request.full_url
        self.asked.append(url)
        answer = self.script.get(url, b"ok")
        if isinstance(answer, str):
            headers = Message()
            headers["Location"] = answer
            raise urllib.error.HTTPError(url, 302, "Found", headers, None)
        return _Reply(url, answer)


def _canonical(url: str, robots: Robots) -> object:
    return canonical_ad.guarded_fetch(robots)(url)


def _exchange(url: str, robots: Robots) -> object:
    return connector_exchange.https_fetcher(robots=robots)(url)


def _collector(url: str, robots: Robots) -> object:
    collect = _load("collect_ads_transport", REPO / "tools" / "collect_ads.py")
    return collect.get(transport.Transport(robots), url)


def _query_board(url: str, robots: Robots) -> object:
    probe = _load(
        "query_board_transport", REPO / ".claude/skills/connector-new/scripts/query_board.py"
    )
    transport._SHARED = robots  # the probe asks the shared one, as every default caller does
    status, size, error = probe.fetch(url, {})
    if status is None:
        raise transport.FetchRefused(error)
    return size


ENTRY_POINTS: dict[str, Callable[[str, Robots], object]] = {
    "canonical_ad.guarded_fetch": _canonical,
    "connector_exchange.https_fetcher": _exchange,
    "tools/collect_ads.get": _collector,
    "connector-new query_board.fetch": _query_board,
}
REFUSALS = (
    transport.FetchRefused,
    PermissionError,
    connector_exchange.ExchangeError,
)


@pytest.fixture
def robots(monkeypatch: pytest.MonkeyPatch) -> Robots:
    monkeypatch.setattr(transport, "_SHARED", None)
    return Robots(fetch=lambda _url: RULES)


def _socket(monkeypatch: pytest.MonkeyPatch, script: dict[str, bytes | str]) -> _Socket:
    sock = _Socket(script)
    monkeypatch.setattr(transport, "_OPENER", sock)
    return sock


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("target", [PRIVATE, DISALLOWED])
def test_a_refused_target_is_never_requested_directly(
    entry: str, target: str, robots: Robots, monkeypatch: pytest.MonkeyPatch
) -> None:
    sock = _socket(monkeypatch, {})
    with pytest.raises(REFUSALS):
        ENTRY_POINTS[entry](target, robots)
    assert sock.asked == []


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("target", [PRIVATE, DISALLOWED, "http://jobs.example.com/x"])
def test_a_refused_target_is_never_requested_through_a_redirect(
    entry: str, target: str, robots: Robots, monkeypatch: pytest.MonkeyPatch
) -> None:
    sock = _socket(monkeypatch, {ALLOWED: target})
    with pytest.raises(REFUSALS):
        ENTRY_POINTS[entry](ALLOWED, robots)
    assert sock.asked == [ALLOWED]


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_an_over_size_body_is_refused_not_cut(
    entry: str, robots: Robots, monkeypatch: pytest.MonkeyPatch
) -> None:
    _socket(monkeypatch, {ALLOWED: b"x" * (transport.MAX_PAGE_BYTES + 1)})
    with pytest.raises(REFUSALS):
        ENTRY_POINTS[entry](ALLOWED, robots)


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_the_negative_control_a_permitted_page_is_read(
    entry: str, robots: Robots, monkeypatch: pytest.MonkeyPatch
) -> None:
    sock = _socket(monkeypatch, {ALLOWED: "https://jobs.example.com/ofertas/2"})
    ENTRY_POINTS[entry](ALLOWED, robots)
    assert sock.asked == [ALLOWED, "https://jobs.example.com/ofertas/2"]


# --- robots.txt itself: the one request that cannot ask robots.txt first -----------


def test_an_over_size_robots_txt_is_unreadable_not_cut(monkeypatch: pytest.MonkeyPatch) -> None:
    _socket(monkeypatch, {"https://big.example.com/robots.txt": b"#" * (512 * 1024 + 1)})
    with pytest.raises(RobotsError):
        Robots(retry_delays=()).allows("https://big.example.com/jobs")


def test_a_robots_txt_redirect_to_a_private_address_is_not_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock = _socket(
        monkeypatch, {"https://jobs.example.com/robots.txt": "https://10.0.0.1/robots.txt"}
    )
    with pytest.raises(RobotsError):
        Robots(retry_delays=()).allows("https://jobs.example.com/jobs")
    assert sock.asked == ["https://jobs.example.com/robots.txt"]


def test_a_private_address_never_has_its_robots_txt_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    sock = _socket(monkeypatch, {})
    assert Robots(retry_delays=()).allows(PRIVATE) is False
    assert sock.asked == []


# --- spacing, on every hop ------------------------------------------------------------


def test_a_redirect_hop_to_the_same_origin_waits_the_crawl_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(transport, "_pause", waits.append)
    monkeypatch.setattr(transport, "_clock", lambda: 0.0)
    _socket(monkeypatch, {ALLOWED: "https://jobs.example.com/ofertas/2"})
    robots = Robots(fetch=lambda _url: "User-agent: *\nAllow: /\nCrawl-delay: 3\n")
    transport.Transport(robots).request(ALLOWED)
    assert waits == [3.0]


def test_a_caller_cannot_send_another_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def send(_m: str, url: str, headers: Any, *_rest: object) -> transport.Hop:
        sent.append(headers["User-Agent"])
        return transport.Hop(200, {}, b"", url)

    robots = Robots(fetch=lambda _url: RULES)
    transport.Transport(robots, send=send).request(ALLOWED, headers={"User-Agent": "Mozilla/5.0"})
    assert sent == [transport.USER_AGENT]
