"""T109: one rule decides where `{page}` may sit, and both readers use it.

`connectors` has two readers of the same question — "which positions in
`list.body_json` carry the page placeholder?". Before this task they were
written separately: the load check asked whether the key `pagination.param`
names holds `"{page}"`, and `build_list_requests` walked the whole structure
replacing every `"{page}"` it met. Both readings are defensible on their own
and they disagree on one shape:

```yaml
body_json:
  Page: "{page}"          # legal, and named by pagination.param
  Filters:
    inner: "{page}"       # refused when it is the only occurrence …
```

Alone, `Filters.inner` is refused at load — `pagination.param` must name a
*top-level* key. Beside a legal `Page`, the load check is satisfied by `Page`
and never looks further, so the document loads and the walk substitutes
**both**. Same nested value, opposite verdict, decided by whether a legal
sibling happens to be present. The path a contributor actually takes makes it
worse than a coin flip: they nest a placeholder, are told to name a top-level
key, add one to satisfy the error, and silently acquire a second substitution
they never declared. The error message teaches a workaround that changes the
request.

This module is the measurement, not the fix — the fix is
`connectors._page_placeholder_paths`, which both readers now come from. What
is measured here is that they cannot drift apart again: each probe below
carries the verdict **the rule requires**, derived from the rule's text and
never from running the code, and the metric counts the probes where the
implementation and the rule disagree.

The metric is named after the wrong outcome (`…_resolved_inconsistently`) and
not after a category of inputs, so it cannot be satisfied by there being no
such inputs: the floor `MINIMUM_PROBES` is what refuses a clean zero over an
empty probe table, and `probes_checked` is reported beside it so a shrinking
table is visible rather than silent.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from integral.connectors import (
    PAGE_PLACEHOLDER,
    Connector,
    ConnectorError,
    build_list_requests,
    parse_connector,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T109.json"

# A FLOOR, never the count of the day — T100's precedent, for T100's reason: a
# denominator committed as an exact value is a number that has to be rewritten
# by changes that have nothing to do with what it measures. Here it also does
# the job `MINIMUM_SCANNED` does in `naming`: zero disagreements over a probe
# table somebody emptied is exactly the vacuous pass this module exists to
# refuse.
MINIMUM_PROBES = 21

# The rule, in one place, quoted by every probe's `clause`. Each line is a
# clause a verdict may cite; nothing below cites the implementation.
RULE = (
    "R1: `{page}` is legal only as a complete value — a string whose entire "
    "content is the placeholder (`_literal_body_violations`).",
    "R1b: a KEY may never be a placeholder — only values substitute, so a body "
    "whose shape varies by page is not a literal body (`_literal_body_violations`).",
    "R2: a body carrying `{page}` must declare `pagination.mode: body_field`.",
    "R3: `pagination.mode: body_field` requires a `{page}` somewhere in the "
    "body — otherwise nothing varies from page to page.",
    "R4: `pagination.param` must name a TOP-LEVEL key of `body_json` whose "
    "value is the placeholder.",
    "R5: the key `pagination.param` names is the ONLY position that may hold "
    "the placeholder — a second or nested occurrence is a substitution "
    "nothing declared.",
    "R6: exactly the position R4 names varies from page to page, and it "
    "becomes the page NUMBER, not the digits as a string.",
    "R6b: the page numbers substituted are counted from `pagination.start`, "
    "which defaults to 1 — so the first two requests carry `start` and `start + 1` "
    "(`Pagination.start`, `build_list_requests`).",
    "R7: `pagination.param` names a body key only under `mode: body_field`. "
    "Under any other mode — `query_param`, `path_segment` — it names a URL key, "
    "so no body position varies (`Pagination.mode`).",
)

_DOCUMENT: dict[str, Any] = {
    "site": "probeboard",
    "locale": "en",
    "version": "1.0.0",
    "last_verified": "2026-08-31",
    "auth": "none",
    "list": {
        "url_pattern": "https://boards.test/Search/ExecuteSearch",
        "method": "POST",
        "from_json": {
            "items": "Jobs",
            "fields": {"title": "Title", "text": "Summary", "detail_url": "PositionURI"},
        },
    },
}


@dataclass(frozen=True)
class Probe:
    """One body shape, and the verdict the rule requires of it.

    `loads` and `varies` are written from `RULE`, before and independently of
    what the implementation does with the shape. That is the whole point: a
    fixture whose expected value was read off a run certifies the run.
    """

    name: str
    body_json: dict[str, Any]
    mode: str
    param: str | None
    loads: bool
    varies: tuple[str, ...]
    clause: str
    #: What the named key becomes on the first two pages. R6's second half —
    #: the page NUMBER, not its digits as a string — is not a *position*, so
    #: `varies` cannot express it and a mutation substituting `str(page)` left
    #: the metric at zero (#338 second-reader F4). Empty when nothing varies.
    values: tuple[Any, ...] = ()
    #: `pagination.start`. A probe could not express anything but the default,
    #: so mutating `start + offset` to `1 + offset` left the metric at zero and
    #: was caught only by a neighbouring gate's test — the dependency `values`
    #: was added to remove, still standing one field along (#338 third read, NF3).
    start: int = 1
    #: `False` builds the connector with `model_copy(update=...)`, which never
    #: meets the validators — the case the module's belt-and-suspenders
    #: posture exists for, and the only way to observe what the request
    #: builder does on its own with a body the load check would have refused.
    #: The load verdict is not compared for such a probe (there was no load);
    #: `varies` is, and that is the half being measured.
    validated: bool = True


PROBES: tuple[Probe, ...] = (
    Probe(
        name="named top-level placeholder, alone",
        body_json={"Keyword": "python", "ResultsPerPage": 25, "Page": PAGE_PLACEHOLDER},
        mode="body_field",
        param="Page",
        loads=True,
        varies=("Page",),
        values=(1, 2),
        clause="R4+R6 — the named top-level key holds it, and it is the one that varies",
    ),
    Probe(
        name="named top-level placeholder, starting at a page other than the first",
        body_json={"Keyword": "python", "Page": PAGE_PLACEHOLDER},
        mode="body_field",
        param="Page",
        loads=True,
        varies=("Page",),
        values=(5, 6),
        start=5,
        clause="R6b — the page numbers are counted from `pagination.start`, "
        "so the first two requests carry 5 and 6",
    ),
    Probe(
        name="nested placeholder, alone",
        body_json={"Keyword": "python", "Filters": {"inner": PAGE_PLACEHOLDER}},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R4 — `Page` is not a key of the body at all",
    ),
    Probe(
        name="nested placeholder BESIDE a legal named one (T109's shape)",
        body_json={"Page": PAGE_PLACEHOLDER, "Filters": {"inner": PAGE_PLACEHOLDER}},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R5 — `Filters.inner` is a second occurrence; fail-open if it loads",
    ),
    Probe(
        name="two top-level placeholders, one of them named",
        body_json={"Page": PAGE_PLACEHOLDER, "Offset": PAGE_PLACEHOLDER},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R5 — `Offset` is a second occurrence; fail-open if it loads",
    ),
    Probe(
        name="placeholder inside a list element, beside a legal named one",
        body_json={"Page": PAGE_PLACEHOLDER, "Sort": [{"by": PAGE_PLACEHOLDER}]},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R5 — `Sort[0].by` is a second occurrence; fail-open if it loads",
    ),
    Probe(
        name="placeholder at an unnamed top-level key, alone",
        body_json={"Keyword": "python", "Offset": PAGE_PLACEHOLDER},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R4 — the named key `Page` is absent",
    ),
    Probe(
        name="body_field declared over a body with no placeholder",
        body_json={"Keyword": "python", "Page": 1},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R3 — nothing would vary from page to page",
    ),
    Probe(
        name="placeholder present but pagination is query_param",
        body_json={"Keyword": "python", "Page": PAGE_PLACEHOLDER},
        mode="query_param",
        param="page",
        loads=False,
        varies=(),
        clause="R2 — a body that paginates must say so with mode: body_field",
    ),
    Probe(
        name="placeholder embedded in a longer string",
        body_json={"Keyword": "python", "Page": f"page {PAGE_PLACEHOLDER} of many"},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R1 — a brace that is not the whole value is refused, not passed through",
    ),
    Probe(
        name="placeholder as a KEY rather than a value",
        body_json={PAGE_PLACEHOLDER: 1, "Page": PAGE_PLACEHOLDER},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R1b — only values substitute; a body whose shape varies by page is not literal",
    ),
    Probe(
        name="deeply nested placeholder, alone, inside a list",
        body_json={"Keyword": "python", "Sort": [{"by": {"deep": PAGE_PLACEHOLDER}}]},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R4 — `Page` is not a key of the body at all",
    ),
    Probe(
        name="literal body, no placeholder, no pagination",
        body_json={"Keyword": "python", "ResultsPerPage": 25},
        mode="none",
        param=None,
        loads=True,
        varies=(),
        clause="R2/R3 vacuous — nothing carries the placeholder, so nothing varies",
    ),
    Probe(
        name="second placeholder reaching the builder past a skipped validator",
        body_json={"Page": PAGE_PLACEHOLDER, "Filters": {"inner": PAGE_PLACEHOLDER}},
        mode="body_field",
        param="Page",
        loads=False,
        varies=("Page",),
        values=(1, 2),
        clause="R6 — only the position R4 names varies, whatever else the body holds",
        validated=False,
    ),
    # ---- #338 second-reader F1: a key whose own spelling collides with a nested
    # position. Paths are compared structurally now; before that both rendered as
    # the string "Filters.inner" and the second occurrence walked through.
    Probe(
        name="top-level key spelled like a nested path, beside that nested path",
        body_json={"Filters.inner": PAGE_PLACEHOLDER, "Filters": {"inner": PAGE_PLACEHOLDER}},
        mode="body_field",
        param="Filters.inner",
        loads=False,
        varies=(),
        clause="R5 — `Filters` → `inner` is a second occurrence, and sharing a "
        "*rendering* with the named key does not make it the named key; fail-open if it loads",
    ),
    Probe(
        name="top-level key spelled like a list index, beside that list element",
        body_json={"Sort[0]": PAGE_PLACEHOLDER, "Sort": [PAGE_PLACEHOLDER]},
        mode="body_field",
        param="Sort[0]",
        loads=False,
        varies=(),
        clause="R5 — `Sort` → element 0 is a second occurrence; fail-open if it loads",
    ),
    Probe(
        name="empty-string key holding the placeholder beside the named one",
        body_json={"": PAGE_PLACEHOLDER, "Page": PAGE_PLACEHOLDER},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R5 — the empty key is a second occurrence; fail-open if it loads",
    ),
    # ---- #338 second-reader F2: `pagination.param` is a URL key under any mode but
    # `body_field`, and handing that name to the body substituter put a page number
    # in a field nothing declared — from a fully validated connector.
    Probe(
        name="literal POST body under query_param pagination",
        body_json={"Keyword": "python", "ResultsPerPage": 25},
        mode="query_param",
        param="page",
        loads=True,
        varies=(),
        clause="R7 — `page` names a URL key here, so no body position varies",
    ),
    # T154 round 3 (R1's mirror), on `connectors.py`'s own separate rule
    # (`_a_page_placeholder_and_a_query_key_imply_each_other`, route 4): this
    # probe used to load, on R7's own reasoning below — the *builder* never
    # touches a body key `param` does not name, so nothing here is R7's
    # concern. But `query_param`'s URL genuinely varies `page` while this
    # body fixes it, and a framework whose merged `request.values` /
    # `$_REQUEST` / `params` honours the body's fixed value over the query's
    # varying one is pinned to page 25 regardless — the same merged-namespace
    # harm route 4 refuses on the `body_field` side, reached from the other
    # direction. Refused at load now, before R7's builder question is ever
    # reached; R7's own point stays true and simply never gets exercised for
    # this shape, the way every route-4-refused shape leaves every later
    # check moot.
    Probe(
        name="literal POST body under query_param pagination, with a key of that name",
        body_json={"Keyword": "python", "page": 25},
        mode="query_param",
        param="page",
        loads=False,
        varies=(),
        clause="R7 — `page` names a URL key here; the body's own `page` is a "
        "declared literal and must not be overwritten. Refused before R7 is even "
        "reached: `connectors._a_page_placeholder_and_a_query_key_imply_each_other`'s "
        "route 4 (T154, round 3) refuses a query_param board whose body repeats the "
        "URL key's own name, fixed — a merged query/body namespace may honour the "
        "body's stale value over the query's varying one",
    ),
    # R7 says "any other mode", and there are two of them. Probing only
    # `query_param` left `path_segment` covered by nothing: widening the
    # allowlist to `("body_field", "path_segment")` was caught by no test and no
    # metric, and with the defensive guard also gone a declared literal at that
    # key was destroyed (#338 delta re-read, N2).
    Probe(
        name="literal POST body under path_segment pagination",
        body_json={"Keyword": "python", "ResultsPerPage": 25},
        mode="path_segment",
        param="page",
        loads=True,
        varies=(),
        clause="R7 — `page` names a URL key here, so no body position varies",
    ),
    Probe(
        name="literal POST body under path_segment pagination, with a key of that name",
        body_json={"Keyword": "python", "page": 25},
        mode="path_segment",
        param="page",
        loads=True,
        varies=(),
        clause="R7 — `page` names a URL key here; the body's own `page` is a "
        "declared literal and must not be overwritten",
    ),
    Probe(
        name="builder handed a placeholder at the URL param's name under path_segment",
        body_json={"Keyword": "python", "page": PAGE_PLACEHOLDER},
        mode="path_segment",
        param="page",
        loads=False,
        varies=(),
        clause="R7 — `page` names a URL key under this mode, so the builder must "
        "vary no body position at all; fail-open if it substitutes",
        validated=False,
    ),
    Probe(
        name="builder handed a placeholder at the URL param's name under query_param",
        body_json={"Keyword": "python", "page": PAGE_PLACEHOLDER},
        mode="query_param",
        param="page",
        loads=False,
        varies=(),
        clause="R7 — `page` names a URL key under this mode, so the builder must "
        "vary no body position at all; fail-open if it substitutes",
        validated=False,
    ),
    Probe(
        name="builder handed a body that lacks the named key at all",
        body_json={"Keyword": "python"},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R6 — nothing at the named position, so nothing varies; the builder "
        "must not CREATE the key",
        validated=False,
    ),
    Probe(
        name="named placeholder with a same-named key nested under it",
        body_json={"Page": PAGE_PLACEHOLDER, "Filters": {"Page": PAGE_PLACEHOLDER}},
        mode="body_field",
        param="Page",
        loads=False,
        varies=(),
        clause="R5 — `Filters.Page` is a second occurrence, and sharing the "
        "named key's spelling does not make it the named key; fail-open if it loads",
    ),
)


def _url_pattern(probe: Probe) -> str:
    """The list URL this probe's *mode* requires, so only its body is on trial.

    Every probe here is about the **body** rule, and the scaffold URL was a
    fixed `.../Search/ExecuteSearch` under every mode. T113's second-reader
    round closed the URL half of the same rule
    (`_a_page_placeholder_and_a_query_key_imply_each_other`), and that URL is
    one of the three shapes it now refuses: a `query_param` or `path_segment`
    connector with no `{page}` anywhere issues the identical URL `max_pages`
    times. Refusing it is correct, and it would have turned every R7 probe into
    a load failure for a reason that has nothing to do with the body.

    So the URL is derived from the mode rather than fixed: `{page}` under the
    key `pagination.param` names for `query_param`, a path position for
    `path_segment`, and none at all for `body_field` and `none` — which is what
    those two modes now require.
    """
    base = _DOCUMENT["list"]["url_pattern"]
    if probe.mode == "query_param" and probe.param is not None:
        return f"{base}?{probe.param}={PAGE_PLACEHOLDER}"
    if probe.mode == "path_segment":
        return f"{base}/{PAGE_PLACEHOLDER}"
    return str(base)


def _document(probe: Probe) -> str:
    """The probe as a whole connector document, ready for `parse_connector`."""
    document = json.loads(json.dumps(_DOCUMENT))
    document["list"]["url_pattern"] = _url_pattern(probe)
    document["list"]["body_json"] = probe.body_json
    pagination: dict[str, Any] = {"mode": probe.mode}
    if probe.param is not None:
        pagination["param"] = probe.param
    if probe.mode != "none":
        pagination["max_pages"] = 2
        pagination["start"] = probe.start
    document["list"]["pagination"] = pagination
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def _differing_paths(first: Any, second: Any, where: str = "") -> list[str]:
    """Every position at which two request bodies differ.

    Compared as parsed structures rather than as bytes, so "the body changed"
    is answered by *where* it changed — the same granularity the load check
    speaks in, which is what makes the two comparable at all.
    """
    if isinstance(first, dict) and isinstance(second, dict):
        if first.keys() != second.keys():
            return [where or "<root>"]
        return [
            path
            for key in first
            for path in _differing_paths(
                first[key], second[key], f"{where}.{key}" if where else key
            )
        ]
    if isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            return [where or "<root>"]
        return [
            path
            for index, (a, b) in enumerate(zip(first, second, strict=True))
            for path in _differing_paths(a, b, f"{where}[{index}]")
        ]
    return [] if first == second else [where or "<root>"]


def _unvalidated(probe: Probe) -> Connector:
    """`probe` as a `Connector` the validators never saw.

    `model_copy(update=...)` is pydantic's documented escape from validation,
    and the reason several checks in `connectors` are repeated at use rather
    than trusted from load. A probe built this way measures the request
    builder alone: whatever the load check would have said, only the position
    `pagination.param` names may vary.
    """
    param = probe.param
    scaffold = parse_connector(
        _document(
            replace(
                probe,
                # A scaffold that always loads, so the only thing this probe
                # measures is the builder. The placeholder is the scaffold's own,
                # never the probe's value at that key: reading the probe's value
                # meant a named key holding `0`, `""` or `False` built an empty
                # body, which `parse_connector` refuses with an UNCAUGHT error
                # that aborts the whole run rather than reporting a disagreement
                # (#338 F7). Under any mode but `body_field` a placeholder in the
                # body is refused at load, so the scaffold carries none there.
                #
                # `param` is the probe's own throughout. Substituting a different
                # name when the probe's body lacks the key made the report read
                # `varies at ['x']` — a key appearing nowhere in the probe (N4),
                # which is a misdescribed input in a task about a refusal that
                # misleads.
                body_json=(
                    {param: PAGE_PLACEHOLDER}
                    if probe.mode == "body_field" and param
                    else {"Keyword": "python"}
                ),
                validated=True,
                loads=True,
            )
        )
    )
    page = scaffold.list.model_copy(update={"body_json": probe.body_json})
    return scaffold.model_copy(update={"list": page})


def _observed(probe: Probe) -> tuple[bool, tuple[str, ...], tuple[Any, ...], str]:
    """What the implementation does: loads?, varies where?, becomes what?, why not."""
    if not probe.validated:
        connector = _unvalidated(probe)
        bodies = [json.loads(request.body or b"null") for request in build_list_requests(connector)]
        varies = tuple(_differing_paths(bodies[0], bodies[1]))
        return probe.loads, varies, _values(probe, bodies), ""
    try:
        connector = parse_connector(_document(probe))
    except ConnectorError as exc:
        return False, (), (), str(exc).replace("\n", " ")
    requests = build_list_requests(connector)
    bodies = [json.loads(request.body or b"null") for request in requests]
    if len(bodies) < 2:
        return True, (), (), ""
    return True, tuple(_differing_paths(bodies[0], bodies[1])), _values(probe, bodies), ""


def _values(probe: Probe, bodies: list[Any]) -> tuple[Any, ...]:
    """What the named key became on each page.

    R6 has a second half — the placeholder becomes the page NUMBER, not its
    digits as a string — and that is a *value*, not a position, so `varies`
    cannot express it: substituting `str(page)` left the metric at zero while
    the pre-existing T89 test caught it (#338 second-reader F4). Measured here
    so T109's own gate does not depend on a neighbouring one.
    """
    if not probe.values or probe.param is None:
        return ()
    return tuple(
        body.get(probe.param) if isinstance(body, dict) else None
        for body in bodies[: len(probe.values)]
    )


def measure(probes: tuple[Probe, ...] = PROBES) -> dict[str, Any]:
    """Every probe whose treatment disagrees with the rule it cites."""
    if len(probes) < MINIMUM_PROBES:
        return {
            "page_placeholders_resolved_inconsistently": 0,
            "page_placeholder_probes_at_least": MINIMUM_PROBES,
            "probes_checked": len(probes),
            "inconsistencies": [],
            "fail_open": 0,
            "gate_status": "unmeasured",
            "unmeasured_reason": (
                f"only {len(probes)} probe(s) (floor {MINIMUM_PROBES}) — zero disagreements "
                "over an empty table is not a pass"
            ),
        }

    inconsistencies: list[dict[str, Any]] = []
    for probe in probes:
        loads, varies, values, refusal = _observed(probe)
        if probe.validated and loads != probe.loads:
            inconsistencies.append(
                {
                    "probe": probe.name,
                    "clause": probe.clause,
                    "rule": "loads" if probe.loads else "refused at load",
                    "observed": "loads" if loads else f"refused: {refusal}",
                    # Loading what the rule refuses is the expensive direction:
                    # the request goes out carrying a page number in a field
                    # nothing declared. The other way costs a contributor a
                    # correction they can see.
                    "direction": "fail-open" if loads else "fail-closed",
                }
            )
            continue
        # An unvalidated probe has no load verdict to compare — it never went
        # through one — so its `varies` and `values` are compared unconditionally.
        # Guarding on `loads` alone made the whole belt-and-suspenders half of the
        # measurement dead code, and restoring the full-structure walk then left
        # the metric at zero. That was found by running a mutation rather than by
        # reading the guard — and narrowing it back is not itself detectable by
        # inverting a probe's load verdict, because the inversion re-enables the
        # guard being narrowed. Each half of this comparison therefore has its own
        # arm in `test_a_deliberately_wrong_probe_table_is_reported`.
        if (loads or not probe.validated) and values != probe.values:
            inconsistencies.append(
                {
                    "probe": probe.name,
                    "clause": probe.clause,
                    "rule": f"the named key becomes {list(probe.values)}",
                    "observed": f"it becomes {list(values)}",
                    # A page number sent as a string is a body the board reads
                    # differently from the one the connector declared.
                    "direction": "fail-open",
                }
            )
            continue
        if (loads or not probe.validated) and varies != probe.varies:
            extra = [path for path in varies if path not in probe.varies]
            inconsistencies.append(
                {
                    "probe": probe.name,
                    "clause": probe.clause,
                    "rule": f"varies at {list(probe.varies)}",
                    "observed": f"varies at {list(varies)}",
                    "direction": "fail-open" if extra else "fail-closed",
                }
            )

    return {
        "page_placeholders_resolved_inconsistently": len(inconsistencies),
        "page_placeholder_probes_at_least": MINIMUM_PROBES,
        "probes_checked": len(probes),
        "inconsistencies": inconsistencies,
        "fail_open": sum(1 for row in inconsistencies if row["direction"] == "fail-open"),
        "gate_status": "measured",
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T109.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.page_placeholder [evidence-path]` → T109's evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 3
    for row in measured["inconsistencies"]:
        print(
            f"{row['direction']}: {row['probe']} — rule says {row['rule']} "
            f"({row['clause']}), implementation {row['observed']}",
            file=sys.stderr,
        )
    return 1 if measured["page_placeholders_resolved_inconsistently"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
