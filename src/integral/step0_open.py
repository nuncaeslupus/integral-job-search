"""T207 — step 0's whole opening in one command, so the candidate is not left waiting.

Two test-mode sessions (ba7a3a96 twice, b461d09a) reported the same thing: on a
returning candidate step 0 spent minutes in silent tool calls finding the profile
and reading it, then "got updated about the user" the same slow way. The step's
skill said *what* to open with and named no command for *how*, so each session
improvised the walk: list `profiles/`, open each `identity.json`, open
`session/state.json`, work out the resumption by hand — one tool call, and one
model round trip, per file.

`uv run python -m integral.step0_open open [--name N | --handle H] [--confirmed]` is that
walk as one call. It follows §6.1's order, and only once the candidate has confirmed
who they are does it read the profile:

* **before resolution** it reads display names (`identity.json`, the roster) and
  nothing else, and says who it would offer — `confirm`, `choose` or `create`;
* **after resolution** it reads the recorded position once, applies §5.3's
  resumption rules, writes `last_activity` straight away (the step's own rule),
  and prints the opening: where the candidate stopped, how long ago, and what the
  runtime says is open next.

So the cost of step 0 is the number of times the candidate has to answer, never
the number of files read: two calls when the candidate is the only profile or names
themselves (offer, then yes), three when they must first choose or give a handle.

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
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from integral.identity import (
    ROSTER_FILE,
    Identity,
    IdentityError,
    ProfileLeak,
    ProfileStore,
    Resolution,
    create_profile,
    default_profiles_root,
    derive_handle,
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
    "names_themselves": 2,
    "only_profile_confirms": 2,
    "one_of_several": 3,
    "same_display_name_first": 3,
    "same_display_name_second": 3,
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


def _same_name(left: str, right: str) -> bool:
    """Display names compare as people read them: NFC, then caseless."""
    return (
        unicodedata.normalize("NFC", left).casefold()
        == unicodedata.normalize("NFC", right).casefold()
    )


def _names(identities: tuple[Identity, ...]) -> str:
    """Display names only; a collision is said, never resolved by listing handles.

    A handle is an identifier, and before anyone has said who they are the only
    cross-profile data step 0 may show is a display name (SKILL, Reads). So two
    profiles with one name are announced as such and the candidate is asked to
    give their own handle.
    """
    names = [identity.display_name for identity in identities]
    shown = ", ".join(names)
    collides = any(
        _same_name(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))
    )
    if collides:
        shown += " (some of these share a name, so give me your handle rather than your name)"
    return shown


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


def _broken_profiles(root: Path) -> list[str]:
    """Directories that are profiles by their `identity.json` and fail to parse it.

    Decided per directory, never by comparing counts: a readable simulated
    profile is not broken, and a stray directory with neither an
    `identity.json` nor a `session/state.json` is not a profile at all. Only the directory names are
    returned, and only so a caller can tell whether the arrival is one of them.
    """
    if not root.is_dir():
        return []
    broken: list[str] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        if not (child / ROSTER_FILE).is_file() and not (child / "session" / "state.json").is_file():
            continue  # no identity and no recorded position: not a profile at all
        try:
            ProfileStore(root, child.name).identity()
        except (IdentityError, ProfileLeak, ProfileError, ValueError):
            broken.append(child.name)
            continue
    return broken


def _day(stamp: str) -> str | None:
    """The calendar day of an ISO timestamp, or `None` when it does not parse."""
    try:
        return datetime.fromisoformat(stamp.strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _started_on(hit: Identity, identities: list[Identity]) -> str | Opened:
    """The one rule for what tells a `--handle` arrival's profile apart, shared by the
    question call and the `--confirmed` call so the two cannot diverge.

    On this path the display name is the shared one by definition, so it cannot tell
    two people apart; the creation day, from the same roster file, can. It must be
    (a) a parseable ISO date and (b) different from the creation day of every other
    profile with the same display name (NFC, caseless). (a) failing is `unreadable`;
    (b) failing refuses to open by handle at all. Only the day is ever shown, and no
    other profile is ever listed.
    """
    day = _day(hit.created_at)
    if day is None:
        return Opened(
            outcome="unreadable",
            say="A saved profile could not be read, so I can't tell who this is yet.",
        )
    for other in identities:
        if other.handle == hit.handle or not _same_name(other.display_name, hit.display_name):
            continue
        if _day(other.created_at) in (None, day):
            return Opened(
                outcome="ambiguous",
                say=(
                    "This profile can't be told apart from another one automatically, "
                    "so it needs manual help before I can open it."
                ),
            )
    return day


def _unreadable(wanted: str, root: Path, include_fiction: bool) -> Opened | None:
    """`unreadable` only when this arrival could be the profile that cannot be read.

    They named it (by its handle, or by a name it would derive that handle from,
    matched caseless like any other name), or nobody readable is left to be. A
    newcomer is still offered create, and the message names nothing: no handle is
    shown before resolution.
    """
    broken = [name.casefold() for name in _broken_profiles(root)]
    if not broken:
        return None
    readable = list_identities(root, include_fiction=include_fiction)
    key = wanted.strip()
    named_it = bool(key) and (
        key.casefold() in broken or derive_candidate_handle(key).casefold() in broken
    )
    if named_it or (not key and not readable):
        return Opened(
            outcome="unreadable",
            say="A saved profile could not be read, so I can't tell who this is yet.",
        )
    return None


def derive_candidate_handle(text: str) -> str:
    try:
        return derive_handle(text)
    except IdentityError:
        return ""


def _open(root: Path, identity: Identity, moment: datetime) -> Opened:
    store = ProfileStore(root, identity.handle)
    sessions = SessionStore(store)
    try:
        state = sessions.read()
    except (SessionError, IdentityError, ProfileLeak, ProfileError):
        return Opened(
            outcome="unreadable",
            say=f"The saved position for {identity.handle} could not be read; nothing changed.",
            handle=identity.handle,
        )
    resumption = decide_resumption(state)
    situation = look(ProfileView(store))
    previous = state.last_activity if state else None
    # The step's own rule: last_activity moves before anything else begins.
    sessions.record(at=moment.isoformat(timespec="seconds"))

    when = _ago(previous, moment)
    if state is None:
        say = f"Hello {identity.display_name} — {resumption.announcement()}"
    else:
        since = f", {when}" if when else ""
        say = f"Hello again, {identity.display_name}{since}. {resumption.announcement()}"
    return Opened(
        outcome="opened",
        say=say,
        handle=identity.handle,
        last_activity=previous,
        offered=situation.offered,
    )


def run(
    root: Path,
    *,
    name: str | None = None,
    handle: str | None = None,
    confirmed: bool = False,
    now: datetime | None = None,
    include_fiction: bool = False,
) -> Opened:
    """One call of step 0: resolve, and once resolved, open.

    The two inputs are kept apart, because one string can be a stranger's handle
    and another person's name (`profiles/ana` is "Bea"; "Ana" is `bea-x`):

    * `name` matches **display names only** (NFC, caseless). One match is offered
      for confirmation, several are a collision (nothing is listed; the candidate
      is asked for their handle), none is a newcomer.
    * `handle` matches **handles only**, exactly, and is for answering a
      collision. It is still offered for confirmation by display name, so a
      mistyped handle cannot open someone else's profile silently.

    No input opens a profile without `confirmed`, which is the caller reporting
    that the human said yes to the offer made on the previous call.
    """
    moment = now or datetime.now(UTC)
    identities = list_identities(root, include_fiction=include_fiction)

    if handle is not None and handle.strip():
        wanted = handle.strip()
        hit = next((i for i in identities if i.handle == wanted), None)
        if hit is None:
            return _unreadable(wanted, root, include_fiction) or _unresolved(
                Resolution(outcome="create", reason="no profile has that handle")
            )
        started = _started_on(hit, identities)
        if isinstance(started, Opened):
            return started
        if not confirmed:
            return Opened(
                outcome="confirm",
                say=f"Is this {hit.display_name}, whose profile was started on {started}?",
            )
        return _open(root, hit, moment)

    if name is not None and name.strip():
        wanted = name.strip()
        matches = [i for i in identities if _same_name(i.display_name, wanted)]
        if len(matches) == 1:
            if not confirmed:
                return Opened(outcome="confirm", say=f"Is this {matches[0].display_name}?")
            return _open(root, matches[0], moment)
        if len(matches) > 1:
            return Opened(
                outcome="choose",
                say=(
                    "More than one profile answers to that name, so give me your handle "
                    "(the short name you chose) rather than your name."
                ),
            )
        return _unreadable(wanted, root, include_fiction) or _unresolved(
            Resolution(outcome="create", reason="no profile matches that name")
        )

    resolution = resolve_handle(root, confirmed=confirmed, include_fiction=include_fiction)
    if resolution.is_resolved and resolution.candidate is not None:
        return _open(root, resolution.candidate, moment)
    return _unreadable("", root, include_fiction) or _unresolved(resolution)


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
    marcos, nuria, twin = ("marcos", "Marcos"), ("nuria", "Núria"), ("marcos-b", "Marcos")
    yes = {"confirmed": True}
    # label -> (profiles that exist, first call's arguments, answers, who opens).
    # An answer repeats what the candidate said and adds their yes to the offer.
    arrivals: dict[
        str, tuple[tuple[tuple[str, str], ...], dict[str, Any], list[dict[str, Any]], str]
    ] = {
        "names_themselves": ((marcos,), {"name": "Marcos"}, [{"name": "Marcos", **yes}], "marcos"),
        "only_profile_confirms": ((marcos,), {}, [yes], "marcos"),
        "one_of_several": (
            (marcos, nuria),
            {},
            [{"name": "Marcos"}, {"name": "Marcos", **yes}],
            "marcos",
        ),
        # The first profile's handle is derived from the shared name: the case the
        # name path cannot answer and the handle path has to.
        "same_display_name_first": (
            (marcos, twin),
            {},
            [{"handle": "marcos"}, {"handle": "marcos", **yes}],
            "marcos",
        ),
        "same_display_name_second": (
            (marcos, twin),
            {},
            [{"handle": "marcos-b"}, {"handle": "marcos-b", **yes}],
            "marcos-b",
        ),
    }
    calls: dict[str, int] = {}
    slowest = 0.0
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="integral-t207-") as tmp:
        for label, (roster, first, answers, expected) in arrivals.items():
            root = Path(tmp) / label / "profiles"
            for index, (handle, display) in enumerate(roster):
                # Twins started on different days: the day is what tells them apart.
                create_profile(
                    root,
                    display,
                    language="en",
                    handle=handle,
                    now=now - timedelta(days=30 + index),
                )
                SessionStore(ProfileStore(root, handle)).record(
                    at="2026-09-13T09:00:00+00:00", current_step="history"
                )
            started = time.monotonic()
            used, opened = drive(root, answers, now, first=first)
            slowest = max(slowest, time.monotonic() - started)
            calls[label] = used
            if "3 weeks ago" not in opened.say:
                failures.append(f"{label}: the opening never said how long ago")
            if opened.handle != expected:
                failures.append(f"{label}: opened {opened.handle!r}, expected {expected!r}")
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
        parser.add_argument("--name", help="the name the candidate gave (display names only)")
        parser.add_argument(
            "--handle", help="a handle, only after a name collision (handles only, exact)"
        )
        parser.add_argument("--confirmed", action="store_true", help="the candidate said yes")
        parser.add_argument("--root", type=Path, help="profiles root (default: $INTEGRAL_HOME)")
        parser.add_argument(
            "--include-fiction", action="store_true", help="test mode: reach simulated candidates"
        )
        args = parser.parse_args(argv[2:])
        root = args.root or default_profiles_root()
        opened = run(
            root,
            name=args.name,
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
