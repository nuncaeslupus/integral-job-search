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
import json
from pathlib import Path

import pytest

from integral import gate_detector_states, gate_reader_agreement
from integral.gate_detector_states import (
    MINIMUM_DETECTOR_STATES_PROBED,
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
    """
    baseline = gate_reader_agreement.measure()
    board_entries = sorted(d for d in baseline["divergent"] if d.startswith("board:"))
    unreadable = {a.name for a in ARRANGEMENTS if not a.carries_a_readable_gate}
    assert set(baseline["divergent"]) == set(), "the healthy board and fixtures agree today"

    monkeypatch.setattr(Probe, "counted_but_never_read", property(lambda self: True))
    forced = gate_reader_agreement.measure()

    forced_board_entries = sorted(d for d in forced["divergent"] if d.startswith("board:"))
    assert forced_board_entries == board_entries, (
        "forcing the fixture-level property changed the board-level findings — "
        "the board half must read only tools/verify_gates.py's own report"
    )
    assert set(forced["divergent"]) - set(baseline["divergent"]) == unreadable, (
        "forcing the property to always divert must add exactly the arrangements the "
        "carries_a_readable_gate split routes through it, no more and no fewer"
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
    full = {"detector_states_probed": [s.name for s in STATES]}
    assert floor_breaches(full) == [], "the full committed set is what a healthy run probes"

    one_short = {"detector_states_probed": [s.name for s in STATES][:-1]}
    assert any("detector state(s) probed" in breach for breach in floor_breaches(one_short)), (
        "a state deleted from the module must breach the floor, not merely leave a diff "
        "line for somebody to notice"
    )


def test_the_committed_evidence_names_every_state_the_module_probes() -> None:
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert set(committed["detector_states_probed"]) == {s.name for s in STATES}
    assert committed["detector_states_probed_at_least"] == MINIMUM_DETECTOR_STATES_PROBED


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
