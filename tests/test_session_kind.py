"""T137 — `session_kind()` tells a candidate session apart from an engineering one.

Named cases, each a real constructed session tree on disk, each run through
`session_kind()` (or `resolve_session_kind()`, for the one case that is about
environment resolution rather than tree contents) and asked for a verdict —
never a test that inspects this module's or `session_kind.py`'s own source.
T121 and T136 are the standing reason: a checker that greps source for the
right shape is defeated by comments and by an unused string holding every
pattern it looks for, so the only test that means anything here is one that
actually calls the function.

The four cases T137's own task file names are covered first, each in its own
test; the rest pin real ambiguous cases the task's text raises but does not
spell out — the "candidate session is never filed as a test" guarantee, and
the cross-session leak `identity.read_active_handle` already guards against
for handles, which `session_kind()` must not reintroduce for ledgers.

Three more (2026-09-19) came from an independent second reader's review of the
first version of this file, and are exactly the shape CLAUDE.md's own "second
reader" section describes — a fixture whose execution path never arrives:
`test_ledger_and_fiction_profile_is_a_test_session` looked like it combined a
resolved handle with a fiction-marked profile and never did, because it never
called `write_active_handle`. F2 and F3 below are the two combinations that
were actually untested; F4 is a corrupt-ledger case the reviewer found
crashed `session_kind()` instead of returning a `Verdict`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from integral.identity import ProfileStore, create_profile, write_active_handle
from integral.session_kind import (
    read_recorded_kind,
    record_session_kind,
    resolve_session_kind,
    session_kind,
)
from integral.state_home import profiles_root
from integral.test_mode import MetaChannel, create_simulated_profile, ledger_path

# ---------------------------------------------------------------------------
# the four cases T137's task file names


def test_resolved_handle_with_no_test_mode_ledger_is_a_candidate(tmp_path: Path) -> None:
    """Case 1. A plainly real, identified candidate — no ledger, no fiction mark."""
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    write_active_handle(root, identity.handle, session_id="sess-1")

    verdict = session_kind(root, session_id="sess-1")

    assert verdict.kind == "candidate"
    assert verdict.signal == "resolved_handle"
    assert verdict.handle == "ada"


def test_ledger_and_fiction_profile_is_a_test_session(tmp_path: Path) -> None:
    """Case 2, as the task file states it: a simulated ledger, and a profile
    independently marked fiction. **This alone does not exercise the fiction
    signal through `session_kind()`** — no handle is ever resolved here (only
    `create_simulated_profile`/`MetaChannel` run, never `write_active_handle`),
    so `fiction` is never even computed; only `simulated_by_ledger` decides the
    verdict. The profile's own `fiction: true` is asserted directly below, as a
    fact about the fixture, not as proof the function read it — the two tests
    right after this one are what pin the handle+test-mode combinations this
    one only looks like it covers (second reader F2/F3, 2026-09-19).
    """
    root = tmp_path / "profiles"
    identity = create_simulated_profile(root, "Marta Ruiz", handle="marta-probe")
    MetaChannel(root, session_id="sess-2", simulated=True, handle=identity.handle)

    verdict = session_kind(root, session_id="sess-2")

    assert verdict.kind == "test"
    assert verdict.signal == "simulated_ledger"
    assert ProfileStore(root, identity.handle).identity().fiction is True


def test_resolved_handle_and_fiction_profile_with_no_ledger_is_a_test_session(
    tmp_path: Path,
) -> None:
    """Second reader F2. `test_ledger_and_fiction_profile_is_a_test_session`
    never resolves a handle, so it cannot tell a working `fiction` check apart
    from a deleted one — proved by deleting that branch and watching every
    shipped test still pass. This case resolves a real handle whose *own*
    profile is fiction-marked, with no ledger anywhere, so the fiction check is
    the only thing that can produce "test" here.
    """
    root = tmp_path / "profiles"
    identity = create_simulated_profile(root, "Invented Via Handle", handle="invented-handle")
    write_active_handle(root, identity.handle, session_id="sess-2b")

    verdict = session_kind(root, session_id="sess-2b")

    assert verdict.kind == "test"
    assert verdict.signal == "fiction_profile"


def test_resolved_handle_and_simulated_ledger_together_is_a_test_session(tmp_path: Path) -> None:
    """Second reader F3. Nothing else combines "a session resolved a real,
    non-fiction handle" with "that same session's ledger says simulated=true"
    — proved by moving the handle check above the ledger/fiction checks and
    watching every shipped test still pass. The ledger must still win: identify
    running first must not be able to promote a test session to "candidate".
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Handle Then Test", handle="handle-then-test", language="en")
    write_active_handle(root, identity.handle, session_id="sess-2c")
    MetaChannel(root, session_id="sess-2c", simulated=True, handle=identity.handle)

    verdict = session_kind(root, session_id="sess-2c")

    assert verdict.kind == "test"
    assert verdict.signal == "simulated_ledger"


