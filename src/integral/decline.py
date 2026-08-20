"""The decline ledger — non-insistence made mechanical (T40).

Process specification §5.4 puts this rule first, and says why it comes first:

> When cooperation drops, stop asking. A subject declined once is not raised
> again in that step; a subject declined twice is not raised again at all
> unless the candidate reopens it. **It is better to find a worse job than to
> make someone feel bad about the questions.** Coverage is a target, never a
> requirement to be extracted from a person.

A rule stated once in a process document is a rule the thirteenth step
implementation will not remember. So the ledger is the thing every question
goes through: `may_ask` is asked before a subject is raised, and it answers
from a record rather than from whoever wrote that step.

**The ledger lives in `session/`, not in the evidence log**, and that is a
deliberate line. Evidence is what is known *about the candidate*; a decline is
a fact about the conversation. Filing refusals as evidence would mean "what do
you know about me?" — which §5.4 guarantees is answerable at any point — comes
back partly as a list of things the person would not discuss. That is the
opposite of what the question is for.

**Reopening is the only thing that clears it**, and only the candidate can do
it. §5.4: "unless the candidate reopens it". Raising a subject themselves is
permission; a new session is not, a new step is not, and time passing is not.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.identity import ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T40.json"

LEDGER_PARTS = ("session", "declines.jsonl")

# A subject is whatever a step would raise: a dimension, a constraint field, a
# topic. Free-form on purpose — the steps that will use this do not share one
# vocabulary, and forcing them to would mean the ledger only covered the
# subjects somebody remembered to enumerate.
SUBJECT = re.compile(r"^[a-z][a-z0-9_]*$")

Action = Literal["declined", "reopened"]

# §5.4's two thresholds. Named rather than inlined, because the difference
# between them *is* the rule: one decline is about this step, two are about the
# subject.
DECLINES_BEFORE_STEP_SILENCE = 1
DECLINES_BEFORE_TOTAL_SILENCE = 2


class DeclineError(Exception):
    """The ledger cannot be read, or a subject is not a subject."""


@dataclass(frozen=True)
class Entry:
    """One line of the ledger."""

    subject: str
    action: Action
    step: str | None
    at: str

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"subject": self.subject, "action": self.action, "at": self.at}
        if self.step is not None:
            payload["step"] = self.step
        return payload


@dataclass(frozen=True)
class Verdict:
    """Whether a subject may be raised, and the sentence that says why not.

    The reason is carried because a step that cannot ask still has to do
    something sensible, and "the candidate declined this twice" and "the
    candidate declined this here" call for different next moves.
    """

    may_ask: bool
    reason: str

    def __bool__(self) -> bool:
        return self.may_ask


def _validate(subject: str) -> str:
    if not SUBJECT.match(subject):
        raise DeclineError(f"not a subject id: {subject!r}")
    return subject


class DeclineLedger:
    """Append-only record of what the candidate would rather not discuss."""

    def __init__(self, store: ProfileStore) -> None:
        self.store = store

    @property
    def path(self) -> Path:
        return self.store.path(*LEDGER_PARTS)

    def entries(self) -> list[Entry]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        found: list[Entry] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                found.append(
                    Entry(
                        subject=payload["subject"],
                        action=payload["action"],
                        step=payload.get("step"),
                        at=payload["at"],
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise DeclineError(f"declines.jsonl:{number} is not a ledger entry: {exc}") from exc
        return found

    def _append(self, entry: Entry) -> Entry:
        self.store.append_jsonl(entry.as_json(), *LEDGER_PARTS)
        return entry

    def decline(self, subject: str, *, step: str, at: str) -> Entry:
        """Record that the candidate would rather not discuss this, here."""
        return self._append(Entry(subject=_validate(subject), action="declined", step=step, at=at))

    def reopen(self, subject: str, *, at: str) -> Entry:
        """The candidate raised it themselves. That, and only that, clears it."""
        return self._append(Entry(subject=_validate(subject), action="reopened", step=None, at=at))

    def since_last_reopening(self, subject: str) -> list[Entry]:
        """The declines that still count — everything after the last reopening."""
        relevant = [entry for entry in self.entries() if entry.subject == subject]
        for index in range(len(relevant) - 1, -1, -1):
            if relevant[index].action == "reopened":
                return relevant[index + 1 :]
        return relevant

    def declines(self, subject: str) -> list[Entry]:
        return [entry for entry in self.since_last_reopening(subject) if entry.action == "declined"]

    def may_ask(self, subject: str, *, step: str) -> Verdict:
        """§5.4's rule, applied to one subject in one step.

        Note what a single decline does *not* do: it does not silence the
        subject everywhere. §2.5 guarantees a path forward without any given
        answer, and a constraint the candidate would not discuss during the
        interview may still be worth one gentle ask when it turns out to decide
        a shortlist. What it must never become is the same question again in
        the same conversation.
        """
        _validate(subject)
        declined = self.declines(subject)
        if len(declined) >= DECLINES_BEFORE_TOTAL_SILENCE:
            return Verdict(
                False,
                f"{subject} was declined {len(declined)} times — not raised again "
                "unless they bring it up",
            )
        if any(entry.step == step for entry in declined):
            return Verdict(False, f"{subject} was already declined in {step}")
        return Verdict(True, f"{subject} has not been declined in {step}")

    def silenced(self) -> list[str]:
        """Every subject that is now off the table entirely."""
        subjects = {entry.subject for entry in self.entries()}
        return sorted(
            subject
            for subject in subjects
            if len(self.declines(subject)) >= DECLINES_BEFORE_TOTAL_SILENCE
        )


# ---------------------------------------------------------------------------
# the gate


@dataclass(frozen=True)
class Ask:
    """One question a scripted step would like to put to the candidate."""

    subject: str
    step: str


def count_repeat_asks(ledger: DeclineLedger, asks: list[Ask]) -> list[str]:
    """Replay a run of questions and count the ones the rule forbids.

    The measurement is over *attempted* asks, not over the ledger's own state:
    a ledger that records everything correctly and is never consulted scores
    perfectly on itself and asks the question anyway.
    """
    offences: list[str] = []
    for ask in asks:
        verdict = ledger.may_ask(ask.subject, step=ask.step)
        if not verdict.may_ask:
            offences.append(f"asked {ask.subject} in {ask.step}: {verdict.reason}")
    return offences


def probe_declines(root: Path) -> dict[str, Any]:
    """Decline, decline again, reopen — and try to ask at every point."""
    from integral.identity import create_profile

    identity = create_profile(root, "Probe One", handle="probe-one")
    ledger = DeclineLedger(ProfileStore(root, identity.handle))
    failures: list[str] = []
    asks = 0

    # Nothing declined: every subject is fair game.
    asks += 1
    if not ledger.may_ask("salary_floor", step="constraints"):
        failures.append("a subject nobody declined was refused")

    ledger.decline("salary_floor", step="constraints", at="2026-08-17T10:00:00Z")
    asks += 1
    if ledger.may_ask("salary_floor", step="constraints"):
        failures.append("a subject declined in a step was raised again in that step")
    asks += 1
    if not ledger.may_ask("salary_floor", step="ranking"):
        failures.append("one decline silenced a subject everywhere, which §2.5 does not ask for")

    ledger.decline("salary_floor", step="ranking", at="2026-08-17T11:00:00Z")
    for step in ("constraints", "ranking", "feedback", "application"):
        asks += 1
        if ledger.may_ask("salary_floor", step=step):
            failures.append(f"a subject declined twice was raised again in {step}")
    if "salary_floor" not in ledger.silenced():
        failures.append("a subject declined twice is not reported as silenced")

    ledger.reopen("salary_floor", at="2026-08-18T09:00:00Z")
    asks += 1
    if not ledger.may_ask("salary_floor", step="constraints"):
        failures.append("the candidate reopened a subject and it stayed closed")
    if ledger.silenced():
        failures.append("a reopened subject is still reported as silenced")

    # And nothing but the candidate clears it: declining again re-silences.
    ledger.decline("salary_floor", step="constraints", at="2026-08-18T09:05:00Z")
    ledger.decline("salary_floor", step="history", at="2026-08-18T09:06:00Z")
    asks += 1
    if ledger.may_ask("salary_floor", step="traits"):
        failures.append("declines after a reopening did not count")

    # The whole run, replayed as a dispatcher would.
    offences = count_repeat_asks(
        ledger,
        [Ask("salary_floor", "constraints"), Ask("salary_floor", "traits")],
    )
    return {
        "repeat_asks_after_decline": len(failures),
        "asks_evaluated": asks,
        "forbidden_asks_detected": len(offences),
        "failures": failures,
    }


MINIMUM_ASKS = 8


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `repeat_asks_after_decline` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="integral-t40-") as tmp:
        measured = probe_declines(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.decline [path]` → T40's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["asks_evaluated"] < MINIMUM_ASKS:
        print(
            f"only {measured['asks_evaluated']} asks were evaluated (floor {MINIMUM_ASKS}) — "
            "zero repeat asks over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
