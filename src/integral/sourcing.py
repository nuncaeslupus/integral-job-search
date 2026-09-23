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

And one thing it refuses to do (T173): send a `client: browser` board to the
plain fetch. Such a board serves its listing only to a client that runs its
JavaScript check, so a plain request is certain to be refused, and the only
ways to make one pass are evasion. It is read from a page the candidate's own
browser rendered and saved (`from_captures`), or reported skipped.

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
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from integral.candidate import Aim, CandidateConstraints
from integral.candidate import Location as ConstraintLocation
from integral.connector_coverage import Package, installed_packages
from integral.connector_health import on_portal_host, rate_limited
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
    source_kind_of,
)
from integral.gate_exit import worst
from integral.identity import ProfileStore
from integral.lifecycle import (
    collect_offer,
    save_lifecycle_offer,
    track_new_offer,
)
from integral.offers import Offer, SourceKind, compute_offer_id
from integral.robots import Robots, RobotsError

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTORS_DIR = _REPO_ROOT / "connectors"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T126.json"
DEFAULT_BROWSER_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T173.json"

#: The first line of a page the candidate's browser saved: the URL it was
#: rendered from. Written by the capture snippet in the step-7 skill, and the
#: only way a capture is matched to a request — a page that does not say where
#: it came from cannot answer for any URL, so it is refused rather than guessed.
CAPTURE_MARK = re.compile(r"\A<!-- integral-capture: (\S+) -->\n")

#: Where a run records what it fetched. Inside the candidate's own tree, like
#: everything else about them — this is provenance about their offers, not a
#: log about the tool.
FETCH_LOG = "_fetches.jsonl"

#: A run that consulted fewer boards than this consulted nothing worth
#: reporting. Spain had six usable packages when this landed.
MINIMUM_BOARDS = 1

#: A run that collected no offers says nothing about how offers get recorded.
#: The committed captures yielded well above this when T126 landed.
#: arsenal-floor-margin: MINIMUM_OFFERS_COLLECTED value=3
MINIMUM_OFFERS_COLLECTED = 3

#: Detail pages fetched per board per run. A listing row that cannot complete an
#: offer sends us to the advert's own page, and a 40-row listing would otherwise
#: turn one listing request into 41. The cap is per board so one badly-shaped
#: connector cannot spend the whole run, and what it stopped is reported rather
#: than dropped silently — `BoardOutcome.detail_fetched` against
#: `detail_needed`.
#: arsenal-floor-margin: DETAIL_FETCH_CEILING value=40
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


def read_capture(path: Path) -> tuple[str, str]:
    """A saved browser page as `(the URL it was rendered from, its HTML)`."""
    text = Path(path).read_text(encoding="utf-8")
    mark = CAPTURE_MARK.match(text)
    if mark is None:
        raise ValueError(
            f"{path} does not start with `<!-- integral-capture: <url> -->`, so it cannot "
            "say which request it answers — capture it again with the step-7 snippet"
        )
    return mark.group(1), text[mark.end() :]


def from_captures(paths: Iterable[Path]) -> Fetch:
    """A `Fetch` answering only from pages the candidate's own browser saved.

    Each page answers **the one URL it names** and nothing else: a capture of
    "farmaceutico" must not stand in for a search for "enfermera", which would
    hand the candidate the wrong adverts as if they were the answer.
    """
    pages = dict(read_capture(Path(path)) for path in paths)

    def fetch(request: ListRequest) -> Response:
        # A saved page is what one GET rendered; it cannot stand for a POST's
        # body-dependent pages, which all share one URL (#455, F4).
        body = pages.get(request.url) if request.method == "GET" else None
        if body is None:
            return Response(
                None, "", error=f"no page from the candidate's browser for {request.url}"
            )
        # ponytail: a capture observes no status. The browser rendering the page
        # is taken as 200; `rate_limited`'s body markers still catch a challenge
        # page it was shown, and the fetch log's `via` says how this arrived.
        return Response(200, body)

    return fetch


def needs_browser(connector: Connector) -> bool:
    """Whether this board is served only to a real browser (T173)."""
    detail = connector.detail
    return connector.list.client == "browser" or (detail is not None and detail.client == "browser")


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
    #: T174 (#466 review, round 1 F6). Rows whose advert host had already
    #: refused — this row's own fetch drew the refusal, or an earlier row's
    #: did — so the row was never read. Not `dropped`: nothing about the row
    #: was wrong, the host stopped answering (`_one_board`'s own `continue`
    #: beside "the host refused, not the row" is what this counts). Left out
    #: of every `_unrealized_rows` bucket, a board whose every row landed
    #: here still satisfied `items > _unrealized_rows(o)` with `added == 0`.
    refused_rows: int = 0
    #: T144. On an ATS host each request is a different employer's board, so
    #: one employer's failure is that employer's, never the host's: the others
    #: are still read, and the failures are named here rather than ending the
    #: round with every counter lost.
    employers_failed: tuple[str, ...] = ()
    #: T172. `"employer"` when the board read was the employer's own — the
    #: same `source_kind_of` every offer it stored carries.
    source_kind: SourceKind | None = None

    @property
    def reached_the_board(self) -> bool:
        """Whether this board answered, not how the round ended.

        Round 3, R3 (T167): a board that served page one and failed on page
        two supplied real offers; reading this off the terminal reason
        credited them to whichever board happened to finish cleanly, and the
        three failure routes disagreed — a 429 kept the board, a timeout
        dropped it, from the same partial read.

        T174 (#466): a board refused at the detail-page level — its list
        came back clean, but every advert was then refused and no offer was
        ever completed — did not answer, however clean the list request
        looked; `refused is None` on its own says that directly.

        `bool(self.added)`, not `self.items`, reconciles both: T174's own
        refused-detail scenario has `items > 0` (the list parsed) and
        `added == 0` (nothing was ever built), and that must read as
        not-reached; R3's scenario has `items > 0` **and** `added > 0`, and
        that must read as reached regardless of which field ended the round.
        Offers actually reaching disk is the property both fixes are really
        about, and `added` is the one field that names it directly.
        """
        return (self.skipped is None and self.error is None and self.refused is None) or bool(
            self.added
        )


