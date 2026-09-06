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
import sys
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
#: than dropped silently — `BoardOutcome.detail_budget_spent` against
#: `detail_needed`.
DETAIL_FETCH_CEILING = 40

#: How many of the candidate's phrases one run may search for. Each phrase is
#: its own request to every steerable board, which is what searching several
#: phrases *means* — they cannot be ANDed into one query — so the fetch count
#: is phrases x boards x pages and this is what stops it running away. The
#: phrases beyond it are reported, never dropped silently: a run that quietly
#: searched four of nine looks exactly like a run that searched all nine.
PHRASE_CEILING = 6


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

    @property
    def searched(self) -> list[str]:
        """The phrases this run actually asked for, in order, without repeats."""
        seen: list[str] = []
        for outcome in self.outcomes:
            if outcome.query and outcome.query not in seen:
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
        for outcome in self.outcomes:
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
        return "\n".join(lines)


def packages_for(constraints: CandidateConstraints, directory: Path | None = None) -> list[Package]:
    """The usable packages serving this candidate's country.

    Reads `location.country` only when the field is `stated`. An `unknown`
    location must not silently select every board on the shelf: sourcing the
    whole world for somebody who has not said where they are is not a generous
    default, it is a search nobody asked for.
    """
    packages = installed_packages(directory or DEFAULT_CONNECTORS_DIR)
    location = constraints.location
    if location.state != "stated" or not location.country:
        return []
    wanted = location.country.strip().upper()
    return [p for p in packages if p.usable and p.country == wanted]


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
) -> BoardOutcome:
    try:
        connector = _connector_of(package, directory)
    except (ConnectorError, OSError) as exc:
        return BoardOutcome(
            package.name, None, False, query, error=f"the package would not load: {exc}"
        )

    steerable = accepts_query(connector)
    if steerable and not query:
        # `build_list_urls` would refuse, and rightly. Reported rather than
        # raised: one un-aimed board must not end a run over five others.
        return BoardOutcome(
            package.name,
            None,
            True,
            query,
            skipped="the board searches, and no terms are recorded — say what you are looking for",
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
    drop_reason: str | None = None
    stale = False
    last: Response | None = None
    for request in requests:
        # Adjudicated per URL, before the request is made. A board that
        # disallows one path may allow another, so this cannot be hoisted to
        # the board — and a robots.txt that cannot be read is a refusal, not a
        # permission: failing open here would fetch exactly the paths nobody
        # could confirm we may.
        try:
            if not robots.allows(request.url):
                return BoardOutcome(
                    package.name,
                    request.url,
                    steerable,
                    query,
                    skipped=f"robots.txt disallows {request.url}",
                )
        except (RobotsError, OSError) as exc:
            return BoardOutcome(
                package.name,
                request.url,
                steerable,
                query,
                skipped=f"robots.txt could not be read, so the path is not permitted: {exc}",
            )
        response = fetch(request)
        last = response
        if response.error is not None:
            return BoardOutcome(
                package.name, request.url, steerable, query, response.status, error=response.error
            )
        result = collect_listing(connector, response.body)
        stale = stale or result.stale
        refusal = rate_limited(response.body, response.status, parsed_items=len(result.items))
        if refusal is not None:
            return BoardOutcome(
                package.name, request.url, steerable, query, response.status, refused=refusal
            )
        items_seen += len(result.items)
        collected: list[str] = []
        for item in result.items:
            detail_url = _absolute(item.get("detail_url"), request.url)
            offer, why = _offer_from(connector, item, url=detail_url)
            if offer is None and connector.detail is not None and detail_url:
                # The list row cannot complete an offer and the connector says
                # the rest of the advert is on its own page. Six installed
                # connectors declare `text` only under `detail:` — correctly,
                # since their list rows carry no teaser — and every one of them
                # produced zero offers for as long as nothing fetched it.
                detail_needed += 1
                if detail_fetched < DETAIL_FETCH_CEILING and _may_fetch(robots, detail_url):
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
    return BoardOutcome(
        package.name,
        requests[-1].url if requests else None,
        steerable,
        query,
        last.status if last else None,
        items=items_seen,
        added=added,
        dropped=dropped,
        drop_reason=drop_reason,
        stale=stale,
        detail_needed=detail_needed,
        detail_fetched=detail_fetched,
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
    aim = Aim(state="stated", terms=("python",))

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


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.sourcing` — T126's evidence, over the fixture run."""
    measured = measure_fixture()
    DEFAULT_EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_EVIDENCE_PATH.write_text(
        json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        for reason in measured.get("reasons", ()):
            print(reason, file=sys.stderr)
        return 3
    return 1 if measured["sourced_offers_without_a_recorded_fetch"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
