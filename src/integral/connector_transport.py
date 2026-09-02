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
    credential_keys,
    credential_query_keys,
    load_connector,
    names_a_credential,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T89.json"
DEFAULT_LEDGER_PATH = DEFAULT_CONNECTORS_DIR / "ruled-out.yaml"
#: The audit's credential-key cases, committed as data so the gate measures
#: them rather than the suite merely asserting them.
DEFAULT_CREDENTIAL_CASES_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "connectors" / "credential_keys.yaml"
)

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

#: Same floor, for the credential-key table: a case list that shrank to
#: nothing would report a clean zero misjudgements. A floor rather than the
#: count of the day, for T100's reason — the exact number moves whenever a
#: case is added, and the number is not the measurement.
MINIMUM_CREDENTIAL_CASES = 50


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


def why_refused(recorded: RecordedRequest) -> list[str]:
    """Every reason **policy** refuses this request, whatever the engine can do.

    A board refused for carrying a credential is not "readable only by POST",
    and counting it as one is what made this gate go permanently red on a
    legitimate ledger addition. The ledger's own test 3 tells the next
    surveyor to record the curl a capture revealed; recording the Algolia call
    for idealist.org — a POST whose payload and query string both carry a key
    — would have turned a measured, correct entry into a gate failure whose
    only cure was deleting the measurement.

    Which is exactly backwards. This tool refusing a board on policy is the
    check *working*: `boards_readable_only_by_post` asks whether the engine
    has a gap, and a board this tool may never fetch cannot answer that
    question either way. So it is counted separately, and the engine's
    question is asked only of the boards left.
    """
    reasons = [
        f"{recorded.site}: the recorded URL's query names a credential ({key!r})"
        for key in credential_query_keys(recorded.url)
    ]
    reasons += [
        f"{recorded.site}: the recorded request sends a {name!r} header"
        for name in recorded.headers
        if names_a_credential(name)
    ]
    # ponytail: JSON bodies only. A form-encoded body carrying a key is
    # reported as unreadable instead, which it also is — the schema declares
    # no form body — so nothing escapes; it is merely filed under the other
    # heading. Parse it here if a form-POST board ever reaches the ledger.
    try:
        body = json.loads(recorded.body) if recorded.body else None
    except json.JSONDecodeError:
        body = None
    reasons += [
        f"{recorded.site}: the recorded body key {key!r} names a credential"
        for key in credential_keys(body)
    ]
    return reasons


def why_unreadable(recorded: RecordedRequest) -> list[str]:
    """Every way the engine still fails to issue the recorded request.

    Asked only of a request `why_refused` cleared — see there for why a policy
    refusal is not an engine gap.
    """
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


def credential_key_misjudgements(
    cases: Path = DEFAULT_CREDENTIAL_CASES_PATH,
) -> tuple[list[str], int]:
    """Every key in the committed table the matcher gets wrong, and how many ran.

    The table is the audit's own cases, committed. A report that is read and
    waved through leaves the code as unprotected as it was, so the accepted
    cases are measured here rather than only asserted in the suite — the
    evidence carries how many keys were judged, and a token list that
    regresses moves a number this gate records.

    Both directions, and the file says which is which. `refused` is the
    fail-open side: a key that names a credential and is admitted is a secret
    committed to a shared library. `accepted` is the fail-closed side, and it
    exists because a matcher that refuses everything passes the first list.
    """
    table = yaml.safe_load(cases.read_text(encoding="utf-8"))
    wrong = [
        f"{key!r} is admitted and names a credential"
        for key in table["refused"]
        if not names_a_credential(key)
    ]
    wrong += [
        f"{key!r} is refused and is an ordinary search key"
        for key in table["accepted"]
        if names_a_credential(key)
    ]
    return wrong, len(table["refused"]) + len(table["accepted"])


def measure(
    ledger: Path = DEFAULT_LEDGER_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
    cases: Path = DEFAULT_CREDENTIAL_CASES_PATH,
) -> dict[str, Any]:
    """T89's reading: `boards_readable_only_by_post`, with every denominator."""

    def _unmeasured(reason: str) -> dict[str, Any]:
        return {
            "boards_readable_only_by_post": 0,
            "boards_readable_only_by_post_evaluated": 0,
            "boards_refused_on_policy": 0,
            "ledger_entries_scanned": 0,
            "get_connectors_still_plain_gets": 0,
            "get_connectors_evaluated": 0,
            "credential_key_misjudged": 0,
            "credential_key_cases_checked": 0,
            "unreadable": [],
            "refused": [],
            "misjudged": [],
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

    # Policy first. A board this tool may never fetch cannot say anything
    # about whether the engine has a gap, so it is counted and set aside
    # rather than scored as one — see `why_refused`.
    refused: list[str] = []
    issuable: list[RecordedRequest] = []
    for recorded in posts:
        reasons = why_refused(recorded)
        if reasons:
            refused.extend(reasons)
        else:
            issuable.append(recorded)
    if not issuable:
        return _unmeasured(
            "every POST retest in the ledger is refused on policy — a zero over boards this "
            "tool may not fetch says nothing about the engine"
        )

    unreadable = [reason for recorded in issuable for reason in why_unreadable(recorded)]
    changed, get_checked = get_packages_that_changed(directory)
    if get_checked == 0:
        return _unmeasured("no committed connector package declares a GET listing")

    try:
        misjudged, case_count = credential_key_misjudgements(cases)
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        return _unmeasured(f"the credential-key case table could not be read: {exc}")
    if case_count < MINIMUM_CREDENTIAL_CASES:
        return _unmeasured(
            f"only {case_count} credential-key case(s) (floor {MINIMUM_CREDENTIAL_CASES}) "
            "— a matcher checked against nothing is not a pass"
        )

    return {
        # The boards the ledger records as answering a POST that the engine
        # still cannot issue. One entry qualifies today (usajobs.gov); the
        # count is of failures, so it stays honest as the ledger grows.
        "boards_readable_only_by_post": len({reason.split(":")[0] for reason in unreadable}),
        "boards_readable_only_by_post_evaluated": len(issuable),
        "boards_refused_on_policy": len({reason.split(":")[0] for reason in refused}),
        "ledger_entries_scanned": scanned,
        "get_connectors_still_plain_gets": get_checked - len(changed),
        "get_connectors_evaluated": get_checked,
        "credential_key_misjudged": len(misjudged),
        "credential_key_cases_checked": case_count,
        "unreadable": unreadable,
        "refused": refused,
        "misjudged": misjudged,
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
    for reason in measured["misjudged"]:
        print(f"credential key misjudged: {reason}", file=sys.stderr)
    # A refusal is reported and is not a failure: it is this tool declining a
    # board, which is the rule working rather than a gap in the engine.
    for reason in measured["refused"]:
        print(f"refused on policy: {reason}")
    if (
        measured["boards_readable_only_by_post"]
        or measured["get_packages_changed"]
        or measured["credential_key_misjudged"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
