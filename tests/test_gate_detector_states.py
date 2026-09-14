"""T158 — the redesigned `Probe.counted_but_never_read`, mutation-tested for real.

Every case below runs `gate_reader_agreement.probe` against a real, textually
mutated copy of `tools/verify_gates.py` — never a hand-built `Probe` — because
the whole point of this task is that no state may be asserted about rather
than run. `bold_label` (the #334 case, `carries_a_readable_gate=False`) is the
fixture every state drives: it is the exact shape whose fence a reverted
classifier treats as declaring a readable gate.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from pathlib import Path

import pytest

from integral import gate_detector_states, gate_reader_agreement
from integral.gate_detector_states import (
    MINIMUM_DETECTOR_STATES_PROBED,
    MINIMUM_DISTINCT_STATE_TRACES,
    STATES,
    DetectorState,
    floor_breaches,
    measure,
    probe_state,
    record,
    write_evidence,
)
from integral.gate_reader_agreement import ARRANGEMENTS, Probe

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "status" / "evidence" / "T158.json"

CROSSED = tuple(s for s in STATES if s.classifier_reverted)
ALONE = tuple(s for s in STATES if not s.classifier_reverted)


def _ids(states: tuple[DetectorState, ...]) -> list[str]:
    return [s.name for s in states]


# ---------------------------------------------------------------------------
# Every state, run for real, pinned to the exact trace the module's docstring
# derives — the boundary between "the classifier alone is enough" and
# "the classifier plus a degraded catch is still enough" is the whole of what
# this task closes, so it is worth pinning exactly rather than only via the
# aggregate metric below.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", CROSSED, ids=_ids(CROSSED))
def test_a_reverted_classifier_trips_the_shipped_detector_regardless_of_the_catch(
    state: DetectorState,
) -> None:
    """The four crossed states: `checked` increments before the catch ever runs.

    `counted_as_asserted` becomes 1 the moment the (mutated) classifier lets
    `bold_label` reach `check_payload`, which happens before either of the
    catch's two effects — whatever `state` does to them. So the shipped,
    redesigned property must read True in all four, independent of whether
    the run itself ends up red or green.
    """
    result = probe_state(state)
    assert result.counted_as_asserted == 1, state.name
    assert result.counted_but_never_read, state.name
    assert state.defect_can_occur


@pytest.mark.parametrize("state", ALONE, ids=_ids(ALONE))
def test_an_intact_classifier_refuses_the_fixture_before_the_catch_matters(
    state: DetectorState,
) -> None:
    """The three states with the classifier untouched: no defect to detect.

    `gate_declaration` (real, unmutated) still calls `bold_label` unreadable,
    so `main` refuses it by name before `check_payload` — and so the catch,
    whichever way `state` has degraded it — is ever reached. `counted_as_asserted`
    stays 0 and the shipped property correctly reads False: not a hole, since
    `defect_can_occur` is False here by construction.
    """
    result = probe_state(state)
    assert result.counted_as_asserted == 0, state.name
    assert not result.counted_but_never_read, state.name
    assert not state.defect_can_occur


def test_the_exact_hole_sd425_measured_is_one_of_the_crossed_states() -> None:
    """`classifier_reverted_first_signal_removed` is #425's own scenario, pinned.

    Report muted (signal 1's only source), failure kept (so the run is still
    red — `green` is False). Under the *old* two-signal property this was the
    state that read clean; the assertion here is that the run really is red,
    which is what made the old second signal (`counted and green`) unable to
    help either.
    """
    result = probe_state(
        next(s for s in STATES if s.name == "classifier_reverted_first_signal_removed")
    )
    assert result.reported_never_read == 0, "the report's own list was muted"
    assert not result.green, "the catch's failure-effect was kept; the run is still red"
    assert result.counted_but_never_read, "the shipped property needs neither input"


# ---------------------------------------------------------------------------
# F3: the catch anchors are asserted present exactly once, same as the other
# two, and a stale or duplicated anchor fails loudly (`RuntimeError`), never
# by silently mutating nothing.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line_name", ["_CATCH_CONDITION_LINE", "_CATCH_END_LINE"], ids=["condition", "end"]
)
def test_a_missing_catch_anchor_raises_rather_than_mutating_nothing(
    line_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anchor that had no `.count(...) != 1` guard before F3.

    Deleting either catch anchor from the text must raise `RuntimeError`
    before `_mutate_catch` ever reaches its `.index()` calls — the same
    contract `_repoint_repo_root` and `_mutate_classifier` already had, and
    the one `_mutate_catch` was missing.
    """
    text = gate_reader_agreement.DEFAULT_VERIFIER.read_text(encoding="utf-8")
    line = getattr(gate_detector_states, line_name)
    assert text.count(line) == 1, "precondition: the real file carries the anchor once today"
    stale = text.replace(line, "        pass  # F3 test: anchor deleted\n", 1)

    with pytest.raises(RuntimeError, match="moved or is no longer unique"):
        gate_detector_states._mutate_catch(stale, report_removed=True, failure_removed=False)


