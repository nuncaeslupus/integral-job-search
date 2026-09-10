"""T126 — the step that actually fetches, and the record that proves it did.

The defect this closes: sourcing had two ends and no middle. `load_connectors`
was imported by nothing that touches a `ProfileStore`; `build_offer` was called
only from two gates; `collect_offer` only from step 5, which is *handed* its
offers; and `build_list_urls` had no production caller at all. There was no path
from `profile/constraints.json` to a live board to `profiles/<handle>/offers/`,
so a candidate's offers arrived because a session put them there by hand.

Nothing reported that, and the reason is worth keeping in view: step 7's
checkpoint asks whether offer *files exist*, not whether anything can produce
them. A step whose artefacts were placed by hand is indistinguishable, to that
check, from one whose implementation works — a coverage check satisfied by
artefacts nobody produced.

So this module records **how each offer arrived**, in `offers/_fetches.jsonl`,
and the gate counts the offers that cannot point at such a record. The existing
hand-placed ones fail it, which is the intended reading rather than an
inconvenience: they were never fetched by this tool and the number should say so.

Three things it refuses to blur, each of which a naive loop would:

* **Searched, versus handed everything.** A board with a `{query}` slot is asked
  the candidate's question; one without returns its whole list. Both are useful
  and they are not the same result, so `BoardOutcome.steered` records which.
* **Refused, versus empty.** `connector_health.rate_limited` decides this, and
  its asymmetry matters: a status decides on its own, body markers are consulted
  only when nothing parsed. A board that refused us is not a board with no jobs.
* **Untrusted, versus empty.** `collect_listing` reports a stale connector, and
  a stale connector's empty page is not evidence about the market.

The fetch itself is injected. Nothing here opens a socket, so the tests are real
tests rather than a recording of one afternoon's internet.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from integral.candidate import Aim, CandidateConstraints
from integral.candidate import Location as ConstraintLocation
from integral.connector_coverage import Package, installed_packages
from integral.connector_health import rate_limited
from integral.connectors import (
    Connector,
    ConnectorError,
    ListRequest,
    accepts_query,
    build_list_requests,
    build_list_urls,
    build_offer,
    client_headers,
    collect_listing,
    load_connector,
    parse_detail_page,
)
from integral.identity import ProfileStore
from integral.lifecycle import (
    collect_offer,
    save_lifecycle_offer,
    track_new_offer,
)
from integral.offers import Offer, compute_offer_id
from integral.robots import Robots, RobotsError

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTORS_DIR = _REPO_ROOT / "connectors"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T126.json"

#: Where a run records what it fetched. Inside the candidate's own tree, like
#: everything else about them — this is provenance about their offers, not a
#: log about the tool.
FETCH_LOG = "_fetches.jsonl"

#: A run that consulted fewer boards than this consulted nothing worth
#: reporting. Spain had six usable packages when this landed.
MINIMUM_BOARDS = 1

#: A run that collected no offers says nothing about how offers get recorded.
#: The committed captures yielded well above this when T126 landed.
MINIMUM_OFFERS_COLLECTED = 3

#: Detail pages fetched per board per run. A listing row that cannot complete an
#: offer sends us to the advert's own page, and a 40-row listing would otherwise
#: turn one listing request into 41. The cap is per board so one badly-shaped
#: connector cannot spend the whole run, and what it stopped is reported rather
#: than dropped silently — `BoardOutcome.detail_fetched` against
#: `detail_needed`.
DETAIL_FETCH_CEILING = 40

#: How many of the candidate's phrases one run may search for. Each phrase is
#: its own request to every steerable board, which is what searching several
#: phrases *means* — they cannot be ANDed into one query — so the fetch count
#: is phrases x boards x pages and this is what stops it running away. The
#: phrases beyond it are reported, never dropped silently: a run that quietly
#: searched four of nine looks exactly like a run that searched all nine.
PHRASE_CEILING = 6

#: New offers one run may write, across every board (T167). Step 7's stop rule:
#: *"a per-run offer ceiling, so one badly-scoped query cannot deliver four
#: hundred adverts nobody will read"*. The owner set 50 on 2026-09-10 — a first
#: setting, per spec-v2-steps' note on caps, not a finding. Past it no advert
#: page is opened, nothing is collected and no further board is asked, and all
#: three are reported.
OFFER_CEILING = 50

#: A package declaring this lists jobs wherever they are, so it serves no
#: country in particular — see `packages_for`.
GLOBAL = "GLOBAL"

#: The reach modes that make a worldwide board worth asking. A worldwide board's
#: jobs are elsewhere, so only a candidate who will work remotely can take them
#: without moving.
_WORLDWIDE_REACH = frozenset({"remote", "cross_border_remote_employer"})

_CEILING_SKIP = "the run reached its offer ceiling"


@dataclass(frozen=True)
class Response:
    """What a fetch came back with. `status` may be `None` for a transport error."""

    status: int | None
    body: str
    error: str | None = None


#: Injected so nothing here opens a socket. A caller supplies the real one.
Fetch = Callable[[ListRequest], Response]


@dataclass(frozen=True)
class BoardOutcome:
    """One board's contribution to a run, including the ways it contributed nothing.

    `items` is what parsed; `added` is what survived dedup and tombstones. They
    differ legitimately — a re-sighted ad is a real result that adds no offer —
    so reporting only one of them would describe a working run as a failed one,
    or the reverse.
    """

    connector: str
    url: str | None
    steered: bool
    #: The phrase this outcome is about, `None` on a board that does not
    #: search. A run holds one outcome per board **per phrase**, so without
    #: this the rows are indistinguishable and the log they produce cannot be
    #: read back per phrase — which is the whole of what `search_terms` reads.
    query: str | None = None
    status: int | None = None
    items: int = 0
    added: int = 0
    dropped: int = 0
    drop_reason: str | None = None
    stale: bool = False
    refused: str | None = None
    skipped: str | None = None
    error: str | None = None
    #: Rows the list page could not complete on its own, and detail fetches
    #: actually made for them. They differ when `DETAIL_FETCH_CEILING` or
    #: robots stopped one, which is a truncated pass and not an empty board.
    detail_needed: int = 0
    detail_fetched: int = 0
    #: T167. Rows an unsteered board returned that matched none of the
    #: candidate's phrases — filtered before any advert page was opened.
    off_aim: int = 0
    #: Rows that needed the advert page after `DETAIL_FETCH_CEILING` was spent.
    #: Not `dropped`: nothing is wrong with the advert, it was never opened.
    unopened: int = 0
    #: Matching rows left uncollected because the run reached `OFFER_CEILING`.
    over_ceiling: int = 0
    #: T144. On an ATS host each request is a different employer's board, so
    #: one employer's failure is that employer's, never the host's: the others
    #: are still read, and the failures are named here rather than ending the
    #: round with every counter lost.
    employers_failed: tuple[str, ...] = ()

    @property
    def reached_the_board(self) -> bool:
        return self.skipped is None and self.error is None


@dataclass
class Run:
    """A whole sourcing pass, reported rather than summed into one number."""

    outcomes: list[BoardOutcome] = field(default_factory=list)
    #: Phrases past `PHRASE_CEILING`, kept so the summary can say them. A run
    #: that searched six of nine and reported "6 boards searched" describes a
    #: partial pass as a whole one.
    unsearched: tuple[str, ...] = ()
    #: Worldwide boards left out because the candidate's reach does not include
    #: remote work, and why in the candidate's terms. Said, so a quiet run is
    #: not read as a quiet world.
    unreached: tuple[str, ...] = ()
    unreached_because: str = ""

    @property
    def searched(self) -> list[str]:
        """The phrases this run actually asked for, in order, without repeats.

        Only outcomes that reached a board count: one stopped by the ceiling or
        by robots carries its phrase and never sent it.
        """
        seen: list[str] = []
        for outcome in self.outcomes:
            if outcome.reached_the_board and outcome.query and outcome.query not in seen:
                seen.append(outcome.query)
        return seen

    @property
    def added(self) -> int:
        return sum(o.added for o in self.outcomes)

    def _boards(self, matching: Callable[[BoardOutcome], bool]) -> list[str]:
        """Board names, in order, without repeats.

        A steerable board now has one outcome **per phrase**, so a plain
        comprehension names it once per phrase — "searched: foorilla,
        foorilla, foorilla" for one board and three terms, which reads as
        three boards. Deduped here rather than at each call site so a fifth
        property added later cannot reintroduce it.
        """
        seen: list[str] = []
        for outcome in self.outcomes:
            if matching(outcome) and outcome.connector not in seen:
                seen.append(outcome.connector)
        return seen

    @property
    def steered(self) -> list[str]:
        """Boards asked the candidate's question."""
        return self._boards(lambda o: o.steered and o.reached_the_board)

    @property
    def unsteered(self) -> list[str]:
        """Boards that returned whatever they had. Not a failure — a different result."""
        return self._boards(lambda o: not o.steered and o.reached_the_board)

    @property
    def refused(self) -> list[str]:
        """Boards that refused the read. Never to be read as "no jobs there"."""
        return self._boards(lambda o: o.refused is not None)

    @property
    def untrusted(self) -> list[str]:
        """Boards whose connector is stale, so their emptiness proves nothing."""
        return self._boards(lambda o: o.stale)

    def summary(self) -> str:
        boards = len({o.connector for o in self.outcomes})
        lines = [f"{self.added} offer(s) added from {boards} board(s)"]
        if self.searched:
            lines.append(f"  searched, one phrase at a time: {', '.join(self.searched)}")
        if self.unsearched:
            lines.append(
                f"  NOT searched this run (over the {PHRASE_CEILING}-phrase ceiling): "
                f"{', '.join(self.unsearched)}"
            )
        if self.steered:
            lines.append(f"  searched for your terms: {', '.join(self.steered)}")
        if self.unsteered:
            lines.append(f"  returned their whole list: {', '.join(self.unsteered)}")
        if self.unreached:
            lines.append(
                f"  NOT asked — worldwide boards, {self.unreached_because}: "
                f"{', '.join(self.unreached)}"
            )
        if self.added >= OFFER_CEILING:
            # Printed on the total, not only on the rows it cut: a ceiling that
            # fills exactly at a page's end stops the next page and leaves no
            # row over it, and that run must not read as a complete pass.
            lines.append(
                f"  STOPPED at the {OFFER_CEILING}-offer ceiling — any rows, pages or "
                "boards after it were not read"
            )
        ceilinged = [
            f"{o.connector} ({o.query})" if o.query else o.connector
            for o in self.outcomes
            if o.skipped == _CEILING_SKIP
        ]
        if ceilinged:
            lines.append(f"  NOT asked, after the ceiling: {', '.join(ceilinged)}")
        for outcome in self.outcomes:
            if outcome.off_aim:
                lines.append(
                    f"  FILTERED {outcome.connector}: {outcome.off_aim} of {outcome.items} "
                    "row(s) matched none of your phrases"
                )
            if outcome.unopened:
                lines.append(
                    f"  UNOPENED {outcome.connector}: {outcome.unopened} row(s) needed the "
                    f"advert's page after the {DETAIL_FETCH_CEILING}-page budget was spent"
                )
            if outcome.over_ceiling:
                lines.append(
                    f"  CEILING  {outcome.connector}: {outcome.over_ceiling} matching row(s) "
                    f"not collected — {_CEILING_SKIP}"
                )
            if outcome.skipped == _CEILING_SKIP:
                continue
            if outcome.refused:
                lines.append(f"  REFUSED {outcome.connector}: {outcome.refused}")
            elif outcome.stale:
                lines.append(f"  STALE   {outcome.connector}: its emptiness proves nothing")
            elif outcome.dropped:
                lines.append(
                    f"  DROPPED {outcome.connector}: {outcome.dropped} of {outcome.items} "
                    f"row(s) were not offers — {outcome.drop_reason}"
                )
            elif outcome.skipped:
                lines.append(f"  skipped {outcome.connector}: {outcome.skipped}")
            elif outcome.error:
                lines.append(f"  ERROR   {outcome.connector}: {outcome.error}")
            if outcome.employers_failed and not outcome.error:
                lines.append(
                    f"  PARTIAL {outcome.connector}: {len(outcome.employers_failed)} employer "
                    f"board(s) not read — {', '.join(outcome.employers_failed)}"
                )
        return "\n".join(lines)


