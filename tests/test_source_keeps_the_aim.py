"""T237 - `source()` never shortens the aim the candidate's step saved.

The first version saved whatever aim it was handed, so the only way to search
the terms past `PHRASE_CEILING` (call again with the remainder) replaced the
stored aim with a slice of it. The cases are derived from a closed rule, not
listed: for every term count at a window boundary (see `_COUNTS`), walk the
passes by `offset` and require (a) the stored aim is untouched, and (b) the
windows tile the terms exactly - nothing skipped, nothing searched twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.candidate import Aim, CandidateConstraints, Location
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.search_terms import load_aim, save_aim
from integral.sourcing import PHRASE_CEILING, Response, browser_urls, source

_CONNECTORS = Path(__file__).resolve().parents[1] / "connectors"
AT = "2026-01-01T00:00:00+00:00"


def _spain() -> CandidateConstraints:
    return CandidateConstraints(
        location=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        )
    )


def _nothing(request: object) -> Response:
    return Response(None, "", error="no network in this test")


def _allow() -> Robots:
    return Robots(fetch=lambda url: "User-agent: *\nAllow: /\n")


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _terms(n: int) -> tuple[str, ...]:
    return tuple(f"term{i}" for i in range(n))


def _run(store: ProfileStore, aim: Aim, offset: int = 0):  # type: ignore[no-untyped-def]
    return source(
        store,
        _spain(),
        aim,
        fetch=_nothing,
        at=AT,
        directory=_CONNECTORS,
        robots=_allow(),
        offset=offset,
    )


def _queried(run) -> set[str]:  # type: ignore[no-untyped-def]
    return {o.query for o in run.outcomes if o.query}


#: Every count at which a window boundary can misbehave, derived from the ceiling:
#: empty, one, either side of each multiple of it, up to the third window.
_COUNTS = sorted({0, 1} | {m * PHRASE_CEILING + d for m in (1, 2) for d in (-1, 0, 1)})


@pytest.mark.parametrize("n", _COUNTS)
def test_walking_every_window_leaves_the_stored_aim_as_it_was(store: ProfileStore, n: int) -> None:
    full = Aim(state="stated", terms=_terms(n), evidence=("e1",)) if n else Aim(state="unknown")
    if n:
        save_aim(store, full)
    before = store.read_json("search", "aim.json") if n else None

    covered: list[str] = []
    offset = 0
    # Bounded: a window that never advanced must fail here, not spin forever.
    for _ in range(len(full.terms) // PHRASE_CEILING + 1):
        run = _run(store, full, offset)
        covered += sorted(_queried(run))
        if not run.unsearched:
            break
        offset += PHRASE_CEILING
    else:
        pytest.fail(f"still unsearched after every window: {run.unsearched}")
    after = store.read_json("search", "aim.json") if store.exists("search", "aim.json") else None
    assert after == before
    if n:
        assert load_aim(store) == full
        # the windows tile the terms: each exactly once, none missed
        assert sorted(covered) == sorted(full.terms)


def test_a_slice_handed_in_as_the_aim_does_not_replace_the_stored_one(
    store: ProfileStore,
) -> None:
    """The old caller's move - pass the remainder as the aim - must not shorten it."""
    full = Aim(state="stated", terms=_terms(PHRASE_CEILING + 3))
    save_aim(store, full)
    _run(store, Aim(state="stated", terms=full.terms[PHRASE_CEILING:]))
    assert load_aim(store) == full


def test_a_first_search_still_records_the_aim(store: ProfileStore) -> None:
    """The reason the write existed: a session that ends badly must not lose it."""
    aim = Aim(state="stated", terms=("python", "developer"))
    _run(store, aim)
    assert load_aim(store) == aim


def test_unsearched_is_what_lies_past_the_window(store: ProfileStore) -> None:
    terms = _terms(2 * PHRASE_CEILING + 1)
    aim = Aim(state="stated", terms=terms)
    assert _run(store, aim).unsearched == terms[PHRASE_CEILING:]
    assert _run(store, aim, PHRASE_CEILING).unsearched == terms[2 * PHRASE_CEILING :]
    assert _run(store, aim, 2 * PHRASE_CEILING).unsearched == ()


def test_a_negative_offset_is_refused_not_wrapped(store: ProfileStore) -> None:
    """`terms[-1:]` would silently search the last phrase and report the rest."""
    with pytest.raises(ValueError):
        _run(store, Aim(state="stated", terms=_terms(3)), -1)


def test_browser_urls_follows_the_same_window() -> None:
    aim = Aim(state="stated", terms=_terms(PHRASE_CEILING + 2))
    first = browser_urls(_spain(), aim, directory=_CONNECTORS, robots=_allow())
    second = browser_urls(
        _spain(), aim, directory=_CONNECTORS, robots=_allow(), offset=PHRASE_CEILING
    )
    if first:  # no steerable browser board installed -> nothing to compare
        assert set(first).isdisjoint(second)
        assert any("term0" in u for u in first) and not any("term0" in u for u in second)
        assert any(f"term{PHRASE_CEILING}" in u for u in second)
