"""The step graph at runtime: what may run, what is owed, how good it is (T34).

T30 made §3.1's declarations machine-checkable. This reads them against a live
profile and answers the three questions §3.1 says the graph exists to answer:

* **which steps may run now?** — `runnable`, over steps whose every
  non-optional input is present;
* **what is still owed?** — `owed`, the missing outputs and the step that
  produces each;
* **how good is what we have?** — `sufficiency`: L0 a handle, L1 constraints
  resolved, L2 traits scored *and* weights fitted.

**The rule that matters is that a required step is never blocked by an offered
one.** §2.5 promises any offered step may be declined; if the runtime refuses to
run Constraints because Intake never produced `claimed_facts`, that promise is
false in code however true it is in prose. T30 proves the property over the
declarations; this proves it over a real tree, by declining everything optional
and walking 0 → 2 → 7 → 8 → 9 to a ranking.

**Presence is detected, never asserted.** Each artefact has a detector that
looks at the candidate's tree, so `unrunnable_step_dispatches` measures what is
actually there. Two detectors do more than check a file exists, and both times
for the same reason — an empty file of the right name is not the artefact:

* `weights` needs fitted part-worths. T6 writes the file shaped-but-empty at
  every rebuild so "no weights yet" is a fact at a known revision rather than a
  missing file; treating that as weights would make every ranking read L2.
* `constraints` needs fields, each in one of the three states §3.1 names. T24
  pins the field set and T41 owns the engine that fills it; what is enforced
  here is only that an unresolved file does not count as resolved.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.identity import ProfileStore
from integral.process_spec import Step, StepList, load_steps
from integral.profile import EvidenceLog, EvidenceRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T34.json"

Sufficiency = Literal["L0", "L1", "L2"]

# The three states §3.1 says every constraint field must be in for constraints
# to count as resolved. T24 pins the field set; these are the states.
RESOLVED_STATES = frozenset({"stated", "declined", "unknown"})


class RuntimeError_(Exception):
    """The runtime cannot read the graph or the profile."""


Detector = Callable[["ProfileView"], bool]


class ProfileView:
    """One candidate's tree, read once, so a decision is made over one snapshot.

    Every question below is asked several times per turn; asking the filesystem
    each time would let a step be offered against a tree that had changed since
    the check that offered it.
    """

    def __init__(self, store: ProfileStore) -> None:
        self.store = store
        self._rows: list[EvidenceRow] | None = None

    @property
    def rows(self) -> list[EvidenceRow]:
        if self._rows is None:
            log = EvidenceLog(self.store)
            self._rows = log.effective_rows() if log.exists() else []
        return self._rows

    def has_file(self, *parts: str) -> bool:
        path = self.store.path(*parts)
        return path.is_file() and path.stat().st_size > 0

    def has_any_under(self, *parts: str) -> bool:
        directory = self.store.path(*parts)
        return directory.is_dir() and any(path.is_file() for path in directory.rglob("*"))

    def json_at(self, *parts: str) -> Any:
        if not self.has_file(*parts):
            return None
        try:
            return json.loads(self.store.path(*parts).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A malformed derived file is an absent artefact, not a present one.
            # Reading it as present would offer a step that then cannot run.
            return None

    def rows_of_kind(self, kind: str) -> list[EvidenceRow]:
        return [row for row in self.rows if row.kind == kind]


def _constraints_resolved(view: ProfileView) -> bool:
    payload = view.json_at("profile", "constraints.json")
    if not isinstance(payload, dict):
        return False
    fields = payload.get("fields")
    if not isinstance(fields, dict) or not fields:
        return False
    return all(
        isinstance(value, dict) and value.get("state") in RESOLVED_STATES
        for value in fields.values()
    )


def _weights_fitted(view: ProfileView) -> bool:
    payload = view.json_at("profile", "weights.json")
    return isinstance(payload, dict) and bool(payload.get("part_worths"))


def _trait_evidence(view: ProfileView) -> bool:
    """Anything the candidate said that bears on a dimension.

    Not "the traits step ran": History produces trait evidence too, and so does
    continuous capture (T28). The artefact is the evidence, not its source.
    """
    return any(row.dimensions for row in view.rows if row.kind in {"episode", "statement"})


# Artefact id → how to tell whether this candidate has it. The ids are the ones
# T30 encoded from §3.1, so a step's declarations and this table cannot drift
# apart silently — `unknown_artefacts` fails the gate when they do.
DETECTORS: dict[str, Detector] = {
    "handle": lambda view: view.has_file("identity.json"),
    "session_state": lambda view: view.has_file("session", "state.json"),
    "cv_master": lambda view: view.has_file("cv", "master.json"),
    "claimed_facts": lambda view: (
        view.has_file("cv", "master.json") or any(row.step == "intake" for row in view.rows)
    ),
    "constraints": _constraints_resolved,
    "currency": _constraints_resolved,
    "locale": lambda view: view.has_file("identity.json"),
    "stories": lambda view: view.has_file("profile", "stories.jsonl"),
    "trait_evidence": _trait_evidence,
    "traits": lambda view: bool((view.json_at("profile", "traits.json") or {}).get("dimensions")),
    "reaction_evidence": lambda view: bool(view.rows_of_kind("reaction")),
    "outcome_evidence": lambda view: bool(view.rows_of_kind("outcome")),
    "weights": _weights_fitted,
    "offers": lambda view: view.has_any_under("offers"),
    "extractions": lambda view: view.has_any_under("extractions"),
    "rankings": lambda view: view.has_any_under("rankings"),
    "generated_documents": lambda view: view.has_any_under("cv", "generated"),
    "interview_preparation": lambda view: view.has_any_under("interviews"),
    "interview_lessons": lambda view: any(row.step == "interview_log" for row in view.rows),
}


def settled_extractions(view: ProfileView) -> tuple[int, int]:
    """`(extractions that settled a dimension, extractions read)` for this candidate — D-19.

    The `extractions` detector answers "is the artefact present", and a file
    whose `scores` are empty is present. That is the seam D-19 found: for a
    Barcelona construction worker the extractor settled **0 of 25** dimensions
    on all seven adverts, wrote a file per offer, and step 8 reported coverage
    met over a vocabulary that had matched nothing.

    Presence and reach are kept apart rather than folded together, for D-21's
    reason: an extraction that settled nothing is not a missing artefact — the
    step ran and produced exactly what it had to say — so reporting it as absent
    would read as "still working" instead of "this vocabulary does not cover
    this market".

    A payload that is not an object, or carries no `scores` key, is read but not
    counted as settled. That is the honest reading of a file this step did not
    write in its own shape.
    """
    directory = view.store.path("extractions")
    if not directory.is_dir():
        return (0, 0)
    read = 0
    settled = 0
    for path in sorted(directory.glob("*.json")):
        payload = view.json_at("extractions", path.name)
        if not isinstance(payload, dict):
            continue
        read += 1
        if payload.get("scores"):
            settled += 1
    return (settled, read)


def present_artefacts(view: ProfileView, steps: StepList) -> set[str]:
    """Which artefacts this candidate has, external ones included.

    External artefacts are always present by definition — they exist before the
    process starts — so they are added rather than detected.
    """
    present = {artefact for artefact, detector in DETECTORS.items() if detector(view)}
    return present | set(steps.external_artefacts)


def unknown_artefacts(steps: StepList) -> list[str]:
    """Artefacts the graph names that no detector can see.

    Without this the runtime silently treats a newly declared input as absent
    forever, and the step that reads it is never offered — a step disappearing
    from the process because somebody added a line to the JSON.
    """
    named = {read.artefact for step in steps.steps for read in step.reads}
    named |= {artefact for step in steps.steps for artefact in step.produces}
    return sorted(named - set(DETECTORS) - set(steps.external_artefacts))


# ---------------------------------------------------------------------------
# the three questions


@dataclass(frozen=True)
class Blocked:
    """A step that cannot run, and the inputs that are why."""

    step: str
    missing: tuple[str, ...]

    def reason(self) -> str:
        return f"{self.step} needs {', '.join(self.missing)}"


@dataclass(frozen=True)
class Owed:
    """An output nothing has produced yet, and the step that would."""

    artefact: str
    step: str


def missing_inputs(step: Step, present: Iterable[str]) -> tuple[str, ...]:
    """The non-optional inputs this step does not have. Optional is optional."""
    have = set(present)
    return tuple(
        read.artefact for read in step.reads if not read.optional and read.artefact not in have
    )


def is_runnable(step: Step, present: Iterable[str]) -> bool:
    return not missing_inputs(step, present)


def is_finished(step: Step, present: Iterable[str]) -> bool:
    """A step is done when everything it produces exists."""
    have = set(present)
    return all(artefact in have for artefact in step.produces)


def runnable(view: ProfileView, steps: StepList | None = None) -> list[Step]:
    """Every step whose declared inputs are satisfied, in journey order."""
    steps = steps or load_steps()
    present = present_artefacts(view, steps)
    return [step for step in sorted(steps.steps, key=lambda s: s.n) if is_runnable(step, present)]


def offered(view: ProfileView, steps: StepList | None = None) -> list[Step]:
    """The steps worth offering: runnable, and not already finished.

    A finished step is not offered again here. Re-entering one is what the
    freshness triggers of §5.2 are for (T36), and they say why — which is a
    different thing from a step still being outstanding.
    """
    steps = steps or load_steps()
    present = present_artefacts(view, steps)
    return [
        step
        for step in sorted(steps.steps, key=lambda s: s.n)
        if is_runnable(step, present) and not is_finished(step, present)
    ]


def blocked(view: ProfileView, steps: StepList | None = None) -> list[Blocked]:
    """Steps that cannot run yet, each with the inputs it is waiting on."""
    steps = steps or load_steps()
    present = present_artefacts(view, steps)
    return [
        Blocked(step=step.id, missing=missing)
        for step in sorted(steps.steps, key=lambda s: s.n)
        if (missing := missing_inputs(step, present))
    ]


def owed(view: ProfileView, steps: StepList | None = None) -> list[Owed]:
    """What is still missing, and which step would produce it.

    This is what makes "where were we?" answerable, and it is why the answer
    can name a step rather than a feeling.
    """
    steps = steps or load_steps()
    present = present_artefacts(view, steps)
    return [
        Owed(artefact=artefact, step=step.id)
        for step in sorted(steps.steps, key=lambda s: s.n)
        for artefact in step.produces
        if artefact not in present
    ]


def sufficiency(view: ProfileView, steps: StepList | None = None) -> Sufficiency:
    """§3.1's three levels, computed from what exists — never asserted.

    L2 needs both traits scored *and* weights fitted. A ranking that recorded
    L2 on the strength of one of them would be labelled as explaining itself in
    salary-equivalent terms while having no salary equivalence to explain with.
    """
    present = present_artefacts(view, steps or load_steps())
    if "handle" not in present:
        return "L0"
    if "constraints" not in present:
        return "L0"
    if "traits" in present and "weights" in present:
        return "L2"
    return "L1"


@dataclass(frozen=True)
class Situation:
    """Everything the runtime can say about where a candidate is, in one answer."""

    sufficiency: Sufficiency
    offered: tuple[str, ...]
    runnable: tuple[str, ...]
    blocked: tuple[Blocked, ...]
    owed: tuple[Owed, ...]


def look(view: ProfileView, steps: StepList | None = None) -> Situation:
    steps = steps or load_steps()
    return Situation(
        sufficiency=sufficiency(view, steps),
        offered=tuple(step.id for step in offered(view, steps)),
        runnable=tuple(step.id for step in runnable(view, steps)),
        blocked=tuple(blocked(view, steps)),
        owed=tuple(owed(view, steps)),
    )


# ---------------------------------------------------------------------------
# the gate


def _produce(store: ProfileStore, artefact: str) -> None:
    """Write whatever makes `artefact` present, as the owning step would.

    Only what the probe needs. Each writer is the *minimum* that the detector
    accepts, which is deliberate: a probe that wrote generous fixtures would
    pass detectors that a real step's output would not.
    """
    if artefact in {"handle", "locale"}:
        # Both come from `identity.json`, which creating the profile wrote —
        # identification is the one step whose output exists before it runs.
        return
    if artefact == "session_state":
        store.write_json({"handle": store.handle, "sufficiency": "L0"}, "session", "state.json")
    elif artefact in {"constraints", "currency"}:
        store.write_json(
            {"fields": {"remote_work": {"state": "stated", "evidence": ["ev-000001"]}}},
            "profile",
            "constraints.json",
        )
    elif artefact == "offers":
        store.write_json({"id": "o1"}, "offers", "o1.json")
    elif artefact == "extractions":
        store.write_json({"offer_id": "o1", "dimensions": {}}, "extractions", "o1.json")
    elif artefact == "rankings":
        store.write_json({"level": "L1", "offers": ["o1"]}, "rankings", "2026-08-18T00-00-00.json")
    elif artefact == "traits":
        store.write_json(
            {"dimensions": {"team_autonomy": {"evidence_count": 2}}}, "profile", "traits.json"
        )
    elif artefact == "weights":
        store.write_json({"part_worths": {"team_autonomy": 120.0}}, "profile", "weights.json")
    else:  # pragma: no cover - the probe only produces what it names
        raise RuntimeError_(f"the probe does not know how to produce {artefact!r}")


REQUIRED_TRACE = ("identify", "constraints", "sourcing", "understanding", "ranking")


def probe_runtime(root: Path, steps: StepList | None = None) -> tuple[int, list[str]]:
    """Walk the required-only trace, declining everything offered, and watch.

    Two things are checked at every stage, and they are different failures:

    * **nothing unrunnable is ever offered** — the gate's own metric. A step
      whose non-optional input is missing must not appear in the offered set,
      because a dispatcher takes that set at its word.
    * **the required trace keeps moving** — 0 → 2 → 7 → 8 → 9 completes with
      every offered step declined. If it stalls, §2.5's promise is false in
      code, which is exactly the shape of the PR #16 defect one level up.
    """
    from integral.identity import create_profile

    steps = steps or load_steps()
    failures: list[str] = []
    probes = 0

    stray = unknown_artefacts(steps)
    probes += 1
    if stray:
        failures.append(f"the graph names artefacts no detector can see: {', '.join(stray)}")

    identity = create_profile(root, "Probe One", handle="probe-one")
    store = ProfileStore(root, identity.handle)
    by_id = {step.id: step for step in steps.steps}

    for expected in REQUIRED_TRACE:
        view = ProfileView(store)
        present = present_artefacts(view, steps)

        probes += 1
        wrongly_offered = [
            step.id for step in offered(view, steps) if missing_inputs(step, present)
        ]
        if wrongly_offered:
            failures.append(
                f"offered {', '.join(wrongly_offered)} without their inputs, at {expected}"
            )

        probes += 1
        if missing_inputs(by_id[expected], present):
            missing = ", ".join(missing_inputs(by_id[expected], present))
            failures.append(
                f"required step {expected!r} is blocked on {missing} with every offered "
                "step declined — §2.5 promises it is not"
            )
            break

        # Run it, and *decline everything else*: nothing optional is produced.
        for artefact in by_id[expected].produces:
            _produce(store, artefact)

    # The ranking exists, and without weights it is provisional.
    probes += 1
    level = sufficiency(ProfileView(store), steps)
    if level != "L1":
        failures.append(f"a ranking with no weights fitted reads {level}, not L1")

    for artefact in ("traits", "weights"):
        _produce(store, artefact)
    probes += 1
    if sufficiency(ProfileView(store), steps) != "L2":
        failures.append("traits scored and weights fitted did not reach L2")

    return probes, failures


# Raised to what `probe_runtime` carries — 13, zero slack — because 8
# tolerated five deleted probes silently, with no margin argued (T159).
MINIMUM_PROBES = 13


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `unrunnable_step_dispatches` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-t34-") as tmp:
        probes, failures = probe_runtime(Path(tmp) / "profiles")
    measured: dict[str, Any] = {
        "unrunnable_step_dispatches": len(failures),
        "probes_run": probes,
        "required_trace": list(REQUIRED_TRACE),
        "failures": failures,
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.step_runtime [path]` → T34's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["probes_run"] < MINIMUM_PROBES:
        print(
            f"only {measured['probes_run']} probes ran (floor {MINIMUM_PROBES}) — "
            "the trace stopped early, so nothing downstream was measured",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