def packages_for(constraints: CandidateConstraints, directory: Path | None = None) -> list[Package]:
    """The usable packages serving this candidate's country.

    Reads `location.country` only when the field is `stated`. An `unknown`
    location must not silently select every board on the shelf: sourcing the
    whole world for somebody who has not said where they are is not a generous
    default, it is a search nobody asked for.

    A `GLOBAL` package is added, after the country's own, only when `reaches_
    worldwide` says so (T167). Before that a candidate country could never equal
    `GLOBAL`, so no worldwide board was ever asked. They come last so the
    candidate's own market spends `OFFER_CEILING` first.
    """
    packages = installed_packages(directory or DEFAULT_CONNECTORS_DIR)
    location = constraints.location
    if location.state != "stated" or not location.country:
        return []
    wanted = location.country.strip().upper()
    domestic = [p for p in packages if p.usable and p.country == wanted]
    if not reaches_worldwide(constraints):
        return domestic
    return domestic + [p for p in packages if p.usable and p.country == GLOBAL]


def reaches_worldwide(constraints: CandidateConstraints) -> bool:
    """Whether the candidate's stated reach includes remote work.

    Unknown or declined reach does not: step 7 says *"an unanswered mobility
    question leaves the reach at its current setting and searches accordingly"*,
    and the setting nobody chose is the narrow one.
    """
    reach = constraints.reach
    return reach.state == "stated" and not _WORLDWIDE_REACH.isdisjoint(reach.modes)