def test_bare_repository_checkout_is_engineering(tmp_path: Path) -> None:
    """Case 3. A real git work tree with no candidate store configured — what an
    engineering session's environment actually looks like, not a stand-in for
    it: `$INTEGRAL_HOME` points inside the clone and `state_home` refuses to
    resolve a store there without `--dev`. This is `resolve_session_kind`'s
    own path, deliberately exercised independently of `_case_bare_repository_
    checkout` in `session_kind.py` — two constructions of the same scenario
    rather than one shared fixture both the gate and this test would trust
    equally if it were wrong.
    """
    work_tree = tmp_path / "clone"
    work_tree.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(work_tree)], cwd=work_tree, check=True, capture_output=True
    )
    env = {"INTEGRAL_HOME": str(work_tree / "state"), "HOME": str(tmp_path / "unused-home")}

    verdict = resolve_session_kind(session_id="sess-3", env=env)

    assert verdict.kind == "engineering"
    assert verdict.signal == "state_home_refused"


def test_identified_nobody_and_wrote_no_profile_defaults_to_engineering(tmp_path: Path) -> None:
    """Case 4 — T137's crux case. A profiles root that exists and resolves fine,
    with nothing under it: no `.active.json`, no `.test-mode/`, no handle
    directory. This is *exactly* what a candidate session mid-step-0 also
    looks like, and the whole point of T137 is that the two must not be told
    apart by guessing "probably a candidate" — fail-open means this reads
    engineering, at the cost of one confirmation prompt for the rare session
    that really is a candidate about to finish step 0.
    """
    root = tmp_path / "profiles"
    root.mkdir(parents=True)

    verdict = session_kind(root, session_id="sess-4")

    assert verdict.kind == "engineering"
    assert verdict.signal == "no_signal"


# ---------------------------------------------------------------------------
# further real cases the task's text raises but does not spell out


def test_nonexistent_profiles_root_also_defaults_to_engineering(tmp_path: Path) -> None:
    """A `root` that was never created at all — the simplest input a caller can
    hand in, and a third, genuinely distinct shape of 'nothing here' from both
    case 3 (a resolver refusal) and case 4 (an empty-but-real directory):
    `session_kind()` never even touches the filesystem to create it, so this
    pins that every read inside stays tolerant of a missing path.
    """
    root = tmp_path / "never-created" / "profiles"

    verdict = session_kind(root, session_id="sess-5")

    assert verdict.kind == "engineering"
    assert verdict.signal == "no_signal"


