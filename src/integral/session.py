"""Session state and resumption (T35).

Two things, and the second is why the first has to be written the way it is.

**`session/state.json`** is process specification §5.1: where the candidate is,
what they have covered, what is outstanding, what was skipped, and at what
sufficiency level. The rule the spec repeats in every step specification is
that **state is written when something new is known, not at the end** — "the
files are the memory, and a memory written only at the end is not one". So
`SessionStore.record` takes a partial update and writes immediately, and there
is no `flush`, no `close`, and no in-memory buffer that a dying session could
take with it.

**Resumption** is §5.3: five rules, highest first, and two constraints on all
of them — the tool says which step it is resuming *and why*, and it never
resumes into a step silently. `decide_resumption` therefore returns a
`Resumption` carrying the step, the rule that chose it, and a sentence; there
is no code path that yields a step without one, because "being dropped back
into a half-finished interview with no explanation is indistinguishable from
being asked the same questions twice".

The gate is `resumption_position_loss == 0`: across a session that is
interrupted anywhere — including in the middle of a step, having never reached
a boundary — resuming lands on the step and the position that were last
recorded. It is measured by killing the object and re-reading the file, because
an in-process check would pass on state that never reached the disk.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from integral.identity import ProfileStore
from integral.process_spec import DEFAULT_STEPS_PATH, load_steps

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T35.json"

STATE_PARTS = ("session", "state.json")

# §3.1 — how much of the profile is settled. L0 has nothing to rank with, L1
# ranks on constraints alone and is labelled provisional (T44), L2 has weights.
Sufficiency = Literal["L0", "L1", "L2"]

# Which of §5.3's five rules chose the step. Carried out of the decision rather
# than reconstructed, so the reason the tool gives is the reason it used.
Rule = Literal["explicit", "cue", "position", "trigger", "sequence"]


class SessionError(Exception):
    """Session state is missing or does not satisfy the §5.1 contract."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Position(Strict):
    """Where inside a step the candidate stopped.

    This is what makes an interrupted step resume at the right question rather
    than at the top, and it is the reason the write rule is "continuously" and
    not "at the boundary".
    """

    covered: tuple[str, ...] = ()
    outstanding: tuple[str, ...] = ()

    @property
    def is_finished(self) -> bool:
        return not self.outstanding

    @property
    def is_started(self) -> bool:
        return bool(self.covered or self.outstanding)


class SessionState(Strict):
    """`profiles/<handle>/session/state.json` — process specification §5.1."""

    handle: str
    current_step: str | None = None
    position: Position = Position()
    last_activity: str | None = None
    # Skipped, not cancelled (§5.1): a step declined once is still offered by
    # rule 4 later, which is what makes declining safe rather than final.
    pending_steps: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    sufficiency: Sufficiency = "L0"

    @model_validator(mode="after")
    def _check(self) -> SessionState:
        overlap = set(self.position.covered) & set(self.position.outstanding)
        if overlap:
            raise ValueError(
                f"a question cannot be covered and outstanding at once: {sorted(overlap)}"
            )
        if self.current_step is None and self.position.is_started:
            raise ValueError("a position without a step does not say where the candidate is")
        return self

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.model_dump_json())
        return payload


