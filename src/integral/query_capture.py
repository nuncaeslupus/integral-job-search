"""T171: a steerable connector's query must sit where a capture recorded one.

A connector whose `list.url_pattern` carries `{query}` (`connectors.accepts_query`)
was proven to *send* the candidate's terms and never that the board *reads*
them. Found by the second reader on #447: swapping `trabajos_es`'s
`?CADENA={query}` for `?q={query}`, a key trabajos.com ignores and answers with
forty unrelated adverts, passed every test and `make evidence`. `jobfluent_es`
shipped the same hole on `main`: `?q={query}&page={page}` over a probe of
`?page=2`, so no capture had ever carried `q`.

This is T113's rule (`integral.pagination_capture`) applied to the other
placeholder. A key present in a **recorded request** says what the board was
asked, and only that certifies the key a fetcher relies on.

**The rule.** For every package where `accepts_query` is true,
`probe/captured.json`'s `url` must be a URL the connector could issue. That is
`url_pattern` with every `{query}` bound to a **filled** value and `{page}` to
a number. Whether the query sits in a query-string key or in a path segment
makes no difference, because the whole URL is matched rather than a key looked
up. So a renamed key, a moved segment, a changed path and a fixed duplicate of
the key all fail, and nobody has to list them.

*Filled* means at least one character, none of them a URL delimiter
(`& # / ?`) or a brace. An empty `q=` asks the board for nothing, which is the
unfiltered list rather than evidence that it reads `q`. A brace rules out the
cheapest forgery, a capture that copies `url_pattern` with `{query}` still in
it. Only the page number is left free, since it is T113's to certify.

**What this does not establish.** A capture carrying the key shows the board
was asked with it, not that the answer depended on it. That second fact is
measured by hand when a probe is recorded: a nonsense term must change the
rows. It is written beside the package's `url_pattern` (see `jobfluent_es`).
Nothing reads it back. Nothing here reads a response body either, for the
reason T113 gives.

**The denominator is the steerable packages checked**, committed as a literal
floor rather than the count of the day (T100, T122). Otherwise a library that
lost its steerable boards would score a clean zero. A breach exits **1**, not 3,
for T115's reason, as `capture_provenance` does.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.connector_coverage import is_example_site, read_package
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    PAGE_PLACEHOLDER,
    QUERY_PLACEHOLDER,
    ConnectorError,
    accepts_query,
    load_connector,
)
from integral.pagination_capture import read_capture

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T171.json"

#: Four steerable packages ship on `main` today: `foorilla_en`,
#: `jobfluent_es`, `landingjobs_en` and `tecnoempleo_es`. The floor sits at
#: that population, so losing any one of them reads `unmeasured` rather than a
#: clean zero over fewer. The margin it keeps later is whatever the library has
#: grown by, and that is deliberate: a floor raised with every new steerable
#: board would turn retiring one into a gate failure, which T100 ruled out.
MINIMUM_STEERABLE_PACKAGES_CHECKED = 4

#: What a filled `{query}` may be: one or more characters, none a delimiter
#: that would end the URL position it sits in, and no brace.
_FILLED = r"[^&#/?{}]+"


def query_measured(url_pattern: str, captured: str | None) -> bool:
    """Is `captured` a URL `url_pattern` issues, with every `{query}` filled?"""
    if captured is None:
        return False
    pattern = "".join(
        r"\d+"
        if part == PAGE_PLACEHOLDER
        else _FILLED
        if part == QUERY_PLACEHOLDER
        else re.escape(part)
        for part in re.split(r"(\{page\}|\{query\})", url_pattern)
    )
    return re.fullmatch(pattern, captured) is not None


@dataclass(frozen=True)
class Finding:
    """One steerable package whose query position no capture measured."""

    package: str
    reason: str

    def as_row(self) -> dict[str, str]:
        # Fail-open by construction: the package sends the candidate's terms
        # somewhere no board was ever asked with them, and the board answers
        # with whatever it has, as if searched.
        return {"package": self.package, "reason": self.reason, "direction": "fail-open"}


def check_package(package: Path) -> tuple[Finding | None, int]:
    """One package: its finding (if any), and 1 if it was steerable, else 0."""
    try:
        connector = load_connector(package)
    except ConnectorError as exc:
        # Fail-closed, as in T113: whether an unreadable package is steerable
        # is unknown, and skipping it would score it as clean.
        return Finding(package.name, f"connector.yaml did not load: {exc}"), 1
    if not accepts_query(connector):
        return None, 0
    pattern = connector.list.url_pattern
    capture = read_capture(package)
    if query_measured(pattern, capture.url):
        return None, 1
    return (
        Finding(
            package.name,
            f"the captured URL {capture.url!r} ({capture.provenance}) is not {pattern!r} "
            f"with {QUERY_PLACEHOLDER} filled",
        ),
        1,
    )


def measure(directory: Path | None = None) -> dict[str, Any]:
    """Every steerable package whose query position no capture measured."""
    directory = DEFAULT_CONNECTORS_DIR if directory is None else directory
    packages = sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []

    examples: list[str] = []
    findings: list[Finding] = []
    checked = 0
    for package in packages:
        if is_example_site(read_package(package).site):
            examples.append(package.name)
            continue
        finding, steerable = check_package(package)
        checked += steerable
        if finding is not None:
            findings.append(finding)

    measured: dict[str, Any] = {
        "steerable_queries_no_capture_measured": len(findings),
        "steerable_packages_checked": checked,
        "example_packages_excluded": examples,
        "findings": [finding.as_row() for finding in findings],
        "gate_status": "measured",
    }
    if checked < MINIMUM_STEERABLE_PACKAGES_CHECKED:
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {checked} steerable package(s) (floor {MINIMUM_STEERABLE_PACKAGES_CHECKED}) "
            "— zero unmeasured queries over a library nobody read is not a pass"
        )
    return measured


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: the live count is dropped and the floor stands in."""
    committed = {k: v for k, v in measured.items() if k != "steerable_packages_checked"}
    committed["steerable_packages_checked_at_least"] = MINIMUM_STEERABLE_PACKAGES_CHECKED
    return committed


def write_evidence(evidence: Path | None = None, directory: Path | None = None) -> dict[str, Any]:
    """Measure and record `status/evidence/T171.json`; nothing on a breach."""
    evidence = DEFAULT_EVIDENCE_PATH if evidence is None else evidence
    measured = measure(directory)
    if measured["gate_status"] == "unmeasured":
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.query_capture [evidence-path]` → exit 0, or 1."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else None)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 1
    for row in measured["findings"]:
        print(f"{row['direction']}: {row['package']} — {row['reason']}", file=sys.stderr)
    return 1 if measured["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