#: `BoardOutcome` fields that are never "a row that never became an offer":
#: totals (`items`, `added`), the offer count itself, and board/request
#: metadata. Named as an exclusion rather than the inclusion T172 wrote
#: (`dropped + off_aim + unopened + over_ceiling`, by hand, at both call
#: sites) — CLAUDE.md's own record on this shape: "an enumeration has no
#: last element … a twin derived from `dataclasses.fields` so a field added
#: later is varied without anyone remembering to." A fifth way for a row to
#: fail to become an offer joins `_unrealized_rows` (and both of its callers)
#: the moment it is declared on the dataclass; nothing here has to change.
_NOT_AN_UNREALIZED_ROW_FIELD = frozenset(
    {
        "connector",
        "url",
        "steered",
        "query",
        "status",
        "items",
        "added",
        "drop_reason",
        "stale",
        "refused",
        "skipped",
        "error",
        "detail_needed",
        "detail_fetched",
        "employers_failed",
        "source_kind",
    }
)


def _fields_outside(cls: type, excluded: frozenset[str]) -> tuple[str, ...]:
    """Every field `cls` (a dataclass) declares, except the names in `excluded`.

    The idiom `tests/test_review_reader.py`'s `_twin_varying_every_non_input_field`
    uses for "every field but the named inputs": inclusion is the default, so a
    field added to the dataclass later is picked up on its own, with no call
    site to update. Order follows declaration order.
    """
    return tuple(f.name for f in dataclass_fields(cls) if f.name not in excluded)


#: The "row that never became an offer" partition, derived once from
#: `BoardOutcome` itself rather than hand-listed at each of its two call
#: sites (`Run.employer_boards`, `measure_flood`'s `rows_not_accounted_for`).
_UNREALIZED_ROW_FIELDS = _fields_outside(BoardOutcome, _NOT_AN_UNREALIZED_ROW_FIELD)