@pytest.mark.parametrize(
    "line_name", ["_CATCH_CONDITION_LINE", "_CATCH_END_LINE"], ids=["condition", "end"]
)
def test_a_duplicated_catch_anchor_raises_rather_than_silently_picking_one(
    line_name: str,
) -> None:
    """The ambiguity `.index()` alone cannot see, which is F3's actual point.

    Before F3, `_mutate_catch` read `_CATCH_CONDITION_LINE`/`_CATCH_END_LINE`
    with a bare `.index()`, which only checks *presence*. If either line had
    drifted to appear twice, `.index()` would silently return the first match
    and mutate the wrong span — no exception, no signal. The two
    `.count(...) != 1` guards this task adds must catch that duplication
    directly, which a presence-only check never could.
    """
    text = gate_reader_agreement.DEFAULT_VERIFIER.read_text(encoding="utf-8")
    line = getattr(gate_detector_states, line_name)
    duplicated = text + line  # a harmless second copy, appended at end of file

    with pytest.raises(RuntimeError, match="moved or is no longer unique"):
        gate_detector_states._mutate_catch(duplicated, report_removed=True, failure_removed=False)


def test_the_end_anchor_present_once_but_before_the_condition_raises_value_error() -> None:
    """The one case `.count(...) != 1` cannot see, driven rather than merely commented.

    T158 review round 3 (F3): the comment above the four `_..._LINE`
    constants used to say a stale anchor "gone entirely" raises `ValueError`.
    Measured: it does not — `.count(...) != 1` catches a missing anchor for
    *either* line and raises `RuntimeError` before either `.index()` call
    runs (see the two tests above). The `ValueError` path is narrower: both
    anchors present exactly once, but the condition anchor sits *after* the
    end anchor, so `.index(_CATCH_END_LINE, start)` — which only searches
    forward from the condition anchor's own position — finds nothing.
    """
    reordered = (
        gate_detector_states._CATCH_END_LINE
        + "        pass  # F3 test: end anchor placed before the condition anchor\n"
        + gate_detector_states._CATCH_CONDITION_LINE
        + "            pass\n"
    )
    assert reordered.count(gate_detector_states._CATCH_CONDITION_LINE) == 1
    assert reordered.count(gate_detector_states._CATCH_END_LINE) == 1

    with pytest.raises(ValueError, match="substring not found"):
        gate_detector_states._mutate_catch(reordered, report_removed=True, failure_removed=False)


