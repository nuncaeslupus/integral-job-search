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
from integral.connectors import accepts_query, build_list_requests, load_connector
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.search_terms import load_aim, save_aim
from integral.sourcing import (
    PHRASE_CEILING,
    Response,
    browser_urls,
    browser_urls_every_phrase,
    needs_browser,
    packages_for,
    source,
    source_every_phrase,
)

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


def test_a_changed_aim_at_offset_zero_replaces_the_stored_one(store: ProfileStore) -> None:
    """F1: the one writer. A changed aim that is searched must be saved too."""
    save_aim(store, Aim(state="stated", terms=("python developer",)))
    changed = Aim(state="stated", terms=("data engineer", "analytics engineer"))
    _run(store, changed)
    assert load_aim(store) == changed


def test_a_continuation_never_writes_even_with_a_different_aim(store: ProfileStore) -> None:
    full = Aim(state="stated", terms=_terms(PHRASE_CEILING + 3))
    save_aim(store, full)
    before = store.read_json("search", "aim.json")
    other = Aim(state="stated", terms=_terms(2 * PHRASE_CEILING)[::-1])
    _run(store, other, PHRASE_CEILING)
    assert store.read_json("search", "aim.json") == before


def test_a_corrupt_stored_aim_does_not_stop_a_first_pass_or_a_continuation(
    store: ProfileStore,
) -> None:
    """F3: the writer need not read the store at all."""
    aim = Aim(state="stated", terms=_terms(PHRASE_CEILING + 1))
    store.write_json(["not", "an", "aim"], "search", "aim.json")
    _run(store, aim, PHRASE_CEILING)  # continuation: reads nothing
    _run(store, aim)  # first pass: overwrites
    assert load_aim(store) == aim


def test_a_first_search_records_the_aim_in_an_empty_store(store: ProfileStore) -> None:
    """The reason the write existed: a session that ends badly must not lose it."""
    aim = Aim(state="stated", terms=("python", "developer"))
    assert not store.exists("search", "aim.json")
    _run(store, aim)
    assert load_aim(store) == aim


@pytest.mark.parametrize(
    "offset", [1, PHRASE_CEILING - 1, PHRASE_CEILING + 1, 2 * PHRASE_CEILING - 1]
)
def test_an_offset_that_is_not_a_whole_window_is_refused(store: ProfileStore, offset: int) -> None:
    """F5: offset=3 would search phrases 3-8 after 0-5, twice over."""
    with pytest.raises(ValueError):
        _run(store, Aim(state="stated", terms=_terms(4 * PHRASE_CEILING)), offset)


@pytest.mark.parametrize("n", [0, 1, PHRASE_CEILING])
def test_an_offset_past_the_last_phrase_is_refused_not_reported_as_no_terms(
    store: ProfileStore, n: int
) -> None:
    """F4: it would fall through to an unsteered "no terms are recorded" run."""
    with pytest.raises(ValueError):
        _run(store, Aim(state="stated", terms=_terms(n)), PHRASE_CEILING)


def test_unsearched_is_what_lies_past_the_window(store: ProfileStore) -> None:
    terms = _terms(2 * PHRASE_CEILING + 1)
    aim = Aim(state="stated", terms=terms)
    assert _run(store, aim).unsearched == terms[PHRASE_CEILING:]
    assert _run(store, aim, PHRASE_CEILING).unsearched == terms[2 * PHRASE_CEILING :]
    assert _run(store, aim, 2 * PHRASE_CEILING).unsearched == ()


@pytest.mark.parametrize("offset", [-1, -PHRASE_CEILING])
def test_a_negative_offset_is_refused_not_wrapped(store: ProfileStore, offset: int) -> None:
    """`terms[-6:0]` is empty and `terms[-1:]` is the last phrase: both silently wrong.
    A negative *multiple* of the ceiling is the case the modulo alone lets through."""
    with pytest.raises(ValueError):
        _run(store, Aim(state="stated", terms=_terms(3)), offset)


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


# --- T251: every term is searched, or named with the offset that searches it ---


def _recording(asked: list[str]):  # type: ignore[no-untyped-def]
    def fetch(request: object) -> Response:
        asked.append(request.url)  # type: ignore[attr-defined]
        return Response(None, "", error="no network in this test")

    return fetch


def _every(store: ProfileStore, aim: Aim, **kwargs):  # type: ignore[no-untyped-def]
    asked: list[str] = []
    run = source_every_phrase(
        store,
        _spain(),
        aim,
        fetch=_recording(asked),
        at=AT,
        directory=_CONNECTORS,
        robots=_allow(),
        **kwargs,
    )
    return run, asked


def _steerable_boards() -> list[str]:
    return [
        p.name
        for p in packages_for(_spain(), _CONNECTORS)
        if accepts_query(load_connector(_CONNECTORS / p.name))
        and not needs_browser(load_connector(_CONNECTORS / p.name))  # asked of the browser
    ]


@pytest.mark.parametrize("n", [m for m in _COUNTS if m])
def test_every_term_is_requested_from_every_board_that_takes_a_query(
    store: ProfileStore, n: int
) -> None:
    """The property itself: the requests that went out, not the run's own
    bookkeeping. One request per (steerable board, term), each built by the
    connector's own URL builder, so a term dropped from any board is missing."""
    boards = _steerable_boards()
    assert boards, "no steerable board is installed, so this proves nothing"
    aim = Aim(state="stated", terms=_terms(n))
    run, asked = _every(store, aim)
    for board in boards:
        connector = load_connector(_CONNECTORS / board)
        for term in aim.terms:
            wanted = {r.url for r in build_list_requests(connector, page_count=1, query=term)}
            assert wanted <= set(asked), (board, term)
    assert run.unsearched == () and run.next_offset is None
    assert load_aim(store) == aim  # the one writer still saved the whole aim, once


def test_a_single_window_still_names_the_offset_that_continues_it(store: ProfileStore) -> None:
    aim = Aim(state="stated", terms=_terms(2 * PHRASE_CEILING + 1))
    run = _run(store, aim)
    assert run.next_offset == PHRASE_CEILING
    assert f"offset={PHRASE_CEILING}" in run.summary()
    last = _run(store, aim, 2 * PHRASE_CEILING)
    assert last.next_offset is None and "NOT searched" not in last.summary()


def test_browser_boards_are_asked_for_every_term_too() -> None:
    aim = Aim(state="stated", terms=_terms(2 * PHRASE_CEILING + 1))
    urls = browser_urls_every_phrase(_spain(), aim, directory=_CONNECTORS, robots=_allow())
    if urls:  # no steerable browser board installed -> nothing to compare
        for term in aim.terms:
            assert any(term in u for u in urls), term
