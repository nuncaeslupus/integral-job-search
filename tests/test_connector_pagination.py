"""T109: where `{page}` may sit, decided once.

`connectors` used to answer "which positions hold the page placeholder?"
twice — once at load, once when building the request — and the two answers
differed on one shape. These tests pin the shape, both directions, and the
consequence a contributor actually meets.

The measurement lives in `integral.page_placeholder`; what is here is the
behaviour it measures, asserted directly so a regression fails `make test`
and not only the evidence run.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from integral import page_placeholder
from integral.connectors import (
    PAGE_PLACEHOLDER,
    ConnectorError,
    build_list_requests,
    parse_connector,
)


def _document(body_json: dict[str, Any], *, mode: str = "body_field", param: str = "Page") -> str:
    """A whole POST connector carrying `body_json`, built the way the gate's
    probes are — one construction, so a test and its evidence cannot diverge
    on the scaffolding rather than on the property."""
    probe = page_placeholder.Probe(
        name="ad hoc",
        body_json=body_json,
        mode=mode,
        param=param,
        loads=False,
        varies=(),
        clause="—",
    )
    return page_placeholder._document(probe)


def test_a_nested_placeholder_gets_the_same_verdict_with_and_without_a_top_level_one() -> None:
    """The defect, stated as the equality it broke.

    A nested `{page}` alone was refused; the identical nested `{page}` with a
    legal `Page: "{page}"` beside it loaded, and both substituted. The verdict
    on a position must not depend on what sits somewhere else in the document.
    """
    nested = {"Keyword": "python", "Filters": {"inner": PAGE_PLACEHOLDER}}
    beside = {"Page": PAGE_PLACEHOLDER, "Filters": {"inner": PAGE_PLACEHOLDER}}

    with pytest.raises(ConnectorError):
        parse_connector(_document(nested))
    with pytest.raises(ConnectorError, match=r"'Filters'\.'inner'"):
        parse_connector(_document(beside))


def test_the_refusal_message_does_not_teach_a_workaround_that_changes_the_request() -> None:
    """The expensive half of T109 was not the refusal — it was the repair it
    invited. Told that `pagination.param` must name a top-level key, an author
    adds one and keeps the nested placeholder; before this, that document
    loaded and quietly sent the page number in a second field. Following the
    message's advice must not produce a request nobody declared.
    """
    with pytest.raises(ConnectorError) as refused:
        parse_connector(_document({"Keyword": "python", "Filters": {"inner": PAGE_PLACEHOLDER}}))
    assert "top-level key" in str(refused.value)

    # The literal repair the message suggests, applied without removing the
    # nested one: still refused, and the message now names the position.
    with pytest.raises(ConnectorError, match=r"'Filters'\.'inner'"):
        parse_connector(
            _document(
                {
                    "Keyword": "python",
                    "Page": PAGE_PLACEHOLDER,
                    "Filters": {"inner": PAGE_PLACEHOLDER},
                }
            )
        )


def test_only_the_named_key_varies_from_page_to_page() -> None:
    """The positive case, and the shape of the substitution: the named key
    becomes the page *number*, and nothing else in the body moves."""
    connector = parse_connector(_document({"Keyword": "python", "Page": PAGE_PLACEHOLDER}))
    bodies = [json.loads(request.body or b"null") for request in build_list_requests(connector)]
    assert bodies == [
        {"Keyword": "python", "Page": 1},
        {"Keyword": "python", "Page": 2},
    ]


def test_the_builder_alone_substitutes_one_key_even_past_a_skipped_validator() -> None:
    """`model_copy(update=...)` never meets a validator, which is why several
    checks in `connectors` are repeated at use. The request builder is one of
    them: handed a body the load check would have refused, it still varies
    only the key `pagination.param` names.
    """
    probe = next(probe for probe in page_placeholder.PROBES if not probe.validated)
    connector = page_placeholder._unvalidated(probe)
    bodies = [json.loads(request.body or b"null") for request in build_list_requests(connector)]
    assert bodies[0]["Filters"] == {"inner": PAGE_PLACEHOLDER}
    assert [body["Page"] for body in bodies] == [1, 2]


def test_the_probe_table_carries_the_fail_open_shapes_and_meets_its_floor() -> None:
    """A gate whose table somebody emptied reports zero disagreements. The
    floor refuses that, and these are the shapes that must stay in it.

    Pinned **by name**, not by count. A count is satisfied by any N probes, so
    the protection it gave T109's own shape was coincidental — adding a ninth
    fail-open probe would have made the original removable while a `>= 8` still
    passed (#338 second-reader F10).
    """
    assert len(page_placeholder.PROBES) >= page_placeholder.MINIMUM_PROBES
    names = {probe.name for probe in page_placeholder.PROBES}
    assert {
        "nested placeholder BESIDE a legal named one (T109's shape)",
        "two top-level placeholders, one of them named",
        "placeholder inside a list element, beside a legal named one",
        "named placeholder with a same-named key nested under it",
        "top-level key spelled like a nested path, beside that nested path",
        "top-level key spelled like a list index, beside that list element",
        "empty-string key holding the placeholder beside the named one",
    } <= names, sorted(names)
    assert {probe.name for probe in page_placeholder.PROBES if not probe.validated}


def test_a_deliberately_wrong_probe_table_is_reported(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The negative control the module lacked.

    `measure()` returning zero is only meaningful if the comparison it performs
    *can* fail. It could not, twice: guarding the load half on `loads != loads`
    and narrowing the `varies` half back to `if loads and ...` each left the
    metric at zero with the whole suite green (#338 second-reader F3). Handing
    it a table whose every expected verdict is inverted must report every
    validated probe — a check on the measurement rather than on the code it
    measures.
    """
    inverted = tuple(
        replace(probe, loads=not probe.loads) for probe in page_placeholder.PROBES
    )
    measured = page_placeholder.measure(inverted)
    validated = [probe for probe in page_placeholder.PROBES if probe.validated]
    assert measured["page_placeholders_resolved_inconsistently"] == len(validated)
    assert measured["fail_open"] >= 1


def test_the_gate_is_measured_and_finds_nothing() -> None:
    """The committed verdict, recomputed."""
    measured = page_placeholder.measure()
    assert measured["gate_status"] == "measured"
    assert measured["page_placeholders_resolved_inconsistently"] == 0
    assert measured["inconsistencies"] == []


def test_an_emptied_probe_table_is_unmeasured_rather_than_a_pass() -> None:
    """The floor, exercised rather than asserted — a zero over nothing is the
    vacuous pass this module exists to refuse."""
    measured = page_placeholder.measure(page_placeholder.PROBES[:2])
    assert measured["gate_status"] == "unmeasured"
    assert "floor" in measured["unmeasured_reason"]