def test_a_stale_anchor_is_fail_closed_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the top-of-file comment now claims, driven rather than reasoned about.

    Before F3 the comment above the four `_..._LINE` constants claimed a
    stale anchor would silently read every state as `defect_can_occur=False`
    — impossible, since that field is `DetectorState.classifier_reverted`, a
    static fact fixed before any mutation runs, never derived from whether
    one succeeded. `probe_state` must instead propagate the exception: the
    run errors, not passes.
    """
    monkeypatch.setattr(gate_detector_states, "_CATCH_CONDITION_LINE", "this text is not present")
    with pytest.raises(RuntimeError):
        gate_detector_states.probe_state(STATES[0])


# ---------------------------------------------------------------------------
# The aggregate metric, and that it is a real gate rather than vacuously 0.
# ---------------------------------------------------------------------------


def test_todays_shipped_detector_clears_the_gate() -> None:
    measured = measure()
    assert measured["gate_status"] == "measured"
    assert measured["reverted_defects_the_metric_reads_as_clean"] == 0, measured[
        "reverted_defects_clean_states"
    ]
    assert len(measured["detector_states_probed"]) >= MINIMUM_DETECTOR_STATES_PROBED
    assert not floor_breaches(measured)


def test_the_pre_t158_two_signal_property_fails_this_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Today's code fails it by construction — the gate, not a pin.

    Swap in the exact two-signal property this task replaces and re-measure:
    it must read a nonzero count, and the one state it misses must be exactly
    `classifier_reverted_first_signal_removed` — #425's own measured hole.
    Without this the gate above could pass no matter what `counted_but_never_read`
    computes, which is the vacuous shape this whole task exists to close.
    """

    def old_two_signal_property(self: Probe) -> bool:
        if self.reported_never_read:
            return True
        return self.counted_as_asserted > 0 and self.green

    monkeypatch.setattr(Probe, "counted_but_never_read", property(old_two_signal_property))
    measured = measure()
    assert measured["reverted_defects_the_metric_reads_as_clean"] == 1
    assert measured["reverted_defects_clean_states"] == ["classifier_reverted_first_signal_removed"]


def test_a_verifier_that_never_counts_anything_fails_this_gate_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A property that always reads False is the other vacuous shape, and must fail too.

    Complements the case above: a metric that only ever notices when the
    *old* property regresses would still pass a property regressed to
    "nothing ever diverges", which is the silent-pass hole wearing yet
    another name.
    """
    monkeypatch.setattr(Probe, "counted_but_never_read", property(lambda self: False))
    measured = measure()
    assert measured["reverted_defects_the_metric_reads_as_clean"] == len(CROSSED)
    assert set(measured["reverted_defects_clean_states"]) == {s.name for s in CROSSED}


# ---------------------------------------------------------------------------
# The two things the redesign must not lose.
# ---------------------------------------------------------------------------


def test_the_controls_would_misread_under_the_rule_alone_and_the_split_protects_them() -> None:
    """`counted_but_never_read` alone misreads a control; `measure`'s split is what saves it.

    The property no longer looks at `green` or `reported_never_read`, so a
    control — which an *unmutated* verifier still counts, being a fence the
    grammar genuinely reaches — reads `counted_but_never_read is True` too.
    That is not a defect in the property: it is why `gate_reader_agreement
    .measure` only ever calls it for `not arrangement.carries_a_readable_gate`
    and routes controls through `stopped_asserting` instead. Both halves are
    pinned here so a future edit that drops the split is caught directly
    rather than only via the board-level regression test below.
    """
    control = next(a for a in ARRANGEMENTS if a.name == "second_fence_after_the_first")
    assert control.carries_a_readable_gate
    result = gate_reader_agreement.probe(control, gate_reader_agreement.DEFAULT_VERIFIER)
    assert result.counted_as_asserted == 1
    assert result.counted_but_never_read, (
        "the rule alone reads a control as a divergence — this is exactly why "
        "`measure` must never call it without the carries_a_readable_gate split"
    )

    measured = gate_reader_agreement.measure()
    assert control.name not in measured["divergent"]
    assert measured["readable_gates_the_verifier_stopped_asserting"] == 0, measured[
        "stopped_asserting"
    ]


def test_the_board_half_never_calls_the_redesigned_property(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing the property to always divert changes only the fixture half.

    `measure`'s `divergent` list is `["board:" + id for id in board[...]] +
    [fixture names]`. If the board half read through `counted_but_never_read`
    at all, forcing it to always return True would add every terminal task on
    the real board to `divergent`; it must instead add exactly the unreadable
    arrangements the split routes through it — no more, no fewer, which is
    why the boundary below is an equality rather than a containment.

    (T158 review round 2, finding F4: this test used to also assert
    ``forced_board_entries == board_entries`` — both sides built by filtering
    ``divergent`` for a ``"board:"`` prefix. On the real board `divergent` is
    ``[]`` before *and* after forcing the property, because the board's
    ``"board:"`` entries come straight from `tools/verify_gates.py`'s own
    subprocess report and are never threaded through any `Probe` — so that
    assertion was `[] == []`, true by construction regardless of what the
    property does, and could not have caught the defect it was named for.
    The equality below is the one assertion here that can actually fail, and
    `test_the_board_half_source_never_references_the_redesigned_property`
    below is the structural pin for what the runtime comparison cannot
    exercise: a future edit that *does* couple the two.)
    """
    baseline = gate_reader_agreement.measure()
    unreadable = {a.name for a in ARRANGEMENTS if not a.carries_a_readable_gate}
    assert set(baseline["divergent"]) == set(), "the healthy board and fixtures agree today"

    monkeypatch.setattr(Probe, "counted_but_never_read", property(lambda self: True))
    forced = gate_reader_agreement.measure()

    assert set(forced["divergent"]) - set(baseline["divergent"]) == unreadable, (
        "forcing the property to always divert must add exactly the arrangements the "
        "carries_a_readable_gate split routes through it, no more and no fewer"
    )


