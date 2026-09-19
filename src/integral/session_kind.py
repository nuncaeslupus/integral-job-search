"""T137 — telling a candidate session apart from a session working on the repo.

A test-mode note captured 2026-09-06 at step `identify` named the gap plainly:
*"How to differentiate between a real live user session and a coding session
for the repo?"* Nothing answered it. Three facts exist and none of them were
joined: a resolved handle (`identity.read_active_handle`, bound to
`profiles/.active.json`), a test-mode ledger under `<profiles root>/.test-mode/`
(`integral.test_mode`), and the `fiction: true` mark a simulated profile
carries. A session working on the repository has **none** of the three — and
so does a candidate session that has not identified anyone yet, which is
exactly step 0's normal, unremarkable state. The two are indistinguishable by
construction, and the cost was not theoretical: one session ran the whole
thirteen-step candidate process for a real person *and* merged six pull
requests, with nothing but the operator's own judgement and manual `[[...]]`
markers keeping the two apart.

`session_kind()` is the join. Given a profiles root and the session that is
asking, it returns one of `"candidate"`, `"test"`, or `"engineering"` — never a
bare guess, always a `Verdict` that names which signal decided it, the same
discipline `identity.Decision` and `session.Resumption` already hold to
elsewhere in this package. `record_session_kind`/`read_recorded_kind` are the
"one place that records the answer": a roster-level marker, bound to the
session that wrote it, in the same shape `identity.write_active_handle` /
`read_active_handle` already use for exactly the same reason — a marker that
does not say *which session* produced it is a standing answer for whoever
reads it next, on a shared machine, which is the failure `read_active_handle`
was built to refuse for handles and this module refuses for kinds.

**Weighted fail-open, on purpose.** Calling an engineering session a candidate
session is the verdict that lets a write land in somebody's real profile tree
by accident; the reverse costs an extra confirmation prompt. So every
ambiguous case here — no signal at all, which is what a bare repository
checkout *and* a candidate session that has not reached step 0's end both look
like — resolves to `"engineering"`, not `"candidate"`. That default is the
whole point of this module; the three signals only get to override it when one
of them actually fires.

**Measured by running, not by reading.** T121 and T136 are the standing
lesson here: a checker that greps source for the right shape is defeated by
comments and by an unused string holding every pattern it looks for. So the
gate below builds real, named session trees on disk — a resolved handle and no
ledger, a simulated ledger and a fiction profile, a git work tree with no
candidate store configured, a profiles root that exists and says nothing yet —
and calls `session_kind()` against each rather than inspecting this file's own
text.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from integral.identity import (
    Handle,
    IdentityError,
    ProfileLeak,
    ProfileStore,
    create_profile,
    read_active_handle,
    write_active_handle,
)
from integral.state_home import StateHomeRefused, profiles_root
from integral.test_mode import (
    MetaChannel,
    MetaNoteError,
    NoteLedger,
    create_simulated_profile,
    ledger_path,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T137.json"

# What a session is, for the purpose of "may it write into a candidate's tree"
# and "should this be filed as a test". Three, not two: the motivating note
# asks for candidate-vs-engineering, but the task itself adds a second
# guarantee — "a candidate session is never filed as a test" — which needs its
# own value rather than being folded into "candidate".
SessionKind = Literal["engineering", "candidate", "test"]

# Which fact produced the verdict — mirrors `session.Rule`: the reason a
# caller gets back is the reason the function actually used, not a
# description reconstructed after the fact from the kind alone.
Signal = Literal[
    "simulated_ledger", "fiction_profile", "resolved_handle", "state_home_refused", "no_signal"
]

#: The roster-level marker `record_session_kind` writes and `read_recorded_kind`
#: reads — the "one place" T137 asks for, named and shaped after
#: `identity.ACTIVE_FILE` on purpose: one JSON object, bound to the session
#: that wrote it, sitting beside `.active.json` at the roster level rather than
#: under any one handle's tree (an engineering session has no handle to hold it
#: under, and that is precisely the case this file has to be able to name).
SESSION_KIND_FILE = ".session-kind.json"


@dataclass(frozen=True)
class Verdict:
    """`session_kind()`'s answer: which kind of session this is, and why.

    Every branch names a `signal` and a `reason` — there is no code path that
    returns a kind without one, the same rule `identity.Decision` and
    `session.Resumption` already hold to elsewhere in this package for exactly
    the same reason: a verdict nobody can explain is indistinguishable from a
    coin flip to whoever reads it later.
    """

    kind: SessionKind
    signal: Signal
    reason: str
    handle: Handle | None = None


def session_kind(root: Path, *, session_id: str | None = None) -> Verdict:
    """Which kind of session this is, joining the three signals T137 names.

    `root` is a profiles root already resolved by the caller — this function
    does not itself touch `$INTEGRAL_HOME` or catch `StateHomeRefused`, the
    same split `identity.guard_decision` keeps from `identity.hook_main`: the
    pure judgement is one function, resolving the ambient environment is
    another (`resolve_session_kind`, below). `root` need not exist on disk —
    every read here already tolerates a missing file or directory, because "no
    store here at all" is one of the four shapes this module has to classify
    correctly, not an error case to guard against.

    The checks, in the order they are applied:

    1. **either test-mode signal — a ledger for this exact session saying
       `simulated: true` (`test_mode.SessionRow.simulated`), or the resolved
       handle's own profile carrying `fiction: true`** — one guard, checked
       together and ahead of anything else, so that **a test session is never
       filed as a candidate** exactly as reliably as its own mirror guarantee
       ("a candidate session is never filed as a test"). That symmetry is why
       the two cannot be checked as a later, lower-priority pair of `elif`s
       hanging off "no handle yet": a simulated candidate's ledger is opened
       (`MetaChannel.__init__`) before `create_simulated_profile` ever runs, so
       a simulated session with no handle resolved must still read `"test"`
       (`test_mode.probe_notes_reaching_evidence` is T137's own precedent for
       this — it never calls `write_active_handle` at all) — and a session
       whose `identify` step *did* run first, resolving a handle before either
       test-mode fact was recorded, must read exactly the same way. Whichever
       of the two fired is named as the `signal`; a ledger corrupted enough to
       be unreadable (`test_mode.MetaNoteError`) is treated as "no ledger
       signal" rather than raised, the same tolerance `read_active_handle`
       already gives a corrupt `.active.json`.
    2. **this session resolved a handle at all** (`identity.read_active_handle`,
       which is already bound to `session_id` the same way this function is) —
       `"candidate"`, reached only once neither test-mode signal fired.
    3. **none of the above** — `"engineering"`. This is the fail-open default
       T137 exists to install: a bare repository checkout and a candidate
       session that has not reached the end of step 0 look identical by these
       signals, and the cheap direction to be wrong in is calling the real
       candidate "engineering" for one extra confirmation prompt, not calling
       the engineering session "candidate" and letting a write through.

    The ledger and handle signals are scoped to `session_id` on purpose,
    reusing `read_active_handle`'s own binding rather than re-deriving it: a
    *different* session's resolved handle or open ledger existing somewhere
    else under the same profiles root must never leak into this session's
    verdict, which is the identical cross-session hazard `read_active_handle`'s
    own docstring names for `.active.json` ("the next session … inherits
    whoever was identified last").
    """
    root = Path(root)
    handle = read_active_handle(root, session_id=session_id)

    simulated_by_ledger = False
    if session_id:
        try:
            header = NoteLedger(ledger_path(root, session_id)).header()
        except (MetaNoteError, ValidationError):
            # A ledger this corrupt — unparseable JSON (MetaNoteError) or
            # JSON that fails the row schema (ValidationError) — names no
            # session state reliably. Treated as absent, not as a crash:
            # `session_kind()` promises a `Verdict` for every reachable
            # tree, corrupt files included (CodeRabbit, PR #517).
            header = None
        simulated_by_ledger = bool(header is not None and header.simulated)

    fiction = False
    if handle is not None:
        try:
            fiction = ProfileStore(root, handle).identity().fiction
        except (IdentityError, ProfileLeak):
            # A handle `.active.json` names but whose profile cannot be read
            # names nobody real either — treated as "not fiction", not as an
            # error, so the fall-through below still gets to weigh in.
            fiction = False

    # Either test-mode signal wins over a merely-resolved handle, checked as
    # one guard rather than two sequential `if`s a later edit could quietly
    # separate — see the docstring's point 1 for why the two must never be
    # allowed to drift into different priority tiers.
    if simulated_by_ledger or fiction:
        signal: Signal = "simulated_ledger" if simulated_by_ledger else "fiction_profile"
        reason = (
            "this session's test-mode ledger opened with simulated=true — an "
            "invented candidate, exercised to test a step (S11)"
            if simulated_by_ledger
            else f"{handle!r}'s profile is marked fiction: true — a simulated "
            "candidate, not a real one"
        )
        return Verdict("test", signal, reason, handle=handle)
    if handle is not None:
        return Verdict(
            "candidate",
            "resolved_handle",
            f"this session identified {handle!r}, and neither the test-mode "
            "ledger nor the profile marks it as simulated",
            handle=handle,
        )
    return Verdict(
        "engineering",
        "no_signal",
        "none of the three signals fired for this session — defaulting to "
        "engineering, the fail-open direction: calling a real candidate "
        "session engineering costs one confirmation prompt, and the reverse "
        "is what lets a write reach somebody's profile tree by accident",
    )


def resolve_session_kind(
    *,
    session_id: str | None,
    env: Mapping[str, str] | None = None,
    dev: bool | None = None,
    record: bool = False,
    now: datetime | None = None,
) -> Verdict:
    """`session_kind()` against a *resolved* store, the way a live caller uses it.

    Resolves the root through `integral.state_home`, never a path built by
    hand — the same resolver every checkpoint script and `identity.
    default_profiles_root` already go through — and treats its refusal as what
    it is: the single clearest engineering signal this codebase has.
    `StateHomeRefused` means the caller is standing inside a git work tree with
    no `--dev` escape (T51, `docs/distribution.md` §2), and a real candidate
    session can never be true of that: the only two ways out of a work tree are
    the explicit `--dev` act, or not being in one. So a refusal here is not an
    error to route around — it is `"engineering"` on the spot, no further
    signal needed. `record=True` also writes the verdict via
    `record_session_kind`, when a root was actually resolved to write it to.
    """
    try:
        root = profiles_root(env=env, dev=dev)
    except StateHomeRefused as exc:
        return Verdict(
            "engineering",
            "state_home_refused",
            f"no candidate store here — {exc}",
        )
    verdict = session_kind(root, session_id=session_id)
    if record:
        if not session_id:
            raise ValueError(
                "record=True requires a session_id — there is nothing to bind the record to"
            )
        record_session_kind(root, verdict, session_id=session_id, now=now)
    return verdict


def record_session_kind(
    root: Path, verdict: Verdict, *, session_id: str, now: datetime | None = None
) -> Path:
    """Write `session_kind()`'s verdict to the one place other code reads it back.

    Same shape as `identity.write_active_handle` on purpose — a single
    roster-level JSON marker, overwritten on every call, bound to the session
    that produced it. `read_recorded_kind` refuses a marker whose `session_id`
    does not match, for the identical reason `read_active_handle` refuses one:
    a marker with no binding is a standing answer for the next session on a
    shared machine, which is exactly the ambiguity this module exists to close.
    """
    if not session_id:
        raise ValueError("a session-kind verdict must be bound to a session")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / SESSION_KIND_FILE
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
    payload = {
        "session_id": session_id,
        "kind": verdict.kind,
        "signal": verdict.signal,
        "reason": verdict.reason,
        "handle": verdict.handle,
        "recorded_at": stamp,
    }
    marker.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return marker


def read_recorded_kind(root: Path, *, session_id: str) -> SessionKind | None:
    """The kind last recorded for this session, or `None` — never another session's.

    Mirrors `identity.read_active_handle` exactly, marker binding included: a
    recorded kind whose `session_id` does not match this one is treated as
    though nothing had been recorded, rather than handed over as though it
    applied here.
    """
    marker = Path(root) / SESSION_KIND_FILE
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("session_id") != session_id:
        return None
    kind = payload.get("kind")
    return kind if kind in ("engineering", "candidate", "test") else None


# ---------------------------------------------------------------------------
# the gate
#
# Not declared as a `repo_gate.EVIDENCE_SOURCES` registrant (T150), and that is
# a considered omission rather than an oversight: that registry is for a
# census over *this repository's own tree* — `naming.measure`/`arsenal_source.
# measure` each count a population of files, and T150's mutation moves them by
# really adding or archiving one (`repo_gate.EvidenceSource.measure(repo_root,
# **population)`). `measure` below counts misclassifications over constructed
# temp directories that have nothing to do with `repo_root` — neither tree
# mutation would ever change its result, which is exactly the shape
# `floor_sweep.py` already declines to register `floors_swept` over, for the
# identical reason, stated there beside its own such omission: a source
# `repo_gate.measure_evidence_stability` cannot move is reported as "moved by
# no mutation" and turns *that* gate `unmeasured` over a registrant that was
# never going to move. `status/evidence/T137.json` is still produced and
# drift-checked every run — through T85's broader, separate mechanism
# (`repo_gate.evidence_writing_modules`, which finds any module that
# constructs a `status/evidence/*.json` path, this one included, and needs no
# registration at all).


@dataclass(frozen=True)
class _Case:
    """One named, constructed session tree, and the kind it must resolve to."""

    name: str
    expected: SessionKind
    run: Callable[[Path], Verdict]
    justification: str


def _case_resolved_handle_no_ledger(tmp: Path) -> Verdict:
    root = tmp / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    write_active_handle(root, identity.handle, session_id="gate-candidate")
    return session_kind(root, session_id="gate-candidate")


def _case_ledger_and_fiction_profile(tmp: Path) -> Verdict:
    root = tmp / "profiles"
    identity = create_simulated_profile(root, "Invented Person", handle="invented")
    MetaChannel(root, session_id="gate-test", simulated=True, handle=identity.handle)
    return session_kind(root, session_id="gate-test")


def _case_bare_repository_checkout(tmp: Path) -> Verdict:
    """A real git work tree, `$INTEGRAL_HOME` unset — what "engineering" looks
    like from `state_home`'s own side, not a stand-in for it (mirrors
    `state_home.probe_refusals`'s own construction)."""
    work_tree = tmp / "clone"
    work_tree.mkdir()
    subprocess.run(
        ["git", "init", "-q", str(work_tree)], cwd=work_tree, check=True, capture_output=True
    )
    env = {"INTEGRAL_HOME": str(work_tree / "state"), "HOME": str(tmp / "unused-home")}
    return resolve_session_kind(session_id="gate-engineering", env=env)


def _case_identified_nobody_wrote_no_profile(tmp: Path) -> Verdict:
    root = tmp / "profiles"
    root.mkdir(parents=True)
    return session_kind(root, session_id="gate-ambiguous")


def _case_handle_and_fiction_profile_no_ledger(tmp: Path) -> Verdict:
    """A resolved handle whose own profile is fiction-marked, and no ledger at
    all — the combination `_case_ledger_and_fiction_profile` reads as covering
    but does not, since that case never resolves a handle. Second reader's F2
    finding: a `signal="fiction_profile"` misclassification here is invisible
    to every other case (deleting the whole branch that produces it left the
    other five untouched)."""
    root = tmp / "profiles"
    identity = create_simulated_profile(root, "Invented Via Handle", handle="invented-handle")
    write_active_handle(root, identity.handle, session_id="gate-fiction-via-handle")
    return session_kind(root, session_id="gate-fiction-via-handle")


def _case_handle_and_simulated_ledger_together(tmp: Path) -> Verdict:
    """A session that resolved a real (non-fiction) handle *and* opened a
    simulated test-mode ledger — second reader's F3 finding: the ledger signal
    must still win over the resolved handle, and nothing in the other five
    cases combines the two, so a regression that checked the handle first
    would have passed every one of them."""
    root = tmp / "profiles"
    identity = create_profile(root, "Handle Then Test", handle="handle-then-test", language="en")
    write_active_handle(root, identity.handle, session_id="gate-handle-and-ledger")
    MetaChannel(root, session_id="gate-handle-and-ledger", simulated=True, handle=identity.handle)
    return session_kind(root, session_id="gate-handle-and-ledger")


#: T137's own four cases, plus two the second reader's F2/F3 findings added
#: (2026-09-19): the ledger+fiction case above never resolves a handle, so
#: nothing before these two ever exercised "resolved handle" combined with
#: either test-mode signal — precisely the combination that must still read
#: `"test"`, not `"candidate"`. `MINIMUM_SESSION_KIND_CASES` below is this
#: tuple's exact length — zero slack, T35's `MINIMUM_PROBES` precedent for the
#: same reason stated there: a floor sitting below its own population lets the
#: first deleted case breach nothing.
_CASES: tuple[_Case, ...] = (
    _Case(
        "resolved_handle_no_ledger",
        "candidate",
        _case_resolved_handle_no_ledger,
        "a plainly real, identified candidate with no test-mode signal at all",
    ),
    _Case(
        "ledger_and_fiction_profile",
        "test",
        _case_ledger_and_fiction_profile,
        "the ledger's own simulated=true is what this case actually exercises "
        "(no handle is ever resolved here, so `fiction` is never read) — the "
        "profile is independently fiction-marked too, but that combination is "
        "pinned on its own by handle_and_fiction_profile_no_ledger, below",
    ),
    _Case(
        "bare_repository_checkout",
        "engineering",
        _case_bare_repository_checkout,
        "no candidate store configured at all — fail-open default applies, "
        "and here it is also the only answer that could be right",
    ),
    _Case(
        "identified_nobody_wrote_no_profile",
        "engineering",
        _case_identified_nobody_wrote_no_profile,
        "T137's crux case: a resolvable, empty profiles root is what an "
        "engineering session *and* a candidate session mid-step-0 both look "
        "like — fail-open means this must read engineering, not candidate",
    ),
    _Case(
        "handle_and_fiction_profile_no_ledger",
        "test",
        _case_handle_and_fiction_profile_no_ledger,
        "second reader F2: a resolved handle must not shadow its own "
        "profile's fiction: true — 'test' wins even with no ledger at all",
    ),
    _Case(
        "handle_and_simulated_ledger_together",
        "test",
        _case_handle_and_simulated_ledger_together,
        "second reader F3: a resolved, non-fiction handle plus a simulated "
        "ledger must still read 'test' — the ledger outranks the handle",
    ),
)

#: Zero slack against `len(_CASES)` — see the tuple's own comment.
MINIMUM_SESSION_KIND_CASES = 6


def run_cases(cases: Sequence[_Case] = _CASES) -> tuple[int, list[str], int]:
    """Run every named case in its own temp directory; report what it got wrong."""
    defects: list[str] = []
    checked = 0
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="integral-session-kind-") as tmp:
            verdict = case.run(Path(tmp))
        checked += 1
        if verdict.kind != case.expected:
            defects.append(
                f"{case.name}: expected {case.expected!r} ({case.justification}), "
                f"got {verdict.kind!r} via {verdict.signal} ({verdict.reason})"
            )
    return len(defects), defects, checked


