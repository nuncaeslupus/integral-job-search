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
`url_pattern` with one **filled** query `q` in every `{query}` slot and an
ASCII page number in `{page}`. The whole URL is matched rather than a key
looked up, so a renamed key, a moved segment, a changed path and a fixed
duplicate of the key all fail without anyone listing them.

**Filled, as a round trip rather than a grammar.** Two rounds of the second
read on #461 each found holes in a *description* of a good value. The first
listed delimiters and left `& # ?` untested. The second listed an alphabet
and left the shape of a `%` escape, `all()` over the slots, and the component
test unpinned. Neither description had a last element, so the rule no longer
describes. Each slot's raw text is decoded to `q`, and `q` must re-encode to
exactly that text:

* as `quote(q, safe="")`, which is how `build_list_urls` writes it;
* or, in the query component only, as `quote_plus(q, safe="")`, the form
  encoding a browser capture writes (`landingjobs_en`'s
  `q=artificial+intelligence`).

A raw delimiter, a malformed `%`, an escaped unreserved character or `%FF`
therefore fails, because none of them is a spelling the encoder produces. Then
three conditions on `q` itself:

* It is the **same** `q` in every slot. The connector substitutes one query,
  so two slots holding two different values is a request it never sends.
* It is not blank by the connector's own test (`not query.strip()`). An empty
  `q=` asks for nothing, and the answer is the board's whole list.
* It does not contain `{query}`, however that was escaped, which rules out a
  capture copied from the pattern.

**Where a slot is.** `urlsplit` decides which component each slot is in,
following RFC 3986's grammar. A slot in the path must not decode to `.` or
`..`: §3.3 names those dot-segments, and §5.2.4 removes them, taking the query
with them. A slot in the fragment, the host or the scheme is never measured.
§3.5 keeps the fragment with the client, so a board is never asked it.

Only the page's value is left free, since it is T113's to certify. It must
still be ASCII digits: `\\d` would accept `٢`, which the connector never
writes.

**What this does not establish.** A capture carrying the key shows the board
was asked with it, not that the answer depended on it. That second fact is
measured by hand when a probe is recorded: a nonsense term must change the
rows. It is written beside the package's `url_pattern` (see `jobfluent_es`).
Nothing reads it back. Nothing here reads a response body either, for the
reason T113 gives.

This rule also does not require the capture to declare how it was made. An
`unrecorded` capture passes if its URL fits. That is T113's posture:
provenance is `integral.capture_provenance`'s question, not this one.

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
from urllib.parse import quote, quote_plus, unquote, unquote_plus, urlsplit

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

#: What a slot's raw text may run to before the canonical check reads it: up to
#: the characters that end a path segment (RFC 3986 §3.3) or a query pair.
#: This only splits the URL. It is not the rule. A value that swallows a
#: delimiter fails the round trip anyway.
_PATH_SLOT = r"([^/?#]*)"
_QUERY_SLOT = r"([^&#]*)"

#: RFC 3986 §3.3's dot-segments, which §5.2.4 removes from a path.
_DOT_SEGMENTS = frozenset({".", ".."})


def _slot_components(url_pattern: str) -> list[bool] | None:
    """For each `{query}` slot in order, whether it is in the query component.

    `None` when a slot is anywhere else (scheme, host, fragment), which is a
    place no request carries a search.
    """
    parts = urlsplit(url_pattern)
    in_path = parts.path.count(QUERY_PLACEHOLDER)
    in_query = parts.query.count(QUERY_PLACEHOLDER)
    if in_path + in_query != url_pattern.count(QUERY_PLACEHOLDER):
        return None
    return [False] * in_path + [True] * in_query


def _decoded(raw: str, in_query_component: bool) -> str | None:
    """The query `raw` spells, when it is filled and spelled as an encoder would."""
    # Only the decoding differs by component. In a path `unquote` leaves `+`
    # alone, so `quote_plus` of the result spells nothing `quote` does not.
    value = unquote_plus(raw) if in_query_component else unquote(raw)
    spellings = {quote(value, safe=""), quote_plus(value, safe="")}
    if raw not in spellings or not value.strip() or QUERY_PLACEHOLDER in value:
        return None
    if not in_query_component and value in _DOT_SEGMENTS:
        return None
    return value


def query_measured(url_pattern: str, captured: str | None) -> bool:
    """Is `captured` a URL `url_pattern` issues for one filled query?"""
    components = _slot_components(url_pattern)
    if captured is None or components is None:
        return False
    slots = iter(components)
    regex = "".join(
        "[0-9]+"
        if part == PAGE_PLACEHOLDER
        else (_QUERY_SLOT if next(slots) else _PATH_SLOT)
        if part == QUERY_PLACEHOLDER
        else re.escape(part)
        for part in re.split(r"(\{page\}|\{query\})", url_pattern)
    )
    match = re.fullmatch(regex, captured)
    if match is None:
        return False
    queries = {_decoded(raw, slot) for raw, slot in zip(match.groups(), components, strict=True)}
    return len(queries) == 1 and None not in queries


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
