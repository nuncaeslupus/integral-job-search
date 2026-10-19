"""T310 - a board's share of the offer ceiling is split into a fixed share per term.

Owner decision 2026-10-06: not round-robin. The rule, stated before the code:

* every term of the aim gets `term_share(share, terms)` on every board that takes a
  query, so a term searched later is never starved by an earlier one;
* what a term does not use is not lent to another term;
* a board's total stays within its share, and the boards' totals within the ceiling;
* a continuation (`source(offset=...)`) hands each of *its* terms its own share and
  never one that an earlier window spent.

Fixtures are built by the same World as `test_source_offer_ceiling`.
"""

from __future__ import annotations

import test_source_offer_ceiling as base
from test_source_offer_ceiling import (
    AT,
    IN_REACH,
    World,
    _added,
    _candidate,
    _terms,
    _walk,
)

from integral.candidate import Aim
from integral.identity import ProfileStore
from integral.robots import Robots
from integral.sourcing import (
    OFFER_CEILING,
    PHRASE_CEILING,
    board_share,
    source,
    term_share,
)

store = base.store  # the fixtures of the file whose World this reuses
world = base.world


def _added_for(run, board: str, term: str) -> int:  # type: ignore[no-untyped-def]
    return sum(o.added for o in run.outcomes if o.connector == f"{board}_en" and o.query == term)


def test_every_term_gets_its_share_on_a_flooding_board(store: ProfileStore, world: World) -> None:
    """The first term used to take the board's whole share (25) and the rest were
    "never searched for". Each of 5 terms now gets 25 // 5 = 5."""
    world.board("flood", lambda term: [IN_REACH] * 40)
    world.board("small", lambda term: [IN_REACH])
    terms = _terms(5)
    run = _walk(store, world, Aim(state="stated", terms=terms))
    per_term = term_share(board_share(2), len(terms))
    assert per_term == 5
    for term in terms:
        assert _added_for(run, "flood", term) == per_term, term
    assert {t for s, t in world.asked if s == "flood"} == set(terms)
    assert not any(terms_left for _, _, terms_left in run.capped.values())


def test_a_terms_leftover_is_not_taken_by_another_term(store: ProfileStore, world: World) -> None:
    """term0 finds 1 row of its 5; term1 finds 40. term1 still gets 5, not 5 + 4."""
    world.board("flood", lambda term: [IN_REACH] * (1 if term == "term0" else 40))
    world.board("small", lambda term: [IN_REACH])
    terms = _terms(5)
    run = _walk(store, world, Aim(state="stated", terms=terms))
    assert _added_for(run, "flood", "term0") == 1
    for term in terms[1:]:
        assert _added_for(run, "flood", term) == 5, term
    assert _added(run, "flood") == 1 + 4 * 5


def test_the_total_stays_within_the_boards_share_and_the_ceiling(
    store: ProfileStore, world: World
) -> None:
    for site in ("a", "b", "c"):
        world.board(f"{site}board", lambda term: [IN_REACH] * 40)
    terms = _terms(PHRASE_CEILING + 3)  # more terms than the 16 // 9 split can serve
    run = _walk(store, world, Aim(state="stated", terms=terms))
    share = board_share(3)
    for site in ("aboard", "bboard", "cboard"):
        assert _added(run, site) <= share, site
    assert run.added <= 3 * share <= OFFER_CEILING


def test_a_continuation_does_not_hand_a_board_a_fresh_share(
    store: ProfileStore, world: World
) -> None:
    """`source(offset=PHRASE_CEILING)` on its own: the terms it searches get exactly
    their per-term share of the *whole* aim, not the share of the six it was
    handed (which would be 25 // 6 = 4 instead of 25 // 8 = 3)."""
    world.board("flood", lambda term: [IN_REACH] * 40)
    world.board("small", lambda term: [IN_REACH])
    terms = _terms(PHRASE_CEILING + 2)
    run = source(
        store,
        _candidate(),
        Aim(state="stated", terms=terms),
        fetch=world.fetch,
        at=AT,
        directory=world.directory,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        offset=PHRASE_CEILING,
    )
    per_term = term_share(board_share(2), len(terms))
    assert per_term == 3
    for term in terms[PHRASE_CEILING:]:
        assert _added_for(run, "flood", term) == per_term, term
    assert _added(run, "flood") == per_term * 2


def test_no_requests_are_made_for_a_term_once_its_share_is_full(
    store: ProfileStore, world: World
) -> None:
    """Per-board version of `requests_after_the_ceiling`, at the default share:
    after a (board, term) has written its part, the pages left for that term are
    not requested."""
    world.board("flood", lambda term: [IN_REACH] * 25)  # one page fills 25
    world.board("small", lambda term: [IN_REACH])
    terms = _terms(5)
    run = _walk(store, world, Aim(state="stated", terms=terms), page_count=3)
    per_term = term_share(board_share(2), len(terms))
    flood_requests = [t for s, t in world.asked if s == "flood"]
    # a page of 25 rows overfills a term's 5 on the first request; no second page
    assert flood_requests == list(terms)
    assert all(_added_for(run, "flood", t) == per_term for t in terms)
