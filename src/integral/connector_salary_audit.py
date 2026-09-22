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

**A known substitution, named rather than hidden.** A package commits one
`fixture/detail.html`, so a bodiless board's N rows are all measured against the
*same* advert page. That is one detail verdict repeated N times, not N
independent ones, and `detail_rows_sharing_one_fixture` reports how many rows
are in that position so the number is visible rather than inferred.

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
from pathlib import Path
from typing import Any

from integral.connectors import (
    _CURRENCIES,
    Connector,
    _json_documents,
    compile_path,
    compile_selector,
    dig_container,
    load_connector,
    parse_detail_page,
    parse_html,
    parse_list_page,
    select_all,
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


@dataclass(frozen=True)
class RowVerdict:
    """One fixture row, measured."""

    index: int
    route: str  # "list", "detail", or "unbuilt"
    publishes: tuple[str, ...]  # the money contexts found, for the report
    salary: dict[str, Any] | None


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
        text = sources[index] if index < len(sources) else ""
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
) -> dict[str, Any] | None:
    """The expectation for one row, with `"*"` standing in for a shared detail.

    A package commits one `fixture/detail.html`, so every row of a bodiless
    board is measured against the same advert and every verdict comes out
    identical. Fifty identical entries would say no more than one does and
    would bury the fact that they are one measurement, so `"*"` is allowed to
    cover them — **and only them**. A `"*"` consulted on the list route would
    be a blanket verdict over rows that genuinely differ, which is the
    declaration-shaped answer this gate refuses, so it is not consulted there.
    """
    row = expected.get(str(verdict.index))
    if row is None and verdict.route == "detail":
        return expected.get("*")
    return row


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
    shared_detail_rows = 0
    rows_measured = 0
    boards: dict[str, dict[str, Any]] = {}

    for directory in _packages(connectors_dir):
        package = directory.name
        expected = _expectations(directory)
        package_read = 0
        package_refused = 0
        for verdict in _verdicts(directory):
            rows_measured += 1
            if verdict.route == "detail":
                shared_detail_rows += 1
            declared = _declared_for(expected, verdict)
            if verdict.salary is not None:
                read_rows += 1
                package_read += 1
                if declared is None or declared.get("verdict") != "read":
                    mismatched.append(f"{package} [{verdict.index}]: read, and nothing declares it")
                elif {k: declared.get(k) for k in ("min", "max", "currency", "period")} != (
                    verdict.salary
                ):
                    mismatched.append(
                        f"{package} [{verdict.index}]: expected {declared}, read {verdict.salary}"
                    )
                continue
            if declared is not None and declared.get("verdict") == "read":
                mismatched.append(
                    f"{package} [{verdict.index}]: declared read, and nothing was read"
                )
            if not verdict.publishes:
                continue
            if declared is not None and declared.get("verdict") == "refused":
                refused_rows += 1
                package_refused += 1
                continue
            unread.append(f"{package} [{verdict.index}]: {verdict.publishes[0]}")
        boards[package] = {"read": package_read, "refused": package_refused}

    boards_unread = len({entry.split(" ", 1)[0] for entry in unread})
    return {
        "boards_that_publish_a_salary_we_do_not_read": boards_unread,
        "salary_rows_read": read_rows,
        "salary_rows_refused": refused_rows,
        "salary_expectation_mismatches": len(mismatched),
        "packages_measured": len(boards),
        "rows_measured": rows_measured,
        "detail_rows_sharing_one_fixture": shared_detail_rows,
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
#: The population is 107 — every row of every committed fixture from which the
#: engine reads a band — and seven points of slack is deliberate rather than
#: the usual three. Seventy-five of the 107 come from two packages whose rows
#: all read through one shared `fixture/detail.html` (`foorilla_en` 50,
#: `usajobs_en` 25), so re-recording either fixture moves this count in tens
#: and nothing between those steps is a meaningful margin. The floor is
#: therefore re-measured when a fixture is re-recorded, not tracked to it.
#: arsenal-floor-margin: MINIMUM_SALARY_ROWS_READ value=100 population=107
MINIMUM_SALARY_ROWS_READ = 100


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

    Two of the six keys are **floors** and two are **exact**, and which is which
    is the argued part rather than a house style applied evenly.

    Floors, because they are denominators — they measure nothing about the code
    and exist only to stop a clean zero resting on an empty scan.
    `salary_rows_read` and `packages_measured` both move whenever a fixture is
    re-recorded or a connector lands, and two branches each adding one write the
    same `+1` with no conflict, which is the silent-merge hazard CLAUDE.md names
    from T85. A floor is a literal, so both sides changing it *is* a conflict.

    Exact, because movement in either is the finding:

    * `salary_rows_refused` is this gate's fail-open surface. A row can leave
      the unread bucket two ways — by being read, or by somebody writing a
      refusal for it — and only the first raises the read floor. Committing the
      refusals exactly is what makes the second show up as a diff a reviewer has
      to look at rather than as a number that slipped under a floor.
    * `detail_rows_sharing_one_fixture` is the other one, and it is the larger
      of the two. 142 of 207 rows are measured against a `fixture/detail.html`
      belonging to a different advert, so for those rows this gate has one
      verdict repeated rather than N independent ones. It is committed exactly,
      churn included, because a number nobody is forced to read is exactly how
      a substitution this size stays invisible.

    `rows_measured` is dropped: with a package floor and a read floor already
    committed it pins nothing further, and it is the most fixture-sensitive
    number here. `unread` and `mismatches` are dropped too — they name rows, so
    they belong to whoever is running the gate, not to the record.
    """
    committed = {
        key: value
        for key, value in measured.items()
        if key not in ("unread", "mismatches", "rows_measured")
    }
    committed.pop("salary_rows_read")
    committed.pop("packages_measured")
    committed["salary_rows_read_at_least"] = MINIMUM_SALARY_ROWS_READ
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
    return (
        1
        if measured["boards_that_publish_a_salary_we_do_not_read"]
        or measured["salary_expectation_mismatches"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
