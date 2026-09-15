"""T144 — sourcing that reads the employer's own board, not only aggregators.

The offer that ended this tool's first complete run was found on the
employer's own posting, never on an aggregator. Every connector until this task
pointed at an aggregator or a job board. An **ATS host** — Greenhouse, Lever,
Ashby, Workable, Rippling — serves thousands of employers behind one URL shape,
so one package with an `{employer}` slot and a `list.employers` table reaches
every employer it lists (`connectors.EMPLOYER_PLACEHOLDER`).

What counts, per package that carries that slot **and** declares
`source_kind: employer` (T172): the slot alone is not an ATS host, since a job
board's company page takes one too.

- it passes T53's contract pack (`connector_contract.check_package`) — its
  fixture parses to an offer, so the package is not a file that fetches nothing;
- it has a row in `connectors/robots-adjudications.yaml` for **its own host**,
  whose `problems()` are empty, and whose recorded answer — the committed
  `robots_txt`, or the `robots_status` a server gave instead of a file — when
  **replayed through `integral.robots`**, admits every URL the package fetches.
  A row's shape is not a verdict: a well-formed row can refuse its own path.

The count is of **distinct hosts**, so a second package pointed at the same API
cannot raise it.

The committed value is the floor it cleared, never above it (T100's reason: an
exact package total drifts on the next connector anyone adds). Below the floor
the measured value is committed, and the gate reads it and fails.

T172 adds `source_kind_defects` to the same record (`measure_attribution`). A
result read from the employer's own board has to say so, both on the stored
offer and in the round summary, and a job board's result must not.
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
from pathlib import Path
from typing import Any, get_args
from urllib.parse import urlsplit

from integral.connector_contract import check_package
from integral.connector_policy import (
    DEFAULT_ADJUDICATIONS_PATH,
    RobotsAdjudication,
    adjudications,
)
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    EMPLOYER_PLACEHOLDER,
    ConnectorError,
    ListRequest,
    build_list_urls,
    load_connector,
    source_kind_of,
)
from integral.offers import SourceKind
from integral.robots import Robots, RobotsError

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T144.json"

#: The gate's floor, `ats_host_connectors_conforming >= 5`.
MINIMUM_CONFORMING = 5


def measure(
    directory: Path = DEFAULT_CONNECTORS_DIR,
    ledger: Path = DEFAULT_ADJUDICATIONS_PATH,
) -> dict[str, Any]:
    """Every ATS-host package in `directory`, and which of them conform."""
    rows = {row.package: row for row in adjudications(ledger)}
    hosts: set[str] = set()
    not_conforming: dict[str, list[str]] = {}
    employers = 0
    for package in sorted(p for p in directory.iterdir() if (p / "connector.yaml").is_file()):
        try:
            connector = load_connector(package)
        except (ConnectorError, OSError):
            continue  # not an ATS package we can recognise; T53 reports it
        pattern = connector.list.url_pattern
        # Both, and neither alone. The slot is what makes one package reach
        # thousands of employers, which is T144's whole economy; the
        # declaration is what makes those boards the employers' own. A job
        # board's company page — `indeed.com/cmp/{employer}/jobs` — takes the
        # slot and is not an ATS host, so counting by the slot alone counts it
        # (T172's F1, inside T144's own gate). A package that is an ATS host
        # and forgets to declare drops the count below the floor, which is the
        # direction this should fail in.
        if EMPLOYER_PLACEHOLDER not in pattern or source_kind_of(connector) != "employer":
            continue
        why = list(check_package(package).violations)
        row = rows.get(f"connectors/{package.name}")
        if row is None:
            why.append("no row in connectors/robots-adjudications.yaml")
        else:
            why += row.problems() + _replay(row, build_list_urls(connector, query="python"))
        if why:
            not_conforming[package.name] = why
            continue
        hosts.add(urlsplit(pattern).hostname or "")
        employers += len(connector.list.employers)
    return {
        "ats_host_connectors_conforming": len(hosts),
        "conforming_hosts": sorted(hosts),
        "employers_listed": employers,
        "not_conforming": not_conforming,
    }


def _replay(row: RobotsAdjudication, urls: list[str]) -> list[str]:
    """Why `row` does not admit every one of `urls` when its answer is re-asked.

    Every URL, not the first: one verdict covers every employer on the host
    only once it has been asked about every employer's path. A row disallowing
    `/v0/postings/` but allowing one slug admitted that slug and counted (#445
    round 2, B1).
    """
    hosts = sorted({urlsplit(url).hostname or "" for url in urls})
    if hosts != [row.site]:
        return [f"the robots row is for {row.site!r}, and the package fetches {hosts!r}"]
    if row.robots_txt.strip():
        answer = row.robots_txt

        def fetch(robots_url: str) -> str:
            return answer

    elif row.robots_status is not None:
        status = row.robots_status

        def fetch(robots_url: str) -> str:
            raise urllib.error.HTTPError(robots_url, status, "recorded", {}, None)  # type: ignore[arg-type]

    else:
        return ["the robots row records neither robots_txt nor robots_status — nothing to replay"]
    robots = Robots(fetch=fetch, browser_fetch=fetch)
    try:
        return [
            f"the recorded robots.txt disallows {url}" for url in urls if not robots.allows(url)
        ]
    except RobotsError as exc:
        return [f"the recorded robots answer refuses the host: {exc}"]


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: the floor once cleared, and nothing that grows with it.

    `conforming_hosts` and `employers_listed` move whenever a package or an
    employer is added, so they are printed by `_main` and never committed.
    """
    count = measured["ats_host_connectors_conforming"]
    return {
        "ats_host_connectors_conforming": min(count, MINIMUM_CONFORMING),
        "ats_host_connectors_floor": MINIMUM_CONFORMING,
        "not_conforming": measured["not_conforming"],
    }