def test_the_board_half_source_never_references_the_redesigned_property() -> None:
    """A structural pin for what no runtime comparison of `divergent` can exercise.

    `measure`'s board line — ``divergent = [f"board:{task_id}" for task_id in
    board["counted_as_asserted_but_never_read"]]`` — reads only the real
    verifier's own JSON report, so any runtime test that forces
    `Probe.counted_but_never_read` and re-reads `divergent`'s `"board:"`
    entries compares two values built identically either way: true by
    construction, whatever the property does (see the finding recorded on
    the test above). The one thing that catches a future edit coupling the
    two is reading the assignment itself.

    (T158 review round 3, finding G1): a previous version of this test
    selected a line out of `inspect.getsource` with `next()` over two
    substring checks, which reads *text* — docstring and comments included —
    not code. One ordinary comment line placed above the assignment is
    enough to make `next()` return the comment instead, and the whole
    89-test suite stayed green over a `divergent` expression that actually
    read `Probe.counted_but_never_read` for the board half, the exact
    coupling the task file's second "must not lose" forbids. That is the
    identical idiom `CLAUDE.md` records three review rounds defeating in
    `tools/verified_gate.sh`, and no further substring closes it — asserting
    the *absence* of a call has no runtime witness, so this reads the AST
    instead: a docstring is an `ast.Constant` and a comment is not in the
    AST at all, so neither can stand in for the assignment a future edit
    would actually change.

    Matches `ast.Assign` *and* `ast.AugAssign` (``divergent += [...]``) with
    "divergent" among the targets, not `ast.Assign` alone: a rewrite of the
    initial list comprehension into an augmented assignment changes the node
    type without changing what is being checked, and a test pinned to one
    node type only would be exactly the "one more substring" shape this
    section exists to end. `divergent.append(...)`/`.extend(...)` — the
    fixture half's own legitimate calls, further down in the same function —
    are `ast.Call` nodes, never `ast.Assign` or `ast.AugAssign`, so they are
    not swept in and do not need excluding by name.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(gate_reader_agreement.measure)))
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AugAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "divergent"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    assert assignments, "measure must still assign or augment `divergent` somewhere"
    assert not any(
        isinstance(inner, ast.Attribute) and inner.attr == "counted_but_never_read"
        for node in assignments
        for inner in ast.walk(node)
    ), (
        "no assignment or augmented assignment to `divergent` may reference the "
        "fixture-level Probe property, structurally — not merely as a matter of what "
        "today's line of text happens to say"
    )


# ---------------------------------------------------------------------------
# The floor: a literal, sized to `STATES`, with both directions pinned.
# ---------------------------------------------------------------------------


def test_the_floor_is_a_literal_sized_to_the_states_it_is_read_against() -> None:
    source = Path(gate_detector_states.__file__).read_text(encoding="utf-8")
    assigned = [
        node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "MINIMUM_DETECTOR_STATES_PROBED"
    ]
    assert len(assigned) == 1, "the floor is assigned once, at module level"
    assert isinstance(assigned[0], ast.Constant) and isinstance(assigned[0].value, int), (
        "the floor must be an integer literal; derived from len(STATES) it shrinks with the "
        "very deletion it exists to catch, and the guard can never fire"
    )
    assert len(STATES) == MINIMUM_DETECTOR_STATES_PROBED, (
        "the literal must equal the population floor_breaches reads it against"
    )
    assert MINIMUM_DETECTOR_STATES_PROBED >= 6


def test_the_floor_fires_on_the_first_deleted_state() -> None:
    """One state deleted from `detector_states_probed` must breach the name floor.

    `state_results` is carried alongside so this isolates the name floor from
    the distinct-trace floor below: `silent_pass_catch_removed_alone` shares
    its observed trace with the other two classifier-intact states, so
    dropping it changes the name count without changing the trace count —
    exactly the case that must trip `MINIMUM_DETECTOR_STATES_PROBED` and
    nothing else.
    """
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    state_results = committed["state_results"]
    full = {
        "detector_states_probed": [s.name for s in STATES],
        "state_results": state_results,
    }
    assert floor_breaches(full) == [], "the full committed set is what a healthy run probes"

    dropped = STATES[-1].name
    one_short = {
        "detector_states_probed": [s.name for s in STATES][:-1],
        "state_results": {k: v for k, v in state_results.items() if k != dropped},
    }
    assert any("detector state(s) probed" in breach for breach in floor_breaches(one_short)), (
        "a state deleted from the module must breach the floor, not merely leave a diff "
        "line for somebody to notice"
    )


def test_the_committed_evidence_names_every_state_the_module_probes() -> None:
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert set(committed["detector_states_probed"]) == {s.name for s in STATES}
    assert committed["detector_states_probed_at_least"] == MINIMUM_DETECTOR_STATES_PROBED


# ---------------------------------------------------------------------------
# The second floor (F2): distinct *observed behaviour*, not state names.
# A state surviving in `detector_states_probed` is not the same as its
# mutation having done anything — see `MINIMUM_DISTINCT_STATE_TRACES`'s own
# comment in gate_detector_states.py.
# ---------------------------------------------------------------------------


def test_the_distinct_trace_floor_is_a_literal_sized_to_the_states_it_is_read_against() -> None:
    source = Path(gate_detector_states.__file__).read_text(encoding="utf-8")
    assigned = [
        node.value
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "MINIMUM_DISTINCT_STATE_TRACES"
    ]
    assert len(assigned) == 1, "the floor is assigned once, at module level"
    assert isinstance(assigned[0], ast.Constant) and isinstance(assigned[0].value, int), (
        "the floor must be an integer literal; derived from the traces it counts it would "
        "shrink with the very collapse it exists to catch, and the guard could never fire"
    )
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    distinct = {
        tuple(
            result[field]
            for field in (
                "counted_as_asserted",
                "exit_status",
                "reported_never_read",
                "green",
                "counted_but_never_read",
            )
        )
        for result in committed["state_results"].values()
    }
    assert len(distinct) == MINIMUM_DISTINCT_STATE_TRACES, (
        "the literal must equal the population of distinct traces a healthy run produces: "
        "four from the classifier-reverted states plus one shared by the three "
        "classifier-intact states, whose catch mutation is unreachable by construction"
    )


def test_the_distinct_trace_floor_fires_when_two_states_stop_being_told_apart() -> None:
    """The boundary case: the committed set clears it, one collapsed pair does not.

    Simulates exactly what F2 measured happening for real — two states that
    used to read differently now read identically — without needing a live
    mutation for this half of the pin; the live mutation is
    `test_an_inert_catch_mutation_is_caught_by_the_distinct_trace_floor_though_not_by_state_count`
    below.
    """
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    state_results = committed["state_results"]
    full = {
        "detector_states_probed": list(state_results),
        "state_results": state_results,
    }
    assert floor_breaches(full) == [], "the committed set is what a healthy run probes"

    donor = "classifier_reverted_detector_intact"
    victim = "classifier_reverted_first_signal_removed"
    collapsed = dict(state_results)
    collapsed[victim] = dict(state_results[donor])  # two states, now one observed trace
    one_trace_short = {
        "detector_states_probed": list(collapsed),
        "state_results": collapsed,
    }
    breaches = floor_breaches(one_trace_short)
    assert any("distinct state trace(s)" in breach for breach in breaches), (
        "two states reading identically must breach the trace floor even though every "
        "name is still present and probed"
    )


def test_an_inert_catch_mutation_is_caught_by_the_distinct_trace_floor_though_not_by_state_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F2, re-run exactly: `_mutate_catch` made inert, driven through real probes.

    This is the live mutation the finding measured, not an assertion about
    it: `_mutate_catch` is replaced with a version that returns its input
    unchanged regardless of `report_removed`/`failure_removed`, so the four
    `classifier_reverted_*` states — which should read four different traces
    — all read the same one. `detector_states_probed` still names all seven
    states (the name floor stays clear, which is F2's own point: a label
    surviving proves nothing), and the distinct-trace floor must be the one
    that catches it.
    """

    def inert_mutate_catch(text: str, *, report_removed: bool, failure_removed: bool) -> str:
        return text

    monkeypatch.setattr(gate_detector_states, "_mutate_catch", inert_mutate_catch)

    measured = measure()

    assert len(measured["detector_states_probed"]) == MINIMUM_DETECTOR_STATES_PROBED, (
        "the name floor reads clean here — every state is still probed and named; "
        "that is exactly the hole F2 found"
    )
    assert measured["reverted_defects_the_metric_reads_as_clean"] == 0, (
        "the metric itself also reads clean over the inert mutation — the defect is "
        "invisible to both the metric and the name floor, which is why a floor over "
        "the observed traces is the only thing left that can see it"
    )
    breaches = floor_breaches(measured)
    assert any("distinct state trace(s)" in breach for breach in breaches), (
        "an inert catch mutation collapses the four classifier-reverted traces onto one "
        "(2 distinct overall, floor 5) and must breach here even though nothing else does"
    )