class SessionStore:
    """Read and write one candidate's session state, and write it eagerly.

    Every write is atomic — a temporary file in the same directory, then a
    rename — because the failure this file exists to survive is a session that
    dies unexpectedly, and a half-written `state.json` loses exactly the
    position it was supposed to preserve.
    """

    def __init__(self, store: ProfileStore) -> None:
        self.store = store

    @property
    def handle(self) -> str:
        return self.store.handle

    @property
    def path(self) -> Path:
        return self.store.path(*STATE_PARTS)

    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> SessionState | None:
        """The recorded state, or `None` for a candidate who has never started."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            state = SessionState.model_validate_json(raw)
        except ValidationError as exc:
            raise SessionError(f"{self.handle}/session/state.json is malformed: {exc}") from exc
        if state.handle != self.handle:
            # Belt and braces over S3: a state file naming somebody else means
            # a tree was copied, and continuing would resume the wrong person.
            raise SessionError(
                f"session state under {self.handle!r} names {state.handle!r} — refusing to resume"
            )
        return state

    def write(self, state: SessionState) -> SessionState:
        if state.handle != self.handle:
            raise SessionError(f"cannot write {state.handle!r} state into {self.handle!r}")
        target = self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.as_json(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        handle_fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return state

    def record(self, *, at: str, **changes: Any) -> SessionState:
        """Write what is now known, immediately. The only mutator.

        Named `record` rather than `update` because there is nothing to flush
        afterwards: by the time this returns, a session that dies has already
        left behind everything it had learned. `at` is mandatory — §5.1 says
        `last_activity` is rewritten whenever state moves, and making it a
        keyword nobody can forget is cheaper than repeating the rule.
        """
        current = self.read() or SessionState(handle=self.handle)
        merged = current.model_dump()
        merged.update(changes)
        merged["handle"] = self.handle
        merged["last_activity"] = at
        try:
            return self.write(SessionState.model_validate(merged))
        except ValidationError as exc:
            raise SessionError(f"refusing to record inconsistent session state: {exc}") from exc

    def note_progress(self, *, at: str, step: str, covered: str) -> SessionState:
        """Mark one question answered inside the current step, and persist it now.

        This is the call a step makes mid-conversation. It exists so that the
        continuous-write rule is one method rather than a paragraph every step
        implementation has to remember.
        """
        current = self.read() or SessionState(handle=self.handle)
        position = current.position if current.current_step == step else Position()
        outstanding = tuple(item for item in position.outstanding if item != covered)
        covered_now = (
            position.covered if covered in position.covered else (*position.covered, covered)
        )
        return self.record(
            at=at,
            current_step=step,
            position=Position(covered=covered_now, outstanding=outstanding).model_dump(),
        )


# ---------------------------------------------------------------------------
# resumption — process specification §5.3


@dataclass(frozen=True)
class Trigger:
    """A freshness trigger competing to be resumed into (§5.2, owned by T36).

    `value` orders them: §5.3 rule 4 resumes "the highest-value gap or the
    oldest stale artefact", so the ordering has to be data rather than the
    order a caller happened to build the list in.
    """

    step: str
    reason: str
    value: float = 0.0


@dataclass(frozen=True)
class Resumption:
    """Which step, chosen by which rule, and the sentence that says so.

    There is no constructor path that yields a step without a reason, which is
    §5.3's second constraint made structural: the tool never resumes silently.
    """

    step: str
    rule: Rule
    reason: str
    position: Position = field(default_factory=Position)

    def announcement(self) -> str:
        """What the tool says out loud before it does anything else."""
        return f"Resuming {self.step} — {self.reason}."


def first_run_order(steps_path: Path = DEFAULT_STEPS_PATH) -> tuple[str, ...]:
    """Step ids in the candidate's journey order, loaded rather than restated.

    A second copy of the step list here would drift from
    `spec-v2-steps.json`, and the sequence rule (§5.3 rule 5) would then resume
    into a step the specification had moved or renamed.
    """
    return tuple(step.id for step in sorted(load_steps(steps_path).steps, key=lambda s: s.n))


def decide_resumption(
    state: SessionState | None,
    *,
    explicit: str | None = None,
    cue_step: str | None = None,
    cue_reason: str | None = None,
    triggers: Sequence[Trigger] = (),
    order: Sequence[str] | None = None,
) -> Resumption:
    """§5.3's five rules, highest first, applied to what this session knows.

    1. an explicit request — a command, or "let's do the interview again";
    2. a conversational cue — "let's carry on" resumes `current_step` at
       `position`; a life event re-enters its own step;
    3. a recorded position — an unfinished step is offered first;
    4. a freshness trigger — the highest-value gap or the oldest stale artefact;
    5. the next step in sequence, or the loop if the first run is complete.

    Every branch returns a rule and a sentence. A caller that wants to know why
    the tool landed somewhere reads the answer rather than reconstructing it.
    """
    sequence = tuple(order) if order is not None else first_run_order()
    if not sequence:
        raise SessionError("no step order to resume into")
    position = state.position if state else Position()

    if explicit:
        return Resumption(
            step=explicit,
            rule="explicit",
            reason="you asked for it",
            position=position if state and state.current_step == explicit else Position(),
        )

    if cue_step:
        carrying_on = bool(state and state.current_step == cue_step)
        return Resumption(
            step=cue_step,
            rule="cue",
            reason=cue_reason or ("picking up where you stopped" if carrying_on else "you said so"),
            position=position if carrying_on else Position(),
        )

    if state and state.current_step and not position.is_finished and position.is_started:
        outstanding = ", ".join(position.outstanding)
        return Resumption(
            step=state.current_step,
            rule="position",
            reason=f"you stopped part-way through, with {outstanding} still open",
            position=position,
        )

    if triggers:
        # Ties broken by step order so the choice is reproducible; a resumption
        # that varies run to run is one nobody can explain afterwards.
        best = max(
            triggers,
            key=lambda trigger: (
                trigger.value,
                -(sequence.index(trigger.step) if trigger.step in sequence else len(sequence)),
            ),
        )
        return Resumption(step=best.step, rule="trigger", reason=best.reason)

    return Resumption(step=_next_in_sequence(state, sequence), rule="sequence", reason=_why(state))


def _next_in_sequence(state: SessionState | None, sequence: Sequence[str]) -> str:
    """The step after the last completed one, skipping nothing that was skipped.

    A `pending_step` is skipped, not cancelled (§5.1), so it is offered again
    here before the run is called complete — which is what stops "I'll come
    back to that" from meaning "never".
    """
    if state is None or state.current_step is None:
        return sequence[0]
    if state.current_step not in sequence:
        return sequence[0]
    index = sequence.index(state.current_step)
    finished_current = state.position.is_finished
    for candidate in sequence[index + (1 if finished_current else 0) :]:
        return candidate
    for candidate in sequence:
        if candidate in state.pending_steps:
            return candidate
    # The first run is complete: §5.3 rule 5's "or the loop".
    return _loop_start(sequence)


def _loop_start(sequence: Sequence[str]) -> str:
    steps = load_steps().steps
    for step in sorted(steps, key=lambda s: s.n):
        if step.phase == "loop" and step.id in sequence:
            return step.id
    return sequence[-1]


def _why(state: SessionState | None) -> str:
    if state is None or state.current_step is None:
        return "this is where the process starts"
    if state.position.is_finished and state.position.is_started:
        return f"{state.current_step} is finished, so this is what comes next"
    return "this is the next step in the process"


# ---------------------------------------------------------------------------
# the gate


def probe_resumption(root: Path) -> tuple[int, list[str]]:
    """Interrupt a session in every way that loses a place, and check none does.

    Each probe writes state, **throws the writing object away**, and reads the
    file back through a fresh store. An in-process assertion passes on state
    that never reached the disk, which is the failure the write rule exists to
    prevent — so measuring it in memory would measure nothing.
    """
    from integral.identity import create_profile

    failures: list[str] = []
    probes = 0
    identity = create_profile(root, "Probe One", handle="probe-one")
    store = ProfileStore(root, identity.handle)

    # 1. Interrupted mid-step, having never reached a boundary.
    SessionStore(store).record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(outstanding=("last_job", "earlier_roles")).model_dump(),
    )
    SessionStore(store).note_progress(at="2026-08-17T10:02:00Z", step="history", covered="last_job")
    probes += 1
    reopened = SessionStore(store).read()
    if reopened is None or reopened.position.covered != ("last_job",):
        failures.append("what was covered mid-step did not survive the session")
    probes += 1
    if reopened is None or reopened.position.outstanding != ("earlier_roles",):
        failures.append("what was outstanding mid-step did not survive the session")

    # 2. Resumption lands on that step, at that position.
    probes += 1
    resumed = decide_resumption(reopened, order=first_run_order())
    if resumed.step != "history" or resumed.position.outstanding != ("earlier_roles",):
        failures.append("resumption did not land at the recorded position")

    # 3. Every rule names a step and a reason — it never resumes silently.
    for rule_name, resumption in {
        "explicit": decide_resumption(reopened, explicit="traits"),
        "cue": decide_resumption(reopened, cue_step="history"),
        "position": decide_resumption(reopened),
        "trigger": decide_resumption(None, triggers=[Trigger("constraints", "still unknown")]),
        "sequence": decide_resumption(None),
    }.items():
        probes += 1
        if not resumption.step or not resumption.reason.strip():
            failures.append(f"the {rule_name} rule resumed without saying which step, or why")
        if resumption.rule != rule_name:
            failures.append(f"the {rule_name} rule was not the one that decided")

    # 4. `last_activity` moves whenever state does.
    probes += 1
    before = SessionStore(store).read()
    after = SessionStore(store).record(at="2026-08-17T11:00:00Z", sufficiency="L1")
    if before is None or after.last_activity == before.last_activity:
        failures.append("last_activity did not move when state did")

    return probes, failures


MINIMUM_PROBES = 6


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `resumption_position_loss` in a throwaway tree and record it."""
    with tempfile.TemporaryDirectory(prefix="integral-t35-") as tmp:
        probes, failures = probe_resumption(Path(tmp) / "profiles")
    measured: dict[str, Any] = {
        "resumption_position_loss": len(failures),
        "probes_run": probes,
        "failures": failures,
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.session [path]` → T35's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["probes_run"] < MINIMUM_PROBES:
        print(
            f"only {measured['probes_run']} probes ran (floor {MINIMUM_PROBES}) — "
            "nothing was measured",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(f"resumption lost a position: {failure}", file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
