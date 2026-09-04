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
import re
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
    probe = next(
        probe
        for probe in page_placeholder.PROBES
        if probe.name == "second placeholder reaching the builder past a skipped validator"
    )
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
        # R7's two other modes: `path_segment` was covered by nothing, and the
        # exact `probes_checked` in the committed evidence was the only thing
        # stopping any unpinned probe being deleted — which is the "count of the
        # day" T100 argues against, doing a job a name should do.
        "literal POST body under query_param pagination",
        "literal POST body under query_param pagination, with a key of that name",
        "literal POST body under path_segment pagination",
        "literal POST body under path_segment pagination, with a key of that name",
        "builder handed a placeholder at the URL param's name under query_param",
        "builder handed a placeholder at the URL param's name under path_segment",
        "builder handed a body that lacks the named key at all",
    } <= names, sorted(names)
    assert {probe.name for probe in page_placeholder.PROBES if not probe.validated}


def test_every_clause_of_the_rule_is_cited_by_some_probe() -> None:
    """A clause nothing probes is a clause the gate does not hold.

    The by-name pin covers the fail-open shapes and R7's modes, and the floor
    covers bulk deletion — but three probes could still be deleted, among them
    the ONLY probe for R1 and the ONLY one for R1b, with every test in this file
    green and the sole red an evidence drift on `probes_checked` (#338 third
    read, NF6). An exact denominator doing a name's job is what T100 argued
    against, so the coverage is asserted by clause instead.
    """
    cited = " ".join(probe.clause for probe in page_placeholder.PROBES)
    missing = []
    for clause in page_placeholder.RULE:
        identifier = clause.split(":", 1)[0]
        # Boundary-aware. A bare `in` made "R1" a prefix of "R1b", so deleting the
        # ONLY R1 probe still passed on the R1b probe's citation — the exact probe
        # this test was written to protect, satisfied for the other one
        # (#338 fourth read, F-B). The lookarounds still tolerate a compound
        # citation like "R4+R6 — …".
        pattern = rf"(?<![0-9A-Za-z]){re.escape(identifier)}(?![0-9A-Za-z])"
        if not re.search(pattern, cited):
            missing.append(identifier)
    assert not missing, missing


@pytest.mark.parametrize("half", ("loads", "varies", "varies-missing", "values"))
def test_a_deliberately_wrong_probe_table_is_reported(half: str) -> None:
    """The negative control, one arm per half of the comparison.

    `measure()` returning zero is only meaningful if the comparison it performs
    *can* fail, and it could not: guarding the load half on `loads != loads`,
    narrowing the `varies` half back to `if loads and ...`, and neutering the
    `values` half each left the metric at zero with the whole suite green.

    One inverted table does not reach all three. Inverting `loads` flips the
    unvalidated probes to `loads=True`, which re-enables the very guard the
    `varies` narrowing removes, so that mutation stayed invisible (#338 delta
    re-read, F3b/F3c). Each half is therefore perturbed on its own, and the
    count of probes that must be reported is derived from the table rather than
    written down.
    """
    probes = page_placeholder.PROBES
    if half == "loads":
        wrong = tuple(replace(probe, loads=not probe.loads) for probe in probes)
        expected = [probe for probe in probes if probe.validated]
    elif half == "varies":
        # A position no body holds. Only probes whose `varies` is compared at
        # all can report — the ones that load, plus every unvalidated one.
        wrong = tuple(replace(probe, varies=(*probe.varies, "no-such-key")) for probe in probes)
        expected = [probe for probe in probes if probe.loads or not probe.validated]
    elif half == "varies-missing":
        # The other direction, and the one the three arms left unasserted:
        # emptying `varies` makes the implementation vary at a position the rule
        # does not name, which is T109's originating defect and the most
        # fail-open row this metric can emit. With only the arm above, hard-coding
        # that branch's label to "fail-closed" was green (#338 fourth read, F-A).
        wrong = tuple(replace(probe, varies=()) for probe in probes)
        expected = [
            probe
            for probe in probes
            if probe.varies and (probe.loads or not probe.validated)
        ]
    else:
        # The digits as a string rather than the number — R6's second half,
        # which is a value and not a position.
        wrong = tuple(
            replace(probe, values=tuple(str(value) for value in probe.values))
            for probe in probes
        )
        expected = [probe for probe in probes if probe.values]

    assert expected, half
    measured = page_placeholder.measure(wrong)
    assert measured["page_placeholders_resolved_inconsistently"] == len(expected), (
        half,
        measured["inconsistencies"],
    )

    # The direction half, which nothing asserted: parametrising this control
    # dropped the one `fail_open >= 1` the file used to carry, and hard-coding
    # every `direction` to "fail-closed" then left the whole suite green and the
    # committed evidence byte-identical (#338 third read, NF1). Fail-open is the
    # dimension this repository weights highest, so a metric reporting it must
    # not be free to report the cheaper class.
    #
    # Each count is derived from the table's declared verdicts, never from a run:
    #   loads  — a probe the rule REFUSES, observed loading, is the fail-open one;
    #            inverted, that is every probe the rule says loads.
    #   varies — the perturbation adds a position the body does not hold, so the
    #            implementation varies a subset of what is expected: fail-closed.
    #   values — a page number sent as the wrong type is always fail-open.
    if half == "loads":
        fail_open = [probe for probe in probes if probe.validated and probe.loads]
    elif half == "varies":
        fail_open = []
    else:
        # `varies-missing` and `values` are both wholly fail-open: the first
        # varies a position nothing declared, the second sends the page number as
        # the wrong type.
        fail_open = expected
    assert measured["fail_open"] == len(fail_open), (half, measured["inconsistencies"])


