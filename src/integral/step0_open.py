"""T207 — step 0's whole opening in one command, so the candidate is not left waiting.

Two test-mode sessions (ba7a3a96 twice, b461d09a) reported the same thing: on a
returning candidate step 0 spent minutes in silent tool calls finding the profile
and reading it, then "got updated about the user" the same slow way. The step's
skill said *what* to open with and named no command for *how*, so each session
improvised the walk: list `profiles/`, open each `identity.json`, open
`session/state.json`, work out the resumption by hand — one tool call, and one
model round trip, per file.

`uv run python -m integral.step0_open open [--handle NAME] [--confirmed]` is that walk
as one call. It does what `identity.resolve_handle` already decides, and only once
a handle has resolved does it read the profile:

* **before resolution** it reads display names (`identity.json`, the roster) and
  nothing else, and says who it would offer — `confirm`, `choose` or `create`;
* **after resolution** it reads the recorded position once, applies §5.3's
  resumption rules, writes `last_activity` straight away (the step's own rule),
  and prints the opening: where the candidate stopped, how long ago, and what the
  runtime says is open next.

So the cost of step 0 is the number of times the candidate has to answer, never
the number of files read: one call when the handle is given, two when they must
confirm or choose.

**What the count measures, and what it does not.** `probe_calls` drives `run()`
the way the skill tells a session to — ask, relay the candidate's answer, ask
again — and counts invocations until the opening comes back. That is the calls
this *tool* needs; it cannot count calls a model chooses to add on top. What holds
that line is the skill, which names this command and forbids the hand walk, and
`tests/test_step0_open.py` pins that it does.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from integral.identity import (
    Identity,
    IdentityError,
    ProfileLeak,
    ProfileStore,
    Resolution,
    create_profile,
    default_profiles_root,
    list_identities,
    resolve_handle,
)
from integral.profile import ProfileError
from integral.session import SessionError, SessionStore, decide_resumption
from integral.step_runtime import ProfileView, look

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T207.json"

#: Wall-clock ceiling for one scenario, in seconds. Generous on purpose and never
#: written to the evidence file: a timing recorded there would drift on every run.
MAX_SECONDS = 60.0

#: How each kind of arrival is answered: the calls the skill tells a session to make.
#: Each is pinned exactly — a ceiling alone (the plan's `<= 3`, asserted in the tests)
#: would let one call split into two, or two into three, pass.
EXPECTED_CALLS = {
    "names_themselves": 1,
    "only_profile_confirms": 2,
    "one_of_several": 2,
    "same_display_name": 2,
}


@dataclass(frozen=True)
class Opened:
    """What one call returns. `say` is the candidate-facing text; the rest is data."""

    outcome: str  # "opened" | "confirm" | "choose" | "create"
    say: str
    handle: str | None = None
    last_activity: str | None = None
    offered: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "handle": self.handle,
            "say": self.say,
            "last_activity": self.last_activity,
            "offered": list(self.offered),
        }


def _ago(then: str | None, now: datetime) -> str | None:
    """'about 3 weeks ago' — or `None` when there is no stamp to read."""
    if not then:
        return None
    try:
        stamp = datetime.fromisoformat(then.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    days = max(0, (now - stamp).days)
    if days == 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"about {round(days / 7)} weeks ago"
    return f"about {round(days / 30)} months ago"


def _names(identities: tuple[Identity, ...]) -> str:
    """Display names; where two collide, each also carries its handle.

    §6.1: two people who answer to one name are asked for something that tells
    them apart. The handle is the identifier the candidate chose, so it is not
    sensitive, and it is what `--handle` resolves on the next call.
    """
    counts: dict[str, int] = {}
    for identity in identities:
        key = identity.display_name.casefold()
        counts[key] = counts.get(key, 0) + 1
    return ", ".join(
        f"{identity.display_name} ({identity.handle})"
        if counts[identity.display_name.casefold()] > 1
        else identity.display_name
        for identity in identities
    )


def _unresolved(resolution: Resolution) -> Opened:
    """Roster-only answers. Nothing here may be read from inside a profile."""
    if resolution.outcome == "confirm" and resolution.candidate:
        return Opened(outcome="confirm", say=f"Is this {resolution.candidate.display_name}?")
    if resolution.outcome == "choose":
        return Opened(outcome="choose", say=f"Who is this — {_names(resolution.choices)}?")
    return Opened(
        outcome="create",
        say="I don't have a profile for you yet — what would you like to be called?",
    )


def _unreadable_profiles(root: Path, readable: int) -> list[str]:
    """Handles of profile directories the roster could not read (names only)."""
    if not root.is_dir():
        return []
    found = [
        child.name
        for child in sorted(root.iterdir())
        if not child.name.startswith(".") and not child.is_symlink() and child.is_dir()
    ]
    return found if len(found) > readable else []


def run(
    root: Path,
    *,
    handle: str | None = None,
    confirmed: bool = False,
    now: datetime | None = None,
    include_fiction: bool = False,
) -> Opened:
    """One call of step 0: resolve, and once resolved, open."""
    moment = now or datetime.now(UTC)
    resolution = resolve_handle(
        root, named=handle, confirmed=confirmed, include_fiction=include_fiction
    )
    if not resolution.is_resolved or resolution.candidate is None:
        known = list_identities(root, include_fiction=include_fiction)
        broken = _unreadable_profiles(root, len(known))
        if broken:
            return Opened(
                outcome="unreadable",
                say=(
                    "A profile on this machine could not be read "
                    f"({', '.join(broken)}) — I can't tell who this is until that is looked at."
                ),
            )
        return _unresolved(resolution)

    store = resolution.store(root)
    sessions = SessionStore(store)
    try:
        state = sessions.read()
    except (SessionError, IdentityError, ProfileLeak, ProfileError):
        return Opened(
            outcome="unreadable",
            say=f"The saved position for {resolution.handle} could not be read; nothing changed.",
            handle=resolution.handle,
        )
    resumption = decide_resumption(state)
    situation = look(ProfileView(store))
    previous = state.last_activity if state else None
    # The step's own rule: last_activity moves before anything else begins.
    sessions.record(at=moment.isoformat(timespec="seconds"))

    name = resolution.candidate.display_name
    when = _ago(previous, moment)
    if state is None:
        say = f"Hello {name} — {resumption.announcement()}"
    else:
        since = f", {when}" if when else ""
        say = f"Hello again, {name}{since}. {resumption.announcement()}"
    return Opened(
        outcome="opened",
        say=say,
        handle=resolution.handle,
        last_activity=previous,
        offered=situation.offered,
    )


# ---------------------------------------------------------------------------
# the measurement


def drive(
    root: Path, answers: list[dict[str, Any]], now: datetime, *, first: dict[str, Any] | None = None
) -> tuple[int, Opened]:
    """Call `run` the way the skill says to until it opens; count the calls.

    `answers` are the candidate's replies, one per question asked. Running out of
    them before the opening comes back is a failure of the *protocol*, so it
    raises rather than looping.
    """
    calls = 0
    kwargs: dict[str, Any] = dict(first or {})
    pending = list(answers)
    while True:
        calls += 1
        result = run(root, now=now, **kwargs)
        if result.outcome == "opened":
            return calls, result
        if not pending:
            raise RuntimeError(f"step 0 still asking ({result.outcome}) with no answer to give")
        kwargs = pending.pop(0)


def probe_calls() -> dict[str, Any]:
    """Calls and seconds for each way a returning candidate arrives."""
    now = datetime(2026, 10, 4, tzinfo=UTC)
    people = (("marcos", "Marcos"), ("nuria", "Núria"), ("marcos-b", "Marcos"))
    # label -> (profiles that exist, first call's arguments, answers to questions asked)
    arrivals: dict[str, tuple[int, dict[str, Any], list[dict[str, Any]]]] = {
        "names_themselves": (1, {"handle": "marcos"}, []),
        "only_profile_confirms": (1, {}, [{"confirmed": True}]),
        "one_of_several": (2, {}, [{"handle": "marcos"}]),
        "same_display_name": (2, {}, [{"handle": "marcos-b"}]),
    }
    calls: dict[str, int] = {}
    slowest = 0.0
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="integral-t207-") as tmp:
        for label, (count, first, answers) in arrivals.items():
            root = Path(tmp) / label / "profiles"
            roster = (people[0], people[2]) if label == "same_display_name" else people[:count]
            for handle, display in roster:
                create_profile(root, display, language="en", handle=handle)
                SessionStore(ProfileStore(root, handle)).record(
                    at="2026-09-13T09:00:00+00:00", current_step="history"
                )
            started = time.monotonic()
            used, opened = drive(root, answers, now, first=first)
            slowest = max(slowest, time.monotonic() - started)
            calls[label] = used
            if "3 weeks ago" not in opened.say:
                failures.append(f"{label}: the opening never said how long ago")
            if used != EXPECTED_CALLS[label]:
                failures.append(f"{label}: took {used} calls, expected {EXPECTED_CALLS[label]}")
    return {
        "scenario_calls": calls,
        "step0_calls_before_profile_read": max(calls.values()),
        "slowest_seconds": slowest,
        "failures": failures,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T207's measurement. Wall clock is reported, never recorded."""
    measured = probe_calls()
    record = {key: value for key, value in measured.items() if key != "slowest_seconds"}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.step0_open open ...` opens step 0; no argument measures it.

    The bare form is the evidence run, because `make evidence` invokes every
    evidence-writing module with no arguments — opening a real profile from there
    would be a side effect of a measurement.
    """
    if len(argv) > 1 and argv[1] == "open":
        parser = argparse.ArgumentParser(prog="step0_open open")
        parser.add_argument("--handle", help="a handle or display name the candidate gave")
        parser.add_argument("--confirmed", action="store_true", help="the candidate said yes")
        parser.add_argument("--root", type=Path, help="profiles root (default: $INTEGRAL_HOME)")
        parser.add_argument(
            "--include-fiction", action="store_true", help="test mode: reach simulated candidates"
        )
        args = parser.parse_args(argv[2:])
        root = args.root or default_profiles_root()
        opened = run(
            root,
            handle=args.handle,
            confirmed=args.confirmed,
            include_fiction=args.include_fiction,
        )
        print(json.dumps(opened.as_json(), ensure_ascii=False))
        return 0

    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    if measured["slowest_seconds"] > MAX_SECONDS:
        print(f"step 0 took {measured['slowest_seconds']:.1f}s", file=sys.stderr)
        return 1
    if set(measured["scenario_calls"]) != set(EXPECTED_CALLS):
        return 3
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