def test_the_reverted_axis_rule_catches_a_pooled_count_compensated_by_the_intact_group() -> None:
    """T158 review round 3's own counterexample (F2), committed as a fixture.

    `MINIMUM_DISTINCT_STATE_TRACES` pools every probed state's trace into one
    set, so a mutation that costs one distinction on the classifier-reverted
    axis and gains one, unrelated, on the classifier-*intact* axis holds the
    pooled count at exactly the floor: `floor_breaches` over the pooled check
    alone reads clean. `_reverted_states_collapse` only ever looks within the
    `classifier_reverted` axis — the only axis `defect_can_occur` is ever
    True for — so the intact-side split cannot compensate for the
    reverted-side collapse there, and it must breach even though the pooled
    floor does not.
    """
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    state_results = dict(committed["state_results"])

    donor = "classifier_reverted_detector_intact"
    victim = "classifier_reverted_first_signal_removed"
    state_results[victim] = dict(state_results[donor])  # reverted axis: 4 -> 3 distinct traces

    split = "second_signal_removed_alone"
    state_results[split] = {
        **state_results[split],
        "counted_but_never_read": True,
    }  # intact axis: 1 -> 2 distinct traces, compensating

    compensated = {
        "detector_states_probed": list(state_results),
        "state_results": state_results,
    }

    pooled_distinct = len(gate_detector_states._distinct_state_traces(state_results))
    assert pooled_distinct == MINIMUM_DISTINCT_STATE_TRACES, (
        "precondition: the compensation must actually hold the pooled floor at exactly "
        f"{MINIMUM_DISTINCT_STATE_TRACES} for this to be the counterexample it claims to be"
    )

    breaches = floor_breaches(compensated)
    assert not any("distinct state trace(s)" in breach for breach in breaches), (
        "precondition: the pooled floor alone must read clean here — that is what makes "
        "the compensation a counterexample rather than an ordinary collapse"
    )
    assert any("classifier-reverted states" in breach for breach in breaches), (
        "a collapse on the reverted axis, compensated by an unrelated split on the intact "
        "axis, must still breach — the closed rule is never pooled across axes and nothing "
        "outside the reverted axis can move its count"
    )