def _unrealized_rows(outcome: BoardOutcome) -> int:
    """Rows `outcome` parsed that never became an offer, summed across every
    `BoardOutcome` field the dataclass itself marks as such (see
    `_UNREALIZED_ROW_FIELDS`)."""
    return sum(getattr(outcome, name) for name in _UNREALIZED_ROW_FIELDS)


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
    #: The whole clause, boards included: "worldwide boards, since …" or
    #: "every installed board, since …". A run blocked by an unstated location
    #: asks nobody at all, and said nothing until round 3's R2.
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

    @staticmethod
    def _answered(outcome: BoardOutcome) -> bool:
        """The board let us read it, or read enough that some of what it
        handed over reached disk **in parsed form**.

        That is the one-sentence property this and `reached_the_board` and
        `employer_boards` are all pinned against, stated once here because
        round 6's second-reader report caught two of the three disagreeing
        about it: a board's work counts as reported when the board answered
        at all, and — for a stale connector specifically — when it parsed at
        least one row, whether or not that row survived dedup. Staleness
        excuses an outcome only when there was truly nothing to attribute,
        never when real rows came back and happened to be re-sighted.

        Round 4 (R4-5) excluded every refused or stale outcome from both
        `steered` and `unsteered`, unconditionally — which silently
        reintroduced the exact defect round 3's R3 had just closed for the
        `error` route: a board that served page one and only then failed
        (a 429 on page two, or `last_verified` gone stale after a page that
        still parsed) has real offers on disk, and hiding it from every
        disposition attributes them to nothing (round 5, F1, reproduced for
        both an unsteered and a steered board).

        `reached_the_board` (T174, merged since) already tells a productive
        refusal — offers written before the host said stop — apart from an
        unproductive one, via `bool(outcome.added)`: that is exactly the
        distinction this function used to have to make for the `refused`
        case on its own, so it no longer needs to. `stale` is the one flag
        `reached_the_board` does not fold in, because staleness says
        nothing about whether the round otherwise succeeded — so it is
        still gated here, but on `items`, not `added`: round 6's F1 measured
        a stale board every one of whose rows was re-sighted
        (`items == 120, added == 0`) and found it excluded from `unsteered`
        with the only line about it reading "its emptiness proves nothing" —
        over 120 real, parsed rows. That is the same shape
        `employer_boards`'s own docstring already calls "a result this
        board produced" for `added == 0` (#462 rounds 2 and 3, G3 and
        H1/H2); this function disagreed with that stance about the identical
        signal, and it was the one that had it backwards. `items`, not
        `added`, is what "the connector's emptiness proves nothing" is
        actually about: whether it parsed anything at all, not whether what
        it parsed later deduplicated to zero. Naming a productive but
        refused-or-stale board under "searched for your terms" or "returned
        their whole list" does not contradict the REFUSED/STALE line
        printed two below; the two report different things — one where the
        offers came from, the other why the board stopped.
        """
        return outcome.reached_the_board and not (outcome.stale and not outcome.items)

    @property
    def steered(self) -> list[str]:
        """Boards asked the candidate's question."""
        return self._boards(lambda o: o.steered and self._answered(o))

    @property
    def unsteered(self) -> list[str]:
        """Boards that returned whatever they had. Not a failure — a different result."""
        return self._boards(
            lambda o: not o.steered and self._answered(o) and not self._parsed_nothing(o)
        )

    @staticmethod
    def _parsed_nothing(outcome: BoardOutcome) -> bool:
        """An **unsteered** board that answered and yielded no row at all.

        Not "no jobs": `landingjobs_en` serves a JavaScript shell that parses
        to zero anchors, and `connectors/ruled-out.yaml` has said so since
        August. A refusal (403/429/503) and a stale connector are already told
        apart; this is the third way a board can answer and mean nothing, and
        it read as "returned their whole list" until it was named.

        **Unsteered only** (round 4, R4-4). The inference holds because such a
        board's page *is* its whole list. A `{query}` board answering a query
        with no row has said there are no jobs for that query — its answer, not
        a parse failure — and saying otherwise spends the signal this exists
        for: a real parse failure would arrive beside three boards that simply
        had nothing.
        """
        return (
            not outcome.steered
            and outcome.reached_the_board
            and not outcome.items
            and not (outcome.refused or outcome.stale or outcome.skipped or outcome.error)
        )

    @property
    def parsed_nothing(self) -> list[str]:
        """Boards that answered with no advert on the page."""
        return self._boards(self._parsed_nothing)

    @property
    def employer_boards(self) -> list[str]:
        """Declared employers' own boards a result of this round came from (T172).

        `items` minus every bucket a row can land in without ever building an
        offer is "some row became an offer", which is what T144 asks for —
        *where each result came from*. Not `reached_the_board`: a board
        refused on its first request is neither skipped nor an error, and
        named here it would claim results it never gave. Not `items` either:
        a row that builds no offer is not a result. And not `added`, which is
        0 for a re-sighting that is still a result this board produced (#462
        rounds 2 and 3, G3 and H1/H2) — the same stance `_answered` states
        for the identical `added == 0` signal.

        `dropped` alone was a complete partition of "not an offer" until
        T167 added `off_aim`, `unopened` and `over_ceiling` — three more ways
        a row never reaches `_offer_from` at all. Left out of the subtraction
        (merged from T172 and T167 separately, each unaware of the other), a
        board every one of whose rows was off-aim or past the ceiling still
        satisfied `items > dropped` with `dropped == 0`, and registered a
        result it never gave.

        Round 6's second-reader report (F2): that four-term subtraction was
        hand-listed here **and** independently hand-listed again in
        `measure_flood`'s `rows_not_accounted_for`, and two of the four terms
        (`unopened`, `over_ceiling`) were asserted by no test in either
        place — dropping either left every evidence key unmoved. `_unrealized_rows`
        (module level, derived from `BoardOutcome`'s own fields via
        `_fields_outside`) replaces both hand-listings with one definition, so
        a fifth bucket a future task adds joins both call sites the moment it
        is declared.
        """
        return self._boards(lambda o: o.source_kind == "employer" and o.items > _unrealized_rows(o))

    @property
    def unaccounted_for(self) -> list[str]:
        """Boards whose read reached disk (rows parsed, or offers added) but
        that appear in neither `steered` nor `unsteered`.

        The mirror `measure_flood` checks (round 3, R3): excluding a board
        from every disposition without saying why attributes real offers, or
        real parsed rows, to nothing — the same failure `deluge_en` supplying
        30 offers under only an ERROR line was.

        Scoped to `reached_the_board`, the same predicate `_answered` already
        requires before naming a board anywhere. A board `reached_the_board`
        correctly excludes — T174's refused-with-nothing-ever-added case,
        `items > 0` and `added == 0` — belongs in neither list *on purpose*,
        and this must not flag it: round 6's F1 measured exactly that
        (`getmanfred_es`, `items == 3, added == 0, refused`) against the old,
        unscoped population (`o.items or o.added`) and found it flagged here
        in the same run `tests/test_sourcing.py` asserts, forty lines away,
        that the board must not be listed as reached — the same test file
        asserting an invariant and its own negation. Filtering by
        `reached_the_board` first closes that: this and `steered`/`unsteered`
        now agree on the same one-sentence property `_answered` states.
        """
        population = {
            o.connector for o in self.outcomes if o.reached_the_board and (o.items or o.added)
        }
        return sorted(population - set(self.steered) - set(self.unsteered))

    @property
    def refused(self) -> list[str]:
        """Boards that refused the read. Never to be read as "no jobs there"."""
        return self._boards(lambda o: o.refused is not None)

    @property
    def untrusted(self) -> list[str]:
        """Boards whose connector is stale, so their emptiness proves nothing."""
        return self._boards(lambda o: o.stale)

    def summary(self) -> str:
        # Boards that answered. Counting every outcome credited the run with
        # boards the ceiling stopped it from ever asking (round 3, minor).
        boards = len({o.connector for o in self.outcomes if o.reached_the_board})
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
            lines.append(f"  NOT asked — {self.unreached_because}: {', '.join(self.unreached)}")
        if self.employer_boards:
            lines.append(
                f"  the employers' own boards, not a job board: {', '.join(self.employer_boards)}"
            )
        if self.added >= OFFER_CEILING:
            # Printed on the total, not only on the rows it cut: a ceiling that
            # fills exactly at a page's end stops the next page and leaves no
            # row over it, and that run must not read as a complete pass.
            lines.append(
                f"  STOPPED at the {OFFER_CEILING}-offer ceiling — any rows, pages or "
                "boards after it were not read"
            )
        if self.parsed_nothing:
            lines.append(
                "  NOTHING PARSED — answered with no advert on the page, which is not "
                f"the same as no jobs: {', '.join(self.parsed_nothing)}"
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
                partial = f" — partial: {outcome.added} added before it" if outcome.added else ""
                lines.append(f"  REFUSED {outcome.connector}: {outcome.refused}{partial}")
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

    A package declaring some OTHER country is added last, and only for
    `cross_border_remote_employer` (#562). Two buckets left the five foreign
    national boards in the library — `builtin_en`, `jobsacuk_en`, `justjoin_en`,
    `nofluffjobs_en`, `usajobs_en` — reachable by nobody, whatever anyone's reach
    said: they are neither the candidate's country nor `GLOBAL`, so they fell
    into neither. T167 made the same argument one step earlier and stopped.

    It is the cross-border mode and not `remote` that opens them, because until
    now the two selected the identical list — a mode sitting in
    `_WORLDWIDE_REACH` beside `remote` and choosing the same packages is a
    distinction with nothing behind it, while `candidate.py` treats the two as
    different states. `remote` is "I will work from home"; this one is "for an
    employer abroad", and a foreign national board is exactly what that reaches.

    Asking the board is not accepting what it returns. A Polish board's on-site
    Kraków vacancy is no more reachable than a Madrid one, and refusing it on
    reach is #550/T201's, not this function's.
    """
    packages = installed_packages(directory or DEFAULT_CONNECTORS_DIR)
    location = constraints.location
    if location.state != "stated" or not location.country:
        return []
    wanted = location.country.strip().upper()
    domestic = [p for p in packages if p.usable and p.country == wanted]
    if not reaches_worldwide(constraints):
        return domestic
    worldwide = [p for p in packages if p.usable and p.country == GLOBAL]
    if not reaches_across_borders(constraints):
        return domestic + worldwide
    foreign = [p for p in packages if p.usable and p.country not in (wanted, GLOBAL)]
    return domestic + worldwide + foreign


def reaches_worldwide(constraints: CandidateConstraints) -> bool:
    """Whether the candidate's stated reach includes remote work.

    Unknown or declined reach does not: step 7 says *"an unanswered mobility
    question leaves the reach at its current setting and searches accordingly"*,
    and the setting nobody chose is the narrow one.
    """
    reach = constraints.reach
    return reach.state == "stated" and not _WORLDWIDE_REACH.isdisjoint(reach.modes)


def reaches_across_borders(constraints: CandidateConstraints) -> bool:
    """Whether the candidate would work remotely for an employer in another country.

    Strictly narrower than `reaches_worldwide`, and deliberately: `remote` alone
    is compatible with wanting a domestic employer, so it opens the `GLOBAL`
    boards and not another country's national ones. An unstated reach is the
    narrow one, for `reaches_worldwide`'s reason.
    """
    reach = constraints.reach
    return reach.state == "stated" and "cross_border_remote_employer" in reach.modes


def _why_not_worldwide(constraints: CandidateConstraints) -> str:
    """Why worldwide boards were left out, without claiming an answer nobody gave.

    "Does not include remote work" is true only of a stated reach. An unknown
    one is step 7's own conversational duty — establish how far the search can
    travel — so it says the question is open.
    """
    state = constraints.reach.state
    if state == "unknown":
        return "worldwide boards, since you have not said whether you would work remotely"
    if state == "declined":
        return "worldwide boards, since you preferred not to say whether you would work remotely"
    return "worldwide boards, since your reach does not include remote work"


def _why_no_location(constraints: CandidateConstraints) -> str:
    """Why *nothing* was asked: `packages_for` selects no board at all without a
    stated country, and a run that asked nobody read as a world with no jobs
    until round 3's R2. The reason is the operative one — answering the reach
    question alone still selects nothing.
    """
    if constraints.location.state == "declined":
        return "every installed board, since you preferred not to say where you are"
    return "every installed board, since you have not said where you are"


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
    browser: Fetch | None = None,
) -> Run:
    """Fetch this candidate's country's boards and collect what they return.

    `robots` is injectable and defaults to a real adjudicator, so the honest
    thing happens without the caller remembering to ask for it. A test that
    wants no network passes one whose fetcher is a fixture — never `None` to
    mean "skip the check", which would make the safe path the one you have to
    opt into.

    `browser` answers the boards `needs_browser` names — normally
    `from_captures` over the pages `browser_urls` asked the candidate's browser
    to save. Without it those boards are reported skipped; they are never sent
    to `fetch` (T173).
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
    location = constraints.location
    if location.state != "stated" or not location.country:
        # Nothing is selected at all, so the whole shelf is what went unasked.
        run.unreached = tuple(p.name for p in installed_packages(directory) if p.usable)
        run.unreached_because = _why_no_location(constraints)
    elif not reaches_worldwide(constraints):
        run.unreached = tuple(
            p.name for p in installed_packages(directory) if p.usable and p.country == GLOBAL
        )
        run.unreached_because = _why_not_worldwide(constraints)
    phrases = aim.terms[:PHRASE_CEILING]
    # T174: shared by every board and phrase, so a host's refusal is its
    # answer for the rest of the run rather than for one request.
    refused_origins: dict[str, str] = {}
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
                    browser=browser,
                    refused_origins=refused_origins,
                )
            )
    return run


