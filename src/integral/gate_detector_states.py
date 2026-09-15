"""T158 — mutation-testing T122's own detector, not just the board it reads.

`gate_reader_agreement.Probe.counted_but_never_read` used to decide T122's
divergence from two signals: what a `tools/verify_gates.py` run **says**
(`reported_never_read`, from its own `counted_as_asserted_but_never_read`
report list) and what it **did** (`counted_as_asserted > 0 and green`). The
second reader on #425 measured a hole: remove the first signal *and* revert
`task_gate.gate_declaration`'s classification of a present-but-unreachable
fence back to "readable" (the pre-T122 substring rule), and every arrangement
comes back False. The reverted verifier is genuinely red about the divergence
— its own silent-pass catch still fires and the run exits 1 — so `green` is
False and the second signal, which requires it, never fires either.
`gates_counted_as_asserted_but_never_read` reads **0** over a defect that is
fully back, and `python -m integral.gate_reader_agreement` exits 0 with it.

**The fix is a redesign, not a patch.** `Probe.counted_but_never_read` is now
a single rule: *counted at all, or green* — in practice, for these fixtures,
just `counted_as_asserted > 0`. A run that counted a gate over an evidence
file that cannot exist has diverged whatever else it reports and whatever its
exit status, so the property no longer consults `reported_never_read` or
`green` at all. That closes the hole rather than moving it: `checked` (and so
`counted_as_asserted`) increments the moment `gate_declaration` treats a fence
as readable, *before* either of the old signals' sources (the silent-pass
catch's two effects, downstream) run at all — so a reverted classifier now
trips the property unconditionally, regardless of what else is also broken
downstream of it.

**This module is that claim, driven rather than asserted.** It builds real,
textual mutations of a *copy* of `tools/verify_gates.py` — never the installed
one — and runs each through `gate_reader_agreement.probe`, the same machinery
the T122 fixtures already use, so every state below is an executed subprocess
over a real fixture (`bold_label`, the #334 case) rather than a hand-built
`Probe`. Two independent axes, both real code paths in `tools/verify_gates.py`:

* **the classifier** — whether `main` still special-cases
  `declaration == "unreadable"` (refusing the payload by name before
  `check_payload` ever runs) or has been reverted to fall through to it, which
  is what "a reverted classifier" means operationally: the fence gets treated
  as declaring a readable gate and counted, exactly as the pre-T122 substring
  rule counted it.
* **the silent-pass catch** — `main`'s `if passed and not output.strip():`
  block has two independent effects: it appends to the report's
  `counted_as_asserted_but_never_read` list (signal 1's only source) and it
  appends to `failures`, which is what turns the run red (signal 2's `green`
  requirement). Either, both, or neither can be muted.

Crossing "classifier reverted" with the four ways the catch's two effects can
be present or missing gives the four states the task names; each of the three
non-classifier mutations run alone (classifier intact) is three more. Seven
states, each executed for real; `MINIMUM_DETECTOR_STATES_PROBED` is a literal
sized to that count, never derived from `len(STATES)` — deriving it would let
both sides of the boundary check shrink together, which is exactly
`MINIMUM_ARRANGEMENTS_PROBED`'s docstring in `gate_reader_agreement.py` and
`profile.MINIMUM_FIELDS_CHECKED`'s failure mode.

**What the metric counts.** `reverted_defects_the_metric_reads_as_clean` is
the number of the seven states in which the T122 defect can actually occur —
which, given `bold_label`'s shape, is exactly the four states where the
classifier is reverted; with it intact, `bold_label` is refused before
`check_payload` ever runs, whatever the catch's mutation is doing downstream
of a path this state never reaches — and
`gate_reader_agreement.Probe.counted_but_never_read`, TODAY's shipped
property, evaluated on the resulting probe, nonetheless reads False. Today's
pre-T158 property fails this by construction: the
`classifier_reverted_first_signal_removed` state is the exact scenario #425
measured (reported_never_read unavailable to the property, exit red so
`green` is False), and it is one of the four enumerated states rather than a
hypothetical — the gate is drivable rather than assertable for exactly that
reason.

**Two things this redesign must not lose, held here as explicit checks
rather than as prose** (`tests/test_gate_detector_states.py`):

* the **controls** (`second_fence_after_the_first`, `label_in_a_later_section`)
  must stay red. They also get `counted_as_asserted == 1` from an unmutated
  verifier, so `counted_but_never_read` taken alone, without
  `gate_reader_agreement.measure`'s `carries_a_readable_gate` split, would
  misclassify them as divergences too — the vacuous pass in a new spelling.
  The split lives in `measure`, is untouched by this task, and is exercised
  directly rather than trusted by name.
* the **board half** is untouched by construction: `measure`'s `divergent`
  list reads `board["counted_as_asserted_but_never_read"]` straight from
  `tools/verify_gates.py`'s own report over the real board, never through
  `Probe.counted_but_never_read`. The simpler rule is a statement about
  fixtures whose evidence path is absent by construction; it was never wired
  to the board and this module does not wire it there either.

**A state's *name* surviving is not the same as its mutation being exercised**
(T158 review round 2, finding F2). `MINIMUM_DETECTOR_STATES_PROBED` counts
labels in `detector_states_probed`, and every one of the seven survives even
when `_mutate_catch` is made inert — returning its input unchanged regardless
of `report_removed`/`failure_removed` — because the state list is built
before any mutation runs. What actually vanishes is the *distinction* between
states: the four `classifier_reverted_*` states, which an intact module
drives to four different observed traces, all read identically once the catch
stops doing anything, and the metric still reads 0 over that. So the module
carries a second floor, `MINIMUM_DISTINCT_STATE_TRACES`, over the number of
*distinct* `(counted_as_asserted, exit_status, reported_never_read, green,
counted_but_never_read)` tuples `state_results` actually contains — a bound
on the thing labelled, not the label.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral import gate_reader_agreement
from integral.gate_reader_agreement import ARRANGEMENTS, Arrangement, Probe

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T158.json"
DEFAULT_VERIFIER = gate_reader_agreement.DEFAULT_VERIFIER

#: The fixture this module drives every state through: `bold_label`, the
#: exact #334 case — a fence present under bold text rather than a heading,
#: so the grammar never reaches it. `carries_a_readable_gate` is False, which
#: is what makes it able to show the defect at all: a control would be
#: correctly counted by an unmutated classifier too, so mutating the
#: classifier would teach us nothing about it (see the controls test).
PROBE_ARRANGEMENT: Arrangement = next(a for a in ARRANGEMENTS if a.name == "bold_label")

#: Sized to `STATES` below and committed as a literal for
#: `MINIMUM_ARRANGEMENTS_PROBED`'s reason in `gate_reader_agreement.py`:
#: derived as `len(STATES)` it would shrink with the very deletion it exists
#: to catch, and the guard could never fire. `test_the_floor_is_a_literal...`
#: and `test_the_floor_fires_on_a_deleted_state` hold it to that population
#: from both directions.
#:
#: **This floor counts state *names*, and a name surviving a mutation is not
#: the mutation being exercised.** T158 review round 2 (finding F2) measured
#: the hole directly: make `_mutate_catch` inert — return the source
#: unchanged regardless of `report_removed`/`failure_removed` — and every one
#: of the seven states is still probed and still named, so this floor stays
#: clear and the metric still reads 0. What actually broke is invisible to a
#: count of labels: the four `classifier_reverted_*` states, which the intact
#: module drives to four *different* observed traces, all collapse onto the
#: same one once the catch stops doing anything. `MINIMUM_DISTINCT_STATE_TRACES`
#: below is the floor that counts the thing this one cannot — the number of
#: distinct behaviours actually observed, not the number of names attached to
#: a probe that may or may not have done anything.
#: arsenal-floor-margin: value=7
MINIMUM_DETECTOR_STATES_PROBED = 7

#: A floor over **observed behaviour**, not over the state list. Each state's
#: `state_results` entry is a probe's actual trace —
#: `(counted_as_asserted, exit_status, reported_never_read, green,
#: counted_but_never_read)` — and `_distinct_state_traces` counts how many
#: *distinct* such tuples the run produced. Today's seven states produce five:
#: four from the classifier-reverted states (each of the catch's four
#: arrangements — intact, report removed, failure removed, both removed —
#: genuinely changes what `verify_gates.py` reports or exits) plus one shared
#: by the three classifier-intact states, whose catch mutation is inert *by
#: construction* (the classifier refuses the fixture before the catch is ever
#: reached, so `defect_can_occur` is False for all three and one shared trace
#: is correct, not a hole — see `DetectorState.defect_can_occur`).
#:
#: Sized to that observed population and committed as a literal for the same
#: reason as the floor above: derived as `len({...})` over the very traces it
#: exists to protect, it would shrink with the collapse it exists to catch.
#: `test_the_distinct_trace_floor_is_a_literal_sized_to_the_states_it_is_read_against`
#: and `test_the_distinct_trace_floor_fires_when_two_states_stop_being_told_apart`
#: hold it to that population from both directions, and
#: `test_an_inert_catch_mutation_is_caught_by_the_distinct_trace_floor_though_not_by_state_count`
#: re-runs F2's own mutation and shows this floor catch what the name floor
#: cannot.
#:
#: **This floor pools every state's trace into one set, and a pool is a sum.**
#: T158 review round 3 (F2's counterexample) measured a mutation that loses a
#: distinction inside the classifier-reverted group while an unrelated split
#: inside the classifier-*intact* group gains one, holding this floor at
#: exactly 5 with `floor_breaches == []` over a run that lost real coverage.
#: `_reverted_states_collapse`, in `floor_breaches` below, is the closed rule
#: that answers it: distinctness checked *within* the `classifier_reverted`
#: axis alone, so nothing outside that axis can compensate for a collapse
#: inside it. This floor stays — it still catches a collapse the closed rule
#: cannot see (one shared trace on the classifier-*intact* side splitting in
#: two would move this number without touching the reverted axis at all) —
#: it is just no longer the only thing standing between a compensated
#: mutation and a clean floor_breaches().
#: arsenal-floor-margin: value=5
MINIMUM_DISTINCT_STATE_TRACES = 5


@dataclass(frozen=True)
class DetectorState:
    """One combination of the two independent mutation axes `tools/verify_gates.py` admits.

    `classifier_reverted` toggles whether `main` still refuses a
    `declaration == "unreadable"` payload by name before `check_payload` ever
    runs. `report_removed` and `failure_removed` toggle the silent-pass
    catch's two independent effects: appending to the report's
    `counted_as_asserted_but_never_read` list, and appending to `failures`
    (which is what makes the run red). Naming them separately is what lets
    "first signal removed" (report gone, catch still reddens the run) and
    "second signal removed" (report intact, catch no longer reddens the run)
    be told apart — they are different states of the same block, not the same
    mutation under two names.
    """

    name: str
    classifier_reverted: bool
    report_removed: bool
    failure_removed: bool

    @property
    def defect_can_occur(self) -> bool:
        """Whether T122's defect can actually happen to `PROBE_ARRANGEMENT` here.

        Only when the classifier is reverted: `check_payload` is the only
        place a false-green over an absent evidence file can occur, and with
        the classifier intact `bold_label` is refused by name before that
        call is ever reached — whatever the catch's own two effects are
        doing lives strictly downstream of a code path this state never
        gets to. A state with `classifier_reverted=False` probes a real
        mutation (the catch, degraded one or both ways) but cannot itself
        produce the defect on this fixture, so a clean read from it is
        correct rather than a hole — it still counts toward
        `detector_states_probed_at_least`.
        """
        return self.classifier_reverted


#: The classifier crossed with the four ways the catch's two effects can
#: stand, then each catch mutation run alone. Seven states; see
#: `MINIMUM_DETECTOR_STATES_PROBED`.
STATES: tuple[DetectorState, ...] = (
    DetectorState("classifier_reverted_detector_intact", True, False, False),
    DetectorState("classifier_reverted_first_signal_removed", True, True, False),
    DetectorState("classifier_reverted_second_signal_removed", True, False, True),
    DetectorState("classifier_reverted_silent_pass_catch_removed", True, True, True),
    DetectorState("first_signal_removed_alone", False, True, False),
    DetectorState("second_signal_removed_alone", False, False, True),
    DetectorState("silent_pass_catch_removed_alone", False, True, True),
)

# The exact literal lines mutated in a *copy* of `tools/verify_gates.py`'s
# text. Each is asserted present exactly once before use — `.count(...) != 1`
# on all four, including the two `_mutate_catch` reads (T158 review round 2,
# finding F3: only the first two ever had the check, so an anchor that had
# drifted to appear twice would have `.index()` silently pick the wrong one).
#
# What a stale or duplicated anchor actually does, measured rather than
# guessed (T158 review round 3, finding F3): an anchor gone entirely, or
# duplicated, is caught by `.count(...) != 1` and raises `RuntimeError` for
# *both* anchors — the guards run before either `.index()` call, so neither
# anchor can reach `.index()` while missing or ambiguous. The bare `.index()`
# miss that raises `ValueError` is a narrower case than "gone entirely": both
# anchors present exactly once, but the condition anchor sits *after* the end
# anchor — `.index(_CATCH_END_LINE, start)` only searches forward from the
# condition anchor's position, so an end anchor that already passed is
# invisible to it. Either way `_write_mutant_verifier` propagates the
# exception and the state's probe never completes. That is fail-**closed**:
# the run errors loudly, not a silent pass. It could not have been the silent
# "every state reads `defect_can_occur=False`" an earlier comment here
# claimed, because `defect_can_occur` is `DetectorState.classifier_reverted`
# — a static fact about which state is being probed, fixed before any
# mutation runs — and is not derived from whether a mutation succeeded at all.
_REPO_ROOT_LINE = "_REPO_ROOT = Path(__file__).resolve().parents[1]\n"
_CLASSIFIER_LINE = '        if declaration == "unreadable":\n'
_CATCH_CONDITION_LINE = "        if passed and not output.strip():\n"
_CATCH_END_LINE = "        elif not passed:\n"


def _repoint_repo_root(text: str) -> str:
    """Bind the copy's `_REPO_ROOT` to the real repository, not the temp file's.

    `tools/verify_gates.py` derives it from `Path(__file__).resolve().parents[1]`,
    which is correct only when the module lives at `<repo>/tools/verify_gates.py`.
    A mutated copy is written somewhere else entirely, so left alone this would
    point `GATE_EVIDENCE` at a path under a throwaway temp directory and every
    probe would fail with "no verifier" rather than measuring anything.
    """
    if text.count(_REPO_ROOT_LINE) != 1:
        raise RuntimeError(
            "tools/verify_gates.py's _REPO_ROOT line moved; T158's mutations are stale"
        )
    return text.replace(_REPO_ROOT_LINE, f"_REPO_ROOT = Path({str(_REPO_ROOT)!r})\n", 1)


def _mutate_classifier(text: str, *, reverted: bool) -> str:
    """Neutralise the `unreadable`-fence refusal, or leave it standing."""
    if text.count(_CLASSIFIER_LINE) != 1:
        raise RuntimeError(
            "tools/verify_gates.py's classifier branch moved; T158's mutations are stale"
        )
    if not reverted:
        return text
    return text.replace(
        _CLASSIFIER_LINE, "        if False:  # T158 mutation: classifier_reverted\n", 1
    )


def _mutate_catch(text: str, *, report_removed: bool, failure_removed: bool) -> str:
    """Rewrite the silent-pass catch's block to keep, drop, or split its two effects.

    Replaces the whole span from the `if passed and not output.strip():`
    condition up to (not including) the following `elif not passed:` with
    freshly authored ASCII text, rather than patching the original lines in
    place — the original block's prose comments carry an em dash, and
    matching around it precisely is more fragile than replacing the span
    outright with a version that says the same thing in the mutation's terms.

    Both anchor lines are checked for a unique occurrence before either
    `.index()` call runs, the same guard `_repoint_repo_root` and
    `_mutate_classifier` apply to their own anchors. Without it a
    `_CATCH_CONDITION_LINE` or `_CATCH_END_LINE` that had drifted to appear
    twice would have `.index()` silently pick the first match rather than
    raising — the ambiguity `text.count(...) != 1` exists to catch, not the
    presence `.index()` alone already checks.
    """
    if text.count(_CATCH_CONDITION_LINE) != 1:
        raise RuntimeError(
            "tools/verify_gates.py's silent-pass catch condition moved or is no longer "
            "unique; T158's mutations are stale"
        )
    if text.count(_CATCH_END_LINE) != 1:
        raise RuntimeError(
            "tools/verify_gates.py's silent-pass catch end line moved or is no longer "
            "unique; T158's mutations are stale"
        )
    start = text.index(_CATCH_CONDITION_LINE)
    end = text.index(_CATCH_END_LINE, start)
    if not report_removed and not failure_removed:
        return text  # both effects intact; nothing to rewrite
    if report_removed and not failure_removed:
        block = (
            _CATCH_CONDITION_LINE
            + "            # T158 mutation: first signal removed (report, not failure)\n"
            + "            failures.append(\n"
            + '                f"{task_id} ({payload_name}): T158 first_signal_removed"\n'
            + "            )\n"
        )
    elif not report_removed and failure_removed:
        block = (
            _CATCH_CONDITION_LINE
            + "            # T158 mutation: second signal removed (failure, not report)\n"
            + "            silently_unread.append(task_id)\n"
        )
    else:
        block = "        if False:  # T158 mutation: silent_pass_catch_removed\n            pass\n"
    return text[:start] + block + text[end:]


def _write_mutant_verifier(root: Path, state: DetectorState) -> Path:
    """A real, executable copy of `tools/verify_gates.py`, mutated per `state`."""
    text = DEFAULT_VERIFIER.read_text(encoding="utf-8")
    text = _repoint_repo_root(text)
    text = _mutate_classifier(text, reverted=state.classifier_reverted)
    text = _mutate_catch(
        text, report_removed=state.report_removed, failure_removed=state.failure_removed
    )
    path = root / f"verify_gates_{state.name}.py"
    path.write_text(text, encoding="utf-8")
    return path


def probe_state(state: DetectorState, arrangement: Arrangement = PROBE_ARRANGEMENT) -> Probe:
    """Run `arrangement` end to end through a fresh mutated copy for `state`."""
    with tempfile.TemporaryDirectory(prefix="t158-") as tmp:
        verifier = _write_mutant_verifier(Path(tmp), state)
        return gate_reader_agreement.probe(arrangement, verifier)


def _unmeasured(reason: str) -> dict[str, Any]:
    return {
        "reverted_defects_the_metric_reads_as_clean": -1,
        "reverted_defects_clean_states": [],
        "detector_states_probed": [],
        "state_results": {},
        "gate_status": "unmeasured",
        "unmeasured_reason": reason,
    }


def measure(
    states: tuple[DetectorState, ...] = STATES,
    arrangement: Arrangement = PROBE_ARRANGEMENT,
) -> dict[str, Any]:
    """Every state in `states`, probed for real; which ones read clean over a live defect."""
    if not DEFAULT_VERIFIER.is_file():
        return _unmeasured(f"no verifier at {DEFAULT_VERIFIER}")

    reverted_defects_clean: list[str] = []
    state_results: dict[str, Any] = {}
    for state in states:
        probed = probe_state(state, arrangement)
        reads_as_clean = not probed.counted_but_never_read
        state_results[state.name] = {
            "counted_as_asserted": probed.counted_as_asserted,
            "exit_status": probed.exit_status,
            "reported_never_read": probed.reported_never_read,
            "green": probed.green,
            "counted_but_never_read": probed.counted_but_never_read,
            "defect_can_occur": state.defect_can_occur,
        }
        if state.defect_can_occur and reads_as_clean:
            reverted_defects_clean.append(state.name)

    return {
        "reverted_defects_the_metric_reads_as_clean": len(reverted_defects_clean),
        "reverted_defects_clean_states": sorted(reverted_defects_clean),
        "detector_states_probed": sorted(state.name for state in states),
        "state_results": state_results,
        "gate_status": "measured",
    }


#: The fields of one `state_results` entry that describe what the probe
#: actually *did* — never `defect_can_occur`, which is a static fact about the
#: state (whether the classifier was reverted), not an observation the probe
#: made. Two states sharing a trace on these five fields produced the same
#: evidence, whatever their names say.
_TRACE_FIELDS = (
    "counted_as_asserted",
    "exit_status",
    "reported_never_read",
    "green",
    "counted_but_never_read",
)


def _state_trace(result: dict[str, Any]) -> tuple[Any, ...]:
    """The observed-behaviour signature of one probed state, for distinctness."""
    return tuple(result[field] for field in _TRACE_FIELDS)


def _distinct_state_traces(state_results: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {_state_trace(result) for result in state_results.values()}


#: Name → `DetectorState`, so a probed state's `classifier_reverted` axis can
#: be recovered from `measured["detector_states_probed"]` (a list of plain
#: strings) without threading `DetectorState` objects through `measured`
#: itself. Built once from `STATES`, so a state added there is covered here
#: without anyone remembering to touch this function.
_STATES_BY_NAME = {state.name: state for state in STATES}

#: Stand-in for a probed name this module does not recognise (never
#: `classifier_reverted`, so an unknown name cannot silently join the
#: reverted axis and cannot silently leave it either).
_UNKNOWN_STATE = DetectorState("unknown", False, False, False)


def _reverted_states_collapse(measured: dict[str, Any]) -> str | None:
    """A closed rule for F2's counterexample: distinctness *within* the reverted axis.

    T158 review round 3 (F2): `MINIMUM_DISTINCT_STATE_TRACES` pools every
    probed state's trace into one set, so a mutation that collapses two
    classifier-reverted traces together can still clear the pooled floor if
    something elsewhere in the run happens to split a different pair — the
    pooled count is a sum, and a sum can hold constant while what it is
    supposed to protect does not. Measured: `failure_removed` never applied to
    the catch (so states 3 and 4 stop probing anything downstream of it) plus
    one unrelated compensating split in the classifier-*intact* group holds
    the pooled count at exactly `MINIMUM_DISTINCT_STATE_TRACES` while two of
    the four reverted states read identically.

    This rule never pools: it asks only whether the states on the
    `classifier_reverted` axis — the only ones `defect_can_occur` is True for,
    and so the only ones a collapse can hide a live defect behind — are still
    pairwise distinct *among themselves*. Nothing outside that axis can move
    this number, so nothing outside it can compensate for a collapse inside
    it. Derived from `DetectorState.classifier_reverted` rather than a
    hand-picked subset of names, so a state added to `STATES` later is
    covered without anyone remembering to widen this function.
    """
    state_results = measured.get("state_results", {})
    reverted_names = [
        name
        for name in measured.get("detector_states_probed", [])
        if _STATES_BY_NAME.get(name, _UNKNOWN_STATE).classifier_reverted
    ]
    reverted_traces = {
        _state_trace(state_results[name]) for name in reverted_names if name in state_results
    }
    if len(reverted_traces) == len(reverted_names):
        return None
    return (
        f"the classifier-reverted states read only {len(reverted_traces)} distinct trace(s) "
        f"among {len(reverted_names)} of them — a collapse on this axis (the only axis "
        "defect_can_occur is ever True for) cannot be masked by a compensating split "
        "elsewhere, because this check is never pooled across axes"
    )


def floor_breaches(measured: dict[str, Any]) -> list[str]:
    """Which denominators came in under their floor. Empty is the pass."""
    breaches = []
    probed = len(measured["detector_states_probed"])
    if probed < MINIMUM_DETECTOR_STATES_PROBED:
        breaches.append(
            f"only {probed} detector state(s) probed (floor {MINIMUM_DETECTOR_STATES_PROBED}) "
            "— a clean zero reached by enumerating fewer states is the defect wearing the "
            "fix's clothes"
        )

    distinct = len(_distinct_state_traces(measured.get("state_results", {})))
    if distinct < MINIMUM_DISTINCT_STATE_TRACES:
        breaches.append(
            f"only {distinct} distinct state trace(s) observed (floor "
            f"{MINIMUM_DISTINCT_STATE_TRACES}) — every state can still be named and probed "
            "while a mutation that should distinguish them (F2: an inert `_mutate_catch`) "
            "leaves two or more reading identically, which a count of state names cannot see"
        )

    collapse = _reverted_states_collapse(measured)
    if collapse is not None:
        breaches.append(collapse)
    return breaches


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: every finding, the state set by name, and the floor in its place."""
    committed = {key: value for key, value in measured.items() if key != "detector_states_probed"}
    committed["detector_states_probed_at_least"] = MINIMUM_DETECTOR_STATES_PROBED
    committed["detector_states_probed"] = measured["detector_states_probed"]
    return committed


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    states: tuple[DetectorState, ...] = STATES,
    arrangement: Arrangement = PROBE_ARRANGEMENT,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T158.json`; return what was measured.

    A run that breaches a floor writes nothing: the only record it could
    write is one whose committed floor claims it held.
    """
    measured = measure(states, arrangement)
    if floor_breaches(measured):
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.gate_detector_states [--check]`."""
    parser = argparse.ArgumentParser(
        description="T158's gate: a reverted classifier trips the detector unconditionally"
    )
    parser.add_argument(
        "--check", action="store_true", help="measure and report only; write no evidence file"
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T158.json)",
    )
    args = parser.parse_args([] if argv is None else argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(
        json.dumps({k: v for k, v in measured.items() if k != "state_results"}, ensure_ascii=False)
    )
    for breach in floor_breaches(measured):
        print(f"gate_detector_states: {breach}", file=sys.stderr)
    for name in measured["reverted_defects_clean_states"]:
        print(
            f"✗ {name}: T122's defect is present and the shipped detector reads 0 over it",
            file=sys.stderr,
        )

    if measured["gate_status"] == "unmeasured":
        return 3
    if floor_breaches(measured):
        return 1
    if measured["reverted_defects_the_metric_reads_as_clean"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