#: T172's constructed round, as a closed product rather than a list of cases.
#: Two axes decide what a board's results are: what it **declares**, and what
#: comes **back**.
#:
#: - every declarable kind: each `SourceKind` value, plus undeclared;
#: - crossed with one request (no slot) or two (an `{employer}` slot, two
#:   employers), so a board can fail part-way;
#: - crossed with every way a request can answer, below.
#:
#: A kind added to `SourceKind`, or an answer added here, joins the round
#: without anyone remembering to (#462 rounds 2 and 3, G1/G4/H1).
ATTRIBUTION_RESPONSES = ("offer", "known", "norows", "badrow", "timeout", "refused")
#: The text a `known` answer returns. Planted in the store before the round, so
#: re-sighting it builds an offer that adds nothing — `added` is 0 where
#: `items` is not (#462 round 3, H1).
ATTRIBUTION_KNOWN_TEXT = "an advert this candidate was already shown"
ATTRIBUTION_BOARDS: dict[str, tuple[SourceKind | None, tuple[str, ...]]] = {
    f"{kind or 'undeclared'}{'slot' if len(answers) == 2 else 'plain'}{''.join(answers)}": (
        kind,
        answers,
    )
    for kind in (*get_args(SourceKind), None)
    for answers in (
        *((one, two) for one in ATTRIBUTION_RESPONSES for two in ATTRIBUTION_RESPONSES),
        *((one,) for one in ATTRIBUTION_RESPONSES),
    )
}
EMPLOYER_BOARDS_LINE = "  the employers' own boards, not a job board: "


def attribution_reads(answers: tuple[str, ...]) -> tuple[str, ...]:
    """The answers a round actually gets: a refusal ends that board's reading.

    The spec's own model, never the code's: `sourcing` returning on a refusal
    is what `#445` F4 settled, and a round that fetched past one would be the
    defect rather than a new expectation.
    """
    reads: list[str] = []
    for answer in answers:
        reads.append(answer)
        if answer == "refused":
            break
    return tuple(reads)


def attribution_expectations() -> tuple[dict[str, SourceKind | None], set[str], list[str]]:
    """What the table requires, derived before anything runs.

    Returns the kind each board's offers must carry, the boards that must store
    a **new** offer, and the boards the summary must name — a declared
    employer's board one of whose rows became an offer, re-sighted or not.
    """
    kinds = {site: kind for site, (kind, _) in ATTRIBUTION_BOARDS.items()}
    must_store = {
        site
        for site, (_, answers) in ATTRIBUTION_BOARDS.items()
        if "offer" in attribution_reads(answers)
    }
    named = sorted(
        f"{site}_en"
        for site, (kind, answers) in ATTRIBUTION_BOARDS.items()
        if kind == "employer"
        and any(read in ("offer", "known") for read in attribution_reads(answers))
    )
    return kinds, must_store, named


def attribution_verdict(
    stored: list[tuple[str, SourceKind | None]], summary: str
) -> dict[str, Any]:
    """Judge one round's stored offers and summary against the table.

    Split from the round so the `-1` rule can be checked for **every** board
    that should store, without running the round once per board (#462 round 3,
    H2/H3). `stored` is `(source, source_kind)` per offer the round wrote.
    """
    kinds, must_store, named = attribution_expectations()
    defects = [
        f"{source}: stored source_kind {kind!r}"
        for source, kind in stored
        if source not in kinds or kind != kinds[source]
    ]
    defects += [
        f"{source}: stored an offer from a board that never read one"
        for source, _ in stored
        if source in kinds and source not in must_store
    ]
    lines = [line for line in summary.split("\n") if line.startswith(EMPLOYER_BOARDS_LINE)]
    if lines != [EMPLOYER_BOARDS_LINE + ", ".join(named)]:
        defects.append(f"the summary's employers line reads {lines!r}")
    silent = sorted(must_store - {source for source, _ in stored})
    return {
        # `-1`, not a clean zero: a board that stored nothing has a label
        # nobody checked, so the round is unmeasured rather than clean.
        "source_kind_defects": len(defects) if not silent else -1,
        "source_kind_offers_checked": len(stored),
        "source_kind_defect_list": defects,
        "source_kind_boards_silent": silent,
    }


