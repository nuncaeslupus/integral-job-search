"""Second-reader cases for #922, #925, #930 and #932, derived from the findings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import integral.sourcing as sourcing
from integral.connectors import ListRequest
from integral.dedup import find_duplicates
from integral.identity import ProfileStore, create_profile, file_safe, id_from_name
from integral.offers import Offer, load_offers
from integral.robots import Robots
from integral.sourcing import Response

HEX = "ab" * 32


def _store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path / "p", "test")


def _offer(n: int, text: str, **fields: object) -> Offer:
    return Offer(id=f"sha256:{n:064x}", source=f"s{n}", text=text, **fields)  # type: ignore[arg-type]


BODY = " ".join(f"w{i}" for i in range(400))


# --- #922 -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title_a", "title_b"),
    [
        ("Backend Engineer", "Backend Developer (Python/Django)"),
        ("Backend Engineer", "BACKEND ENGINEER"),
        ("Ingeniero Backend", "Ingeniero backend."),
        ("Data Engineer", "Data Engineer - Remote"),
    ],
)
def test_one_role_re_titled_on_a_second_board_still_merges(title_a: str, title_b: str) -> None:
    a = _offer(1, BODY, title=title_a, company="Acme")
    b = _offer(2, BODY + " extra", title=title_b, company="ACME")
    assert len(find_duplicates([a, b])) == 1


@pytest.mark.parametrize(
    ("title_a", "title_b"),
    [
        ("Backend Engineer", "Frontend Engineer"),
        ("Senior Backend Engineer", "Junior Backend Engineer"),
        ("Product Designer", "Data Analyst"),
    ],
)
def test_different_roles_of_one_employer_do_not_merge(title_a: str, title_b: str) -> None:
    a = _offer(1, BODY, title=title_a, company="Acme")
    b = _offer(2, BODY + " extra", title=title_b, company="Acme")
    assert find_duplicates([a, b]) == []


def test_different_titles_at_different_employers_are_left_to_the_text() -> None:
    # The veto is per employer: a reposted advert under an agency name keeps the text rule.
    a = _offer(1, BODY, title="Backend Engineer", company="Acme")
    b = _offer(2, BODY + " extra", title="Frontend Engineer", company="Agency Ltd")
    assert len(find_duplicates([a, b])) == 1


def test_a_blank_title_leaves_the_text_rule_in_charge() -> None:
    a = _offer(1, BODY, title="   ", company="Acme")
    b = _offer(2, BODY + " extra", title="Frontend Engineer", company="Acme")
    assert len(find_duplicates([a, b])) == 1


# --- #930 -------------------------------------------------------------------


def test_only_the_id_prefix_is_rewritten_and_the_mapping_round_trips() -> None:
    assert file_safe(f"sha256:{HEX}.json") == f"sha256-{HEX}.json"
    assert id_from_name(file_safe(f"sha256:{HEX}")) == f"sha256:{HEX}"
    for other in ("2026-11-11T08:00:00.json", "a:sha256:x", "offers", "x:y"):
        assert file_safe(other) == other


def test_a_store_holding_both_names_of_one_offer_counts_it_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer = Offer(id=f"sha256:{HEX}", source="s", text="one offer")
    data = json.dumps(offer.model_dump(mode="json"))
    offers = tmp_path / "p" / "test" / "offers"
    offers.mkdir(parents=True, exist_ok=True)
    (offers / f"sha256:{HEX}.json").write_text(data, encoding="utf-8")
    (offers / f"sha256-{HEX}.json").write_text(data, encoding="utf-8")
    assert [o.id for o in load_offers(store).offers] == [offer.id]


# --- #925 -------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.waits: list[float] = []

    def pause(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


_ROBOTS = Robots(fetch=lambda url: "User-agent: *\nAllow: /\n")


def _spacing(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(sourcing, "_pause", clock.pause)
    monkeypatch.setattr(sourcing, "_clock", lambda: clock.now)
    monkeypatch.setattr(sourcing, "_last_request_at", {})
    return clock


def test_a_second_request_to_one_origin_waits_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _spacing(monkeypatch)
    robots = Robots(fetch=lambda url: "User-agent: *\nAllow: /\n")
    sourcing._space(robots, "https://a.example/1")
    assert clock.waits == []
    sourcing._space(robots, "https://a.example/2")
    assert clock.waits == [sourcing.REQUEST_FLOOR_SECONDS]


def test_time_already_spent_counts_toward_the_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _spacing(monkeypatch)
    robots = Robots(fetch=lambda url: "User-agent: *\nAllow: /\n")
    sourcing._space(robots, "https://a.example/1")
    clock.now += 0.75
    sourcing._space(robots, "https://a.example/2")
    assert clock.waits == [pytest.approx(0.25)]
    clock.now += 5
    sourcing._space(robots, "https://a.example/3")
    assert clock.waits == [pytest.approx(0.25)]


def test_spacing_is_per_origin_not_global(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _spacing(monkeypatch)
    robots = Robots(fetch=lambda url: "User-agent: *\nAllow: /\n")
    sourcing._space(robots, "https://a.example/1")
    sourcing._space(robots, "https://b.example/1")
    sourcing._space(robots, "http://a.example/1")  # another scheme is another origin
    assert clock.waits == []
    sourcing._space(robots, "https://a.example:443/2")  # the default port is the same origin
    assert clock.waits == [sourcing.REQUEST_FLOOR_SECONDS]


def test_a_longer_crawl_delay_wins_and_a_shorter_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _spacing(monkeypatch)
    texts = {
        "https://slow.example/robots.txt": "User-agent: *\nAllow: /\nCrawl-delay: 7\n",
        "https://quick.example/robots.txt": "User-agent: *\nAllow: /\nCrawl-delay: 0.2\n",
    }
    robots = Robots(fetch=lambda url: texts[url])
    for host in ("slow", "quick"):
        sourcing._space(robots, f"https://{host}.example/1")
        sourcing._space(robots, f"https://{host}.example/2")
    assert clock.waits == [7.0, sourcing.REQUEST_FLOOR_SECONDS]


# --- #932 -------------------------------------------------------------------

AT = "2026-11-11T08:00:00+00:00"


def _request(url: str = "https://boards.example/acme/jobs") -> ListRequest:
    return ListRequest(url=url, method="GET", headers={}, body=None)


@pytest.mark.parametrize(
    "answer",
    [
        Response(429, "slow down", error="HTTP 429"),
        Response(503, "", error="HTTP 503"),
        Response(None, "", error="timeout"),
        Response(200, "<html>Access denied</html>"),
        Response(202, '{"jobs": []}'),
    ],
)
def test_a_refusal_or_error_is_never_kept(tmp_path: Path, answer: Response) -> None:
    store = _store(tmp_path)
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return answer

    sourcing._list_of_the_day(store, _request(), AT, fetch, _ROBOTS)
    sourcing._list_of_the_day(store, _request(), AT, fetch, _ROBOTS)
    assert len(asked) == 2


def test_a_kept_page_is_reused_that_day_for_that_url_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(200, json.dumps({"jobs": [{"title": request.url}]}))

    first = sourcing._list_of_the_day(store, _request(), AT, fetch, _ROBOTS)
    again = sourcing._list_of_the_day(
        store, _request(), "2026-11-11T23:59:00+00:00", fetch, _ROBOTS
    )
    other = sourcing._list_of_the_day(
        store, _request("https://boards.example/beta/jobs"), AT, fetch, _ROBOTS
    )
    assert (again.status, again.body) == (first.status, first.body)
    assert other.body != first.body
    assert len(asked) == 2


def test_clearing_old_days_touches_nothing_outside_the_board_cache(tmp_path: Path) -> None:
    store = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    sibling = Path(store.path("cache", "other"))
    sibling.mkdir(parents=True)
    (sibling / "keep.txt").write_text("x", encoding="utf-8")
    boards = Path(store.path("cache", "boards"))
    boards.mkdir(parents=True)
    (boards / "2026-11-10").mkdir()
    (boards / "link").symlink_to(outside, target_is_directory=True)

    sourcing._list_of_the_day(
        store, _request(), AT, lambda r: Response(200, '{"jobs": []}'), _ROBOTS
    )
    assert (outside / "keep.txt").exists()
    assert (sibling / "keep.txt").exists()
    assert not (boards / "2026-11-10").exists()


def test_a_cache_hit_does_not_wait_for_the_host_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review follow-up on #943: spacing is for real requests, not for a kept page."""
    clock = _spacing(monkeypatch)
    store = _store(tmp_path)
    fetch = lambda r: Response(200, '{"jobs": []}')  # noqa: E731
    sourcing._list_of_the_day(store, _request(), AT, fetch, _ROBOTS)
    sourcing._list_of_the_day(store, _request(), AT, fetch, _ROBOTS)
    assert clock.waits == []


