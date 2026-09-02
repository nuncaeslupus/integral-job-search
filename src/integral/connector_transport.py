"""T89 — the engine could only issue a GET, so a POST-only board was unreadable.

`ListPage.url_pattern` is a URL. Until T89 there was nowhere in the schema to
put a method or a request body, so a board whose search is a POST carrying the
whole query in its payload could not be expressed at all, however public it
was. That is the ordinary shape of a modern search back end, and
`connectors/ruled-out.yaml` carries a live example: usajobs.gov sits under
`corrected` with a measured `retest:` command — a bare `curl -X POST` under
this tool's own product token, no key, no cookie, no session — describing a
surface nothing in this repository could fetch.

## What this module measures, and why it is not circular

`boards_readable_only_by_post` counts the boards the ledger records as
answering a **POST**, for which the connector schema still cannot express that
request.

The expected request is not restated here. It is read out of the ledger's own
`retest:` command — the committed record of a request somebody measured
against the live board — and the engine's `build_list_requests` output is
compared against it, field by field: method, URL, `Content-Type`, and the body
as a parsed structure. A test written by the implementer that asserts "the
POST I built is the POST I meant" proves nothing; asserting it against a curl
line written before this module existed, from a response nobody here produced,
is a different claim.

Nothing is fetched. The ledger is committed text and the comparison is
arithmetic over it — this module has no HTTP client for the same reason
`connector_contract` has none.

## Why a POST board is detected by its retest and not by its prose

Every board in the ledger carries prose, and prose is where "the rows come
from a POST" appears for boards that are ruled out for other reasons — the
idealist.org entry says exactly that, and idealist is ruled out because the
call carries an API key, which this schema may never hold and no engine change
can fix. A **`retest:` command** is a stronger claim: it is a request that was
run, under this tool's own token, and that returned rows. Keying on it is what
keeps this gate about the engine gap rather than about every board anybody has
ever described.

## The other half: the default did not move

A POST route that quietly changed what a GET connector sends would break every
existing package silently, and a count of zero POST-only boards would still
read green. So `get_connectors_still_plain_gets` enumerates every committed
package from disk — not a list anybody has to remember to extend — and asserts
each still builds a plain GET with no body and no headers.
"""

from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    Connector,
    ConnectorError,
    build_list_requests,
    connector_packages,
    load_connector,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T89.json"
DEFAULT_LEDGER_PATH = DEFAULT_CONNECTORS_DIR / "ruled-out.yaml"

#: curl options that consume the token after them. Anything else beginning
#: with `-` is a bare flag, and the first remaining positional that looks like
#: a URL is the request target. Without this set `-A "integral-job-search/…"`
#: would be read as the URL.
_VALUE_OPTIONS = frozenset(
    {
        "-X",
        "--request",
        "-H",
        "--header",
        "-d",
        "--data",
        "--data-raw",
        "--data-binary",
        "--data-ascii",
        "-A",
        "--user-agent",
        "-e",
        "--referer",
        "-o",
        "--output",
        "-u",
        "--user",
        "-b",
        "--cookie",
        "-w",
        "--write-out",
        "--connect-timeout",
        "-m",
        "--max-time",
    }
)

#: A ledger that parsed to almost nothing is a scan that measured nothing, not
#: a board with no problems — the same floor `connectors.MINIMUM_PROBES` sets
#: for its own probe run. The committed ledger holds 24 board entries.
MINIMUM_LEDGER_ENTRIES = 10


@dataclass(frozen=True)
class RecordedRequest:
    """The request a ledger entry's `retest:` command actually makes."""

    site: str
    url: str
    method: str
    headers: dict[str, str]
    body: str | None