def test_a_corrupt_ledger_does_not_crash_and_resolves_as_if_absent(tmp_path: Path) -> None:
    """Second reader F4. `NoteLedger.raw_rows` raises `test_mode.MetaNoteError`
    on an unreadable line, and nothing caught it — a session whose ledger got
    corrupted (a partial write, a crash mid-append) crashed `session_kind()`
    instead of returning a `Verdict`, breaking the "every read here already
    tolerates a missing file" promise the module's own docstring makes. A
    resolved, non-fiction handle sits next to the corrupt ledger so the
    assertion is not merely "did not raise" but "resolves exactly as it would
    if the unreadable ledger were not there at all".
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Corrupt Ledger", handle="corrupt-ledger", language="en")
    write_active_handle(root, identity.handle, session_id="sess-corrupt")
    corrupt = ledger_path(root, "sess-corrupt")
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("{not valid json\n", encoding="utf-8")

    verdict = session_kind(root, session_id="sess-corrupt")

    assert verdict.kind == "candidate"
    assert verdict.signal == "resolved_handle"


def test_a_real_candidate_under_test_mode_without_fiction_is_still_a_candidate(
    tmp_path: Path,
) -> None:
    """T137's second guarantee, pinned directly: 'a candidate session is never
    filed as a test'. Test mode may run *over* a real, non-invented candidate
    (test_mode.py: 'the way to improve the thirteen step skills is to run a
    real session and notice, in the moment' — nothing there requires the
    candidate to be fictional). A ledger existing must not, by itself, demote
    a real person to 'test' — only `simulated: true` on that ledger, or
    `fiction: true` on the profile, may do that, and neither is present here.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Grace Hopper", handle="grace", language="en")
    write_active_handle(root, identity.handle, session_id="sess-6")
    MetaChannel(root, session_id="sess-6", simulated=False, handle=identity.handle)

    verdict = session_kind(root, session_id="sess-6")

    assert verdict.kind == "candidate"
    assert verdict.signal == "resolved_handle"


def test_a_test_mode_ledger_from_a_different_session_does_not_leak_into_this_one(
    tmp_path: Path,
) -> None:
    """The cross-session hazard `identity.read_active_handle` already refuses for
    handles ('the next session … inherits whoever was identified last') must
    not reappear here for ledgers. Session B ran a simulated test candidate;
    session A, asking about itself, has no ledger and no handle of its own —
    it must read as ambiguous-so-engineering, never borrow B's 'test' verdict.
    """
    root = tmp_path / "profiles"
    identity = create_simulated_profile(root, "Someone Else", handle="someone-else")
    MetaChannel(root, session_id="session-b", simulated=True, handle=identity.handle)

    verdict = session_kind(root, session_id="session-a")

    assert verdict.kind == "engineering"
    assert verdict.signal == "no_signal"


def test_a_resolved_handle_from_a_different_session_does_not_leak_into_this_one(
    tmp_path: Path,
) -> None:
    """Same hazard, for signal 3 instead of signal 1: session B identified a
    real candidate; session A must not inherit that binding just because it
    shares a profiles root — this is `read_active_handle`'s own guarantee,
    pinned again here because `session_kind()` is a second caller of it and a
    second place the guarantee could quietly stop being reused correctly.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Someone Else", handle="someone-else", language="en")
    write_active_handle(root, identity.handle, session_id="session-b")

    verdict = session_kind(root, session_id="session-a")

    assert verdict.kind == "engineering"
    assert verdict.signal == "no_signal"


# ---------------------------------------------------------------------------
# "one place that records the answer"


def test_record_session_kind_round_trips_through_read_recorded_kind(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    write_active_handle(root, identity.handle, session_id="sess-record")
    verdict = session_kind(root, session_id="sess-record")

    record_session_kind(root, verdict, session_id="sess-record")

    assert read_recorded_kind(root, session_id="sess-record") == "candidate"


def test_a_recorded_verdict_is_not_read_back_for_a_different_session(tmp_path: Path) -> None:
    """Same binding discipline as the verdict itself: a marker recorded for one
    session must read as absent, not as an answer, to any other session id —
    otherwise the marker becomes exactly the standing, unbound authorisation
    `identity.read_active_handle`'s docstring warns a shared machine cannot
    afford.
    """
    root = tmp_path / "profiles"
    root.mkdir(parents=True)
    verdict = session_kind(root, session_id="sess-a")

    record_session_kind(root, verdict, session_id="sess-a")

    assert read_recorded_kind(root, session_id="sess-b") is None


def test_resolve_session_kind_records_only_when_asked(tmp_path: Path) -> None:
    """`record=False` (the default) must not write the marker — a caller that
    only wants to know the kind, such as a diagnostic run, must not have a
    side effect it never asked for."""
    root = tmp_path / "profiles"
    root.mkdir(parents=True)
    env = {"INTEGRAL_HOME": str(tmp_path / "state"), "HOME": str(tmp_path / "unused-home")}

    resolve_session_kind(session_id="sess-diagnostic", env=env)

    resolved_root = profiles_root(env=env)
    assert read_recorded_kind(resolved_root, session_id="sess-diagnostic") is None
