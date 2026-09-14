"""T144 — sourcing that reads the employer's own board, not only aggregators.

The offer that ended this tool's first complete run was found on the
employer's own posting, never on an aggregator. Every connector until this task
pointed at an aggregator or a job board. An **ATS host** — Greenhouse, Lever,
Ashby, Workable, Rippling — serves thousands of employers behind one URL shape,
so one package with an `{employer}` slot and a `list.employers` table reaches
every employer it lists (`connectors.EMPLOYER_PLACEHOLDER`).

What counts, per package whose `url_pattern` carries that slot:

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
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from typing import Any
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
    build_list_urls,
    load_connector,
)
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
        if EMPLOYER_PLACEHOLDER not in pattern:
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


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    committed = record(measure())
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return committed


def _main(argv: list[str]) -> int:
    """`python -m integral.employer_boards` — measure, record, exit 1 below the floor."""
    measured = measure()
    write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
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