def _why_not_worldwide(constraints: CandidateConstraints) -> str:
    """Why worldwide boards were left out, without claiming an answer nobody gave.

    "Does not include remote work" is true only of a stated reach. An unknown
    one is step 7's own conversational duty — establish how far the search can
    travel — so it says the question is open.
    """
    state = constraints.reach.state
    if state == "unknown":
        return "since you have not said whether you would work remotely"
    if state == "declined":
        return "since you preferred not to say whether you would work remotely"
    return "since your reach does not include remote work"


def _words(text: str) -> set[str]:
    """Casefolded, NFKD-folded words (NFKD, not NFD: it is what turns Catalan
    `ŀ` into `l·` and fullwidth letters into ASCII).

    A `+`/`#` run stays on its word unless a **letter** follows — `c++`, `c#`,
    and `C++17` is `c++, 17` — so `I+D+i` is `i, d, i` and `Python+Django` is
    two words, exactly as `R&D&I` already was. Edge: `Python+3` is `python+`.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return set(re.findall(r"\w+(?:[+#]++(?![^\W\d_]))?", bare))


def matches_aim(item: dict[str, str], phrases: Sequence[str]) -> bool:
    """Whether a listing row matches any of the candidate's phrases (T167).

    A phrase matches when **every** word of it is a whole word of the row's
    `title` plus any list-row `text`, in any order — the AND a board applies to
    a query, so an unsteered board is narrowed the way a steered one narrows
    itself. `Aim`'s objection to a title filter is to a *silent* one; the rows
    this removes are counted in `BoardOutcome.off_aim` and printed.

    ponytail: whole words only, so "developers" does not match "developer" and
    "ingeniera" does not match "ingeniero"; stemming per language if that loses
    real adverts. A phrase with no words matches nothing, never everything.

    ponytail: a leading `.` is not part of a word, so ".net developer" also
    matches "net salary ... developer tools". Kept deliberately: boards write
    `.NET` as `NET` too (infojobs_es's capture: "Arquitecto NET"), and the
    stricter rule would lose those adverts to save a row the ceiling bounds.
    """
    have = _words(" ".join(item.get(key) or "" for key in ("title", "text")))
    return any((need := _words(phrase)) and need <= have for phrase in phrases)


#: `time.sleep`, named so a test can replace it rather than wait.
_pause = time.sleep


def _connector_of(package: Package, directory: Path) -> Connector:
    return load_connector(directory / package.name)


def source(
    store: ProfileStore,
    constraints: CandidateConstraints,
    aim: Aim,
    *,
    fetch: Fetch,
    at: str,
    directory: Path | None = None,
    page_count: int = 1,
    robots: Robots | None = None,
) -> Run:
    """Fetch this candidate's country's boards and collect what they return.

    `robots` is injectable and defaults to a real adjudicator, so the honest
    thing happens without the caller remembering to ask for it. A test that
    wants no network passes one whose fetcher is a fixture — never `None` to
    mean "skip the check", which would make the safe path the one you have to
    opt into.
    """
    from integral.search_terms import save_aim  # circular at module scope

    directory = directory or DEFAULT_CONNECTORS_DIR
    adjudicator = Robots() if robots is None else robots
    # Recorded by the act of searching, not by a caller remembering to.
    # The phrases used to survive a session only as an evidence row, so the
    # next session did not know what had worked — and a persistence step that
    # has to be called separately is one that is skipped exactly when the
    # session ends badly, which is when it was most needed.
    if aim.terms:
        save_aim(store, aim)
    run = Run(unsearched=aim.terms[PHRASE_CEILING:])
    if not reaches_worldwide(constraints):
        run.unreached = tuple(
            p.name for p in installed_packages(directory) if p.usable and p.country == GLOBAL
        )
        run.unreached_because = _why_not_worldwide(constraints)
    phrases = aim.terms[:PHRASE_CEILING]
    for package in packages_for(constraints, directory):
        # A board that does not search returns the same list whatever was
        # asked, so asking it once per phrase is N identical requests for one
        # answer. Deciding here rather than inside `_one_board` is what makes
        # that visible; the load failure is still reported there, once, in the
        # one place that already knows how to phrase it.
        try:
            steerable = accepts_query(_connector_of(package, directory))
        except (ConnectorError, OSError):
            steerable = False
        queries: tuple[str | None, ...] = phrases if steerable and phrases else (None,)
        for query in queries:
            room = OFFER_CEILING - run.added
            if room <= 0:
                run.outcomes.append(
                    BoardOutcome(package.name, None, steerable, query, skipped=_CEILING_SKIP)
                )
                continue
            run.outcomes.append(
                _one_board(
                    store,
                    package,
                    query,
                    fetch=fetch,
                    at=at,
                    directory=directory,
                    page_count=page_count,
                    robots=adjudicator,
                    phrases=phrases,
                    room=room,
                )
            )
    return run


def _absolute(url: str | None, against: str) -> str | None:
    """A row's `detail_url` as something fetchable.

    Boards write it both ways — `builtin_en` yields `/job/<slug>`, others a full
    URL — and a relative one is not fetchable and is not a usable `Offer.url`
    either. `urljoin` leaves an absolute URL untouched, so this is safe on both.
    """
    if not url:
        return None
    return urljoin(against, url)


def _may_fetch(robots: Robots, url: str) -> bool:
    """Robots, adjudicated for a detail page exactly as for a list page.

    A `robots.txt` that cannot be read is a refusal, not a permission — the same
    direction `_one_board` takes for the listing, and for the same reason.
    """
    try:
        return robots.allows(url)
    except (RobotsError, OSError):
        return False


def _detail_record(connector: Connector, url: str, *, fetch: Fetch) -> dict[str, str] | None:
    """The advert's own page, parsed for whatever `connector.detail` names.

    `ListRequest` is the shape `Fetch` takes; a detail page is a plain GET, so
    it is built here rather than given a second request type nothing else needs.

    **The detail page gets its own client's headers** (T133), derived from
    `connector.detail` rather than from the listing: a board serving both
    behind htmx targets different elements for each, and foorilla.com does
    exactly that — `mc_1` for the list, `mc_2` for the advert. Sending none was
    silent in the worst way: the fetch answered 200 with the site's shell, the
    detail selectors matched nothing, and 40 adverts were dropped for "no text"
    over a board that had returned all 50 rows.
    """
    detail = connector.detail
    headers = client_headers(detail.client, detail.client_target) if detail else {}
    response = fetch(ListRequest(url=url, method="GET", headers=headers, body=None))
    if response.error is not None or response.status != 200:
        return None
    try:
        return parse_detail_page(connector, response.body)
    except ConnectorError:
        return None


def _one_board(
    store: ProfileStore,
    package: Package,
    query: str | None,
    *,
    fetch: Fetch,
    at: str,
    directory: Path,
    page_count: int,
    robots: Robots,
    phrases: Sequence[str] = (),
    room: int = OFFER_CEILING,
) -> BoardOutcome:
    """One board, asked `query` if it searches, else narrowed to `phrases`.

    `room` is how many new offers the run may still write (`OFFER_CEILING`).
    """
    try:
        connector = _connector_of(package, directory)
    except (ConnectorError, OSError) as exc:
        return BoardOutcome(
            package.name, None, False, query, error=f"the package would not load: {exc}"
        )

    steerable = accepts_query(connector)
    if (steerable and not query) or (not steerable and not phrases):
        # `build_list_urls` would refuse a steerable one, and rightly. An
        # unsteered one would hand over its whole list for a search nobody
        # stated (T167). Reported rather than raised: one un-aimed board must
        # not end a run over five others.
        return BoardOutcome(
            package.name,
            None,
            steerable,
            query,
            skipped="no terms are recorded — say what you are looking for",
        )
    try:
        requests = build_list_requests(connector, page_count=page_count, query=query)
    except ConnectorError as exc:
        return BoardOutcome(package.name, None, steerable, query, error=str(exc))

    items_seen = 0
    added = 0
    dropped = 0
    detail_needed = 0
    detail_fetched = 0
    off_aim = 0
    unopened = 0
    over_ceiling = 0
    drop_reason: str | None = None
    stale = False
    failed: list[str] = []
    last: Response | None = None

    def ended(
        url: str | None,
        status: int | None = None,
        *,
        skipped: str | None = None,
        error: str | None = None,
        refused: str | None = None,
    ) -> BoardOutcome:
        # A round that stops part-way still says what it read before stopping
        # (#445 round 2, N3): a 429 on employer 3 used to report "0 added"
        # over the offers employers 1 and 2 had already put in the store.
        return BoardOutcome(
            package.name,
            url,
            steerable,
            query,
            status,
            items=items_seen,
            added=added,
            dropped=dropped,
            drop_reason=drop_reason,
            stale=stale,
            detail_needed=detail_needed,
            detail_fetched=detail_fetched,
            off_aim=off_aim,
            unopened=unopened,
            over_ceiling=over_ceiling,
            employers_failed=tuple(failed),
            skipped=skipped,
            error=error,
            refused=refused,
        )

    for index, request in enumerate(requests):
        if added >= room:
            break
        # Adjudicated per URL, before the request is made. A board that
        # disallows one path may allow another, so this cannot be hoisted to
        # the board — and a robots.txt that cannot be read is a refusal, not a
        # permission: failing open here would fetch exactly the paths nobody
        # could confirm we may.
        #
        # A disallowed path is that path's answer, so on an ATS host it is one
        # employer's, and the next is still asked. An **unreadable** robots.txt
        # is the whole origin's (RFC 9309 §2.3.1.4), and every employer shares
        # the origin — the slot is confined to the path — so it ends the board.
        try:
            if not robots.allows(request.url):
                if request.employer:
                    failed.append(f"{request.employer} (robots.txt disallows it)")
                    continue
                return ended(request.url, skipped=f"robots.txt disallows {request.url}")
        except (RobotsError, OSError) as exc:
            return ended(
                request.url,
                skipped=f"robots.txt could not be read, so the path is not permitted: {exc}",
            )
        if index:
            # The site's own Crawl-delay between one board's requests. Moot
            # while a board was one page per run; an ATS host is dozens (T144).
            _pause(robots.delay(request.url, 0.0))
        response = fetch(request)
        last = response
        blocked = rate_limited(None, response.status) if response.error is not None else None
        if blocked is not None:
            # The host refused the read — a 429 on one employer is not leave
            # to ask for the next (#445 round 2, B2). Checked before the
            # per-employer `continue` below, which it used to follow.
            return ended(request.url, response.status, refused=blocked)
        if response.error is not None and request.employer:
            failed.append(f"{request.employer} ({response.error})")
            _record_fetch(
                store,
                connector=package.name,
                url=request.url,
                status=response.status,
                items=0,
                steered=steerable,
                query=query,
                at=at,
                offer_ids=[],
            )
            continue
        if response.error is not None:
            return ended(request.url, response.status, error=response.error)
        result = collect_listing(connector, response.body)
        stale = stale or result.stale
        refusal = rate_limited(response.body, response.status, parsed_items=len(result.items))
        if refusal is not None:
            return ended(request.url, response.status, refused=refusal)
        items_seen += len(result.items)
        collected: list[str] = []
        for item in result.items:
            if not steerable and not matches_aim(item, phrases):
                off_aim += 1
                continue
            if added >= room:
                over_ceiling += 1
                continue
            if request.employer and not item.get("company"):
                # T144: an ATS posting rarely names its employer — the board is
                # the employer's — so the name comes from the list that chose it.
                item = {**item, "company": request.employer}
            detail_url = _absolute(item.get("detail_url"), request.url)
            offer, why = _offer_from(connector, item, url=detail_url)
            if offer is None and connector.detail is not None and detail_url:
                # The list row cannot complete an offer and the connector says
                # the rest of the advert is on its own page. Six installed
                # connectors declare `text` only under `detail:` — correctly,
                # since their list rows carry no teaser — and every one of them
                # produced zero offers for as long as nothing fetched it.
                detail_needed += 1
                if detail_fetched >= DETAIL_FETCH_CEILING:
                    # A budget stop, not a connector that produced no text
                    # (#445 round 2 N5, T167): counted apart from `dropped`.
                    unopened += 1
                    continue
                if _may_fetch(robots, detail_url):
                    _pause(robots.delay(detail_url, 0.0))
                    detail_fetched += 1
                    fields = _detail_record(connector, detail_url, fetch=fetch)
                    if fields:
                        offer, why = _offer_from(connector, item, fields, url=detail_url)
            if offer is None:
                dropped += 1
                drop_reason = drop_reason or why
                continue
            collected.append(offer.id)
            outcome = collect_offer(store, offer, at=at)
            if outcome.added_as_new:
                added += 1
        _record_fetch(
            store,
            connector=package.name,
            url=request.url,
            status=response.status,
            items=len(result.items),
            steered=steerable,
            query=query,
            at=at,
            offer_ids=collected,
        )
    return ended(
        requests[-1].url if requests else None,
        last.status if last else None,
        error=(
            f"every employer board failed: {', '.join(failed)}"
            if failed and len(failed) == len(requests)
            else None
        ),
    )


def _offer_from(
    connector: Connector,
    item: dict[str, str],
    detail_fields: dict[str, str] | None = None,
    url: str | None = None,
) -> tuple[Any, str | None]:
    """One parsed row as an `Offer`, or `(None, why)` when it cannot be one.

    A row the schema refuses is dropped rather than raised: one malformed card
    on page one must not discard the other twenty-nine. But the **reason** comes
    back with it, because a count alone is a symptom. Measured live on
    2026-09-05, `getmanfred_es` parsed 22 rows and produced 0 offers; "22 items,
    0 added" leaves the next reader guessing, and the exception says exactly
    which field the board stopped supplying.
    """
    try:
        return (
            build_offer(
                connector,
                list_fields=item,
                detail_fields=detail_fields,
                url=url or item.get("detail_url"),
            ),
            None,
        )
    except (ConnectorError, ValueError) as exc:
        return None, str(exc).splitlines()[0][:160]


def _record_fetch(
    store: ProfileStore,
    *,
    connector: str,
    url: str,
    status: int | None,
    items: int,
    steered: bool,
    query: str | None,
    at: str,
    offer_ids: Sequence[str],
) -> None:
    """Write one row of provenance: this request, and what it produced.

    The gate below reads these. An offer that matches no row was not fetched by
    this tool, whatever else is true of it.
    """
    store.append_jsonl(
        {
            "connector": connector,
            "url": url,
            "status": status,
            "items": items,
            "steered": steered,
            "query": query,
            "at": at,
            "offer_ids": list(offer_ids),
        },
        "offers",
        FETCH_LOG,
    )


def recorded_offer_ids(store: ProfileStore) -> set[str]:
    """Every offer id any recorded fetch claims to have produced."""
    if not store.exists("offers", FETCH_LOG):
        return set()
    ids: set[str] = set()
    for row in store.read_jsonl("offers", FETCH_LOG):
        if isinstance(row, dict):
            ids.update(str(i) for i in row.get("offer_ids", ()))
    return ids


def offers_without_a_recorded_fetch(store: ProfileStore) -> list[str]:
    """Offers in the tree that no fetch record accounts for."""
    recorded = recorded_offer_ids(store)
    present = {
        path.stem
        for path in (Path(store.path("offers")).glob("*.json"))
        if not path.name.startswith("_")
    }
    return sorted(present - recorded)


def measure(stores: Iterable[ProfileStore]) -> dict[str, Any]:
    """T126's gate reading over whatever candidate trees are supplied."""
    stores = list(stores)
    unrecorded: list[str] = []
    evaluated = 0
    for store in stores:
        present = [
            path.stem
            for path in Path(store.path("offers")).glob("*.json")
            if not path.name.startswith("_")
        ]
        evaluated += len(present)
        unrecorded += [f"{store.handle}:{oid}" for oid in offers_without_a_recorded_fetch(store)]
    return {
        "sourced_offers_without_a_recorded_fetch": len(unrecorded),
        "sourced_offers_evaluated": evaluated,
        "profiles_scanned": len(stores),
        "gate_status": "measured" if stores else "unmeasured",
        "unrecorded": unrecorded[:50],
    }


# ---------------------------------------------------------------------------
# the gate — a constructed run, and the control that proves the number moves


def measure_fixture() -> dict[str, Any]:
    """Run the whole driver over the committed example package and measure it.

    Deliberately a **constructed** run rather than whatever is in the
    developer's own profile tree: a gate whose number depends on one laptop's
    private data is not a gate anyone else can reproduce, and this repo's
    candidate data is outside the clone by design.

    Two readings, because the first alone is satisfiable by a metric that
    counts nothing:

    * a driven run records every offer it collected — 0 unrecorded;
    * an offer written straight into the tree, the way every existing offer
      arrived, is **found** — 1 unrecorded. Without this the gate would pass
      just as happily over an `offers_without_a_recorded_fetch` that always
      returns the empty list.
    """
    import tempfile
    from urllib.parse import urlsplit

    from integral.identity import create_profile

    constraints = CandidateConstraints(
        location=ConstraintLocation(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        )
    )
    # Three phrases, because an unsteered board keeps only rows matching one
    # (T167) and no unsteered Spanish capture carries a Python row: with
    # "python" alone no advert page would be needed, and the run would fall to
    # the vacuous branch below.
    aim = Aim(state="stated", terms=("python", "developer", "engineer"))

    # Each board answers with **its own** committed capture, matched by host.
    # Handing one package's markup to another's selectors would parse nothing
    # and the run would report a clean zero over six boards that produced no
    # offers — the exact vacuous pass this gate is built to refuse.
    by_host: dict[str, str] = {}
    detail_by_host: dict[str, str] = {}
    list_paths: set[str] = set()
    for package in packages_for(constraints, DEFAULT_CONNECTORS_DIR):
        capture = DEFAULT_CONNECTORS_DIR / package.name / "fixture" / "list.html"
        if capture.is_file() and package.site:
            by_host[package.site] = capture.read_text(encoding="utf-8")
        advert = DEFAULT_CONNECTORS_DIR / package.name / "fixture" / "detail.html"
        if advert.is_file() and package.site:
            detail_by_host[package.site] = advert.read_text(encoding="utf-8")
        # Which paths are listings, so the answerer can tell the two apart. A
        # board's adverts live on its own host, so the host alone cannot.
        connector = _connector_of(package, DEFAULT_CONNECTORS_DIR)
        for phrase in aim.terms:
            for url in build_list_urls(connector, query=phrase):
                list_paths.add(urlsplit(url).path)

    def answer(request: ListRequest) -> Response:
        host = (urlsplit(request.url).hostname or "").removeprefix("www.")
        served = by_host if urlsplit(request.url).path in list_paths else detail_by_host
        for site, html in served.items():
            if host == site.removeprefix("www."):
                return Response(200, html)
        return Response(404, "", error=f"no committed capture for {host}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
        store = ProfileStore(root, "fixture")

        # A robots adjudicator whose fetcher is a constant: the fixture must not
        # reach the network, and "allow everything" is the right answer for a
        # capture that was already lawfully made. What robots *does* is
        # exercised by `tests/test_sourcing.py`, not smuggled through here.
        run = source(
            store,
            constraints,
            aim,
            fetch=answer,
            at="2026-01-01T00:00:00+00:00",
            directory=DEFAULT_CONNECTORS_DIR,
            robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        )
        driven = offers_without_a_recorded_fetch(store)
        collected = len(
            [
                path
                for path in Path(store.path("offers")).glob("*.json")
                if not path.name.startswith("_")
            ]
        )

        # The control: an offer placed the way every existing one was placed.
        planted = Offer(
            id=compute_offer_id("planted by hand, never fetched"),
            source="by-hand",
            text="planted by hand, never fetched",
        )
        save_lifecycle_offer(
            store, planted, track_new_offer(planted, at="2026-01-01T00:00:00+00:00")
        )
        detected = len(offers_without_a_recorded_fetch(store)) - len(driven)

        starved = [
            outcome.connector
            for outcome in run.outcomes
            if outcome.items and not outcome.added and outcome.detail_needed
        ]

        measured: dict[str, Any] = {
            "sourced_offers_without_a_recorded_fetch": len(driven),
            "sourced_offers_evaluated": collected,
            "boards_consulted": len(run.outcomes),
            "boards_with_a_committed_capture": len(by_host),
            "boards_steered": len(run.steered),
            # T130. A board whose list page parsed rows and yielded no offer,
            # while its connector declares a detail page carrying the rest, is
            # a board the engine starved rather than one the market emptied.
            # Six installed connectors were in that state until the detail
            # fetch existed; the count is the gate.
            "boards_starved_by_a_missing_detail_fetch": len(starved),
            "boards_needing_the_advert_page": sum(1 for o in run.outcomes if o.detail_needed),
            "unrecorded_offers_detected_by_the_control": detected,
            "gate_status": "measured",
        }
        if collected < MINIMUM_OFFERS_COLLECTED:
            measured["gate_status"] = "unmeasured"
            measured["reasons"] = [
                f"only {collected} offer(s) collected (floor {MINIMUM_OFFERS_COLLECTED}) — "
                "a run that collected nothing proves nothing about how offers are recorded"
            ]
        elif not measured["boards_needing_the_advert_page"]:
            # A zero over a run where no board ever needed the advert page is
            # the vacuous pass this key exists to refuse: it would read clean
            # with the detail fetch deleted. T127 met the same shape from the
            # other side — a rot check whose two sides carried the same offers.
            measured["gate_status"] = "unmeasured"
            measured["reasons"] = [
                "no board's listing needed the advert page, so a zero starved "
                "count says nothing about whether the advert page is fetched"
            ]
        elif detected != 1:
            measured["gate_status"] = "unmeasured"
            measured["reasons"] = [
                "the control offer was not detected — `offers_without_a_recorded_fetch` "
                "is not measuring anything"
            ]
        return measured


FLOOD_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T167.json"

#: The constructed flood (T167): worldwide boards of two pages. A page's rows
#: run in a cycle of four: two match `_FLOOD_TERMS[0]` and two are near misses
#: carrying exactly one of its words — off-aim by "every word", and invisible to
#: a filter that only ever met rows sharing none.
_FLOOD_PAGES = 2
_FLOOD_PAGE_ROWS = 120
_FLOOD_KINDS = (
    ("Senior Python Engineer", True),
    ("Python Developer", False),
    ("Engineer, Python platform", True),
    ("Sales Engineer", False),
)
#: The second is a phrase with no words, as a candidate may type one. It must
#: match nothing; a matcher for which it matches everything floods the tree.
_FLOOD_TERMS = ("python engineer", "—")

#: The gate's layout, in the order the boards are selected. 60-row pages carry
#: 30 matches each, so: deluge's page one writes 30; its page two **fails**
#: after offers are already on disk (round 2's N1 — a lost count hands the
#: next board the whole ceiling again); flood's page one fills the ceiling
#: part-way; flood's page two and all of torrent come after it. The per-run
#: count, the failed page, the page stop and the board stop are all inside.
_FLOOD_BOARDS = ("deluge", "flood", "torrent")
_FLOOD_GATE_ROWS = 60
_FLOOD_FAILING = "https://deluge.integral.local/jobs?page=2"

_FLOOD_CONNECTOR = """\
site: SITE
locale: en
version: "1.0.0"
last_verified: "2026-09-10"
auth: none
list:
  url_pattern: "https://SITE.integral.local/jobs?page={page}"
  pagination:
    mode: query_param
    param: page
    start: 1
    max_pages: 2
  item: ".job"
  fields:
    detail_url:
      css: "a"
      attr: href
    title:
      css: ".title"
    company:
      css: ".company"
    text:
      css: ".text"
"""


@dataclass(frozen=True)
class FloodPage:
    """One served page, and which of its advert texts match by construction."""

    html: str
    matching: frozenset[str]
    off_aim: frozenset[str]


def flood_board(
    directory: Path, site: str = "flood", rows: int = _FLOOD_PAGE_ROWS
) -> dict[str, FloodPage]:
    """Install one worldwide board under `directory`; return its pages by URL.

    The labels come from construction, never from `matches_aim` — a gate that
    asked the matcher which rows were off-aim would certify the matcher by its
    own answer.
    """
    package = directory / f"{site}_en"
    package.mkdir(parents=True)
    (package / "connector.yaml").write_text(
        _FLOOD_CONNECTOR.replace("SITE", site), encoding="utf-8"
    )
    (package / "meta.yaml").write_text(
        f"site: {site}.integral.local\ncountry: {GLOBAL}\nlanguage: en\n", encoding="utf-8"
    )
    pages: dict[str, FloodPage] = {}
    for number in range(1, _FLOOD_PAGES + 1):
        matching: set[str] = set()
        off_aim: set[str] = set()
        cards = []
        for i in range(rows):
            kind, hit = _FLOOD_KINDS[i % len(_FLOOD_KINDS)]
            title = f"{kind} {site}-{number}-{i}"
            text = f"Advert {site}-{number}-{i}: {title}, fully remote."
            (matching if hit else off_aim).add(text)
            cards.append(
                f'<div class="job"><a href="/jobs/{number}-{i}">{title}</a>'
                f'<span class="title">{title}</span><span class="company">Employer {i}</span>'
                f'<span class="text">{text}</span></div>'
            )
        url = f"https://{site}.integral.local/jobs?page={number}"
        pages[url] = FloodPage(
            "<html><body>" + "".join(cards) + "</body></html>",
            frozenset(matching),
            frozenset(off_aim),
        )
    return pages


def measure_flood() -> dict[str, Any]:
    """T167's gate: worldwide boards that return far more than was asked for.

    A remote-reaching candidate searches three two-page boards laid out as
    `_FLOOD_BOARDS` describes. Every component is something the ceiling or the
    filter was built to refuse, read off the run's **effects** — what reached
    disk, which requests went out, which rows were served — never off its
    report alone:

    * an off-aim row written as an offer;
    * an offer written past `OFFER_CEILING` (whose value is also recorded, so
      raising it moves committed evidence rather than passing quietly), or a
      reported `added` that disagrees with what is on disk;
    * a request made once the ceiling's offers were on disk — the next page,
      the next board, an advert page;
    * a board reported as asked that was sent no request;
    * served rows the outcomes do not report, an outcome whose parts do not sum
      to its rows, or an off-aim count that disagrees with the off-aim rows
      actually served;
    * a worldwide board selected for the same candidate with an unknown reach.

    `unmeasured` unless the run itself reached the ceiling, cut rows at it and
    met the failing page — a zero over a run that never got there says nothing.
    """
    import tempfile
    from urllib.parse import urlsplit

    from integral.candidate import Reach
    from integral.identity import create_profile
    from integral.offers import load_offer

    location = ConstraintLocation(state="stated", country="ES", accepts_onsite_in_country=True)
    remote = CandidateConstraints(location=location, reach=Reach(state="stated", modes=("remote",)))
    unknown = CandidateConstraints(location=location)
    aim = Aim(state="stated", terms=_FLOOD_TERMS)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        directory = root / "connectors"
        pages: dict[str, FloodPage] = {}
        for site in _FLOOD_BOARDS:
            pages |= flood_board(directory, site, _FLOOD_GATE_ROWS)
        create_profile(root, "Fixture", handle="fixture", language="en", fiction=True)
        store = ProfileStore(root, "fixture")
        offers_dir = Path(store.path("offers"))

        def on_disk() -> list[Path]:
            return [p for p in offers_dir.glob("*.json") if not p.name.startswith("_")]

        served: list[str] = []
        late: list[str] = []

        def fetch(request: ListRequest) -> Response:
            if len(on_disk()) >= OFFER_CEILING:
                late.append(request.url)
            served.append(request.url)
            page = pages.get(request.url)
            if request.url == _FLOOD_FAILING or page is None:
                return Response(None, "", error="timed out")
            return Response(200, page.html)

        run = source(
            store,
            remote,
            aim,
            fetch=fetch,
            at="2026-01-01T00:00:00+00:00",
            directory=directory,
            page_count=_FLOOD_PAGES,
            robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        )
        written = [load_offer(store, path.stem).text for path in on_disk()]
        selected_without_reach = [p.name for p in packages_for(unknown, directory)]

    off_aim = frozenset().union(*(page.off_aim for page in pages.values()))
    asked = {f"{(urlsplit(url).hostname or '').split('.')[0]}_en" for url in served}
    answered = [pages[url] for url in served if url in pages and url != _FLOOD_FAILING]
    components = {
        "offers_written_off_aim": sum(1 for text in written if text in off_aim),
        "offers_written_past_the_ceiling": max(0, len(written) - OFFER_CEILING),
        "offers_on_disk_differ_from_run_added": abs(len(written) - run.added),
        "requests_after_the_ceiling": len(late),
        "boards_reported_asked_without_a_request": len(
            {o.connector for o in run.outcomes if o.reached_the_board} - asked
        ),
        "rows_served_not_reported": abs(
            sum(o.items for o in run.outcomes)
            - sum(len(page.matching) + len(page.off_aim) for page in answered)
        ),
        "rows_not_accounted_for": sum(
            abs(o.items - (o.off_aim + o.over_ceiling + o.unopened + o.dropped + o.added))
            for o in run.outcomes
        ),
        "off_aim_rows_misreported": abs(
            sum(o.off_aim for o in run.outcomes) - sum(len(page.off_aim) for page in answered)
        ),
        "worldwide_boards_selected_without_remote_reach": len(selected_without_reach),
    }
    measured: dict[str, Any] = {
        "flood_violations": sum(components.values()),
        **components,
        "offer_ceiling": OFFER_CEILING,
        "boards_installed": len(_FLOOD_BOARDS),
        "pages_per_board": _FLOOD_PAGES,
        "requests_made": len(served),
        "rows_served": sum(o.items for o in run.outcomes),
        "offers_written": len(written),
        "rows_reported_off_aim": sum(o.off_aim for o in run.outcomes),
        "rows_reported_over_the_ceiling": sum(o.over_ceiling for o in run.outcomes),
        "gate_status": "measured",
    }
    # Only a clean zero can be vacuous. A violation is a finding whatever else
    # the run failed to reach, and must never be downgraded to "unmeasured".
    if not measured["flood_violations"] and (
        len(written) != OFFER_CEILING
        or not measured["rows_reported_over_the_ceiling"]
        or _FLOOD_FAILING not in served
    ):
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            "the run did not fill the ceiling, cut rows at it and meet the failing page — "
            "a zero over it says nothing about the per-run count, the page or board stop"
        ]
    return measured


def _write(path: Path, measured: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(measured, ensure_ascii=False))
    for reason in measured.get("reasons", ()):
        print(reason, file=sys.stderr)


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.sourcing` — T126's evidence over the fixture run, and
    T167's over the flood."""
    measured = measure_fixture()
    flood = measure_flood()
    _write(DEFAULT_EVIDENCE_PATH, measured)
    _write(FLOOD_EVIDENCE_PATH, flood)
    if "unmeasured" in (measured["gate_status"], flood["gate_status"]):
        return 3
    return (
        1 if measured["sourced_offers_without_a_recorded_fetch"] or flood["flood_violations"] else 0
    )


if __name__ == "__main__":
    raise SystemExit(_main())
