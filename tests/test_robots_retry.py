"""T238: one failed read of robots.txt must not cost a board its whole round.

A network-level failure (no route, reset, timeout) is retried a bounded number
of times; an HTTP answer keeps its existing meaning and is never retried as a
network fault. When the retries run out the board is still skipped — never read
as permission — and the skip says "unreachable", so it is not mistaken for
"refused" (the site's own disallow). Every case runs through `source`, the path
a candidate's round takes, and not only through `Robots`.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from integral.candidate import Aim, CandidateConstraints, Location
from integral.connectors import ListRequest
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots, RobotsUnreachable
from integral.sourcing import Response, _may_fetch, source

ALLOW_ALL = "User-agent: *\nAllow: /\n"
AT = "2026-01-01T00:00:00+00:00"
_CONNECTORS = Path(__file__).resolve().parents[1] / "connectors"


def _spain() -> CandidateConstraints:
    return CandidateConstraints(
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        )
    )


URL = "https://www.getmanfred.com/ofertas-empleo/8389/scala-developer"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


class _Flaky:
    """A robots fetcher that fails `failures` times, then answers `text`."""

    def __init__(self, failures: int, error: Exception, text: str = ALLOW_ALL) -> None:
        self.failures = failures
        self.error = error
        self.text = text
        self.calls = 0

    def __call__(self, url: str) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return self.text


def _robots(fetch: _Flaky, delays: tuple[float, ...] = (0.5, 2.0)) -> tuple[Robots, list[float]]:
    slept: list[float] = []
    return Robots(fetch=fetch, retry_delays=delays, sleep=slept.append), slept


def _run(store: ProfileStore, robots: Robots) -> tuple[list[str], list[str | None]]:
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
        robots=robots,
    )
    return asked, [o.skipped for o in run.outcomes]


def _http(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x.test/robots.txt", code, "x", {}, None)  # type: ignore[arg-type]


def test_a_transient_network_error_is_retried_and_the_board_is_read(store: ProfileStore) -> None:
    flaky = _Flaky(1, OSError(113, "No route to host"))
    robots, slept = _robots(flaky)
    asked, skipped = _run(store, robots)
    assert asked, "the board was dropped for the round over one failed read"
    assert not any(s and "robots" in s for s in skipped), skipped
    assert slept[:1] == [0.5], "the first retry waited the first configured delay"


def test_a_timeout_and_a_urlerror_are_network_failures_too() -> None:
    for error in (TimeoutError("timed out"), urllib.error.URLError("no route")):
        flaky = _Flaky(2, error)
        robots, slept = _robots(flaky)
        assert robots.allows(URL) is True
        assert flaky.calls == 3
        assert slept == [0.5, 2.0]


def test_a_persistent_network_error_skips_as_unreachable_not_as_permission(
    store: ProfileStore,
) -> None:
    flaky = _Flaky(10**6, OSError(113, "No route to host"))
    robots, slept = _robots(flaky)
    asked, skipped = _run(store, robots)
    assert asked == [], "an unreadable robots.txt was read as permission"
    assert skipped and all(s for s in skipped)
    for reason in skipped:
        assert reason is not None
        assert "unreachable" in reason
        assert "disallows" not in reason and "refused" not in reason
    assert slept, "no retry was made before giving up"
    # bounded: one try plus the two configured retries, per origin
    per_origin = flaky.calls
    assert per_origin >= 3 and per_origin % 3 == 0


def test_a_network_failure_is_remembered_so_an_adverts_check_does_not_retry_it() -> None:
    flaky = _Flaky(10**6, OSError("down"))
    robots, _ = _robots(flaky)
    assert _may_fetch(robots, URL) is False
    calls_after_first = flaky.calls
    assert calls_after_first == 3
    for _ in range(5):
        assert _may_fetch(robots, URL + "/other") is False
    assert flaky.calls == calls_after_first, "a failure was retried per advert"
    with pytest.raises(RobotsUnreachable):
        robots.allows(URL)


@pytest.mark.parametrize("code", [403, 404, 500])
def test_an_http_answer_is_not_retried_as_a_network_fault(code: int) -> None:
    flaky = _Flaky(10**6, _http(code))
    slept: list[float] = []

    def browser(url: str) -> str:
        raise _http(403)

    robots = Robots(fetch=flaky, browser_fetch=browser, retry_delays=(0.5, 2.0), sleep=slept.append)
    if code == 404:
        assert robots.allows(URL) is True  # "no rules", the existing meaning
    else:
        with pytest.raises(Exception) as caught:
            robots.allows(URL)
        assert not isinstance(caught.value, RobotsUnreachable)
    assert flaky.calls == 1, "an HTTP status was re-asked"
    assert slept == []


@pytest.mark.parametrize("code", [403, 500])
def test_an_http_failure_skips_without_saying_unreachable(store: ProfileStore, code: int) -> None:
    robots = Robots(
        fetch=_Flaky(10**6, _http(code)),
        browser_fetch=lambda url: (_ for _ in ()).throw(_http(403)),
        retry_delays=(0.5,),
        sleep=lambda s: None,
    )
    asked, skipped = _run(store, robots)
    assert asked == []
    assert skipped and all(s and "unreachable" not in s for s in skipped), skipped


def test_a_robots_disallow_is_worded_as_refused(store: ProfileStore) -> None:
    robots, slept = _robots(_Flaky(0, OSError("x"), "User-agent: *\nDisallow: /\n"))
    asked, skipped = _run(store, robots)
    assert asked == []
    assert skipped and all(s and s.startswith("refused") for s in skipped), skipped
    assert not any("unreachable" in (s or "") for s in skipped)
    assert slept == []
