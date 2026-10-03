"""T200 — every board that publishes a salary, read against its own fixture.

The gate is `boards_that_publish_a_salary_we_do_not_read == 0`, and the task
file states the trap it exists to avoid in one sentence:

    Counting connectors that declare a salary field is not the gate — it is
    satisfiable by declaring fields that never match, which is exactly how the
    current shape reads as working.

So nothing here counts declarations. Each package's **own committed fixture** is
parsed the way `source()` parses it, row by row, and every row that publishes a
figure has to end in one of two places: a `Salary` whose numbers this module was
told to expect, or a written refusal naming why the figure is not a band. A row
that publishes money and lands in neither is the defect.

## The route matters, and measuring the wrong one reports defects that do not exist

`source()` fetches an advert's own page **only when the list row could not build
an offer by itself** (`sourcing.py:1138`). Two consequences, and the first
version of this measurement got both wrong:

* A *bodiless* board — one whose list declares no `text` — always reads its
  salary from the detail page. Parsing its rows list-only reports every one of
  them as unread, which is a defect on a route the engine never takes.
* A *complete* list row never opens the detail page at all, so salary fields
  declared under `detail:` on such a connector are dead. `jobfluent_es` was in
  exactly that position: four correct schema.org salary fields, never reached.

`_verdicts` therefore does what `source()` does — list first, detail only for
the rows that produced no offer.

**A wildcard is confined to what it can adjudicate.** A package commits one
`fixture/detail.html`, so a bodiless board's N rows share one advert page. A
`"*"` entry in `salary.json` may adjudicate a row only when the row's *list card
publishes no money* — the salary can then only come from the shared detail page.
A card that shows its own band is judged row by row (`list_says`), so editing
that band turns the audit red. `rows_adjudicated_by_a_wildcard` reports how many
rows a wildcard still covers, and the floor counts *distinct* adjudications.

## What "publishes a salary" means here, and why it is derived

A row publishes money when a currency token or a wage noun sits within
`_WINDOW` characters of a digit. Both vocabularies are **imported from the
modules that already own them** — `connectors._CURRENCIES` and
`salary_recovery._WAGE_NOUN` — rather than listed again here. A currency added
to that table widens this scan on the same commit, which is the difference
between a rule and an enumeration: an enumeration has no last element, and the
one written by the session that also writes the expectations describes the code
it just wrote.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any

from integral.connectors import (
    _CURRENCIES,
    Connector,
    _json_documents,
    _numbers_in,
    _outside_annual_bound,
    _take,
    compile_path,
    compile_selector,
    dig_container,
    load_connector,
    parse_detail_page,
    parse_html,
    parse_list_page,
    select_all,
)
from integral.connectors import (
    _CURRENCY_TOKEN as _CONNECTOR_CURRENCY_TOKEN,
)
from integral.salary_recovery import _WAGE_NOUN
from integral.sourcing import _offer_from

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTORS_DIR = _REPO_ROOT / "connectors"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T200.json"

#: A URL for the parse. Nothing is fetched — the fixtures are on disk — but
#: `build_offer` wants one, and a value that is obviously not a board keeps a
#: stray copy of it out of anybody's offer store.
_FIXTURE_URL = "https://fixture.invalid/advert"

#: How far a digit may sit from a currency token or a wage noun and still be
#: the figure it names. Wide enough for "Salary: up to £2,206 per module" and
#: narrow enough that a currency in a filter dropdown does not adopt a headcount
#: from the other end of the card.
_WINDOW = 40

#: The shortest reason an entry may give for a card it declares uncomparable. A
#: floor on prose is a proxy, and says so: it only stops a bare `"x"`.
_MIN_REASON = 40

#: Every currency this repository can recognise, longest token first, bounded by
#: ASCII letters exactly as `connectors._CURRENCY_TOKEN` bounds them — `CAD`
#: inside `CADENCE` is not money here either. Derived from the table rather than
#: restated, so the two cannot drift apart.
_CURRENCY_TOKEN = re.compile(
    "|".join(
        rf"(?<![A-Z]){re.escape(token)}(?![A-Z])"
        for token in sorted(_CURRENCIES, key=len, reverse=True)
    )
)


#: The slice of a card that states a band: two figures joined by a dash, each
#: optionally led by a currency token and trailed by a `K`/`M`. It only *cuts the
#: text out*; what the figures and the currency are is decided by the connector
#: engine's own `_take` vocabulary (`range_low`, `range_high`, `currency`), so the
#: audit reads money the way a connector's `take:` does and owns no parser.
_CUR = _CONNECTOR_CURRENCY_TOKEN.pattern
#: One figure as a card writes it: a currency token before or after (or neither),
#: and a `K`/`M` only as a whole token — the text is upper-cased before it is
#: sliced, so `MADRID` must not lend its `M` to the number in front of it.
_FIGURE = rf"(?:{_CUR})?\s*\d[\d.,]*(?:\s*[KM](?!\w))?\s*(?:{_CUR})?"
_BAND_SLICE = re.compile(rf"{_FIGURE}\s*(?:[-\u2013\u2014]|\bTO\b)\s*{_FIGURE}")
#: A lone figure with a currency token attached to it, either side.
_SINGLE_SLICE = re.compile(
    rf"(?:{_CUR})\s*\d[\d.,]*(?:\s*[KM](?!\w))?|\d[\d.,]*(?:\s*[KM](?!\w))?\s*(?:{_CUR})"
)


_TAG = re.compile(r"<[^>]*>")


def _flat(text: str) -> str:
    """The card's text as a reader sees it: entities decoded, tags dropped,
    whitespace collapsed, upper-cased. A board that ships its advert as escaped
    HTML (`&lt;span&gt;$320,000&lt;/span&gt;&amp;mdash;…`) prints a band the raw
    string hides behind markup, and a card the slice cannot see is a card the
    audit skips."""
    decoded = unescape(text)
    if "<" in decoded:
        decoded = unescape(_TAG.sub(" ", decoded))
    return " ".join(decoded.split()).upper()


def card_figure(text: str) -> tuple[float, str | None] | None:
    """`(figure, currency or None)` for a card that prints exactly one money
    figure and no band, or `None`.

    The single-figure twin of `card_band`: `CAD 42K`, `$143,913 Per year`. It
    says nothing when the card prints a band (that is `card_band`'s) or two
    different figures (nothing to hold a declared read against).
    """
    if card_band(text) is not None:
        return None
    flat = _flat(text)
    found = set()
    for match in _SINGLE_SLICE.finditer(flat):
        chunk = match.group(0)
        figures = _numbers_in(chunk)
        if len(figures) != 1 or figures[0] <= 0:
            continue
        # A second figure of the same order of magnitude beside this one is a
        # band written without a dash (`40.000 a 50.000`, `entre 30.000 y 40.000
        # EUR`, `40.000 / 50.000`): reading it as one figure lets an engine that
        # reads a single end pass. Refuse, so the row is counted instead. Small
        # numbers (a grade `GS 14-15`, a count) are another order and do not.
        low, high = max(0, match.start() - _WINDOW), match.end() + _WINDOW
        before, after = flat[low : match.start()], flat[match.end() : high]
        # A window edge that lands inside a token leaves half a number behind
        # (`"DOCUMENTID": "88246` out of `882464100`), which is not on the card.
        if low > 0:
            before = before.split(" ", 1)[-1]
        if high < len(flat):
            after = after.rsplit(" ", 1)[0]
        context = f"{before} {after}"
        if any(0.1 <= other / figures[0] <= 10 for other in _numbers_in(context) if other > 0):
            return None
        found.add((figures[0], _take("currency", chunk)))
    return found.pop() if len(found) == 1 else None


def card_band(text: str) -> tuple[float, float, str] | None:
    """`(min, max, currency)` the card's own text publishes, or `None`.

    `None` when the card states no two-figure band with a resolvable currency,
    or states two different ones: the audit then has nothing to hold a declared
    read against, and says nothing rather than guess.
    """
    flat = _flat(text)
    found = set()
    for match in _BAND_SLICE.finditer(flat):
        chunk = match.group(0)
        low, high, currency = (
            _take("range_low", chunk),
            _take("range_high", chunk),
            _take("currency", chunk),
        )
        if low is not None and high is not None and currency is not None:
            found.add((float(low), float(high), currency))
    return found.pop() if len(found) == 1 else None


@dataclass(frozen=True)
class RowVerdict:
    """One fixture row, measured."""

    index: int
    route: str  # "list", "detail", or "unbuilt"
    publishes: tuple[str, ...]  # the money contexts found, for the report
    salary: dict[str, Any] | None
    #: The subset of `publishes` found in the row's **own list text**. A `"*"`
    #: may stand in only for money found on the shared detail page; money the
    #: row itself prints is that row's own fact and needs its own entry.
    list_publishes: tuple[str, ...] = ()
    #: True when the salary was read through the shared detail page — the
    #: connector's `detail:` block declares a salary field — so the committed
    #: `detail.html` (another advert's) decided the numbers, not the card.
    detail_supplies_salary: bool = False
    #: What the row's own card publishes, by `card_band` — `None` when it states
    #: no band. A declared read is held against this, never against the engine's
    #: read alone: an entry that copies the code's output agrees with the code by
    #: construction, and only the card can say the code is wrong.
    card: tuple[float, float, str] | None = None
    #: The single-figure twin, by `card_figure` — set only when `card` is `None`.
    card_single: tuple[float, str | None] | None = None
    #: Every number the row's own card prints, read by the engine's `_numbers_in`.
    #: What a waived card's pinned figures are held against.
    card_numbers: frozenset[float] = frozenset()
    #: True when a money window of the row's own card carries a word that names
    #: a pay period (`_PERIOD_WORD`). A refusal that says "the card states no
    #: period" is held against this: it stands only while the card really says
    #: none, so a board that starts printing `/ h` turns the waiver into a
    #: counted refusal instead of leaving a declaration nothing checks.
    card_mentions_period: bool = False


#: A word that names a pay period, or the `/` and `per` that introduce one. Wide
#: on purpose: this decides whether a "the card states no period" waiver may
#: stand, and the unsafe error is a waiver standing over a card that does.
_PERIOD_WORD = re.compile(
    r"/|\bper\b|\b(?:h|hr|hrs|hour\w*|day|daily|week\w*|month\w*|year\w*|annual\w*|annum|p\.?a\.?)\b",
    re.IGNORECASE,
)

#: A declared refusal whose reason names the annual bound or a missing period.
#: Case-sensitive on purpose: `Period` capitalised is the type name in a reason
#: about a cadence the vocabulary cannot represent (jobsacuk's per-module rate),
#: which is a different refusal from a period nobody read.
_BOUND_OR_PERIOD = re.compile(
    r"_BOUNDS|bounded as annual|annual wage|\bno period\b|\bperiod `take`|normalize_period"
)


def _refused_for_bound_or_period(declared: dict[str, Any], verdict: RowVerdict) -> bool:
    """Whether this declared refusal is one the bound or a period `take` could
    still fix, by its own stated reason (T214).

    The one refusal that stays — a card that states no period at all (trabajos
    `9 € - 13 €`) — is exempt only if it says so with `card_states_no_period`
    **and** the audit finds no period word in the card's money windows. The
    declaration alone would be the author's word about the card.
    """
    why = declared.get("why")
    if not (isinstance(why, str) and _BOUND_OR_PERIOD.search(why)):
        return False
    return not (declared.get("card_states_no_period") is True and not verdict.card_mentions_period)


def _money_contexts(text: str) -> tuple[str, ...]:
    """Every place in `text` where a figure is published, as quoted windows.

    Deduplicated by window, because a card that prints its band twice (the
    responsive-duplicate trap several of these boards set) publishes one salary,
    not two.
    """
    flat = " ".join(text.split())
    spans = sorted(
        (match.start(), match.end())
        for match in list(_CURRENCY_TOKEN.finditer(flat.upper())) + list(_WAGE_NOUN.finditer(flat))
    )
    found: list[str] = []
    reported_to = -1
    for start, end in spans:
        if start <= reported_to:
            # Inside a window already quoted. One published figure, not two —
            # a JSON payload naming a currency six times in one object is the
            # same salary, and quoting it six times says nothing extra.
            continue
        low, high = max(0, start - _WINDOW), min(len(flat), end + _WINDOW)
        if not re.search(r"\d", flat[low:high]):
            continue
        found.append(flat[low:high])
        reported_to = high
    return tuple(found)


def _row_sources(connector: Connector, list_html: str) -> list[str]:
    """The raw text of each list row, on whichever route the connector reads.

    A JSON board has no markup to walk, so the row's own document is dumped;
    what matters is that the scan sees everything the board published on that
    row, not that it sees it as a person would.
    """
    source = connector.list.from_json
    if source is not None:
        rows: list[str] = []
        for document in _json_documents(list_html, source):
            for item in dig_container(document, compile_path(source.items or "")):
                rows.append(json.dumps(item, ensure_ascii=False))
        return rows
    if connector.list.item is None:
        return []
    root = parse_html(list_html)
    return [node.text_content() for node in select_all(root, compile_selector(connector.list.item))]


def _as_record(salary: Any) -> dict[str, Any] | None:
    if salary is None:
        return None
    return {
        "min": salary.min,
        "max": salary.max,
        "currency": salary.currency,
        "period": salary.period,
    }


def _verdicts(directory: Path) -> list[RowVerdict]:
    """Every row of one package's fixture, on the route `source()` takes."""
    connector = load_connector(directory)
    list_html = (directory / "fixture" / "list.html").read_text(errors="replace")
    items = parse_list_page(connector, list_html)
    sources = _row_sources(connector, list_html)

    detail_path = directory / "fixture" / "detail.html"
    detail = None
    detail_text = ""
    if connector.detail is not None and detail_path.exists():
        detail = parse_detail_page(connector, detail_path.read_text(errors="replace"))
        detail_text = " ".join(str(value) for value in detail.values())

    verdicts: list[RowVerdict] = []
    for index, item in enumerate(items):
        list_text = sources[index] if index < len(sources) else ""
        text = list_text
        offer, _ = _offer_from(connector, item, url=_FIXTURE_URL)
        route = "list"
        if offer is None and detail is not None:
            offer, _ = _offer_from(connector, item, detail, url=_FIXTURE_URL)
            route = "detail"
            # Both texts, because the salary can come from either and route
            # alone does not say which. `trabajos_es` is the case that settles
            # it: rows 3 and 8 reach the detail page for their *body*, and
            # their bands were in `span.salario` on the list row all along.
            # Scanning only the detail text there would look past a published
            # band — fail-open, on the two rows the connector's own comment
            # was wrong about. The cost of scanning both is nil, because a row
            # that reads a salary is not a defect however many other figures
            # it prints: only a row that publishes and reads nothing is.
            text = f"{text}\n{detail_text}"
        if offer is None:
            route = "unbuilt"
        verdicts.append(
            RowVerdict(
                index=index,
                route=route,
                publishes=_money_contexts(text),
                salary=_as_record(offer.salary if offer is not None else None),
                list_publishes=_money_contexts(list_text),
                card=card_band(list_text),
                card_single=card_figure(list_text),
                card_numbers=frozenset(_numbers_in(_flat(list_text))),
                card_mentions_period=any(
                    _PERIOD_WORD.search(window) for window in _money_contexts(list_text)
                ),
                detail_supplies_salary=route == "detail"
                and detail is not None
                and any(key.startswith("salary") for key in detail),
            )
        )
    return verdicts


def _expectations(directory: Path) -> dict[str, dict[str, Any]]:
    """`fixture/salary.json`, keyed by row index as a string. Absent means none."""
    path = directory / "fixture" / "salary.json"
    if not path.exists():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")).get("rows", {}))


def _declared_for(
    expected: dict[str, dict[str, Any]], verdict: RowVerdict
) -> tuple[dict[str, Any] | None, bool]:
    """The expectation for one row and whether `"*"` supplied it.

    `"*"` stands in for a shared detail.

    A package commits one `fixture/detail.html`, so every row of a bodiless
    board is measured against the same advert and every verdict comes out
    identical. Fifty identical entries would say no more than one does and
    would bury the fact that they are one measurement, so `"*"` is allowed to
    cover them — **and only them**. A `"*"` consulted on the list route would
    be a blanket verdict over rows that genuinely differ, which is the
    declaration-shaped answer this gate refuses, so it is not consulted there.

    Nor is it consulted for a detail-route row whose **own list text** publishes
    money: the shared detail page cannot speak for a figure the row prints
    itself, and a `"*"` that did would certify fifty different bands with one
    (foorilla_en's list cards carry five currencies; the wildcard read them all
    as one CAD band and no edit to a card could turn the gate red). Such a row
    is adjudicated by its own entry or by a refusal naming it.
    """
    row = expected.get(str(verdict.index))
    if row is None and verdict.route == "detail" and not verdict.list_publishes:
        wildcard = expected.get("*")
        return wildcard, wildcard is not None
    return row, False


def _single_figure_agrees(declared: dict[str, Any], card: tuple[float, str | None]) -> bool:
    """Does an entry's read match the one figure its card prints?

    Exactly one of `min`/`max` is set and it is that figure — which side is the
    engine's call (a floor, a ceiling), the figure is the card's. The currency
    is held only when both sides name one: usajobs' engine declares none for a
    `$` card, which is a gap in what is read and not a disagreement about it.
    """
    figure, card_currency = card
    bounds = [b for b in (declared.get("min"), declared.get("max")) if b is not None]
    declared_currency = declared.get("currency")
    currency_clash = (
        card_currency is not None
        and declared_currency is not None
        and card_currency != declared_currency
    )
    return bounds == [figure] and not currency_clash


def _pin_holds(declared: dict[str, Any], pinned: Any, card_numbers: frozenset[float]) -> bool:
    """A waived card's figures: listed, all on the card, and the entry reads
    exactly them (one bound or two)."""
    if not isinstance(pinned, list) or not pinned:
        return False
    figures = sorted(float(x) for x in pinned)
    bounds = sorted(b for b in (declared.get("min"), declared.get("max")) if b is not None)
    return all(f in card_numbers for f in figures) and bounds == figures


def _declared_band(declared: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (declared.get("min"), declared.get("max"), declared.get("currency"))


def _as_band(salary: dict[str, Any] | None) -> tuple[Any, Any, Any] | None:
    return None if salary is None else _declared_band(salary)


def _verdict_key(package: str, declared: dict[str, Any]) -> tuple[Any, ...]:
    """One adjudication: what a package's entry says is read, period included."""
    return (package, *_declared_band(declared), declared.get("period"))


def _packages(connectors_dir: Path) -> list[Path]:
    return sorted(
        directory
        for directory in connectors_dir.iterdir()
        if (directory / "connector.yaml").exists()
        and (directory / "fixture" / "list.html").exists()
    )


def measure(connectors_dir: Path = DEFAULT_CONNECTORS_DIR) -> dict[str, Any]:
    """T200's gate, over every package's own committed fixture."""
    unread: list[str] = []
    mismatched: list[str] = []
    read_rows = 0
    refused_rows = 0
    wildcard_rows = 0
    substituted_rows = 0
    uncompared: list[str] = []
    refused_for_bound_or_period = 0
    declared_uncomparable = 0
    distinct_verdicts: set[tuple[Any, ...]] = set()
    rows_measured = 0
    boards: dict[str, dict[str, Any]] = {}

    for directory in _packages(connectors_dir):
        package = directory.name
        expected = _expectations(directory)
        package_read = 0
        package_refused = 0
        for verdict in _verdicts(directory):
            rows_measured += 1
            declared, by_wildcard = _declared_for(expected, verdict)
            if (
                declared is not None
                and verdict.detail_supplies_salary
                and verdict.list_publishes
                and declared.get("list_says") != verdict.list_publishes[0]
            ):
                # The entry has to be pinned to the card it answers for. Without
                # this, a per-row entry written over a detail-route row is one
                # more declaration: editing the card's own band would leave it
                # green, which is the mutation that turned foorilla's `"*"` up.
                mismatched.append(
                    f"{package} [{verdict.index}]: the card prints "
                    f"{verdict.list_publishes[0]!r}, the entry says {declared.get('list_says')!r}"
                )
            if (
                verdict.route == "detail"
                and verdict.detail_supplies_salary
                and verdict.list_publishes
            ):
                # The salary came through the ONE committed `detail.html`, which
                # belongs to another advert, so the engine's read says nothing
                # about this row. Its own card does: the declared read has to be
                # the card's band (`card_band`, cut out of the card and read by
                # the connector engine's own `_take`), and a card whose money
                # is not a band the engine can name has to be refused.
                if verdict.card is None:
                    if declared is not None and declared.get("verdict") == "refused":
                        refused_rows += 1
                        package_refused += 1
                        refused_for_bound_or_period += _refused_for_bound_or_period(
                            declared, verdict
                        )
                    else:
                        unread.append(f"{package} [{verdict.index}]: {verdict.list_publishes[0]}")
                    continue
                if declared is None or declared.get("verdict") != "read":
                    mismatched.append(
                        f"{package} [{verdict.index}]: the card publishes {verdict.card}, "
                        "and nothing declares a read of it"
                    )
                    continue
                read_rows += 1
                package_read += 1
                if _outside_annual_bound(None, verdict.card[2], verdict.card[0], verdict.card[1]):
                    # The shared detail page is one advert's, so the engine's
                    # read says nothing about this card. The card's band still
                    # has to clear the bound the connector route applies to a
                    # band with no period, in its OWN currency: a read the
                    # engine would refuse is not a read.
                    mismatched.append(
                        f"{package} [{verdict.index}]: the card publishes {verdict.card}, "
                        "and the connector route's bound refuses it"
                    )
                elif _declared_band(declared) != verdict.card:
                    mismatched.append(
                        f"{package} [{verdict.index}]: the card publishes {verdict.card}, "
                        f"the entry declares {_declared_band(declared)}"
                    )
                elif _as_band(verdict.salary) != verdict.card:
                    substituted_rows += 1
                distinct_verdicts.add(_verdict_key(package, declared))
                continue
            if verdict.salary is not None:
                read_rows += 1
                package_read += 1
                if by_wildcard:
                    wildcard_rows += 1
                if declared is None or declared.get("verdict") != "read":
                    mismatched.append(f"{package} [{verdict.index}]: read, and nothing declares it")
                elif {k: declared.get(k) for k in ("min", "max", "currency", "period")} != (
                    verdict.salary
                ):
                    mismatched.append(
                        f"{package} [{verdict.index}]: expected {declared}, read {verdict.salary}"
                    )
                elif verdict.card is not None and _declared_band(declared) != verdict.card:
                    mismatched.append(
                        f"{package} [{verdict.index}]: the card publishes {verdict.card}, "
                        f"the entry declares {_declared_band(declared)}"
                    )
                elif verdict.card is None and verdict.card_single is not None:
                    if not _single_figure_agrees(declared, verdict.card_single):
                        mismatched.append(
                            f"{package} [{verdict.index}]: the card publishes the single "
                            f"figure {verdict.card_single}, the entry declares "
                            f"{_declared_band(declared)}"
                        )
                elif verdict.card is None and (verdict.list_publishes or verdict.route == "list"):
                    # The card carries money the audit can read neither as a band
                    # nor as one figure. It is never skipped quietly: either the
                    # entry says so, with a reason, and the row is counted under
                    # its own exact key, or it lands in `uncompared`, the key
                    # this gate drives to zero.
                    reason = declared.get("card_uncomparable") if declared else None
                    pinned = declared.get("card_figures") if declared else None
                    where = (verdict.list_publishes or ("no figure beside a currency token",))[0]
                    if not (isinstance(reason, str) and len(reason) >= _MIN_REASON):
                        uncompared.append(f"{package} [{verdict.index}]: {where}")
                    elif not _pin_holds(declared or {}, pinned, verdict.card_numbers):
                        # A waiver is not a blanket: it pins the figures the
                        # card prints, they must be on the card, and the read
                        # must be exactly them.
                        mismatched.append(
                            f"{package} [{verdict.index}]: the waiver pins {pinned}, the card "
                            f"prints {sorted(verdict.card_numbers)[:12]} and the entry reads "
                            f"{_declared_band(declared or {})}"
                        )
                    else:
                        declared_uncomparable += 1
                if declared is not None and declared.get("verdict") == "read":
                    distinct_verdicts.add(_verdict_key(package, declared))
                continue
            if declared is not None and declared.get("verdict") == "read":
                mismatched.append(
                    f"{package} [{verdict.index}]: declared read, and nothing was read"
                )
            if not verdict.publishes:
                continue
            if declared is not None and declared.get("verdict") == "refused":
                wildcard_rows += by_wildcard
                refused_rows += 1
                package_refused += 1
                refused_for_bound_or_period += _refused_for_bound_or_period(declared, verdict)
                continue
            unread.append(f"{package} [{verdict.index}]: {verdict.publishes[0]}")
        boards[package] = {"read": package_read, "refused": package_refused}

    boards_unread = len({entry.split(" ", 1)[0] for entry in unread})
    return {
        "boards_that_publish_a_salary_we_do_not_read": boards_unread,
        "salary_rows_read": read_rows,
        "salary_rows_refused": refused_rows,
        "salary_rows_refused_for_bound_or_period": refused_for_bound_or_period,
        "salary_expectation_mismatches": len(mismatched),
        "packages_measured": len(boards),
        "rows_measured": rows_measured,
        "rows_adjudicated_by_a_wildcard": wildcard_rows,
        "rows_read_through_a_substituted_detail": substituted_rows,
        "distinct_salary_verdicts_read": len(distinct_verdicts),
        "rows_read_whose_card_money_was_not_compared": len(uncompared),
        "rows_read_with_a_declared_uncomparable_card": declared_uncomparable,
        "uncompared": tuple(uncompared),
        "unread": tuple(unread),
        "mismatches": tuple(mismatched),
    }


#: The floor under what this library actually reads, and the whole anti-hollowing
#: pin. `boards_that_publish_a_salary_we_do_not_read` can be driven to zero from
#: either end — by reading a band, or by writing a refusal for it — and only one
#: of those two raises this number. A commit that answers a gap by refusing it
#: leaves the floor where it was, so the gate stays green and the diff has to
#: say out loud that nothing new is being read.
#:
#: The population is 80 — the number of *distinct verdicts* read, each one a
#: `(package, min, max, currency, period)` tuple out of the committed entries.
#: It is not a row count: rows minus wildcard rows still counts fifty identical
#: entries as fifty, and reverting to a plain row count left every test green
#: (second-reader round 2, R2). Three points of slack is the repository's margin
#: for a fixed in-repo collection.
#: arsenal-floor-margin: MINIMUM_DISTINCT_SALARY_VERDICTS_READ value=77 population=80
MINIMUM_DISTINCT_SALARY_VERDICTS_READ = 77


#: The denominator under the whole measurement: how many connector packages
#: carry a committed `fixture/list.html` for this module to walk. The
#: population is 27 and this keeps three points of slack, the margin this
#: repository uses everywhere the population is a fixed in-repo collection —
#: unlike the row floor above, packages are added and removed one at a time,
#: so three is a real buffer rather than a rounding of one fixture.
#:
#: It is here because `boards_that_publish_a_salary_we_do_not_read == 0` is
#: satisfiable by measuring nothing at all: a `_packages` that stopped finding
#: directories, or a fixture path renamed, scores a clean zero with an empty
#: scan and no other key in this record would move.
#:
#: arsenal-floor-margin: MINIMUM_PACKAGES_MEASURED value=24 population=27
MINIMUM_PACKAGES_MEASURED = 24


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    Two of the keys are **floors** and the rest are **exact**, and which is which
    is the argued part rather than a house style applied evenly.

    Floors, because they are denominators — they measure nothing about the code
    and exist only to stop a clean zero resting on an empty scan.
    `distinct_salary_verdicts_read` and `packages_measured` both move whenever a fixture is
    re-recorded or a connector lands, and two branches each adding one write the
    same `+1` with no conflict, which is the silent-merge hazard CLAUDE.md names
    from T85. A floor is a literal, so both sides changing it *is* a conflict.

    Exact, because movement in either is the finding:

    * `salary_rows_refused` is this gate's fail-open surface. A row can leave
      the unread bucket two ways — by being read, or by somebody writing a
      refusal for it — and only the first raises the read floor. Committing the
      refusals exactly is what makes the second show up as a diff a reviewer has
      to look at rather than as a number that slipped under a floor.
    * `rows_adjudicated_by_a_wildcard` is the other one. Those rows have one
      verdict repeated rather than N independent ones; it is committed exactly,
      churn included, because a number nobody is forced to read is how a
      substitution stays invisible.

    * `rows_read_through_a_substituted_detail` is the third: rows whose salary the
      engine read from the one shared `detail.html` (another advert's), so the
      engine's read is not evidence about them and only the card's own band is.
      Exact for the same reason — a number nobody is forced to read is how a
      substitution stays invisible.

    `rows_measured` is dropped: with a package floor and a read floor already
    committed it pins nothing further, and it is the most fixture-sensitive
    number here. `unread` and `mismatches` are dropped too — they name rows, so
    they belong to whoever is running the gate, not to the record.
    """
    committed = {
        key: value
        for key, value in measured.items()
        if key not in ("unread", "mismatches", "rows_measured", "uncompared")
    }
    committed.pop("salary_rows_read")
    committed.pop("distinct_salary_verdicts_read")
    committed.pop("packages_measured")
    committed["distinct_salary_verdicts_read_at_least"] = MINIMUM_DISTINCT_SALARY_VERDICTS_READ
    committed["packages_measured_at_least"] = MINIMUM_PACKAGES_MEASURED
    return committed


# No `EVIDENCE_SOURCES` declaration here, deliberately. That registry is
# `repo_gate`'s T150 gate, and joining it is a contract this measurement cannot
# meet: every registered source must *move* under a tree mutation — a Markdown
# file added, a task file archived — and must accept those populations as
# keyword arguments. This record is derived from `connectors/`, so neither
# mutation touches it, and a source that moves under no mutation makes T150
# read `unmeasured`. Declaring it and watching the gate go red is how that was
# found. The archive-stability argument the registry exists to make is made
# here by construction instead: `record` commits floors rather than the counts
# of the day, for T100's reason.


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T200.json`."""
    measured = measure()
    committed = record(measured)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="connector_salary_audit — boards that publish a salary we do not read (T200)."
    )
    parser.add_argument(
        "--census",
        action="store_true",
        help="print every row's route, money contexts and salary, and write nothing",
    )
    parser.add_argument("--package", action="append", help="limit --census to this package")
    args = parser.parse_args(argv[1:])

    if args.census:
        for directory in _packages(DEFAULT_CONNECTORS_DIR):
            if args.package and directory.name not in args.package:
                continue
            for verdict in _verdicts(directory):
                if not verdict.publishes and verdict.salary is None:
                    continue
                print(
                    json.dumps(
                        {
                            "package": directory.name,
                            "index": verdict.index,
                            "route": verdict.route,
                            "salary": verdict.salary,
                            "publishes": verdict.publishes[:1],
                            "publishes_n": len(verdict.publishes),
                        },
                        ensure_ascii=False,
                    )
                )
        return 0

    measured = write_evidence()
    print(json.dumps(record(measured), ensure_ascii=False))
    for entry in measured["unread"]:
        print(f"connector_salary_audit: unread {entry}", file=sys.stderr)
    for entry in measured["mismatches"]:
        print(f"connector_salary_audit: mismatch {entry}", file=sys.stderr)
    for entry in measured["uncompared"]:
        print(f"connector_salary_audit: uncompared {entry}", file=sys.stderr)
    return (
        1
        if measured["boards_that_publish_a_salary_we_do_not_read"]
        or measured["salary_expectation_mismatches"]
        or measured["rows_read_whose_card_money_was_not_compared"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