def test_the_record_commits_the_floor_and_names_the_states() -> None:
    committed = record(
        {
            "reverted_defects_the_metric_reads_as_clean": 0,
            "reverted_defects_clean_states": [],
            "detector_states_probed": ["a", "b"],
            "state_results": {},
            "gate_status": "measured",
        }
    )
    assert committed["detector_states_probed_at_least"] == MINIMUM_DETECTOR_STATES_PROBED
    assert committed["detector_states_probed"] == ["a", "b"]


def test_a_floor_breach_writes_no_evidence_file(tmp_path: Path) -> None:
    evidence = tmp_path / "T158.json"
    measured = write_evidence(evidence=evidence, states=STATES[:2])
    assert floor_breaches(measured)
    assert not evidence.exists()


def test_a_healthy_run_writes_the_record(tmp_path: Path) -> None:
    evidence = tmp_path / "T158.json"
    measured = write_evidence(evidence=evidence)
    assert not floor_breaches(measured)
    assert evidence.is_file()
    assert json.loads(evidence.read_text(encoding="utf-8")) == record(measured)


# ---------------------------------------------------------------------------
# `_main` wiring — the exit codes `make evidence` and `make verify-gates` read.
# ---------------------------------------------------------------------------


def test_main_check_exits_zero_on_a_healthy_run() -> None:
    assert gate_detector_states._main(["prog", "--check"]) == 0


def test_main_reports_a_nonzero_metric_as_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    dirty = {
        "reverted_defects_the_metric_reads_as_clean": 1,
        "reverted_defects_clean_states": ["something"],
        "detector_states_probed": [s.name for s in STATES],
        "state_results": {},
        "gate_status": "measured",
    }
    monkeypatch.setattr(gate_detector_states, "measure", lambda *a, **k: dirty)
    assert gate_detector_states._main(["prog", "--check"]) == 1


def test_main_reports_unmeasured_as_exit_three(monkeypatch: pytest.MonkeyPatch) -> None:
    unmeasured = {
        "reverted_defects_the_metric_reads_as_clean": -1,
        "reverted_defects_clean_states": [],
        "detector_states_probed": [],
        "state_results": {},
        "gate_status": "unmeasured",
    }
    monkeypatch.setattr(gate_detector_states, "measure", lambda *a, **k: unmeasured)
    assert gate_detector_states._main(["prog", "--check"]) == 3


def test_main_default_path_rewrites_the_record(tmp_path: Path) -> None:
    written = tmp_path / "T158.json"
    assert gate_detector_states._main(["prog", "--write-evidence", str(written)]) == 0
    assert written.is_file()