def measure() -> dict[str, Any]:
    """T137's gate reading: `session_kind_misclassifications`, as written to evidence."""
    misclassifications, defects, checked = run_cases()
    measured: dict[str, Any] = {
        "session_kind_misclassifications": misclassifications,
        "session_kind_cases": checked,
        "session_kind_defects": defects,
        "gate_status": "measured",
    }
    if checked < MINIMUM_SESSION_KIND_CASES:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {checked} case(s) ran (floor {MINIMUM_SESSION_KIND_CASES}) — "
            "a zero over too few cases says nothing about telling the kinds apart"
        ]
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T137.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Two entry points, one module.

    python -m integral.session_kind                     -> T137's gate, evidence written
    python -m integral.session_kind --record ID [--dev]  -> classify + persist the live verdict
    """
    parser = argparse.ArgumentParser(
        description="session_kind — candidate, test, or engineering session (T137)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T137.json)",
    )
    parser.add_argument(
        "--record",
        metavar="SESSION_ID",
        help="classify this session against the ambient profiles root, "
        "record the verdict there, and print it",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="the state_home escape (INTEGRAL_DEV=1): resolve a store even inside a git work tree",
    )
    args = parser.parse_args(argv[1:])

    if args.record:
        verdict = resolve_session_kind(
            session_id=args.record, dev=True if args.dev else None, record=True
        )
        print(
            json.dumps(
                {
                    "kind": verdict.kind,
                    "signal": verdict.signal,
                    "reason": verdict.reason,
                    "handle": verdict.handle,
                },
                ensure_ascii=False,
            )
        )
        return 0

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for defect in measured["session_kind_defects"]:
        print(f"session_kind: {defect}", file=sys.stderr)
    if measured["gate_status"] == "unmeasured":
        for reason in measured.get("reasons", ()):
            print(reason, file=sys.stderr)
        return 3
    return 1 if measured["session_kind_misclassifications"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
