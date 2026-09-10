"""T110: a POST and a body imply each other, and no request goes out without both.

`ListPage` had an opinion about one direction of the relationship between
`list.method` and `list.body_json` and none about the other. A body without a
POST was refused — "only a POST carries a request body" — while a POST with no
body loaded happily, and `build_list_requests` then took its *bodyless* branch
and returned

```python
ListRequest(url=..., method="POST", headers={}, body=None)
```

a POST with **no `Content-Type`**, which several back ends answer 400 or 415
to. Nothing shipped declares that shape today, so the defect was latent; what
made it worth settling is that the schema was silent rather than permissive —
a contributor writing `method: POST` and forgetting the body got no error at
load, no header at send, and a status code from the board as their first
feedback.

The half of this that is not a header is the reason the schema had to pick
rather than bless: `Content-Type` is *derived* from the declared body form,
because a connector that could name a header could name an `Authorization`
(see `JSON_CONTENT_TYPE`). A bodyless POST therefore has nothing to derive a
content type from, and blessing it would mean inventing one for a request with
no content. So `_a_post_and_a_body_imply_each_other` refuses it, in the
direction that costs a contributor one error message rather than the direction
that puts a malformed request on the wire.

This module is the measurement, not the fix. The metric is named after the
**request** rather than after the document — `bodyless_posts_sent_without_a_
content_type` — so it cannot be satisfied by a load check that reads well: what
is counted is what `build_list_requests` actually returns, over every shipped
package and over a probe table whose verdicts are derived from `RULE` and never
from a run. Delete the refusal and the probes below stop being refused, the
builder emits exactly the offending request, and the count is what it counts.

Two denominators, because a zero has two vacuous ways to be true here:

- `packages_checked` (floor `MINIMUM_PACKAGES`) — zero offenders over a library
  nobody read is what an empty scan also reports.
- `legal_shapes_refused` — zero offenders is trivially reached by refusing
  every request, and "a GET with no body" is the shape twenty of the twenty-one
  committed packages have. The fail-closed overreach is cheap for a board and
  fatal for the library, so it is measured rather than assumed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from integral.connectors import (
    JSON_CONTENT_TYPE,
    Connector,
    ConnectorError,
    build_list_requests,
    connector_packages,
    load_connector,
    parse_connector,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T110.json"
DEFAULT_CONNECTORS_DIR = _REPO_ROOT / "connectors"

# A FLOOR, never the count of the day — T100's precedent, for T100's reason.
# Its job here is `naming.MINIMUM_SCANNED`'s: zero bodyless POSTs over a
# library that failed to enumerate is the vacuous pass this module refuses.
MINIMUM_PACKAGES = 20

# Likewise for the probe table, which is the half that survives an empty
# `connectors/` directory. Raised to what `PROBES` carries — 9, zero slack —
# because 8 tolerated the first deleted probe silently: `len(PROBES) == 9` and
# nothing short of the whole table breached it (T159).
MINIMUM_PROBES = 9

# Some packages carry `{query}` in their URL and refuse to be built for
# nothing. What the search term is does not matter to this measurement; that
# there is one does.
PROBE_QUERY = "python"

# The rule, in one place, quoted by every probe's `clause`. Each line is a
# clause a verdict may cite; nothing below cites the implementation.
RULE = (
    "R1: `Content-Type` is derived from the declared body form and from "
    "nothing else — a connector may not name a header, which is how 'a "
    "connector may not carry a credential' is kept structurally "
    "(`JSON_CONTENT_TYPE`, `ListPage.body_json`).",
    "R2: `list.body_json` is legal only with `list.method: POST` — a body a "
    "GET cannot send is a document contradicting itself "
    "(`_a_post_and_a_body_imply_each_other`).",
    "R3: `list.method: POST` requires a `list.body_json` — declared, which the "
    "schema tests as `body_json is not None`, so an empty mapping is a body "
    "and only its absence is not. By R1 a bodyless POST has no content type "
    "to derive, so such a DOCUMENT is refused AT LOAD rather than sent "
    "without one (`_a_post_and_a_body_imply_each_other`).",
    "R4: `list.method: GET` with no body is the default and stays legal — it "
    "is the shape every package written before T89 has, and refusing it is "
    "the fail-closed way to report zero offenders.",
    "R5: a POST that loads carries `Content-Type: application/json` on every "
    "request built from it (`build_list_requests`).",
    "R6: no request this engine builds is a POST with no body — the refusal "
    "is repeated WHERE THE REQUEST IS MADE, because an object built with "
    "`model_copy(update=...)` never met a validator (`build_list_urls` "
    "repeats its clamp for the same reason).",
)

_DOCUMENT: dict[str, Any] = {
    "site": "probeboard",
    "locale": "en",
    "version": "1.0.0",
    "last_verified": "2026-08-31",
    "auth": "none",
    "list": {
        "url_pattern": "https://boards.test/Search/ExecuteSearch",
        "from_json": {
            "items": "Jobs",
            "fields": {"title": "Title", "text": "Summary", "detail_url": "PositionURI"},
        },
    },
}


#: The three verdicts a probe can carry, and the reason there are three rather
#: than two. A boolean "does it load" cannot tell R3 from R6: with the load
#: check deleted, a document the schema should refuse still reaches the
#: builder's clamp and is still refused, so a two-valued table would stay green
#: over a schema that had lost the opinion T110 gave it. WHERE the refusal
#: fires is the property, not merely that one does.
REFUSED_AT_LOAD = "refused at load"
REFUSED_WHEN_BUILT = "refused when built"
BUILDS = "builds a request"


@dataclass(frozen=True)
class Probe:
    """One `method`/`body_json` pairing, and the verdict the rule requires.

    `verdict` is written from `RULE`, before and independently of what the
    implementation does with the shape — a fixture whose expected value was
    read off a run certifies the run.

    `validated=False` is the `model_copy(update=...)` escape: the shape is
    assembled on an in-memory object that no validator ever saw, so what it
    measures is the request builder alone, whatever the load check would have
    said.
    """

    name: str
    method: str
    body_json: dict[str, Any] | None
    verdict: str
    clause: str
    validated: bool = True


PROBES: tuple[Probe, ...] = (
    Probe(
        name="a GET with no body — the default shape",
        method="GET",
        body_json=None,
        verdict=BUILDS,
        clause="R4",
    ),
    Probe(
        name="a POST carrying a body",
        method="POST",
        body_json={"Keyword": "python", "ResultsPerPage": 25},
        verdict=BUILDS,
        clause="R5",
    ),
    Probe(
        name="a POST with no body",
        method="POST",
        body_json=None,
        verdict=REFUSED_AT_LOAD,
        clause="R3",
    ),
    Probe(
        name="a GET carrying a body",
        method="GET",
        body_json={"Keyword": "python"},
        verdict=REFUSED_AT_LOAD,
        clause="R2",
    ),
    Probe(
        name="a POST whose body is an empty mapping",
        method="POST",
        # R3 asks for a *declared* body, and `{}` is one — the schema's test is
        # `body_json is None`, and an empty mapping is a form to derive a
        # content type from. So this loads and carries the header, which is
        # what the probe pins: "no body" and "an empty body" are different
        # documents, and only the first is T110's shape. Written this way
        # after the first table asserted a refusal the rule does not require —
        # a verdict invented by the fixture author is the failure mode this
        # table exists to avoid, and it showed up on the first run.
        body_json={},
        verdict=BUILDS,
        clause="R3",
    ),
    Probe(
        name="an unvalidated POST with no body",
        method="POST",
        body_json=None,
        # R6: no request this engine builds is a bodyless POST, so the builder
        # refuses an object the load check never saw. This probe never meets
        # the load check at all, which is what makes it the one that measures
        # the clamp rather than the schema.
        verdict=REFUSED_WHEN_BUILT,
        clause="R6",
        validated=False,
    ),
    Probe(
        name="an unvalidated GET carrying a body",
        method="GET",
        body_json={"Keyword": "python"},
        # R2's half of R6. The clamp is repeated in both directions or the
        # builder is not the validator's equal: this object never met the load
        # check, and without the second arm it was issued as a GET carrying a
        # body and a Content-Type — a request no connector can declare.
        verdict=REFUSED_WHEN_BUILT,
        clause="R2",
        validated=False,
    ),
    Probe(
        name="an unvalidated GET with no body",
        method="GET",
        body_json=None,
        verdict=BUILDS,
        clause="R4",
        validated=False,
    ),
    Probe(
        name="an unvalidated POST carrying a body",
        method="POST",
        body_json={"Keyword": "python"},
        verdict=BUILDS,
        clause="R5",
        validated=False,
    ),
)


def _document(probe: Probe) -> str:
    """`probe` as a whole connector document, ready for `parse_connector`."""
    document = json.loads(json.dumps(_DOCUMENT))
    document["list"]["method"] = probe.method
    if probe.body_json is not None:
        document["list"]["body_json"] = probe.body_json
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _unvalidated(probe: Probe) -> Connector:
    """`probe` as a `Connector` the validators never saw.

    The scaffold is the one shape that always loads — a GET with no body — and
    the probe's `method` and `body_json` are then written onto it with
    `model_copy(update=...)`, pydantic's documented escape from validation.
    This is the same construction `page_placeholder._unvalidated` uses, for the
    same reason: several checks in `connectors` are repeated at use rather than
    trusted from load, and a check that is only ever exercised through a load
    is not the check that is claimed.
    """
    scaffold = parse_connector(
        _document(Probe(name="scaffold", method="GET", body_json=None, verdict=BUILDS, clause="R4"))
    )
    page = scaffold.list.model_copy(update={"method": probe.method, "body_json": probe.body_json})
    return scaffold.model_copy(update={"list": page})


def _offending(requests: list[Any]) -> int:
    """How many of `requests` are a bodyless POST with no `Content-Type`.

    The metric's definition, in one place. A request is counted when it is not
    a GET, carries no body, and names no content type — all three, because a
    POST carrying `Content-Type: application/json` over an empty body would be
    a different (and stranger) defect than the one T110 names, and calling it
    this one would misreport what was measured.
    """
    return sum(
        1
        for request in requests
        if request.method != "GET"
        and request.body is None
        and not any(name.lower() == "content-type" for name in request.headers)
    )


def _built(probe: Probe) -> tuple[str, list[Any], str]:
    """What the implementation does with `probe`: verdict, requests, refusal text.

    The two refusals are told apart because they are different properties. A
    document the schema accepts and the builder then refuses is not the same
    library as one the schema refuses: the first tells a contributor about
    their mistake when a search runs, the second when the file is read — and
    only the second is what R3 asks for.
    """
    if not probe.validated:
        try:
            # An unvalidated probe still needs a SCAFFOLD that loads — a legal
            # GET with no body — so a load check widened until it refuses that
            # refuses this too. Reported rather than allowed to escape: a
            # measurement that dies of the defect it is measuring writes no
            # evidence and reads as a crash rather than as the fail-closed
            # finding it is.
            #
            # Its own arm, and the message says whose refusal it was. Sharing
            # one `except` with the probe's own document reported a broken
            # scaffold as a verdict about the SHAPE under test — a finding
            # attributed to the wrong input, which in a module whose entire
            # output is "this input, this verdict" is the one error a reader
            # cannot correct for (T110's second-reader NOTE 1).
            connector = _unvalidated(probe)
        except ConnectorError as exc:
            return (
                REFUSED_AT_LOAD,
                [],
                f"the probe scaffold itself was refused: {str(exc).replace(chr(10), ' ')}",
            )
    else:
        try:
            connector = parse_connector(_document(probe))
        except ConnectorError as exc:
            return REFUSED_AT_LOAD, [], str(exc).replace("\n", " ")
    try:
        return BUILDS, list(build_list_requests(connector, query=PROBE_QUERY)), ""
    except ConnectorError as exc:
        return REFUSED_WHEN_BUILT, [], str(exc).replace("\n", " ")


def library_offenders(
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> tuple[list[str], list[str], int]:
    """The shipped library, read three ways: offenders, refusals, and how many ran.

    Enumerated from disk, so a package added after this task is covered without
    anybody remembering to list it — `connector_transport.get_packages_that_changed`'s
    posture, for its reason.

    A package that no longer **loads or builds** is reported rather than
    skipped, and that is not tidiness. Every committed package is a legal shape
    by construction, so a refusal here is the fail-closed overreach this
    module's second denominator exists to catch — widening the load check until
    a plain GET is refused takes the offender count to zero, which is precisely
    the "fix" that must not read as a pass. Skipping the exception instead
    would have let that mutation through; letting it escape (the first
    version) aborted the run with a traceback and wrote no evidence at all,
    which is `page_placeholder`'s #338 F7 one module later.

    A package declaring the bodyless POST itself therefore lands in `refused`
    and not in `offenders`, and that placement is the metric's definition
    rather than a mislabelling: the load check refuses the document, so no
    request is ever built from it and nothing is *sent* without a content type.
    `offenders` is for a package that builds one. The refusal string carries
    the schema's own message, so a reader triaging the record can tell this
    rule from an unrelated schema break by reading it — which is why the string
    is kept rather than the package name alone.
    """
    offenders: list[str] = []
    refused: list[str] = []
    checked = 0
    for package in connector_packages(directory):
        checked += 1
        try:
            connector = load_connector(package)
            requests = list(build_list_requests(connector, query=PROBE_QUERY))
        except ConnectorError as exc:
            refused.append(f"{package.name}: {str(exc).replace(chr(10), ' ')}")
            continue
        if _offending(requests):
            offenders.append(package.name)
    return offenders, refused, checked


def measure(
    probes: tuple[Probe, ...] = PROBES, directory: Path = DEFAULT_CONNECTORS_DIR
) -> dict[str, Any]:
    """T110's gate reading: bodyless POSTs built, and the verdicts behind them."""
    offenders, unbuildable, packages = library_offenders(directory)
    sent = len(offenders)
    disagreements: list[dict[str, Any]] = []
    refused_legal: list[str] = []

    for probe in probes:
        verdict, requests, refusal = _built(probe)
        sent += _offending(requests)
        if verdict == probe.verdict:
            # R5's half that a load verdict cannot express: a POST that loads
            # must carry the content type on every request built from it.
            missing = [
                request.url
                for request in requests
                if request.method == "POST"
                and request.headers.get("Content-Type") != JSON_CONTENT_TYPE
            ]
            if missing:
                disagreements.append(
                    {
                        "probe": probe.name,
                        "clause": "R5",
                        "rule": f"every request carries Content-Type: {JSON_CONTENT_TYPE}",
                        "observed": f"{len(missing)} request(s) carry none",
                        "direction": "fail-open",
                    }
                )
            continue
        disagreements.append(
            {
                "probe": probe.name,
                "clause": probe.clause,
                "rule": probe.verdict,
                "observed": verdict if verdict == BUILDS else f"{verdict}: {refusal}",
                # Accepting what the rule refuses is the expensive direction —
                # the document loads, or the request goes out, in a shape no
                # connector described. A refusal the rule does not ask for
                # costs a contributor a correction they can see, and is
                # counted separately in `legal_shapes_refused`, because
                # reaching zero by refusing everything is the fix this gate
                # must not accept. R3-vs-R6 — refused, but in the wrong place
                # — is neither: the schema lost an opinion it is supposed to
                # hold, so it is reported as fail-open.
                "direction": "fail-closed" if probe.verdict == BUILDS else "fail-open",
            }
        )
        if probe.verdict == BUILDS:
            refused_legal.append(probe.name)

    record: dict[str, Any] = {
        "bodyless_posts_sent_without_a_content_type": sent,
        "packages_checked_at_least": MINIMUM_PACKAGES,
        "packages_checked": packages,
        "probes_at_least": MINIMUM_PROBES,
        "probes_checked": len(probes),
        # Both halves of the second denominator: a probe the rule says must
        # build and did not, and a committed package that stopped building at
        # all. Either is the fail-closed way to report no offenders.
        "legal_shapes_refused": len(refused_legal) + len(unbuildable),
        "offending_packages": offenders,
        "packages_that_no_longer_build": unbuildable,
        "disagreements": disagreements,
        "fail_open": sum(1 for row in disagreements if row["direction"] == "fail-open"),
        "gate_status": "measured",
    }
    if packages < MINIMUM_PACKAGES or len(probes) < MINIMUM_PROBES:
        record["gate_status"] = "unmeasured"
        record["unmeasured_reason"] = (
            f"{packages} package(s) (floor {MINIMUM_PACKAGES}) and {len(probes)} probe(s) "
            f"(floor {MINIMUM_PROBES}) — zero bodyless POSTs over an empty scan is not a pass"
        )
    return record


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    `packages_checked` is dropped and only its floor is kept, which is T100's
    rule applied where it bites: `make evidence` diffs `status/evidence/` byte
    for byte, so an exact package count committed here would be regenerated
    with a different value by **any** PR that adds or removes a connector, and
    would redden that PR's gate over a change that is not a finding. That is
    not hypothetical — `status/evidence/T89.json`'s analogous count has already
    drifted once, which is what T111 exists to repair. Found by this task's
    second-reader review, which is the case for having one.

    `probes_checked` is kept. It moves only when the table in THIS file moves,
    which is this module's own pull request, and a shrinking probe table is
    exactly the thing the reader of this record needs to see.

    `unmeasured_reason` names the live count, and is present only when the
    floor is already breached — a state in which the record says so rather than
    reporting a zero, and in which a moving string is the least of it.
    """
    dropped = ("packages_checked",)
    committed = {key: value for key, value in measured.items() if key not in dropped}
    committed["packages_checked_at_least"] = MINIMUM_PACKAGES
    return committed


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, directory: Path = DEFAULT_CONNECTORS_DIR
) -> dict[str, Any]:
    """Measure and record `status/evidence/T110.json`.

    Returns what was *measured*; writes what is *recorded* — `_main` still
    needs the live count to check it against its floor, and the file must not
    carry it. See `record`.
    """
    measured = measure(directory=directory)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.bodyless_post [evidence-path]` → T110's evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 3
    for row in measured["disagreements"]:
        print(
            f"{row['direction']}: {row['probe']} — rule says {row['rule']} "
            f"({row['clause']}), implementation {row['observed']}",
            file=sys.stderr,
        )
    for package in measured["offending_packages"]:
        print(
            f"fail-open: {package} builds a POST with no body and no Content-Type",
            file=sys.stderr,
        )
    for package in measured["packages_that_no_longer_build"]:
        print(f"fail-closed: {package}", file=sys.stderr)
    # Any disagreement is a failure of the run, and the metric alone is not the
    # whole of it: with the load check deleted and the builder's clamp intact,
    # nothing bad is *sent* — the count stays a truthful zero — and what has
    # gone is the schema's opinion, which R3 is about and the metric's name is
    # not. Reporting that through this exit status keeps the metric honest
    # about what it counts while `make evidence` still goes red, which is the
    # split "a green gate is necessary and is not sufficient" describes.
    failed = (
        measured["bodyless_posts_sent_without_a_content_type"]
        or measured["legal_shapes_refused"]
        or measured["disagreements"]
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
