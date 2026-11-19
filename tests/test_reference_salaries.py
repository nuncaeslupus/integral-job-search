"""Reference salary lookup, over an invented payload (the real one is CC BY-NC)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from integral import reference_salaries as rs
from integral.identity import ProfileStore
from integral.robots import Robots

PAYLOAD = json.dumps(
    {
        "bands": [
            {
                "role": "Widget",
                "seniority": "senior",
                "company_type": "scaleup",
                "min": 1000,
                "max": 2000,
            }
        ]
    }
).encode()


class FakeRobots:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def allows(self, url: str) -> bool:
        return self.ok


def _robots(ok: bool) -> Robots:
    return cast(Robots, FakeRobots(ok))


def _fetcher(calls: list[str]) -> Callable[[str], bytes]:
    def fetch(url: str) -> bytes:
        calls.append(url)
        return PAYLOAD

    return fetch


def _lookup(store: ProfileStore, role: str, ok: bool, calls: list[str]) -> Any:
    return rs.reference_band(
        store, role, "Senior", "scaleup", fetch=_fetcher(calls), robots=_robots(ok)
    )


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles", "ada")


def test_lookup_returns_cited_band(store: ProfileStore) -> None:
    band = _lookup(store, "widget", True, [])
    assert band == rs.Band(1000, 2000)
    assert band.source == "Manfred Tech Career Report 2026"


def test_unknown_role_returns_none(store: ProfileStore) -> None:
    assert _lookup(store, "gadget", True, []) is None


def test_robots_refusal_fetches_nothing(store: ProfileStore) -> None:
    calls: list[str] = []
    assert _lookup(store, "widget", False, calls) is None
    assert calls == []


def test_cache_lives_under_profile_root(store: ProfileStore) -> None:
    _lookup(store, "widget", True, [])
    cached = store.path(*rs.CACHE_PARTS)
    assert cached.is_file()
    assert store.home in cached.parents
    assert Path(rs.__file__).resolve().parents[2] not in cached.parents