def test_the_value_half_is_armed_on_the_probes_that_can_carry_it() -> None:
    """`values` is opt-in, and an opt-in assertion is one that can be switched
    off without a test noticing. Deleting both `values=(1, 2)` lines left `make
    host-gate` fully green — probes intact, `probes_checked` unchanged,
    `evidence: no drift` — and a `str(page)` regression invisible to the gate
    again (#338 delta re-read, N1). Every probe whose named key is expected to
    vary must carry the value it becomes.
    """
    armed = {probe.name for probe in page_placeholder.PROBES if probe.values}
    assert armed == {
        probe.name
        for probe in page_placeholder.PROBES
        if probe.param is not None and probe.varies == (probe.param,)
    }, armed
    assert len(armed) >= 2, armed
    for probe in page_placeholder.PROBES:
        if probe.values:
            assert probe.values == (probe.start, probe.start + 1), probe.name
    # And at least one of them starts somewhere other than the default, or
    # `pagination.start` is a field no probe can vary and mutating `start +
    # offset` to `1 + offset` is invisible here (#338 third read, NF3).
    assert any(probe.start != 1 for probe in page_placeholder.PROBES if probe.values)


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


def test_two_positions_never_share_a_refusal_message() -> None:
    """The message unambiguity as a property, not as two literal regexes.

    A top-level key named `Filters.inner` and the nested pair `Filters` -> `inner`
    are different positions, and the refusal has to say which one it found — the
    comparison being structural is only half of T109's fix, because the other half
    is a message that does not teach the wrong repair. Asserted over pairs rather
    than by pinning one string, so a rendering change that re-introduces a
    collision fails here even if it keeps both regexes matching.
    """
    collisions = (
        ({"Filters.inner": PAGE_PLACEHOLDER}, {"Filters": {"inner": PAGE_PLACEHOLDER}}),
        ({"Sort[0]": PAGE_PLACEHOLDER}, {"Sort": [PAGE_PLACEHOLDER]}),
        ({"0": PAGE_PLACEHOLDER}, {"": [PAGE_PLACEHOLDER]}),
    )
    for left, right in collisions:
        messages = set()
        for extra in (left, right):
            with pytest.raises(ConnectorError) as refused:
                parse_connector(_document({"Page": PAGE_PLACEHOLDER, **extra}))
            messages.add(str(refused.value))
        assert len(messages) == 2, (left, right, messages)