def test_a_list_page_actually_fetched_still_waits_for_the_host_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second reader on #944: moving the wait into the cache path must not drop it."""
    clock = _spacing(monkeypatch)
    store = _store(tmp_path)
    fetch = lambda r: Response(200, '{"jobs": []}')  # noqa: E731
    sourcing._list_of_the_day(store, _request(), AT, fetch, _ROBOTS)
    sourcing._list_of_the_day(
        store, _request("https://boards.example/beta/jobs"), AT, fetch, _ROBOTS
    )
    assert clock.waits == [sourcing.REQUEST_FLOOR_SECONDS]


# --- review follow-up on #943: directory readers count one offer once ----------


def _both_names(base: Path) -> None:
    for name in (f"sha256:{HEX}", f"sha256-{HEX}"):
        (base / name).mkdir(parents=True)


def test_the_directory_readers_list_an_offer_stored_under_both_names_once(tmp_path: Path) -> None:
    from integral import applications_board, brand_measure, interview_log

    store = _store(tmp_path)
    for offer in (f"sha256:{HEX}", f"sha256-{HEX}"):
        (Path(store.path("cv", "generated")) / offer / "v1").mkdir(parents=True)
        held = Path(store.path("interviews")) / offer / "iv-001"
        held.mkdir(parents=True)
        (held / "held.json").write_text("{}", encoding="utf-8")
    _both_names(Path(store.path("applications")))

    assert len(brand_measure.generated_versions(store)) == 1
    assert len(interview_log.logged_interviews(store)) == 1
    assert [r.offer_id for r in applications_board.collect(store).rows] == [f"sha256:{HEX}"]


def test_a_constructed_round_can_skip_the_spacing_wait_and_restores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _spacing(monkeypatch)
    with sourcing.no_waiting():
        sourcing._space(_ROBOTS, "https://a.example/1")
        sourcing._space(_ROBOTS, "https://a.example/2")
    assert clock.waits == []
    sourcing._space(_ROBOTS, "https://a.example/3")
    assert clock.waits == [sourcing.REQUEST_FLOOR_SECONDS]
