"""The shipped live fetcher: `source()` over the network through `integral.transport` (#920).

No real network: the transport's `send` is injected, so the guards above it are the
real code and nothing leaves the process.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from integral import transport
from integral.candidate import Aim, CandidateConstraints, Location
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.live_fetch import _main, live_fetch
from integral.relevance import record as record_relevance
from integral.robots import Robots
from integral.sourcing import source

REPO = Path(__file__).resolve().parents[1]
ALLOW = "User-agent: *\nAllow: /\n"
URL = "https://jobs.example.com/api/jobs"


class _Socket:
    def __init__(self, answers: dict[str, bytes | Exception] | None = None) -> None:
        self.answers = answers or {}
        self.sent: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: Any,
        body: bytes | None,
        _timeout: float,
        max_bytes: int,
    ) -> transport.Hop:
        self.sent.append((method, url, dict(headers), body))
        answer = self.answers.get(url, b"[]")
        if isinstance(answer, Exception):
            raise answer
        if len(answer) > max_bytes:
            raise transport.BodyTooLarge("too big")
        return transport.Hop(200, {}, answer, url)


def _request(url: str = URL, **kw: Any) -> ListRequest:
    return ListRequest(
        url=url,
        method=kw.get("method", "GET"),
        headers=kw.get("headers", {}),
        body=kw.get("body"),
        charset=kw.get("charset", "utf-8"),
    )


def _fetch(sock: _Socket, rules: str = ALLOW) -> Any:
    return live_fetch(Robots(fetch=lambda _url: rules), send=sock)


def test_the_body_is_decoded_by_the_connectors_charset() -> None:
    sock = _Socket({URL: "Técnico de sistemas".encode("latin-1")})
    response = _fetch(sock)(_request(charset="iso-8859-1"))
    assert (response.status, response.body, response.error) == (200, "Técnico de sistemas", None)


def test_a_body_that_does_not_decode_is_an_error_not_replacement_characters() -> None:
    sock = _Socket({URL: "Técnico".encode("cp1252")})
    response = _fetch(sock)(_request(charset="utf-8"))
    assert response.error and "does not decode" in response.error
    assert "�" not in response.body


def test_a_post_keeps_its_method_body_and_headers_and_our_agent() -> None:
    sock = _Socket()
    request = _request(
        method="POST",
        body=b'{"q": "python"}',
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    _fetch(sock)(request)
    ((method, url, headers, body),) = sock.sent
    assert (method, url, body) == ("POST", URL, b'{"q": "python"}')
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == transport.USER_AGENT


@pytest.mark.parametrize(
    "url",
    ["https://127.0.0.1/jobs", "https://jobs.example.com/private/1", "http://jobs.example.com/x"],
)
def test_a_refused_request_is_reported_and_never_sent(url: str) -> None:
    sock = _Socket()
    response = _fetch(sock, "User-agent: *\nDisallow: /private\n")(_request(url))
    assert response.status is None and response.error and response.error.startswith("refused")
    assert sock.sent == []


def test_an_over_size_answer_is_refused() -> None:
    sock = _Socket({URL: b"x" * (transport.MAX_PAGE_BYTES + 1)})
    response = _fetch(sock)(_request())
    assert response.error and response.error.startswith("refused")


def test_a_network_fault_is_reported_as_unreachable() -> None:
    sock = _Socket({URL: TimeoutError("timed out")})
    response = _fetch(sock)(_request())
    assert response.status is None and response.error == "unreachable: timed out"


# --- through a real `source()` round ------------------------------------------------


def _package(tmp: Path) -> Path:
    package = tmp / "connectors" / "atshost_en"
    package.mkdir(parents=True)
    (package / "connector.yaml").write_text(
        "site: atshost\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-09-10'\n"
        "list:\n  url_pattern: 'https://api.ats.example.com/v1/boards/{employer}/jobs'\n"
        "  pagination: {mode: none, max_pages: 1}\n"
        "  from_json:\n    items: jobs\n    fields: {title: title, company: company, text: body}\n"
        "  employers:\n    acme: Acme Corp\n    beta: Beta Inc\n    gamma: Gamma SL\n",
        encoding="utf-8",
    )
    meta = (REPO / "connectors" / "greenhouse_en" / "meta.yaml").read_text(encoding="utf-8")
    (package / "meta.yaml").write_text(meta.replace("GLOBAL", "ES"), encoding="utf-8")
    shutil.copytree(REPO / "connectors" / "greenhouse_en" / "fixture", package / "fixture")
    return package.parent


def test_a_round_reads_through_the_live_fetcher_spaced_once_per_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(transport, "_pause", waits.append)
    monkeypatch.setattr(transport, "_clock", lambda: 0.0)
    base = "https://api.ats.example.com/v1/boards"

    def jobs(name: str) -> bytes:
        return json.dumps({"jobs": [{"title": f"Python developer {name}", "body": name}]}).encode()

    sock = _Socket({f"{base}/{name}/jobs": jobs(name) for name in ("acme", "beta", "gamma")})
    robots = Robots(fetch=lambda _url: "User-agent: *\nDisallow: /v1/boards/beta\n")
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path / "p", "test")
    record_relevance(store, 0.0)

    run = source(
        store,
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
        ),
        Aim(state="stated", terms=("python",)),
        fetch=live_fetch(robots, send=sock),
        at="2026-11-22T00:00:00+00:00",
        directory=_package(tmp_path),
        robots=robots,
    )

    assert [url for _, url, _, _ in sock.sent] == [f"{base}/acme/jobs", f"{base}/gamma/jobs"]
    assert run.added == 2
    assert waits == [transport.REQUEST_FLOOR_SECONDS], "one gap between two requests, not two"


def test_the_command_says_what_is_missing_rather_than_improvising(tmp_path: Path) -> None:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    assert _main(["run", "--handle", "test", "--root", str(tmp_path)]) == 2
    assert _main([]) == 2


# --- #994 second reader ---------------------------------------------------------------

_ATS_YAML = (
    "site: atshost\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-09-10'\n"
    "list:\n  url_pattern: 'https://api.ats.example.com/v1/boards/{employer}/jobs'\n"
    "  pagination: {mode: none, max_pages: 1}\n"
    "  from_json:\n    items: jobs\n    fields: {title: title, company: company, text: body}\n"
    "  employers:\n    acme: Acme Corp\n    beta: Beta Inc\n    gamma: Gamma SL\n"
)


def _round(tmp_path: Path, answers: dict[str, bytes], rules: str = ALLOW) -> tuple[Any, list[str]]:
    base = "https://api.ats.example.com/v1/boards"
    sock = _Socket({f"{base}/{name}/jobs": body for name, body in answers.items()})
    robots = Robots(fetch=lambda _url: rules)
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path / "p", "test")
    record_relevance(store, 0.0)
    run = source(
        store,
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
        ),
        Aim(state="stated", terms=("python",)),
        fetch=live_fetch(robots, send=sock),
        at="2026-11-22T00:00:00+00:00",
        directory=_package(tmp_path),
        robots=robots,
    )
    return run, [url for _, url, _, _ in sock.sent]


def _jobs(name: str) -> bytes:
    return json.dumps({"jobs": [{"title": f"Python developer {name}", "body": name}]}).encode()


@pytest.mark.parametrize("bad", [b"\xef\xbb\xbf\xe9", b"\xff\xfe\x00\xd8"])
def test_a_bom_followed_by_undecodable_bytes_fails_one_board_not_the_round(
    tmp_path: Path, bad: bytes
) -> None:
    run, asked = _round(tmp_path, {"acme": bad, "beta": _jobs("beta"), "gamma": _jobs("gamma")})
    assert len(asked) == 3, "the round stopped at the undecodable body"
    assert run.added == 2
    (outcome,) = run.outcomes
    assert any("Acme Corp" in failed and "decode" in failed for failed in outcome.employers_failed)


def test_every_request_builder_carries_the_connectors_charset(tmp_path: Path) -> None:
    """Both list builders and the advert page: a non-UTF-8 board is decoded as declared."""
    from integral import sourcing
    from integral.connectors import build_list_requests, parse_connector

    fixtures = REPO / "tests" / "fixtures" / "connectors"
    ats = parse_connector(_ATS_YAML + "charset: iso-8859-1\n")
    post = parse_connector(
        (fixtures / "post_board.yaml").read_text(encoding="utf-8") + "charset: iso-8859-1\n"
    )
    built = build_list_requests(ats) + build_list_requests(post)
    assert built and {request.charset for request in built} == {"iso-8859-1"}

    detailed = parse_connector(
        _ATS_YAML.replace("text: body", "detail_url: url")
        + "detail:\n  fields:\n    text:\n      css: 'div.content'\n"
        + "charset: iso-8859-1\n"
    )
    seen: list[str] = []

    def fetch(request: ListRequest) -> Any:
        seen.append(request.charset)
        return sourcing.Response(200, "<div class='content'>x</div>")

    sourcing._detail_record(detailed, "https://jobs.example.com/a/1", fetch=fetch)
    assert seen == ["iso-8859-1"]


class _Reply:
    def __init__(self, url: str, body: bytes) -> None:
        self.url, self.status, self._body = url, 200, body
        self.headers: dict[str, str] = {}

    def read(self, limit: int = -1) -> bytes:
        return self._body[:limit] if limit >= 0 else self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *_a: object) -> None:
        return None


def test_the_command_reads_robots_once_and_spaces_the_first_request_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI's own wiring, not a test that hands both halves one object."""
    from integral import live_fetch as module
    from integral import sourcing

    asked: list[str] = []

    class _Opener:
        def open(self, request: Any, timeout: float = 0) -> _Reply:
            asked.append(request.full_url)
            if request.full_url.endswith("/robots.txt"):
                return _Reply(request.full_url, b"User-agent: *\nAllow: /\nCrawl-delay: 4\n")
            return _Reply(request.full_url, _jobs(request.full_url.split("/")[-2]))

    waits: list[float] = []
    monkeypatch.setattr(transport, "_OPENER", _Opener())
    monkeypatch.setattr(transport, "_pause", waits.append)
    monkeypatch.setattr(transport, "_clock", lambda: 0.0)
    monkeypatch.setattr(sourcing, "DEFAULT_CONNECTORS_DIR", _package(tmp_path))
    monkeypatch.setattr(
        module,
        "load_constraints",
        lambda _payload: CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
        ),
    )
    monkeypatch.setattr(module, "load_aim", lambda _store: Aim(state="stated", terms=("python",)))
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path / "p", "test")
    record_relevance(store, 0.0)
    from integral.constraints_step import CONSTRAINTS_PARTS

    store.write_json({}, *CONSTRAINTS_PARTS)

    assert _main(["run", "--handle", "test", "--root", str(tmp_path / "p")]) == 0

    robots_reads = [url for url in asked if url.endswith("/robots.txt")]
    assert robots_reads == ["https://api.ats.example.com/robots.txt"]
    assert len(asked) == 4  # robots.txt, then three employers
    assert waits == [4.0, 4.0, 4.0], "every list request waits the crawl delay, the first too"


def test_a_handle_that_is_not_a_name_exits_2_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(["run", "--handle", "../x", "--root", str(tmp_path)]) == 2
    assert "Traceback" not in capsys.readouterr().err
