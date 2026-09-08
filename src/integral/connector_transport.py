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
each still builds a plain GET with no body, and with exactly the headers its
own declaration derives: none for a connector with no `client`, and that
client's fixed set for one that names one (T133). Comparing against the empty
dict was right while no package declared a client, and the first one that did
would have forced the check to be relaxed to "some headers are allowed", which
asserts nothing. What must never happen is a package acquiring a header nobody
declared, and that is what the derived expectation still catches.

## What is committed out of that half, and why it is not the count (T111)

`get_connectors_evaluated` was committed as an exact census — the number of
GET packages on the day — so the sixteenth connector package moved a number in
`status/evidence/T89.json` and reddened `make evidence` on a pull request that
had touched nothing here. That is T55's and T100's defect in this module: a
**denominator** committed as a value. It measures nothing about the transport;
it exists to stop a clean `get_packages_changed: []` resting on a scan of
nothing.

So `record` commits `get_connectors_evaluated_at_least` — the floor `measure`
checks the live count against, the way `naming.MINIMUM_SCANNED` is checked —
and drops the two censuses. The equality that mattered,
`get_connectors_still_plain_gets == get_connectors_evaluated`, is kept where it
can fail: it is exactly `get_packages_changed == []`, which stays in the record
as the finding, and `measure` still computes both counts for a caller that
wants to see them.

`measure_growth_sensitivity` is the proof rather than the assertion. It runs
the whole reading twice — once over the committed library, once over that
library plus one more GET package — and compares the two **records** key by
key. `growth_sensitive_evidence_keys` is how many moved, and
`evidence_keys_compared` is what says the comparison happened at all: a
`record` that satisfied "nothing moved" by committing nothing would otherwise
score a clean zero (T100's lesson, and T104's `record_keys_compared` after it).
"""

from __future__ import annotations

import json
import shlex
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    Connector,
    ConnectorError,
    build_list_requests,
    client_headers,
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

#: curl options that carry a credential in the token after them, mapped to the
#: name a refusal reports. **Only the name is ever kept** — `parse_curl` records
#: which of these appeared and discards the value, because a credential read out
#: of a ledger and held in a dataclass is a credential this library carries, and
#: `connectors.py`'s rule is that it may not.
_CREDENTIAL_OPTIONS = {
    "-u": "--user",
    "--user": "--user",
    "-b": "--cookie",
    "--cookie": "--cookie",
}

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

#: The floor `get_connectors_evaluated` is checked against, and what the
#: record carries in its place (T111). A floor rather than the census for
#: `naming.MINIMUM_SCANNED`'s reason: the count is a **denominator** — it says
#: the default-did-not-move check ran over something — and committing it as an
#: exact value made every new connector package a drift in an evidence file
#: that PR never touched. Well under the twenty packages that declare a GET
#: listing today, so the library can lose one without the gate turning red for
#: a reason that is not a finding.
MINIMUM_GET_PACKAGES = 10

#: T111's own record, beside T89's — one reading, two questions: did the
#: default move, and can what we commit about it survive one more package.
DEFAULT_GROWTH_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T111.json"

#: A literal, not `len(record(measure()))`: asserting the denominator against
#: the thing it is the denominator of is the self-reference #297 caught as
#: D-4 on T104. The record carries twelve keys and this is twelve — no slack,
#: unlike the census floors above, because this is not a census: the number of
#: keys `record` commits moves only when somebody edits `record`, never when
#: the library grows. Ten left two keys of headroom, which is exactly enough
#: for `record` to stop committing `get_packages_changed` — the finding itself
#: — and still score green here (second-reader note on #402).
MINIMUM_RECORD_KEYS_COMPARED = 12

#: The site name the simulated seventeenth package takes. Not a board and
#: never fetched — it exists inside one `measure_growth_sensitivity` call, in
#: a throwaway directory, to answer "what does one more GET package do to the
#: committed record".
GROWTH_PROBE_SITE = "growthprobe"


#: Any terms will do: these checks measure a request's *shape* — method, body,
#: headers — never what it searched for. A connector whose `url_pattern` carries
#: `{query}` refuses to build a URL without one, so a shape check has to hand it
#: something rather than quietly skip every board that can be steered.
PROBE_QUERY = "python"


@dataclass(frozen=True)
class RecordedRequest:
    """The request a ledger entry's `retest:` command actually makes."""

    site: str
    url: str
    method: str
    headers: dict[str, str]
    body: str | None
    #: The credential-bearing curl options the recorded command used, by long
    #: name and never with their values. `why_refused` reads this; without it a
    #: POST needing HTTP Basic or a session cookie parsed to a request carrying
    #: neither, and the gate reported it readable (#295 review).
    credential_options: tuple[str, ...] = ()


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
    credentials: list[str] = []

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
            elif token in _CREDENTIAL_OPTIONS:
                # The name, not `value`. See `_CREDENTIAL_OPTIONS`.
                credentials.append(_CREDENTIAL_OPTIONS[token])
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
    return RecordedRequest(
        site="",
        url=url,
        method=method,
        headers=headers,
        body=body,
        credential_options=tuple(dict.fromkeys(credentials)),
    )


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
                    credential_options=request.credential_options,
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
    # A credential does not have to be in the URL, a header or the body: curl
    # puts `-u` on the wire as `Authorization` and `-b` as `Cookie` itself, so
    # neither is visible to the three checks above. The parser used to consume
    # both and drop them, which made a board needing HTTP Basic parse into a
    # request carrying no credential at all — and a request carrying no
    # credential is refused by nothing, so the gate scored it as one the engine
    # could read (#295 review). That is the fail-open shape this module exists
    # to refuse: a check answering "no problem" because it could not see one.
    reasons += [
        f"{recorded.site}: the recorded curl passes {option} — a credential curl puts on the "
        f"wire itself, which no connector may carry"
        for option in recorded.credential_options
    ]
    return reasons


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """One header by name, case-insensitively (RFC 9110 §5.1).

    `parse_curl` keeps whatever case the recorded command was written in, and a
    recorded `-H 'content-type: application/json'` used to make
    `headers.get("Content-Type")` return `None` — which skipped the comparison
    entirely rather than failing it. A check that reports no gap because it could
    not find the header is the fail-open this module exists to close (#295
    review): `why_unreadable` returning an empty list is read as "the engine can
    issue this request".
    """
    wanted = name.lower()
    return next((value for key, value in headers.items() if key.lower() == wanted), None)