def browser_urls(
    constraints: CandidateConstraints,
    aim: Aim,
    *,
    directory: Path | None = None,
    page_count: int = 1,
    robots: Robots | None = None,
) -> list[str]:
    """The listing URLs `source` will ask `browser` for — what to open, in order.

    Exactly the requests `_one_board` would make for the `needs_browser`
    boards, robots adjudicated the same way first: the candidate's browser is
    never sent to a path the tool itself may not read.
    """
    directory = directory or DEFAULT_CONNECTORS_DIR
    adjudicator = Robots() if robots is None else robots
    phrases = aim.terms[:PHRASE_CEILING]
    urls: list[str] = []
    for package in packages_for(constraints, directory):
        try:
            connector = _connector_of(package, directory)
        except (ConnectorError, OSError):
            continue
        if not needs_browser(connector):
            continue
        steerable = accepts_query(connector)
        if steerable and not phrases:
            continue
        for query in phrases if steerable else (None,):
            try:
                requests = build_list_requests(connector, page_count=page_count, query=query)
            except ConnectorError:
                continue  # `source` reports the same phrase as an error; nothing to open
            for request in requests:
                if _may_fetch(adjudicator, request.url) and request.url not in urls:
                    urls.append(request.url)
    return urls


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


def _origin(url: str) -> str:
    """RFC 6454's (scheme, host, port), with the default port filled in.

    `usajobs_en`'s adverts link to `https://www.usajobs.gov:443/job/…` while its
    list is `https://www.usajobs.gov/…` — one host, and it must be one origin,
    or a refusal on one spelling leaves the other free to be asked (#466 F1).
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port: int | str | None
    try:
        port = parts.port or {"http": 80, "https": 443}.get(scheme)
    except ValueError:  # a malformed port in a board's own link: keep it as written
        port = parts.netloc.rpartition(":")[2].lower()
    return f"{scheme}://{parts.hostname or ''}:{port}"


def _detail_record(
    connector: Connector, url: str, *, fetch: Fetch
) -> tuple[dict[str, str] | None, str | None]:
    """The advert's own page, parsed for whatever `connector.detail` names,
    and why the host refused it — `(None, None)` for a page that merely failed.

    T174: the refusal comes back apart from the failure because the two ask
    for opposite things. A 404 is one missing advert and the next may be read;
    a 429 is the host saying stop, and the caller must not ask it again.

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
    refusal = rate_limited(None, response.status)
    if refusal is not None:
        return None, refusal
    if response.error is not None or response.status != 200:
        return None, None
    try:
        return parse_detail_page(connector, response.body), None
    except ConnectorError:
        return None, None


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
    browser: Fetch | None = None,
    refused_origins: dict[str, str] | None = None,
) -> BoardOutcome:
    """One board, asked `query` if it searches, else narrowed to `phrases`.

    `room` is how many new offers the run may still write (`OFFER_CEILING`).
    """
    refused_origins = {} if refused_origins is None else refused_origins
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

    # T173. A plain request to this board is certain to be refused, and the only
    # ways to make it pass are evasion — so it is never made. Decided after
    # robots, below: a path nobody may read is not one to send a browser to.
    via: str | None = None
    unanswerable = needs_browser(connector) and browser is None
    if needs_browser(connector) and browser is not None:
        fetch, via = browser, "candidate_browser"

    items_seen = 0
    added = 0
    dropped = 0
    detail_needed = 0
    detail_fetched = 0
    off_aim = 0
    unopened = 0
    over_ceiling = 0
    refused_rows = 0
    drop_reason: str | None = None
    stale = False
    refused: str | None = None
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
            refused_rows=refused_rows,
            employers_failed=tuple(failed),
            source_kind=source_kind_of(connector),
            skipped=skipped,
            error=error,
            refused=refused,
        )

    for index, request in enumerate(requests):
        if added >= room:
            break
        prior = refused_origins.get(_origin(request.url))
        if prior is not None:
            # T174: the host already said stop this run, so it is not asked
            # again. A break, not a return, so earlier pages still count.
            # A board that refused an advert page keeps its own reason.
            refused = (
                refused or f"not asked again this run — {_origin(request.url)} refused: {prior}"
            )
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
        if unanswerable:
            return ended(
                request.url,
                skipped="served only to a real browser — open its search in the candidate's "
                "own browser (`browser_urls`) and pass the saved pages as `browser=`",
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
            refused_origins[_origin(request.url)] = blocked
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
                via=via,
            )
            continue
        if response.error is not None:
            return ended(request.url, response.status, error=response.error)
        result = collect_listing(connector, response.body)
        stale = stale or result.stale
        refusal = rate_limited(response.body, response.status, parsed_items=len(result.items))
        if refusal is not None:
            refused_origins[_origin(request.url)] = refusal
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
                origin = _origin(detail_url)
                if detail_fetched >= DETAIL_FETCH_CEILING:
                    # A budget stop, not a connector that produced no text
                    # (#445 round 2 N5, T167): counted apart from `dropped`.
                    unopened += 1
                    continue
                if origin not in refused_origins and _may_fetch(robots, detail_url):
                    _pause(robots.delay(detail_url, 0.0))
                    detail_fetched += 1
                    fields, refusal = _detail_record(connector, detail_url, fetch=fetch)
                    if refusal is not None:
                        refused_origins[origin] = f"{refusal}, on an advert page ({detail_url})"
                    elif fields:
                        offer, why = _offer_from(connector, item, fields, url=detail_url)
                if origin in refused_origins:
                    # T174: the host refused, not the row — so it is unread,
                    # never "dropped" as a connector that produced no text.
                    # Counted in `refused_rows` (#466 review, round 1 F6):
                    # left uncounted, it inflated `items` past every
                    # `_unrealized_rows` bucket, and a board whose every row
                    # landed here still read as having built an offer.
                    refused_rows += 1
                    refused = refused or refused_origins[origin]
                    continue
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
            via=via,
        )
    return ended(
        requests[-1].url if requests else None,
        last.status if last else None,
        error=(
            f"every employer board failed: {', '.join(failed)}"
            if failed and len(failed) == len(requests)
            else None
        ),
        refused=refused,
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
    via: str | None = None,
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
            # Present only when the page did not come from `fetch` (T173).
            **({"via": via} if via else {}),
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

        # `detail_fetched < detail_needed`, not `not outcome.added`: T166 made
        # trabajos_es steered, so this fixture asks it once per phrase against
        # the same committed list capture, and the second and third queries'
        # rows are all re-sighted — `detail_fetched == detail_needed` (every
        # fetch the engine owed it, completed) but `added == 0` (nothing new).
        # That is not the market emptying and not the engine starving it
        # either; it is T130's own motivating case (arbeitnow_en: 35 rows,
        # `detail_fetched` stuck at 0 because the fetch did not exist yet) told
        # apart from a re-sighting neither `not outcome.added` nor `outcome.
        # items` can tell apart on their own (round 5 merge finding, T167).
        starved = [
            outcome.connector
            for outcome in run.outcomes
            if outcome.items
            and outcome.detail_needed
            and outcome.detail_fetched < outcome.detail_needed
        ]

        # T174. The same run with every advert page answering 429. Each host
        # may be asked for one advert — the one that refused — and a board
        # that refused must not be listed as one that answered.
        adverts_asked: list[str] = []

        def refusing(request: ListRequest) -> Response:
            if urlsplit(request.url).path in list_paths:
                return answer(request)
            adverts_asked.append(request.url)
            return Response(429, "Too Many Requests")

        refused_run = source(
            store,
            constraints,
            aim,
            fetch=refusing,
            at="2026-01-01T00:00:00+00:00",
            directory=DEFAULT_CONNECTORS_DIR,
            robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        )
        # Counted by hostname, never by `_origin`: a metric that shares the
        # function it checks reads 0 whenever that function is wrong (#466 F2).
        hosts_asked = [urlsplit(url).hostname for url in adverts_asked]
        # Independent of the fix: a board with one advert the budget could
        # have asked for cannot show a second request, so a zero over no such
        # board would be vacuous. The budget is part of that — `detail_needed`
        # alone counts rows `DETAIL_FETCH_CEILING` would never reach, which
        # would keep the population at 2 with a ceiling of 1 (#466 N3).
        second_advert = sum(
            1 for o in refused_run.outcomes if min(o.detail_needed, DETAIL_FETCH_CEILING) > 1
        )

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
            "advert_requests_after_a_refusal": len(hosts_asked) - len(set(hosts_asked)),
            # Boards that asked for an advert, every one of which was refused —
            # not `Run.refused`, which is the fix's own output and would read
            # a vacuous zero if the refusal were never recorded.
            "refused_boards_listed_as_reached": len(
                {o.connector for o in refused_run.outcomes if o.detail_fetched}
                & set(refused_run.steered + refused_run.unsteered)
            ),
            "boards_with_a_second_advert_to_refuse": second_advert,
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
        elif not second_advert:
            measured["gate_status"] = "unmeasured"
            measured["reasons"] = [
                "no board needed a second advert page, so a zero count of requests "
                "after a refusal says nothing about whether a refusal stops them"
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


def measure_reach_selection() -> dict[str, Any]:
    """#562's gate: which boards each stated reach can actually be asked.

    Three packages, one per bucket `packages_for` can put a board in — the
    candidate's own country, `GLOBAL`, and some other country — against the
    three reaches that select differently. The library's real shape is the
    reason the third bucket matters: five of its boards are foreign national
    ones (`builtin_en`, `jobsacuk_en`, `justjoin_en`, `nofluffjobs_en`,
    `usajobs_en`) and two buckets left every one of them unreachable by anyone.

    Both directions are components, because one of them alone is satisfied by
    "ask every board", which is the remedy wearing a gate: a candidate who has
    not said they would work for an employer abroad must still be asked their
    own country and `GLOBAL` and nothing else.

    The names are read out of `packages_for`'s answer rather than its length —
    a count cannot tell a missing foreign board from an extra domestic one.
    """
    import tempfile

    from integral.candidate import Reach

    location = ConstraintLocation(state="stated", country="ES", accepts_onsite_in_country=True)
    reaches = {
        "unknown": CandidateConstraints(location=location),
        "remote": CandidateConstraints(
            location=location, reach=Reach(state="stated", modes=("remote",))
        ),
        "cross_border": CandidateConstraints(
            location=location,
            reach=Reach(state="stated", modes=("cross_border_remote_employer",)),
        ),
    }
    countries = {"home": "ES", "worldwide": GLOBAL, "foreign": "US"}

    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "connectors"
        for site, country in countries.items():
            flood_board(directory, site, 1)
            (directory / f"{site}_en" / "meta.yaml").write_text(
                f"site: {site}.integral.local\ncountry: {country}\nlanguage: en\n",
                encoding="utf-8",
            )
        selected = {
            name: {p.name for p in packages_for(constraints, directory)}
            for name, constraints in reaches.items()
        }

    home, worldwide, foreign = ("home_en", "worldwide_en", "foreign_en")
    components = {
        # #562 itself: the board a cross-border candidate is asking for.
        "foreign_boards_unreachable_to_a_cross_border_candidate": len(
            {foreign} - selected["cross_border"]
        ),
        # …and the direction that stops the fix being "ask everyone". A reach
        # that does not say "an employer abroad" does not reach another
        # country's national board, and an unstated reach reaches neither it
        # nor `GLOBAL`.
        "foreign_boards_selected_without_cross_border_reach": len(
            (selected["remote"] | selected["unknown"]) & {foreign}
        ),
        # `worldwide_boards_selected_without_remote_reach` is deliberately NOT
        # here: the flood half already writes that key, and a second source
        # writing it would shadow the first in the shared record rather than
        # corroborate it — `measure_flood_and_reach` refuses the overlap.
        "home_boards_missing_from_any_reach": sum(
            1 for chosen in selected.values() if home not in chosen
        ),
        "worldwide_boards_unreachable_to_a_remote_candidate": len({worldwide} - selected["remote"]),
    }
    measured: dict[str, Any] = {
        "reach_selection_violations": sum(components.values()),
        **components,
        "buckets_installed": len(countries),
        "reaches_compared": len(reaches),
        "gate_status": "measured",
    }
    # A clean zero over a directory that installed nothing says nothing at all:
    # the widest reach must see one board of each bucket, or no component below
    # it had a population to count.
    if len(selected["cross_border"]) != len(countries):
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            "the widest reach was offered "
            f"{sorted(selected['cross_border'])} rather than one board per bucket, "
            "so every component below counted over an empty population"
        ]
    return measured


def measure_flood_and_reach() -> dict[str, Any]:
    """T167's record, both halves — they share a file rather than a T-number.

    The flood half asks what a board returns; #562's half asks which boards are
    put to one at all. Both are `packages_for`'s answer read through `source`,
    so a single record is the honest place for them, and neither half can be
    green while the other is `unmeasured`.
    """
    flood = measure_flood()
    reach = measure_reach_selection()
    separate = ("gate_status", "reasons")
    contributed = {k: v for k, v in reach.items() if k not in separate}
    # A dict merge is silent about a key both halves write, and the survivor is
    # whichever was merged second — one measurement reported under another's
    # name. Refused rather than resolved: the two populations differ, so the
    # answer is a second key, never a winner.
    shadowed = sorted(set(flood) & set(contributed))
    if shadowed:
        raise ValueError(
            f"T167: {shadowed} is measured by both halves of this record — name the "
            "second one for the population it counts rather than overwriting the first"
        )
    merged = {**flood, **contributed}
    reasons = [*flood.get("reasons", ()), *reach.get("reasons", ())]
    merged["gate_status"] = (
        "unmeasured" if "unmeasured" in (flood["gate_status"], reach["gate_status"]) else "measured"
    )
    if reasons:
        merged["reasons"] = reasons
    return merged


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
            if request.url == _FLOOD_FAILING:
                # A real refusal (round 6, F1/E-M4), not a transport error: a
                # transport error sets `.error`, which `_answered`'s and
                # `reached_the_board`'s exclusion logic never inspects, so a
                # regression that blanket-excludes every `refused` board
                # (round 4's own defect, reinstated) had nothing here to act
                # on and `flood_violations` could not move. Deluge already has
                # real offers on disk from page one when this fires — exactly
                # F1's shape — so this is now the fixture that closes the
                # gap the round-6 report named.
                return Response(429, "", error=None)
            page = pages.get(request.url)
            if page is None:
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
        # The mirror (round 3, R3): a board that read rows and is reported as
        # neither searched nor handing over its list. One direction alone let
        # `deluge_en` supply 30 offers and be named only as an ERROR. `Run.
        # unaccounted_for` is the same check `Run` itself exposes (round 6,
        # F1) — scoped to `reached_the_board` so a board T174 deliberately
        # excludes (refused, nothing ever added) is not double-counted as a
        # violation of a rule it was never meant to satisfy.
        "boards_that_read_rows_without_being_reported_asked": len(run.unaccounted_for),
        "rows_served_not_reported": abs(
            sum(o.items for o in run.outcomes)
            - sum(len(page.matching) + len(page.off_aim) for page in answered)
        ),
        # Round 6, F2: `_unrealized_rows` is the same derived partition
        # `Run.employer_boards` uses, so a bucket added to `BoardOutcome`
        # later moves both instead of only the one someone remembered to
        # update.
        "rows_not_accounted_for": sum(
            abs(o.items - (_unrealized_rows(o) + o.added)) for o in run.outcomes
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
    # What the RUN had to do for a zero to mean anything, each named so a
    # weakened guard shows as a missing name rather than as a silent pass
    # (round 3, R1 — the three used to be one boolean, and a construction that
    # tripped two of them certified a guard that had kept only one).
    exercised = {
        "fill the ceiling": len(written) == OFFER_CEILING,
        "cut rows at the ceiling": bool(measured["rows_reported_over_the_ceiling"]),
        "meet the failing page": _FLOOD_FAILING in served,
    }
    unmet = [name for name, done in exercised.items() if not done]
    # Only a clean zero can be vacuous. A violation is a finding whatever else
    # the run failed to reach, and must never be downgraded to "unmeasured".
    if not measured["flood_violations"] and unmet:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"the run did not {', did not '.join(unmet)} — a zero over it says nothing "
            "about the per-run count, the page stop or the board stop"
        ]
    return measured


def measure_browser_route(directory: Path | None = None) -> dict[str, Any]:
    """T173's gate reading: `browser_boards_fetched_over_plain_http`.

    Three constructed runs over the installed Spanish boards — no browser, a
    browser holding the right page, a browser holding a page of another search
    — with a plain fetch that records every host it is asked for and answers
    nothing. The browser boards' pages are their own committed list captures,
    saved the way the step-7 snippet saves them.

    A zero is only a reading when the runs also show the two things it could be
    hiding: offers really arrived through the browser, and a plain board really
    reached the plain fetch. A sourcing pass that fetched nothing at all would
    otherwise score a clean zero.
    """
    import tempfile

    from integral.identity import create_profile

    directory = directory or DEFAULT_CONNECTORS_DIR
    constraints = CandidateConstraints(
        location=ConstraintLocation(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona",),
        )
    )
    aim = Aim(state="stated", terms=("farmaceutico",))
    robots = Robots(fetch=lambda url: "User-agent: *\nAllow: /\n")
    browser_sites = [
        p.site
        for p in packages_for(constraints, directory)
        if p.site and needs_browser(_connector_of(p, directory))
    ]
    asked: list[str] = []

    def plain(request: ListRequest) -> Response:
        asked.append(request.url)
        return Response(None, "", error="no network in a measurement")

    def run_with(root: Path, captures: list[Path] | None) -> Run:
        create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
        return source(
            ProfileStore(root, "fixture"),
            constraints,
            aim,
            fetch=plain,
            at="2026-01-01T00:00:00+00:00",
            directory=directory,
            robots=robots,
            browser=None if captures is None else from_captures(captures),
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        saved: list[Path] = []
        misfiled: list[Path] = []
        for url in browser_urls(constraints, aim, directory=directory, robots=robots):
            site = next(s for s in browser_sites if on_portal_host(url, s))
            package = next(p for p in packages_for(constraints, directory) if p.site == site)
            html = (directory / package.name / "fixture" / "list.html").read_text(encoding="utf-8")
            for bucket, named in ((saved, url), (misfiled, url + "-another-search")):
                path = root / f"capture-{len(saved) + len(misfiled)}.html"
                path.write_text(f"<!-- integral-capture: {named} -->\n{html}", encoding="utf-8")
                bucket.append(path)
        runs = {
            "none": run_with(root / "none", None),
            "right": run_with(root / "right", saved),
            "another": run_with(root / "another", misfiled),
        }

    def from_browser(run: Run) -> int:
        return sum(
            o.added
            for o in run.outcomes
            if any(on_portal_host(o.url or "", s) for s in browser_sites)
        )

    over_plain = [u for u in asked if any(on_portal_host(u, s) for s in browser_sites)]
    measured: dict[str, Any] = {
        "browser_boards_fetched_over_plain_http": len(over_plain),
        "browser_boards": len(browser_sites),
        "offers_collected_through_the_browser": from_browser(runs["right"]),
        "offers_collected_from_a_capture_of_another_search": from_browser(runs["another"]),
        "plain_requests_made": len(asked) - len(over_plain),
        "gate_status": "measured",
    }
    reasons = []
    if not browser_sites:
        reasons.append("no installed board declares `client: browser`, so nothing was guarded")
    if not measured["offers_collected_through_the_browser"]:
        reasons.append("no offer arrived through the browser, so the route was never exercised")
    if not measured["plain_requests_made"]:
        reasons.append(
            "no plain board reached the plain fetch, so a run that fetched nothing passes"
        )
    if reasons:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = reasons
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.sourcing` — T126's, T167's and T173's evidence.

    The three gates' exits are combined by `gate_exit.worst`, never by hand: a
    hand-rolled "unmeasured wins" let one gate's failure hide behind another's
    `unmeasured` (second reader on #455, F1).
    """
    codes: list[int] = []
    for path, measured, keys in (
        (
            DEFAULT_EVIDENCE_PATH,
            measure_fixture(),
            (
                "sourced_offers_without_a_recorded_fetch",
                # T174: a refusal must stop the host it came from, and a
                # refused board must not be reported as one that answered.
                "advert_requests_after_a_refusal",
                "refused_boards_listed_as_reached",
            ),
        ),
        (
            FLOOD_EVIDENCE_PATH,
            measure_flood_and_reach(),
            ("flood_violations", "reach_selection_violations"),
        ),
        (
            DEFAULT_BROWSER_EVIDENCE_PATH,
            measure_browser_route(),
            ("browser_boards_fetched_over_plain_http",),
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(measured, ensure_ascii=False))
        failed = any(measured[k] for k in keys) or measured.get(
            "offers_collected_from_a_capture_of_another_search"
        )
        if measured["gate_status"] == "unmeasured":
            for reason in measured.get("reasons", ()):
                print(reason, file=sys.stderr)
        codes.append(1 if failed else 3 if measured["gate_status"] == "unmeasured" else 0)
    return worst(*codes)


if __name__ == "__main__":
    raise SystemExit(_main())
