"""Every former HTTP entry point refuses the same three things, through one layer (#929).

The socket is replaced at its lowest level (`transport._OPENER`), so the size cap,
the redirect handling and every check above it are the real code. "Refused" is
asserted over what reached the socket, not over a return value: a private address
or a disallowed path must never be requested at all.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import urllib.error
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from typing import Any, cast

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


# --- #993 second reader: F1-F6 ---------------------------------------------------------

#: F1: a host urllib would unquote, or one no hostname needs, is refused before it
#: is classified — `%`, NUL, whitespace or a control character anywhere in it.
UNSAFE_HOSTS = [
    "https://127%2e0%2e0%2e1:8443/x",
    "https://%31%32%37.0.0.1/",
    "https://%6c%6f%63%61%6c%68%6f%73%74/",
    "https://jobs%2eexample.com/",
    "https://exa\x00mple.com/",
    "https://exa mple.com/",
    "https://exa\x01mple.com/",
    "https://exa\x7fmple.com/",
]
#: F4: an IPv6 literal carrying a non-public IPv4 address, however it carries it.
EMBEDDED_V4 = [
    "https://[::127.0.0.1]/",  # IPv4-compatible
    "https://[64:ff9b::7f00:1]/",  # NAT64 well-known prefix, RFC 6052
    "https://[64:ff9b:1::a00:1]/",  # NAT64 local-use prefix, 10.0.0.1
    "https://[2002:7f00:1::1]/",  # 6to4 of 127.0.0.1
    "https://[::ffff:10.0.0.1]/",  # IPv4-mapped
]


class _AllowAll:
    """A policy that checks no address: the transport's own check must hold (F3)."""

    def allows(self, url: str) -> bool:
        return True

    def delay(self, url: str, floor: float) -> float:
        return 0.0


def _recording_send(sent: list[tuple[str, dict[str, str]]], script: dict[str, str]) -> Any:
    def send(_m: str, url: str, headers: Any, *_rest: object) -> transport.Hop:
        sent.append((url, dict(headers)))
        if url in script:
            return transport.Hop(302, {"Location": script[url]}, b"", url)
        return transport.Hop(200, {}, b"ok", url)

    return send


@pytest.mark.parametrize("url", UNSAFE_HOSTS + EMBEDDED_V4 + ["https://u@jobs.example.com/"])
def test_the_transport_refuses_it_even_under_a_policy_that_checks_nothing(url: str) -> None:
    sent: list[tuple[str, dict[str, str]]] = []
    with pytest.raises(transport.FetchRefused):
        transport.Transport(_AllowAll(), send=_recording_send(sent, {})).request(url)
    assert sent == []


@pytest.mark.parametrize("url", UNSAFE_HOSTS + EMBEDDED_V4)
def test_the_address_rule_itself_refuses_it(url: str) -> None:
    assert transport.is_public_web_url(url) is False


def test_a_robots_txt_url_with_userinfo_is_refused_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sock = _socket(monkeypatch, {})
    with pytest.raises(transport.FetchRefused):
        transport.fetch_policy("https://u:p@jobs.example.com/robots.txt")
    assert sock.asked == []


@pytest.mark.parametrize("target", UNSAFE_HOSTS[:3] + EMBEDDED_V4[:2])
def test_the_same_spellings_are_refused_as_a_redirect_target(target: str) -> None:
    sent: list[tuple[str, dict[str, str]]] = []
    send = _recording_send(sent, {ALLOWED: target})
    with pytest.raises(transport.FetchRefused):
        transport.Transport(_AllowAll(), send=send).request(ALLOWED)
    assert [url for url, _ in sent] == [ALLOWED]


def test_a_public_ipv6_literal_and_an_idn_host_still_pass() -> None:
    """The negative control for F1 and F4."""
    assert transport.is_public_web_url("https://[2606:4700::6810:84e5]/")
    assert transport.is_public_web_url("https://bücher.example/")


def _fake_dns(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[tuple[str, int]]:
    connected: list[tuple[str, int]] = []

    def getaddrinfo(host: str, port: int, *_a: object, **_k: object) -> list[Any]:
        return [(0, 0, 0, "", (ip, port)) for ip in answers]

    def create_connection(address: tuple[str, int], *_a: object) -> Any:
        connected.append(address)
        return object()

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    return connected


class _Conn:
    _tunnel_host: str | None = None
    _tunnel_port: int | None = None


@pytest.mark.parametrize(
    "answers", [["127.0.0.1"], ["93.184.215.14", "10.0.0.7"], ["::ffff:192.168.1.1"]]
)
def test_a_name_resolving_anywhere_private_is_never_connected(
    answers: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: `127.0.0.1.nip.io` and rebinding. One private answer refuses the name."""
    connected = _fake_dns(monkeypatch, answers)
    create = transport._checked_create_connection(cast(Any, _Conn()))
    with pytest.raises(transport.FetchRefused, match="not a public address"):
        create(("127.0.0.1.nip.io", 443))
    assert connected == []


def test_the_connection_goes_to_the_address_that_was_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected = _fake_dns(monkeypatch, ["93.184.215.14"])
    transport._checked_create_connection(cast(Any, _Conn()))(("jobs.example.com", 443))
    assert connected == [("93.184.215.14", 443)]


def test_through_a_proxy_the_targets_own_resolution_is_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected = _fake_dns(monkeypatch, ["10.1.2.3"])
    conn = _Conn()
    conn._tunnel_host, conn._tunnel_port = "intranet.example.com", 443
    with pytest.raises(transport.FetchRefused):
        transport._checked_create_connection(cast(Any, conn))(("proxy.local", 3128))
    assert connected == []


def test_the_real_opener_refuses_a_name_that_resolves_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2 end to end: the shipped `urllib_send`, no socket ever opened."""
    connected = _fake_dns(monkeypatch, ["127.0.0.1"])
    with pytest.raises(transport.FetchRefused):
        transport.Transport(_AllowAll()).request("https://127.0.0.1.nip.io/x")
    assert connected == []


def test_a_cross_origin_redirect_carries_none_of_the_callers_headers() -> None:
    """F5: RFC 9110 §15.4. A same-origin hop keeps them."""
    other = "https://elsewhere.example.org/x"
    same = "https://jobs.example.com/ofertas/2"
    sent: list[tuple[str, dict[str, str]]] = []
    send = _recording_send(sent, {ALLOWED: same, same: other})
    transport.Transport(_AllowAll(), send=send).request(
        ALLOWED, headers={"HX-Request": "true", "Authorization": "x"}
    )
    assert [("HX-Request" in h, "Authorization" in h) for _, h in sent] == [
        (True, True),
        (True, True),
        (False, False),
    ]
    assert sent[-1][1]["User-Agent"] == transport.USER_AGENT


def test_a_userinfo_url_is_a_refusal_in_the_collector_not_a_crash(
    robots: Robots, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: `https://u@host/` used to escape as `InvalidURL` from robots.allows."""
    sock = _socket(monkeypatch, {})
    with pytest.raises(PermissionError):
        _collector("https://u@jobs.example.com/ofertas", robots)
    assert sock.asked == []
