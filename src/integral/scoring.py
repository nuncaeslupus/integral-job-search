"""Scoring triggers — three occasions, and never per message (T39).

Process specification §4.2 separates two things that look like one: **capture**
is cheap and always on, **scoring** is expensive and happens at exactly three
triggers.

1. **A step boundary** — any step ending recomputes what its evidence touched.
2. **An explicit request** — "what do you know about me now?"
3. **A batch threshold** — N new trait-bearing evidence rows since the last
   scoring run. N is 20, set in the Traits step specification.

The sentence that makes this safe is the last one in §4.2: *"Because the
profile is a pure function of the log, deferring scoring costs freshness and
nothing else — the log is never behind, and no evidence is ever lost to a
scoring run that did not happen."* Capture (T6) is what makes that true; this
module is what makes it worth relying on.

**"Never per message" is about the scoring, not the check.** Asking whether the
threshold has been reached is a count over the log and costs nothing; running
the scoring is the expensive part. So an ordinary message may *reach* the
threshold and score — but the run is then attributed to `batch_threshold`,
because that is what authorised it. There is no fourth trigger called "a
message arrived", and a run that cannot name one of the three is exactly what
`unscheduled_scoring_runs` counts.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.identity import ProfileStore
from integral.profile import EvidenceLog, EvidenceRow, ProfileRevision, rebuild

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T39.json"

MARKER_PARTS = ("session", "scoring.json")

# §4.2's three, and nothing else. A run whose trigger is not one of these is
# the defect this module exists to prevent, so the type is closed.
Trigger = Literal["step_boundary", "explicit_request", "batch_threshold"]
TRIGGERS: frozenset[str] = frozenset({"step_boundary", "explicit_request", "batch_threshold"})

# What just happened in the conversation. Note that `message` is an *occasion*
# and never a trigger: it is the thing scoring must not run for on its own.
Occasion = Literal["message", "step_boundary", "explicit_request"]

# N, from the Traits step specification: twenty new trait-bearing rows.
BATCH_THRESHOLD = 20


class ScoringError(Exception):
    """The scoring marker cannot be read."""


@dataclass(frozen=True)
class LastScoring:
    """When scoring last ran, and over how much."""

    revision: ProfileRevision
    rows: int
    trigger: str
    at: str

    def as_json(self) -> dict[str, Any]:
        return {
            "profile_revision": self.revision.as_json(),
            "rows": self.rows,
            "trigger": self.trigger,
            "at": self.at,
        }


@dataclass(frozen=True)
class Decision:
    """Whether to score now, and which of the three triggers says so."""

    run: bool
    trigger: Trigger | None
    reason: str
    pending: int

    def __bool__(self) -> bool:
        return self.run


def is_trait_bearing(row: EvidenceRow) -> bool:
    """Whether a row would move a trait score.

    A row with no dimension attached cannot change `traits.json`, so counting
    it towards the batch threshold would make the threshold fire on volume
    rather than on content — twenty remarks about the weather triggering a
    rescore that has nothing to rescore.
    """
    return bool(row.dimensions) and row.kind in {"episode", "statement", "reaction"}


def read_last_scoring(store: ProfileStore) -> LastScoring | None:
    marker = store.path(*MARKER_PARTS)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ScoringError(f"{store.handle}/session/scoring.json is malformed: {exc}") from exc
    stamp = payload.get("profile_revision", {})
    return LastScoring(
        revision=ProfileRevision(rows=stamp.get("rows", 0), sha256=stamp.get("sha256", "")),
        rows=payload.get("rows", 0),
        trigger=payload.get("trigger", ""),
        at=payload.get("at", ""),
    )


def pending_rows(store: ProfileStore) -> list[EvidenceRow]:
    """Trait-bearing rows appended since the last scoring run.

    Indexed by position in the log rather than filtered by time, for the same
    reason as `revision.rows_since`: the log is append-only and a revision
    counts rows, so two rows in the same second are two rows.
    """
    log = EvidenceLog(store)
    last = read_last_scoring(store)
    rows = log.rows()[last.rows :] if last else log.rows()
    return [row for row in rows if is_trait_bearing(row)]


def decide(
    store: ProfileStore, occasion: Occasion, *, threshold: int = BATCH_THRESHOLD
) -> Decision:
    """§4.2's rule, applied to whatever just happened.

    A step boundary and an explicit request authorise a run outright. A message
    authorises nothing on its own — it can only be the moment at which the
    batch threshold turns out to have been reached, and the run is attributed
    to the threshold, because that is what permitted it.
    """
    waiting = len(pending_rows(store))
    if occasion == "step_boundary":
        return Decision(
            True, "step_boundary", "a step ended, so what it touched is recomputed", waiting
        )
    if occasion == "explicit_request":
        return Decision(True, "explicit_request", "you asked what is known now", waiting)
    if waiting >= threshold:
        return Decision(
            True,
            "batch_threshold",
            f"{waiting} new trait-bearing rows since the last scoring (threshold {threshold})",
            waiting,
        )
    return Decision(
        False,
        None,
        f"{waiting} new trait-bearing rows, below the threshold of {threshold} — "
        "nothing is lost by waiting",
        waiting,
    )


def score(store: ProfileStore, decision: Decision, *, at: str) -> dict[str, str]:
    """Recompute the derived files, and record that it happened and why.

    Refuses a decision that names no trigger. That refusal is the mechanism
    behind `unscheduled_scoring_runs == 0`: there is no way to reach the
    expensive path without one of §4.2's three, so the count is enforced rather
    than audited after the fact.
    """
    if not decision.run or decision.trigger is None:
        raise ScoringError(f"refusing to score without one of §4.2's triggers ({decision.reason})")
    if decision.trigger not in TRIGGERS:  # pragma: no cover - the type forbids it
        raise ScoringError(f"{decision.trigger!r} is not one of §4.2's three triggers")
    written = rebuild(store)
    log = EvidenceLog(store)
    store.write_json(
        LastScoring(
            revision=log.revision(), rows=len(log.rows()), trigger=decision.trigger, at=at
        ).as_json(),
        *MARKER_PARTS,
    )
    return written


def score_if_due(
    store: ProfileStore, occasion: Occasion, *, at: str, threshold: int = BATCH_THRESHOLD
) -> Decision:
    """The call a conversation makes on every turn. Usually it does nothing."""
    decision = decide(store, occasion, threshold=threshold)
    if decision.run:
        score(store, decision, at=at)
    return decision


# ---------------------------------------------------------------------------
# the gate


def probe_scoring(root: Path, *, threshold: int = 5) -> dict[str, Any]:
    """Run a conversation past the module and watch when scoring happens.

    A small threshold so the probe is a conversation rather than a load test;
    the number itself is `BATCH_THRESHOLD`'s job and is pinned by a test.
    """
    from integral.identity import create_profile

    identity = create_profile(root, "Probe One", handle="probe-one")
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    failures: list[str] = []
    runs: list[str] = []
    turns = 0

    def say(index: int, *, dimensions: tuple[str, ...] = ("team_autonomy",)) -> None:
        log.append(
            recorded_at=f"2026-08-17T10:{index:02d}:00Z",
            step="history",
            kind="statement",
            dimensions=list(dimensions),
            text=f"Something said in turn {index}.",
            source="conversation",
        )

    # A handful of ordinary messages, none of which may score on their own.
    for index in range(1, threshold):
        say(index)
        turns += 1
        decision = score_if_due(
            store, "message", at=f"2026-08-17T10:{index:02d}:30Z", threshold=threshold
        )
        if decision.run:
            failures.append(f"scoring ran on message {index}, below the threshold")
        runs.extend([decision.trigger] if decision.trigger else [])

    # Nothing has been scored, and nothing has been lost.
    if read_last_scoring(store) is not None:
        failures.append("a scoring run was recorded while below every trigger")
    if len(log.rows()) != threshold - 1:
        failures.append("capture stopped while scoring was deferred")

    # The threshold turn.
    say(threshold)
    turns += 1
    decision = score_if_due(store, "message", at="2026-08-17T10:30:00Z", threshold=threshold)
    if not decision.run or decision.trigger != "batch_threshold":
        failures.append("the batch threshold was reached and scoring did not run")
    runs.extend([decision.trigger] if decision.trigger else [])

    # Everything said while scoring was deferred is in the derived files now.
    stories = store.read_text("profile", "traits.json")
    for row in log.effective_rows():
        if row.id not in stories:
            failures.append(f"{row.id} was appended while scoring was deferred and was lost")

    # A step boundary and an explicit request each authorise a run outright.
    for occasion in ("step_boundary", "explicit_request"):
        turns += 1
        decision = score_if_due(
            store,
            occasion,
            at="2026-08-17T11:00:00Z",
            threshold=threshold,
        )
        if decision.trigger != occasion:
            failures.append(f"{occasion} did not score as {occasion}")
        runs.extend([decision.trigger] if decision.trigger else [])

    # And the expensive path cannot be reached without one of the three.
    try:
        score(store, Decision(False, None, "just because", 0), at="2026-08-17T11:05:00Z")
    except ScoringError:
        pass
    else:
        failures.append("scoring ran without naming a trigger")

    unscheduled = [trigger for trigger in runs if trigger not in TRIGGERS]
    return {
        "unscheduled_scoring_runs": len(unscheduled) + len(failures),
        "turns_evaluated": turns,
        "scoring_runs": runs,
        "failures": failures,
    }


#: A floor, never the count of the day (T100), on `probe_scoring`'s own running
#: tally of evaluated turns rather than a collection this module lists — the
#: scripted scenario run *is* the fixture. Raised to what the probe carries — 7,
#: zero slack — because 6 tolerated the first deleted turn silently, with no
#: margin argued (T159).
MINIMUM_TURNS = 7


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `unscheduled_scoring_runs` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-t39-") as tmp:
        measured = probe_scoring(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.scoring [path]` → T39's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["turns_evaluated"] < MINIMUM_TURNS:
        print(
            f"only {measured['turns_evaluated']} turns were evaluated (floor {MINIMUM_TURNS}) — "
            "zero unscheduled runs over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