def why_unreadable(recorded: RecordedRequest) -> list[str]:
    """Every way the engine still fails to issue the recorded request.

    Asked only of a request `why_refused` cleared — see there for why a policy
    refusal is not an engine gap.
    """
    try:
        connector = _probe_connector(recorded)
    except (ConnectorError, ValueError) as exc:
        return [f"{recorded.site}: the schema cannot express the recorded request: {exc}"]

    requests = build_list_requests(connector, query=PROBE_QUERY)
    if not requests:
        return [f"{recorded.site}: the engine builds no request at all"]
    built = requests[0]

    reasons: list[str] = []
    if built.method != recorded.method:
        reasons.append(f"{recorded.site}: method is {built.method}, recorded {recorded.method}")
    if built.url != recorded.url:
        reasons.append(f"{recorded.site}: url is {built.url}, recorded {recorded.url}")
    expected_type = _header(recorded.headers, "Content-Type")
    built_type = _header(built.headers, "Content-Type")
    if expected_type is not None and built_type != expected_type:
        reasons.append(
            f"{recorded.site}: Content-Type is {built_type!r}, recorded {expected_type!r}"
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
        # T133. A connector declaring a `client` sends that client's fixed
        # headers, and its own and nothing else — so the expectation is
        # *derived* from the declaration rather than being the empty dict.
        # Relaxing this to "any headers are fine once one package has some"
        # would retire the check the paragraph above exists to keep: what must
        # never happen is a package acquiring a header nobody declared.
        expected = client_headers(connector.list.client, connector.list.client_target)
        for request in build_list_requests(connector, query=PROBE_QUERY):
            if request.method != "GET" or request.body or request.headers != expected:
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
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # `ValueError` is `shlex.split` refusing an unmatched quote in a
        # `retest:` command (#295 review). A malformed entry is a ledger the
        # gate cannot read, which is what `unmeasured` is for — letting it
        # propagate takes `make evidence` down with a traceback instead, and a
        # module that dies never gets to record that it could not measure.
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
    if get_checked < MINIMUM_GET_PACKAGES:
        # T111 raised this from `== 0`: the record no longer carries how many
        # packages ran, so the floor is the whole of what says the check ran
        # over a library rather than over a directory somebody emptied.
        return _unmeasured(
            f"only {get_checked} committed package(s) declare a GET listing (floor "
            f"{MINIMUM_GET_PACKAGES}) — a default checked against nothing is not a pass"
        )

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


def record(measured: Mapping[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured (T111).

    The two GET censuses go out and the floor they were checked against goes
    in. Nothing about the finding changes: `get_packages_changed` is still the
    list of packages whose request stopped being a plain GET, and it is empty
    exactly when `get_connectors_still_plain_gets == get_connectors_evaluated`.
    What stops being committed is a number that moves when somebody adds a
    connector — which is the whole of the defect, and none of the check.

    The floor goes in **only when the run met it** (second-reader BLOCK on
    #402, T104's `floor_breaches` one module over). Since the census is no
    longer committed, `get_connectors_evaluated_at_least` is now the only line
    in the file that speaks to how much was scanned — so writing it out of an
    unmeasured reading turns the record of a scan over nothing into a claim
    that ten packages were read. That is a floor asserted by a run that failed
    it, which is worse than the census it replaced: the census at least said
    zero.
    """
    committed = {
        key: value
        for key, value in measured.items()
        if key not in ("get_connectors_evaluated", "get_connectors_still_plain_gets")
    }
    if measured.get("gate_status") == "measured":
        committed["get_connectors_evaluated_at_least"] = MINIMUM_GET_PACKAGES
    return committed


@contextmanager
def _library_grown_by_one(directory: Path) -> Iterator[Path]:
    """`directory` as it would be with one more GET package in it.

    Every existing package is linked, not copied — the library is three
    megabytes of recorded fixtures and none of it is read here — and the extra
    package is a committed one's `connector.yaml` under a new site name,
    because `load_connector` requires the directory to be called
    `<site>_<locale>`. Deriving it from a real package rather than writing a
    connector out here keeps this from becoming a second, private idea of what
    a connector looks like.
    """
    source = next(
        (
            package
            for package in connector_packages(directory)
            if load_connector(package).list.method == "GET"
        ),
        None,
    )
    if source is None:
        raise ConnectorError(f"no package under {directory} declares a GET listing")
    declaration = yaml.safe_load((source / "connector.yaml").read_text(encoding="utf-8"))
    declaration["site"] = GROWTH_PROBE_SITE
    with tempfile.TemporaryDirectory(prefix="growth-probe-") as tmp:
        grown = Path(tmp) / "connectors"
        grown.mkdir()
        for package in connector_packages(directory):
            (grown / package.name).symlink_to(package.resolve(), target_is_directory=True)
        added = grown / f"{GROWTH_PROBE_SITE}_{declaration['locale']}"
        added.mkdir()
        (added / "connector.yaml").write_text(
            yaml.safe_dump(declaration, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        yield grown


def measure_growth_sensitivity(
    ledger: Path = DEFAULT_LEDGER_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
    cases: Path = DEFAULT_CREDENTIAL_CASES_PATH,
) -> dict[str, Any]:
    """T111's gate: `growth_sensitive_evidence_keys`.

    Not a test of the fix's shape but of its effect, T100's form on the axis
    that moves here. A `record` that dropped the finding as well as the census
    would satisfy "nothing moved", and `evidence_keys_compared` is what
    catches it; a simulated package that never entered the scan would prove
    nothing at all, which is why the raw counts are read back and required to
    have risen by exactly one before anything is compared.
    """

    def _unmeasured(reason: str) -> dict[str, Any]:
        return {
            "growth_sensitive_evidence_keys": 0,
            "evidence_keys_compared": 0,
            "gate_status": "unmeasured",
            "unmeasured_reason": reason,
            "grown_by": None,
            "sensitive": [],
        }

    live = measure(ledger, directory, cases)
    if live["gate_status"] != "measured":
        return _unmeasured(f"the committed library does not measure: {live['unmeasured_reason']}")
    try:
        with _library_grown_by_one(directory) as grown_directory:
            grown = measure(ledger, grown_directory, cases)
    except (ConnectorError, OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        return _unmeasured(f"the library could not be grown for the comparison: {exc}")
    if grown["gate_status"] != "measured":
        return _unmeasured(f"the grown library does not measure: {grown['unmeasured_reason']}")
    if grown["get_connectors_evaluated"] != live["get_connectors_evaluated"] + 1:
        return _unmeasured(
            "the simulated package did not enter the scan: "
            f"{live['get_connectors_evaluated']} GET package(s) before, "
            f"{grown['get_connectors_evaluated']} after"
        )
    before, after = record(live), record(grown)
    sensitive = sorted(key for key in before | after if before.get(key) != after.get(key))
    return {
        "growth_sensitive_evidence_keys": len(sensitive),
        "evidence_keys_compared": len(before | after),
        "gate_status": "measured",
        "grown_by": f"{GROWTH_PROBE_SITE}_*",
        "sensitive": sensitive,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    ledger: Path = DEFAULT_LEDGER_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T89.json`.

    Returns what was *measured*; writes what is *recorded*. The caller still
    wants both live counts for its own report, and the file must not carry
    either — that is T111.

    **An unmeasured run writes nothing at all**, which is T104's
    `test_a_sub_floor_run_leaves_an_existing_record_untouched` in this module.
    The exit code is not a run's only output: whatever is on disk afterwards is
    what the next `make evidence` diffs against, so a sub-floor run that
    overwrote the committed record would make the *second* run of a broken
    library green. Nothing this run could write is true — the floor is a
    constant, and it is the only remaining line about scan size — so it writes
    nothing and `_main` carries the finding in an exit code the caller stops
    on.
    """
    measured = measure(ledger, directory)
    if measured["gate_status"] != "measured":
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def write_growth_sensitivity_evidence(
    evidence: Path = DEFAULT_GROWTH_EVIDENCE_PATH,
    ledger: Path = DEFAULT_LEDGER_PATH,
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T111.json`.

    Returns the whole reading; commits all of it but `unmeasured_reason`,
    which is a sentence about one run rather than a measurement — the same
    treatment T89's own record gives it.
    """
    measured = measure_growth_sensitivity(ledger, directory)
    committed = {k: v for k, v in measured.items() if k != "unmeasured_reason"}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connector_transport [evidence-path]` → T89 and T111.

    Two files from one reading, `naming`'s shape: T89's record beside T111's
    answer to whether that record survives the library growing.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        # Exit 1, not 3, and the two floors in this module now agree on it
        # (second-reader note on #402). `Makefile`'s evidence loop prints
        # "unmeasured (recorded)" for 3 and carries on — and `write_evidence`
        # records nothing for an unmeasured reading, so 3 would be a claim
        # that a record was written when none was, and `make evidence` would
        # go green over a library that scanned nothing. Every unmeasured path
        # here is a floor breached or an input that could not be read: a
        # finding, and T115's shape if it only advises.
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 1
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

    # T111, beside T89 — the same reading asked a second question. Written
    # next to whichever file T89's record went to, so a measurement of another
    # tree lands beside it rather than over this repository's own record.
    sensitivity = write_growth_sensitivity_evidence(target.parent / "T111.json")
    for key in sensitivity["sensitive"]:
        print(
            f"✗ `{key}` changes when one more GET package is added — a committed value "
            "that moves on a connector nobody in this PR touched is what reddens "
            "`make evidence` elsewhere (T111)",
            file=sys.stderr,
        )
    if sensitivity["growth_sensitive_evidence_keys"]:
        return 1
    # This 3 is not the inconsistency #402's second reader named — that was
    # the *package* floor, and it is a 1 above now. Here the reading really
    # was recorded: `write_growth_sensitivity_evidence` has already written
    # the unmeasured reading, so "unmeasured (recorded)" is what happened.
    if sensitivity["gate_status"] != "measured":
        print(
            "growth_sensitive_evidence_keys: UNMEASURED — "
            f"{sensitivity['unmeasured_reason']}. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    # The denominator, last and as a hard failure. Exit 1 rather than 3 for
    # #297's D-1 reason: `Makefile`'s evidence loop maps 3 to
    # `unmeasured (recorded)` and carries on, so a floor that exits 3 is
    # decoration (T115). A record that compared fewer keys than this ran — it
    # is a finding, not the absence of a measurement.
    if sensitivity["evidence_keys_compared"] < MINIMUM_RECORD_KEYS_COMPARED:
        print(
            f"only {sensitivity['evidence_keys_compared']} record key(s) were compared "
            f"(floor {MINIMUM_RECORD_KEYS_COMPARED}) — zero growth-sensitive keys over a "
            "record that committed almost nothing is not a measurement",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
