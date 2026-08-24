"""Freshness triggers and proactive re-entry (T36).

Process specification §5.2 is the requirement that separates this from a form:
**if something could have changed, ask.** A candidate who returns after two
years saying "I lost my job" should not be handed a stale ranking; they should
be asked what happened, because that is both the most useful thing to know and
the most human thing to say.

Three trigger kinds, evaluated at session start after identification:

* **elapsed time** — from `last_activity`, and from `occurred_at` on the most
  recent role evidence;
* **a life event in the conversation** — the candidate says it: lost or left a
  job, moved, finished a course, changed field;
* **a gap** — a constraint still `unknown`, a pending step, a trait below
  sufficiency.

A fourth arrived with iterative sourcing (T63, `iterative-sourcing.md` §5.3):

* **exhaustion** — the sourcing cycle keeps finding the same jobs
  (`Exhaustion.exhausted`, T62). It is a **kind beside staleness, never a
  change to it**: staleness fires on elapsed time, exhaustion on a repeat
  share, and neither reads the other's input. What makes it its own kind rather
  than another gap is that re-entry has to **carry a proposal** — re-running the
  same search because it returned the same jobs is the failure the trigger
  exists to prevent, so an exhausted offer with no proposal cannot be
  constructed. That is `stuck_cycles_without_a_proposal`, measured in
  `integral.sourcing_reentry`.

**The process-level rule is that a trigger produces an offer, never an
action.** So nothing in this module writes to the profile or enters a step:
`offers` is a pure read, and the only writing function here records a *decline*.
That is not a convention — it is what `unoffered_reentries == 0` measures, by
comparing the tree before and after the triggers are evaluated.

**What proactive re-entry must never become is an audit.** "It has been eight
months, let's update your file" is a form. "You said you left in March — how
did that end up?" is a conversation, and it is the one that gets an answer. So
every offer carries the sentence it would say, and the sentence names the thing
that prompted it.

Declining is recorded so it is not asked again next week — through the same
ledger as §5.4's non-insistence rule (T40), because a candidate who has waved
away the same suggestion twice has said the same thing either way.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from integral.decline import DeclineLedger
from integral.identity import ProfileStore
from integral.process_spec import StepList, load_steps
from integral.profile import EvidenceLog
from integral.revision import stale_artefacts
from integral.session import SessionStore
from integral.sourcing_strategy import Exhaustion

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T36.json"

Kind = Literal["elapsed", "life_event", "gap", "exhausted"]

# §5.2 says the thresholds for "elapsed" belong to each step's specification.
# Until those land this is the process-level default, and it is a parameter
# everywhere rather than a constant read at the point of use — so a step spec
# supplying its own does not have to change this module.
DEFAULT_ELAPSED_DAYS = 180


class FreshnessError(Exception):
    """A trigger cannot be evaluated."""


@dataclass(frozen=True)
class Offer:
    """Something the tool noticed, and what it would like to ask.

    An offer, never an action — §5.2. `subject` is what a decline is recorded
    against, so waving the same suggestion away twice silences it for good
    through the same ledger as every other question.
    """

    kind: Kind
    step: str
    subject: str
    says: str
    reason: str = ""
    # ponytail: a string stands in for T64's `ScopeProposal` (§5.4). What
    # re-entry needs here is only *that* a proposal accompanies the trigger;
    # T64 replaces the annotation with the typed, symmetric-by-construction
    # thing and nothing else in this module changes.
    proposal: str | None = None

    def __post_init__(self) -> None:
        if self.kind != "exhausted":
            return
        if not self.reason.strip():
            raise FreshnessError("an exhaustion with no reason is a violation, not a trigger")
        if not (self.proposal or "").strip():
            raise FreshnessError(
                "an exhausted step re-entered with no proposal — that is re-running "
                "the same search because it returned the same jobs"
            )

    def sentence(self) -> str:
        return self.says


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def steps_for_event(event: str, steps: StepList | None = None) -> list[str]:
    """Which step(s) an event re-enters, from `reentry_events` in the step list.

    Read from the data rather than from a table here: §3.5 gives three examples
    and says explicitly that they are examples, not the set. A hardcoded map
    would answer for those three and silently answer nothing for "I moved" or
    "I finished the course".
    """
    steps = steps or load_steps()
    return [
        step.id for step in sorted(steps.steps, key=lambda s: s.n) if event in step.reentry_events
    ]


def elapsed_offers(
    store: ProfileStore, *, now: datetime, elapsed_days: int = DEFAULT_ELAPSED_DAYS
) -> list[Offer]:
    """Time has passed, so something could have changed (§5.2, row one)."""
    state = SessionStore(store).read()
    last = _parse(state.last_activity if state else None)
    if last is None:
        return []
    gap = now - last
    if gap < timedelta(days=elapsed_days):
        return []
    months = gap.days // 30
    return [
        Offer(
            kind="elapsed",
            step=step,
            subject=f"elapsed_{step}",
            says=says,
        )
        for step, says in (
            (
                "history",
                f"It has been about {months} months since we last spoke — "
                "what have you been doing since then?",
            ),
            (
                "constraints",
                "Has anything changed about what you need from a job — where you can work, "
                "what you need to earn?",
            ),
        )
    ]


def life_event_offers(
    event: str, *, steps: StepList | None = None, said: str | None = None
) -> list[Offer]:
    """The candidate said something that re-enters a step (§5.2, row two).

    The sentence quotes them rather than announcing a process step. "You said
    you left in March — how did that end up?" is a conversation; "re-entering
    step 3" is not.
    """
    entered = steps_for_event(event, steps)
    if not entered:
        raise FreshnessError(f"no step declares {event!r} as a re-entry event")
    spoken = f"You mentioned {said}. " if said else ""
    return [
        Offer(
            kind="life_event",
            step=step,
            subject=f"life_event_{event}",
            says=f"{spoken}Would it help to go over that?",
        )
        for step in entered
    ]


def gap_offers(store: ProfileStore, *, steps: StepList | None = None) -> list[Offer]:
    """Something is missing, and a step owns it (§5.2, row three).

    Three sources, in the order §5.2 lists them: a constraint still `unknown`,
    a pending step, and the oldest stale artefact — which is T37's computation
    rather than a second opinion about it.
    """
    steps = steps or load_steps()
    found: list[Offer] = []

    constraints = _read_json(store, "profile", "constraints.json")
    if isinstance(constraints, dict):
        fields = constraints.get("fields")
        if isinstance(fields, dict):
            for name, value in sorted(fields.items()):
                if isinstance(value, dict) and value.get("state") == "unknown":
                    found.append(
                        Offer(
                            kind="gap",
                            step="constraints",
                            subject=f"gap_{name}",
                            says=f"We never settled {name.replace('_', ' ')} — worth a minute?",
                        )
                    )

    state = SessionStore(store).read()
    for step in state.pending_steps if state else ():
        found.append(
            Offer(
                kind="gap",
                step=step,
                subject=f"pending_{step}",
                says=f"We skipped {step} earlier — would you like to come back to it?",
            )
        )

    stale = [entry for entry in stale_artefacts(store) if entry.artefact_class == "authored"]
    for entry in sorted(stale, key=lambda item: item.artefact):
        found.append(
            Offer(
                kind="gap",
                step="application",
                subject=f"stale_{entry.artefact}",
                says=f"{entry.artefact} was made before {entry.reason()} — regenerate it?",
            )
        )
    return found


def exhaustion_offers(exhaustion: Exhaustion, *, proposal: str | None) -> list[Offer]:
    """The sourcing cycle keeps finding the same jobs (§5.3, the fourth row).

    Fires on `Exhaustion.exhausted` and on nothing else — no clock is read, so
    a search that went stale and a search that went round in circles stay two
    separate observations. T62's `reason` is carried through verbatim rather
    than restated: it already names the repeat share, the cycle, and what was
    repeated, and a second wording of the same fact is a second thing to keep
    true.
    """
    if not exhaustion.exhausted:
        return []
    return [
        Offer(
            kind="exhausted",
            step="sourcing",
            subject="exhausted_sourcing",
            says=f"{exhaustion.reason}. Shall we change where we look?",
            reason=exhaustion.reason,
            proposal=proposal,
        )
    ]


def _read_json(store: ProfileStore, *parts: str) -> Any:
    path = store.path(*parts)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def offers(
    store: ProfileStore,
    *,
    now: datetime,
    event: str | None = None,
    said: str | None = None,
    elapsed_days: int = DEFAULT_ELAPSED_DAYS,
    steps: StepList | None = None,
    exhaustion: Exhaustion | None = None,
    proposal: str | None = None,
) -> list[Offer]:
    """Everything the tool noticed, minus what the candidate has waved away.

    A pure read. Nothing here writes to the profile, and the gate proves it by
    comparing the tree before and after.

    `exhaustion` is optional and defaults to absent, so every caller that never
    sourced anything behaves exactly as it did before this kind existed.
    """
    steps = steps or load_steps()
    raised = [
        *elapsed_offers(store, now=now, elapsed_days=elapsed_days),
        *(life_event_offers(event, steps=steps, said=said) if event else []),
        *gap_offers(store, steps=steps),
        *(exhaustion_offers(exhaustion, proposal=proposal) if exhaustion else []),
    ]
    ledger = DeclineLedger(store)
    return [offer for offer in raised if ledger.may_ask(offer.subject, step=offer.step).may_ask]


def decline(store: ProfileStore, offer: Offer, *, at: str) -> None:
    """Record that the candidate does not want to be asked this.

    The only writing function in the module, and it writes a refusal rather
    than an action — "declining is recorded so it is not asked again next week"
    (§5.2), through the same ledger as §5.4.
    """
    DeclineLedger(store).decline(offer.subject, step=offer.step, at=at)


def tree_fingerprint(store: ProfileStore) -> dict[str, bytes]:
    """Every byte under one profile, so "it only offered" can be checked."""
    home = store.path()
    if not home.is_dir():
        return {}
    return {
        str(path.relative_to(home)): path.read_bytes()
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# the gate


def probe_freshness(root: Path) -> dict[str, Any]:
    """Fire each trigger kind and check the tool offered rather than acted.

    The central check is a byte-for-byte comparison of the tree before and
    after evaluating every trigger. "It only offered" is otherwise a claim
    about code somebody has to read; this way it is a measurement.
    """
    from integral.identity import create_profile

    failures: list[str] = []
    identity = create_profile(root, "Probe One", handle="probe-one")
    store = ProfileStore(root, identity.handle)
    session = SessionStore(store)
    session.record(
        at="2024-01-01T10:00:00Z",
        current_step="history",
        pending_steps=("traits",),
    )
    store.write_json(
        {"fields": {"salary_floor": {"state": "unknown"}}}, "profile", "constraints.json"
    )
    EvidenceLog(store).append(
        recorded_at="2024-01-01T10:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="A while ago now.",
        source="conversation",
    )

    now = datetime.fromisoformat("2026-08-18T09:00:00+00:00")
    before = tree_fingerprint(store)
    raised = offers(store, now=now, event="left_job", said="you left your job in March")
    after = tree_fingerprint(store)

    if after != before:
        failures.append("evaluating the triggers changed the profile — a trigger acted")

    kinds = {offer.kind for offer in raised}
    for kind in ("elapsed", "life_event", "gap"):
        if kind not in kinds:
            failures.append(f"the {kind} trigger produced no offer")
    for offer in raised:
        if not offer.sentence().strip():
            failures.append(f"the {offer.kind} offer for {offer.step} says nothing")
        if "step" in offer.sentence().lower() and offer.kind == "life_event":
            failures.append("a life-event offer announced a process step instead of a conversation")

    # §3.5 — "I left my job" re-enters History, and the step list is what says so.
    entered = {offer.step for offer in raised if offer.kind == "life_event"}
    if entered != set(steps_for_event("left_job")):
        failures.append(f"left_job entered {sorted(entered)} rather than the step the spec names")
    if "history" not in entered:
        failures.append("left_job did not re-enter History")

    # Declining is recorded, and the same suggestion is not made again.
    declined = next(offer for offer in raised if offer.kind == "gap")
    decline(store, declined, at="2026-08-18T09:05:00Z")
    again = offers(store, now=now, event="left_job", said="you left your job in March")
    if any(offer.subject == declined.subject and offer.step == declined.step for offer in again):
        failures.append("a declined trigger was raised again in the same step")

    return {
        "unoffered_reentries": len(failures),
        "offers_raised": len(raised),
        "trigger_kinds": sorted(kinds),
        "failures": failures,
    }


MINIMUM_OFFERS = 3


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `unoffered_reentries` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-t36-") as tmp:
        measured = probe_freshness(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.freshness [path]` → T36's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["offers_raised"] < MINIMUM_OFFERS:
        print(
            f"only {measured['offers_raised']} offers were raised (floor {MINIMUM_OFFERS}) — "
            "a trigger that fires nothing cannot be shown to offer rather than act",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