def _entries(node: Any) -> list[dict[str, Any]]:
    """Every board entry in the ledger, wherever a section happens to nest it.

    A board is a mapping carrying a `site`. The ledger's sections are lists in
    most places and a mapping-of-lists under `engine_gap_json`, and both are
    real shapes it uses today — walking for the marker key rather than for a
    known layout means a section added later is scanned without anybody
    remembering to name it here.
    """
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("site"), str):
            found.append(node)
        for value in node.values():
            found.extend(_entries(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_entries(item))
    return found


def parse_curl(command: str) -> RecordedRequest | None:
    """The request a `retest:` curl makes, or `None` if it is not a POST.

    Tokenised with `shlex`, never run: the ledger is committed text, but a
    module that executed a string out of a data file would be exactly the
    "a connector is data, not code" line crossed one directory over. The
    command is cut at the first pipe — every retest in the ledger pipes curl
    into a counter, and the counter is not part of the request.
    """
    tokens = shlex.split(command)
    if "|" in tokens:
        tokens = tokens[: tokens.index("|")]
    if not tokens or tokens[0] != "curl":
        return None

    method = "GET"
    url: str | None = None
    headers: dict[str, str] = {}
    body: str | None = None

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in _VALUE_OPTIONS:
            value = tokens[index + 1] if index + 1 < len(tokens) else ""
            if token in {"-X", "--request"}:
                method = value.upper()
            elif token in {"-H", "--header"} and ":" in value:
                name, _, contents = value.partition(":")
                headers[name.strip()] = contents.strip()
            elif token in {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii"}:
                body = value
                # curl's own behaviour: data without an explicit -X is a POST.
                if method == "GET":
                    method = "POST"
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if url is None and token.startswith(("http://", "https://")):
            url = token
        index += 1

    if method != "POST" or url is None:
        return None
    return RecordedRequest(site="", url=url, method=method, headers=headers, body=body)


def recorded_post_boards(ledger: Path = DEFAULT_LEDGER_PATH) -> tuple[list[RecordedRequest], int]:
    """Every board whose committed retest is a POST, and how many were scanned."""
    document = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    entries = _entries(document)
    posts = []
    for entry in entries:
        retest = entry.get("retest")
        if not isinstance(retest, str):
            continue
        request = parse_curl(retest)
        if request is not None:
            posts.append(
                RecordedRequest(
                    site=entry["site"],
                    url=request.url,
                    method=request.method,
                    headers=request.headers,
                    body=request.body,
                )
            )
    return posts, len(entries)


def _probe_connector(recorded: RecordedRequest) -> Connector:
    """A connector declaring exactly the request the ledger recorded.

    Built as a **structure**, never as a YAML string with the URL and body
    interpolated into it: templating a connector file out of external text to
    test that connectors are not templates would be a poor joke. The list
    route below is markup and is never parsed — this probe asks one question,
    "what request does the engine issue", and reading the response is a
    separate concern this module has no fixture for.
    """
    body = json.loads(recorded.body) if recorded.body else None
    return Connector.model_validate(
        {
            "site": "probe",
            "locale": "en",
            "version": "1.0.0",
            "last_verified": "2026-01-01",
            "auth": "none",
            "list": {
                "url_pattern": recorded.url,
                "method": recorded.method,
                "body_json": body,
                "item": ".result",
                "fields": {"title": {"css": ".title"}, "text": {"css": ".body"}},
            },
        }
    )


def why_unreadable(recorded: RecordedRequest) -> list[str]:
    """Every way the engine still fails to issue the recorded request."""
    try:
        connector = _probe_connector(recorded)
    except (ConnectorError, ValueError) as exc:
        return [f"{recorded.site}: the schema cannot express the recorded request: {exc}"]

    requests = build_list_requests(connector)
    if not requests:
        return [f"{recorded.site}: the engine builds no request at all"]
    built = requests[0]

    reasons: list[str] = []
    if built.method != recorded.method:
        reasons.append(f"{recorded.site}: method is {built.method}, recorded {recorded.method}")
    if built.url != recorded.url:
        reasons.append(f"{recorded.site}: url is {built.url}, recorded {recorded.url}")
    expected_type = recorded.headers.get("Content-Type")
    if expected_type is not None and built.headers.get("Content-Type") != expected_type:
        reasons.append(
            f"{recorded.site}: Content-Type is {built.headers.get('Content-Type')!r}, "
            f"recorded {expected_type!r}"
        )
    if recorded.body:
        if built.body is None:
            reasons.append(f"{recorded.site}: the engine sends no body")
        elif json.loads(built.body.decode("utf-8")) != json.loads(recorded.body):
            reasons.append(
                f"{recorded.site}: body is {built.body.decode('utf-8')}, recorded {recorded.body}"
            )
    return reasons


def get_packages_that_changed(directory: Path = DEFAULT_CONNECTORS_DIR) -> tuple[list[str], int]:
    """Committed GET packages that no longer build a plain GET, and how many ran.

    Enumerated from disk so a package added after T89 is covered without
    anybody remembering to list it.
    """
    changed: list[str] = []
    checked = 0
    for package in connector_packages(directory):
        connector = load_connector(package)
        if connector.list.method != "GET":
            continue
        checked += 1
        for request in build_list_requests(connector):
            if request.method != "GET" or request.body or request.headers:
                changed.append(package.name)
                break
    return changed, checked


def measure(
    ledger: Path = DEFAULT_LEDGER_PATH, directory: Path = DEFAULT_CONNECTORS_DIR
) -> dict[str, Any]:
    """T89's reading: `boards_readable_only_by_post`, with both denominators."""

    def _unmeasured(reason: str) -> dict[str, Any]:
        return {
            "boards_readable_only_by_post": 0,
            "boards_readable_only_by_post_evaluated": 0,
            "ledger_entries_scanned": 0,
            "get_connectors_still_plain_gets": 0,
            "get_connectors_evaluated": 0,
            "unreadable": [],
            "get_packages_changed": [],
            "gate_status": "unmeasured",
            "unmeasured_reason": reason,
        }

    try:
        posts, scanned = recorded_post_boards(ledger)
    except (OSError, yaml.YAMLError) as exc:
        return _unmeasured(f"the ruled-out ledger could not be read: {exc}")
    if scanned < MINIMUM_LEDGER_ENTRIES:
        return _unmeasured(
            f"only {scanned} board entr(y/ies) in the ledger (floor {MINIMUM_LEDGER_ENTRIES}) "
            "— a scan over nothing is not a pass"
        )
    if not posts:
        return _unmeasured("no board in the ledger records a POST retest command")

    unreadable = [reason for recorded in posts for reason in why_unreadable(recorded)]
    changed, get_checked = get_packages_that_changed(directory)
    if get_checked == 0:
        return _unmeasured("no committed connector package declares a GET listing")

    return {
        # The boards the ledger records as answering a POST that the engine
        # still cannot issue. One entry qualifies today (usajobs.gov); the
        # count is of failures, so it stays honest as the ledger grows.
        "boards_readable_only_by_post": len({reason.split(":")[0] for reason in unreadable}),
        "boards_readable_only_by_post_evaluated": len(posts),
        "ledger_entries_scanned": scanned,
        "get_connectors_still_plain_gets": get_checked - len(changed),
        "get_connectors_evaluated": get_checked,
        "unreadable": unreadable,
        "get_packages_changed": changed,
        "gate_status": "measured",
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    ledger: Path = DEFAULT_LEDGER_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T89.json`."""
    measured = measure(ledger, directory)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connector_transport [evidence-path]` → T89's evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 3
    for reason in measured["unreadable"]:
        print(f"still unreadable: {reason}", file=sys.stderr)
    for name in measured["get_packages_changed"]:
        print(f"{name} no longer builds a plain GET — the default moved", file=sys.stderr)
    if measured["boards_readable_only_by_post"] or measured["get_packages_changed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