def attribution_round() -> tuple[list[tuple[str, SourceKind | None]], str]:
    """Run `ATTRIBUTION_BOARDS` through `sourcing.source` once.

    Constructed rather than read from the library, for two reasons. The ATS
    packages are `GLOBAL`, which `sourcing.packages_for` never selects (T167).
    And a metric over the committed packages would move whenever one is added.
    """
    from integral.candidate import Aim, CandidateConstraints, Location
    from integral.identity import ProfileStore, create_profile
    from integral.lifecycle import collect_offer, load_lifecycle_offer
    from integral.offers import Offer, compute_offer_id
    from integral.sourcing import Response, source

    at = "2026-01-01T00:00:00+00:00"
    meta = (DEFAULT_CONNECTORS_DIR / "greenhouse_en" / "meta.yaml").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "connectors"
        for site, (kind, answers) in ATTRIBUTION_BOARDS.items():
            slot = len(answers) == 2
            package = directory / f"{site}_en"
            package.mkdir(parents=True)
            url = (
                f"https://{site}.test/b/{{employer}}/jobs" if slot else f"https://{site}.test/jobs"
            )
            (package / "connector.yaml").write_text(
                f"site: {site}\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-09-10'\n"
                + (f"source_kind: {kind}\n" if kind else "")
                + f"list:\n  url_pattern: '{url}'\n  pagination: {{mode: none, max_pages: 1}}\n"
                "  from_json:\n    items: jobs\n    fields: {title: title, text: body}\n"
                + ("  employers:\n    acme: Acme\n    beta: Beta\n" if slot else ""),
                encoding="utf-8",
            )
            (package / "meta.yaml").write_text(meta.replace("GLOBAL", "ES"), encoding="utf-8")
        create_profile(Path(tmp) / "p", "Fixture", handle="fixture", language="en", fiction=True)
        store = ProfileStore(Path(tmp) / "p", "fixture")
        # The `known` advert, already in the store before the round reads it.
        planted = Offer(
            id=compute_offer_id(ATTRIBUTION_KNOWN_TEXT),
            source="planted",
            text=ATTRIBUTION_KNOWN_TEXT,
        )
        collect_offer(store, planted, at=at)

        def fetch(request: ListRequest) -> Response:
            parts = urlsplit(request.url)
            site = (parts.hostname or "").removesuffix(".test")
            answers = ATTRIBUTION_BOARDS[site][1]
            index = 1 if parts.path.split("/")[2:3] == ["beta"] else 0
            answer = answers[index]
            if answer == "timeout":
                return Response(None, "", error="timed out")
            if answer == "refused":
                return Response(429, json.dumps({"jobs": []}))
            if answer == "norows":
                return Response(200, json.dumps({"jobs": []}))
            if answer == "badrow":
                return Response(200, json.dumps({"jobs": [{"title": f"{site}{index}"}]}))
            body = ATTRIBUTION_KNOWN_TEXT if answer == "known" else f"an advert at {site} {index}"
            return Response(200, json.dumps({"jobs": [{"title": f"{site}{index}", "body": body}]}))

        run = source(
            store,
            CandidateConstraints(
                location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
            ),
            # T167 filters an unsteered board's rows by phrase; every
            # constructed row that has a body (the "offer" and "known"
            # answers) carries the word "advert", and none of the others
            # (badrow, norows, refused, timeout) has any text to match
            # regardless of the phrase chosen, so this is the one term that
            # neither starves the matrix nor privileges any one board.
            Aim(state="stated", terms=("advert",)),
            fetch=fetch,
            at=at,
            directory=directory,
            robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        )
        stored = [
            (offer.source, offer.source_kind)
            for path in store.path("offers").glob("sha256:*.json")
            for offer in [load_lifecycle_offer(store, path.stem)[0]]
            if offer.id != planted.id
        ]
    return stored, run.summary()


def measure_attribution() -> dict[str, Any]:
    """T172: what one `attribution_round` stored and reported, judged by the table.

    - Every stored offer carries exactly its board's **declared** kind. The
      `{employer}` slot never decides it: a job board's company page takes one
      too (F1).
    - The summary's employers line names exactly the declared employer boards
      one of whose rows became an offer. A board that answered with no rows, or
      with rows that build no offer, gave no result to name (T144: "where each
      result came from"); one refused after reading some did (F3, G3, H1/H2).
    """
    stored, summary = attribution_round()
    return attribution_verdict(stored, summary)


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    attribution = measure_attribution()
    committed = {
        **record(measure()),
        "source_kind_defects": attribution["source_kind_defects"],
        "source_kind_offers_checked": attribution["source_kind_offers_checked"],
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return committed


def _main(argv: list[str]) -> int:
    """`python -m integral.employer_boards` — measure, record, exit 1 below the floor."""
    measured = measure()
    committed = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    if committed["source_kind_defects"] != 0:
        print(f"source_kind_defects = {committed['source_kind_defects']}", file=sys.stderr)
        return 1
    if measured["ats_host_connectors_conforming"] < MINIMUM_CONFORMING:
        print(
            f"only {measured['ats_host_connectors_conforming']} ATS host(s) conform "
            f"(floor {MINIMUM_CONFORMING})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
