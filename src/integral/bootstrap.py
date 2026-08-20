"""First-run bootstrap: the tool installs its own dependencies, and says so (T52).

`docs/distribution.md` §1 settles the install: `git clone`, `cd`, `claude`, and
then the candidate talks. A clone delivers both halves of the tool — the
thirteen step skills under `.claude/skills/` and the checkpoint code under
`src/` — but not the *installed* dependencies. This module closes that gap.

Two layers, because either alone leaves a hole:

1. a **`SessionStart` hook** that checks whether the environment is present and
   current and syncs when it is not — silent when there is nothing to do, so a
   returning candidate pays nothing for it;
2. a **check inside step 0**, before the first call into the code, for the
   session whose hook did not fire (a surface that runs no hooks, a clone opened
   some other way). Both call the same function, so the bootstrap is idempotent
   by construction rather than by care.

**This module imports nothing outside the standard library, and that is the
whole point.** It exists to prevent an `ImportError` on `pydantic`; a bootstrap
that imported `pydantic` to describe its own report would fail in exactly the
situation it was written for. `dataclasses` where the rest of this package uses
Pydantic models, `tomllib` to read the dependency list, `importlib.metadata` to
see what is installed. `test_bootstrap_imports_without_third_party_dependencies`
holds the line, because the failure is invisible in a developed checkout where
everything happens to be installed already.

**The candidate is told the first time, and only the first time.** A tool that
silently runs a package manager on somebody's machine is not one they should
trust with their working history — and a tool that announces it at every session
start is one they stop reading. The marker recording that first announcement
lives in the candidate store (`integral.state_home`), never in the clone: it is
per-machine state about a person's environment, and T51's rule is that such
things do not live in a repository.

`uv` absent is a reported outcome, never a raised one: the fallback is
`python -m venv` plus `pip`, and if there is no usable interpreter either the
report says so in a sentence a person can act on. Failing at a traceback is what
this module forbids — a candidate cannot be expected to read one.

The gate is `unbootstrapped_first_runs == 0`: over every simulated way a first
run can arrive, none reaches the code with dependencies missing and nothing said.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T52.json"

#: Where the "we have told this person already" marker lives — in the candidate
#: store, never in the clone (T51).
MARKER_NAME = "bootstrap.json"

#: The one-line installer offered when `uv` is absent, quoted rather than run.
UV_INSTALLER = "curl -LsSf https://astral.sh/uv/install.sh | sh"

# PEP 508: the distribution name is everything before the first version
# specifier, extra marker, or environment marker; the rest is the specifier.
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$")
# Only the ordering operators this project actually declares are interpreted.
# Anything else is treated as "cannot verify", which means presence alone
# satisfies it — stated here rather than discovered later.
_FLOOR = re.compile(r"(>=|==|~=)\s*([0-9][0-9A-Za-z.\-]*)")

Runner = Callable[[Sequence[str], Path], "CommandResult"]
Announcer = Callable[[str], None]


class BootstrapError(Exception):
    """The bootstrap could not even be described. Raised only for a broken clone."""


@dataclass(frozen=True)
class CommandResult:
    """What running the install command did — enough to report, not to guess."""

    argv: tuple[str, ...]
    returncode: int
    stderr: str = ""


@dataclass(frozen=True)
class Report:
    """One bootstrap attempt, as a candidate-facing outcome rather than a status code.

    `action` is the whole answer:

    * `current`     — the environment is present and current; nothing ran, nothing said.
    * `installed`   — dependencies were missing and the install command succeeded.
    * `failed`      — the install command ran and failed; `detail` says how.
    * `unavailable` — no package manager to run; `detail` carries the one-line fix.
    * `in-progress` — another session holds the install lock; it is doing this.

    `reached_the_code_unbootstrapped` is the gate's question, and it is
    deliberately not the same as "everything went well": a run that could not
    install but *said so clearly* has not failed this gate, because the
    candidate is not staring at an `ImportError`. The failure this forbids is
    silence.
    """

    action: str
    entry_point: str
    missing: tuple[str, ...] = ()
    manager: str | None = None
    command: tuple[str, ...] = ()
    announcement: str | None = None
    detail: str = ""

    @property
    def dependencies_ready(self) -> bool:
        return self.action in {"current", "installed"}

    @property
    def spoke(self) -> bool:
        return bool(self.announcement)

    @property
    def reached_the_code_unbootstrapped(self) -> bool:
        """Missing dependencies, and nothing said about it — the forbidden outcome."""
        return not self.dependencies_ready and not self.spoke


# ---------------------------------------------------------------------------
# what the project declares, and what is actually installed


def declared_requirements(root: Path = _REPO_ROOT) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """`(name, version floor)` per runtime dependency in `pyproject.toml`.

    Read rather than restated: a hardcoded list here would keep reporting a
    clean environment after somebody adds a dependency, which is the same
    self-counting mistake this repo's gates document at length.

    The floor matters. Comparing names alone let an installed `pydantic 1.x`
    satisfy `pydantic>=2.9`, so the environment read as current and the code
    failed downstream anyway — the bootstrap reporting success is worse than
    the ImportError it replaced, because nothing then tries to fix it. An
    empty tuple means "no floor this parser understands", and presence alone
    satisfies it.
    """
    manifest = root / "pyproject.toml"
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapError(f"{manifest} could not be read: {exc}") from exc

    requirements = data.get("project", {}).get("dependencies", [])
    parsed: list[tuple[str, tuple[int, ...]]] = []
    for requirement in requirements:
        match = _REQUIREMENT.match(str(requirement))
        if not match:
            continue
        floor = _FLOOR.search(match.group(2) or "")
        parsed.append((_normalise(match.group(1)), _version(floor.group(2)) if floor else ()))
    return tuple(parsed)


def declared_dependencies(root: Path = _REPO_ROOT) -> tuple[str, ...]:
    """Just the names, for the messages a person reads."""
    return tuple(name for name, _floor in declared_requirements(root))


def _version(text: str) -> tuple[int, ...]:
    """The leading numeric release segment of a version, for ordering.

    `2.9.1rc1` reads as `(2, 9, 1)`: enough to answer "is this at least 2.9",
    which is the only question asked here, without carrying a PEP 440
    implementation into a module that must stay stdlib-only.
    """
    parts: list[int] = []
    for chunk in text.split("."):
        digits = re.match(r"\d+", chunk)
        if digits is None:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def _normalise(name: str) -> str:
    """PEP 503 normalisation — `types-PyYAML` and `types_pyyaml` are one name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def site_packages(root: Path = _REPO_ROOT) -> Path | None:
    """The project venv's `site-packages`, if a venv is there at all."""
    venv = root / ".venv"
    candidates = [*venv.glob("lib/python*/site-packages"), venv / "Lib" / "site-packages"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def missing_dependencies(root: Path = _REPO_ROOT) -> tuple[str, ...]:
    """Declared distributions nothing installed satisfies, in declared order.

    Read out of the venv's own `site-packages` rather than by importing:
    importing works only from inside the environment being checked, and the
    `SessionStart` hook runs outside it.

    "Satisfies" means present *and* at or above the declared floor — a
    too-old distribution is missing as far as this module is concerned, since
    the outcome it produces is the same failed import.
    """
    declared = declared_requirements(root)
    if not declared:
        return ()

    packages = site_packages(root)
    if packages is None:
        return tuple(name for name, _floor in declared)

    installed: dict[str, tuple[int, ...]] = {}
    for dist in importlib.metadata.Distribution.discover(path=[str(packages)]):
        if dist.metadata is None or not dist.metadata["Name"]:
            continue
        installed[_normalise(str(dist.metadata["Name"]))] = _version(
            str(dist.metadata["Version"] or "0")
        )

    missing: list[str] = []
    for name, floor in declared:
        if name not in installed or (floor and installed[name] < floor):
            missing.append(name)
    return tuple(missing)


def environment_is_current(root: Path = _REPO_ROOT) -> bool:
    """Whether every declared dependency is installed in the project venv."""
    return not missing_dependencies(root)


# ---------------------------------------------------------------------------
# how to install, and whether we can


def package_manager(
    which: Callable[[str], str | None] = shutil.which,
    executable: str = sys.executable,
) -> str | None:
    """`uv` if it is on PATH, else `pip` when an interpreter can make a venv, else None.

    `executable` is injectable, and empty means "no interpreter". Reading
    `sys.executable` directly made the "no package manager at all" branch
    unreachable — the interpreter running this module is always truthy — so the
    probe for that arrival passed while measuring the `pip` branch instead. A
    case a gate cannot reach is a case the gate does not check.
    """
    if which("uv"):
        return "uv"
    if which("python3") or which("python") or executable:
        return "pip"
    return None


def venv_interpreter(root: Path = _REPO_ROOT) -> Path:
    """The project venv's interpreter, POSIX or Windows layout.

    Returned whether or not it exists: the pip path *creates* the venv, so the
    caller needs the path it is about to bring into being.
    """
    windows = root / ".venv" / "Scripts" / "python.exe"
    if windows.exists():
        return windows
    return root / ".venv" / "bin" / "python"


def install_commands(
    manager: str,
    root: Path = _REPO_ROOT,
    executable: str = sys.executable,
) -> tuple[tuple[str, ...], ...]:
    """Every argv this bootstrap would run, in order — returned before any of it runs.

    Plural because the pip path is two steps. The single-command version ran
    `<host python> -m pip install -e .` when `.venv` was absent, which installs
    into whatever interpreter happened to be running — often refused outright
    on an externally managed Python, and invisible to `missing_dependencies`
    either way, since that reads `.venv/site-packages`. The bootstrap would
    then report success and find the same dependencies missing next time. So
    the venv is created first, and pip is that venv's own pip.

    `executable` is injectable for the same reason `package_manager`'s is, plus
    one more: this argv is *recorded in the evidence file*, and reading
    `sys.executable` directly wrote the measuring machine's own interpreter path
    into it. CI then regenerated the file on a different machine and reported
    drift on a repository nobody had touched — the T51 lesson, arriving a second
    time by a different door.
    """
    if manager == "uv":
        return (("uv", "sync", "--extra", "dev"),)

    python = venv_interpreter(root)
    install = (str(python), "-m", "pip", "install", "-e", ".[dev]")
    if python.exists():
        return (install,)
    return ((executable or "python3", "-m", "venv", ".venv"), install)


def _run(argv: Sequence[str], cwd: Path) -> CommandResult:
    """Run one install step, turning a failure to *start* into a result too.

    `shutil.which` said the binary was there; between that answer and this call
    it can be removed, replaced, or left non-executable, and `subprocess.run`
    then raises. An uncaught `FileNotFoundError` here would surface in step 0 as
    exactly the traceback this module exists to prevent, so the exception
    becomes a `CommandResult` like any other failure.
    """
    try:
        completed = subprocess.run(  # fixed argv, no shell
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return CommandResult(tuple(argv), 127, f"{argv[0]} could not be started: {exc}")
    return CommandResult(tuple(argv), completed.returncode, completed.stderr.strip())


# ---------------------------------------------------------------------------
# telling the candidate, once


def _marker_path(env: dict[str, str] | None = None) -> Path | None:
    """`<store root>/bootstrap.json`, or None when no store root can be resolved.

    Imported lazily and defensively: `state_home` is stdlib-only too, but a
    refusal (T51) or a read-only home must degrade to "announce again" rather
    than stop the tool from starting.
    """
    try:
        from integral.state_home import candidate_root

        return candidate_root(env=env) / MARKER_NAME
    except Exception:
        return None


def already_announced(env: dict[str, str] | None = None) -> bool:
    marker = _marker_path(env)
    if marker is None:
        return False
    try:
        return bool(json.loads(marker.read_text(encoding="utf-8")).get("announced_at"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def claim_announcement(
    installed: Sequence[str],
    commands: Sequence[Sequence[str]],
    *,
    env: dict[str, str] | None = None,
    now: str | None = None,
) -> bool:
    """Claim the right to announce, atomically. True means "you are the one who tells them".

    Written with `O_CREAT | O_EXCL` and *before* the install rather than after,
    because check-then-write is a race: two sessions starting together both read
    "not announced yet" and both address the candidate. Exclusive creation means
    the filesystem picks one. Claiming first also means a crashed install does
    not re-announce on every later start, which is the failure mode a person
    actually notices.

    A store that cannot be written returns True — announcing twice is a far
    smaller fault than installing in silence.
    """
    marker = _marker_path(env)
    if marker is None:
        return True
    payload = {
        "announced_at": now or datetime.now(UTC).isoformat(),
        "installed": list(installed),
        "commands": [list(command) for command in commands],
    }
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    except OSError:
        return True
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
    return True


@contextmanager
def installation_lock(root: Path) -> Iterator[bool]:
    """Hold the per-clone install lock, or yield False when somebody else has it.

    Two package-manager processes mutating one `.venv` at the same time is the
    kind of corruption that is hard to diagnose and easy to avoid: a session
    that loses the race waits for nothing and simply reports the environment as
    being prepared elsewhere. A lock older than an hour is treated as abandoned
    — a crashed install must not wedge every future session.
    """
    lock = root / ".integral-bootstrap.lock"
    acquired = False
    try:
        if lock.exists():
            try:
                stale = (datetime.now(UTC).timestamp() - lock.stat().st_mtime) > 3600
            except OSError:
                stale = False
            if stale:
                lock.unlink(missing_ok=True)
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            yield False
            return
        except OSError:
            # An unwritable clone is not a reason to refuse to install.
            yield True
            return
        os.close(handle)
        acquired = True
        yield True
    finally:
        if acquired:
            lock.unlink(missing_ok=True)


def announcement_for(missing: Sequence[str], commands: Sequence[Sequence[str]]) -> str:
    """What the candidate reads, the first time this happens.

    Names what is being installed and what is running it. "Setting things
    up…" would technically be an announcement and would tell them nothing.
    """
    what = ", ".join(missing)
    how = " then ".join(f"`{' '.join(command)}`" for command in commands)
    return (
        "First run: this tool needs a few Python packages that a clone does not carry "
        f"({what}), so it is installing them now with {how}. "
        "This happens once; later sessions start silently."
    )


# ---------------------------------------------------------------------------
# the two entry points, which are one function


def ensure_ready(
    root: Path = _REPO_ROOT,
    *,
    entry_point: str = "session-start",
    run: Runner | None = None,
    announce: Announcer | None = None,
    which: Callable[[str], str | None] = shutil.which,
    executable: str = sys.executable,
    env: dict[str, str] | None = None,
    now: str | None = None,
) -> Report:
    """Make the environment usable, saying so the first time — idempotent by design.

    Called by both the `SessionStart` hook and step 0's own pre-flight, with
    only `entry_point` differing, so "the hook did not fire" and "the hook fired
    twice" are the same code path and neither can drift from the other.
    """
    announce = announce or (lambda message: print(message, file=sys.stderr))

    missing = missing_dependencies(root)
    if not missing:
        return Report(action="current", entry_point=entry_point)

    manager = package_manager(which, executable)
    if manager is None:
        detail = (
            "No package manager is available to install them. Install uv with "
            f"`{UV_INSTALLER}`, or install Python 3.12+ with pip, then start again."
        )
        unavailable = (
            f"This tool needs Python packages a clone does not carry ({', '.join(missing)}). "
            + detail
        )
        announce(unavailable)
        return Report(
            action="unavailable",
            entry_point=entry_point,
            missing=missing,
            announcement=unavailable,
            detail=detail,
        )

    commands = install_commands(manager, root, executable)
    with installation_lock(root) as mine:
        if not mine:
            # Another session is already installing into this clone. Two package
            # managers writing one .venv is the failure worth avoiding; waiting
            # is not, since that session will finish and this one re-checks at
            # its next entry point.
            busy = "This tool's dependencies are being installed by another session."
            announce(busy)
            return Report(
                action="in-progress",
                entry_point=entry_point,
                missing=missing,
                manager=manager,
                command=commands[0],
                announcement=busy,
                detail=busy,
            )

        # Re-read inside the lock: the session that just released it may have
        # installed exactly what this one was about to.
        missing = missing_dependencies(root)
        if not missing:
            return Report(action="current", entry_point=entry_point)

        message: str | None = None
        if claim_announcement(missing, commands, env=env, now=now):
            message = announcement_for(missing, commands)
            announce(message)

        runner = run or _run
        for command in commands:
            result = runner(command, root)
            if result.returncode != 0:
                detail = result.stderr or f"{' '.join(command)} exited {result.returncode}"
                failure = f"Installing this tool's dependencies failed: {detail}"
                announce(failure)
                return Report(
                    action="failed",
                    entry_point=entry_point,
                    missing=missing,
                    manager=manager,
                    command=command,
                    announcement=message or failure,
                    detail=detail,
                )

    return Report(
        action="installed",
        entry_point=entry_point,
        missing=missing,
        manager=manager,
        command=commands[-1],
        announcement=message,
    )


# ---------------------------------------------------------------------------
# the gate


@dataclass(frozen=True)
class Simulation:
    """One way a first run can arrive, and what the bootstrap did about it."""

    name: str
    entry_point: str
    report: Report
    expected_action: str
    expected_to_speak: bool
    reasons: tuple[str, ...] = field(default=())

    @property
    def passes(self) -> bool:
        return not self.reasons


def _simulate(
    name: str,
    *,
    entry_point: str,
    root: Path,
    expected_action: str,
    expected_to_speak: bool,
    which: Callable[[str], str | None],
    run: Runner,
    env: dict[str, str],
    base: Path,
    executable: str = "/usr/bin/python3",
) -> Simulation:
    spoken: list[str] = []
    report = ensure_ready(
        root,
        entry_point=entry_point,
        run=run,
        announce=spoken.append,
        which=which,
        executable=executable,
        env=env,
        now="1970-01-01T00:00:00+00:00",
    )
    # The throwaway clone's path appears inside the recorded argv (the pip path
    # runs `.venv/bin/python` *of that clone*), and this report is written to
    # committed evidence. Redacted here, where the temporary directory is owned,
    # rather than at each call site — this is the third variant of "a number
    # that changes with the machine measuring it" in two tasks.
    report = replace(
        report, command=tuple(part.replace(str(base), "<clone>") for part in report.command)
    )

    reasons: list[str] = []
    if report.action != expected_action:
        reasons.append(f"expected action {expected_action!r}, got {report.action!r}")
    if bool(spoken) != expected_to_speak:
        said = "spoke" if spoken else "said nothing"
        wanted = "to speak" if expected_to_speak else "to stay silent"
        reasons.append(f"expected {wanted}, but it {said}")
    if report.reached_the_code_unbootstrapped:
        reasons.append("reached the code with dependencies missing and nothing said")
    return Simulation(
        name=name,
        entry_point=entry_point,
        report=report,
        expected_action=expected_action,
        expected_to_speak=expected_to_speak,
        reasons=tuple(reasons),
    )


def simulate_first_runs(tmp_factory: Callable[[], Path] | None = None) -> list[Simulation]:
    """Every arrival this bootstrap must handle, measured against a throwaway clone.

    The install command is *recorded* rather than executed: a gate that ran a
    real `uv sync` per case would measure the network. What is being checked is
    that each arrival is handled and none is silent — the command's own shape is
    covered by `install_command` and its tests.
    """
    import tempfile

    del tmp_factory  # reserved for callers that want to supply their own root
    ok: Runner = lambda argv, cwd: CommandResult(tuple(argv), 0)  # noqa: E731
    broken: Runner = lambda argv, cwd: CommandResult(tuple(argv), 1, "network unreachable")  # noqa: E731
    has_uv: Callable[[str], str | None] = lambda name: "/usr/bin/uv" if name == "uv" else None  # noqa: E731
    no_uv: Callable[[str], str | None] = lambda name: None if name == "uv" else "/usr/bin/python3"  # noqa: E731
    nothing: Callable[[str], str | None] = lambda name: None  # noqa: E731

    simulations: list[Simulation] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        bare = _fake_clone(base / "bare", with_venv=False)
        ready = _fake_clone(base / "ready", with_venv=True)
        home = base / "home"

        def env(name: str) -> dict[str, str]:
            return {"INTEGRAL_HOME": str(home / name)}

        simulations.append(
            _simulate(
                "the SessionStart hook fires on a fresh clone",
                entry_point="session-start",
                root=bare,
                expected_action="installed",
                expected_to_speak=True,
                which=has_uv,
                run=ok,
                env=env("hook"),
                base=base,
            )
        )
        simulations.append(
            _simulate(
                "no hook fired; step 0 checks before it needs the code",
                entry_point="step-0",
                root=bare,
                expected_action="installed",
                expected_to_speak=True,
                which=has_uv,
                run=ok,
                env=env("step0"),
                base=base,
            )
        )
        simulations.append(
            _simulate(
                "a returning candidate whose environment is current",
                entry_point="session-start",
                root=ready,
                expected_action="current",
                expected_to_speak=False,
                which=has_uv,
                run=ok,
                env=env("returning"),
                base=base,
            )
        )
        simulations.append(
            _simulate(
                "uv is absent, so venv + pip is used instead",
                entry_point="session-start",
                root=bare,
                expected_action="installed",
                expected_to_speak=True,
                which=no_uv,
                run=ok,
                env=env("pip"),
                base=base,
            )
        )
        simulations.append(
            _simulate(
                "no package manager at all — reported, never raised",
                entry_point="session-start",
                root=bare,
                expected_action="unavailable",
                expected_to_speak=True,
                which=nothing,
                executable="",
                run=ok,
                env=env("bare"),
                base=base,
            )
        )
        simulations.append(
            _simulate(
                "the install itself fails — reported, never raised",
                entry_point="session-start",
                root=bare,
                expected_action="failed",
                expected_to_speak=True,
                which=has_uv,
                run=broken,
                env=env("failed"),
                base=base,
            )
        )

        # The second run against the same store must not repeat the announcement:
        # this is the one case whose expectation depends on the case before it.
        shared = env("announced-once")
        _simulate(
            "first run against a fresh store",
            entry_point="session-start",
            root=bare,
            expected_action="installed",
            expected_to_speak=True,
            which=has_uv,
            run=ok,
            env=shared,
            base=base,
        )
        simulations.append(
            _simulate(
                "a later run does not repeat the announcement",
                entry_point="session-start",
                root=bare,
                expected_action="installed",
                expected_to_speak=False,
                which=has_uv,
                run=ok,
                env=shared,
                base=base,
            )
        )
    return simulations


def _fake_clone(root: Path, *, with_venv: bool) -> Path:
    """A clone with this project's real dependency list, and optionally its venv."""
    root.mkdir(parents=True, exist_ok=True)
    declared = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    (root / "pyproject.toml").write_text(declared, encoding="utf-8")
    if not with_venv:
        return root

    packages = root / ".venv" / "lib" / "python3.12" / "site-packages"
    packages.mkdir(parents=True, exist_ok=True)
    for name, floor in declared_requirements(root):
        # At the declared floor, not 0.0.0: since the readiness check learned to
        # honour version floors, a placeholder version would make this "ready"
        # clone read as stale and the probe would measure the wrong arrival.
        version = ".".join(str(part) for part in floor) if floor else "1.0"
        dist = packages / f"{name}-{version}.dist-info"
        dist.mkdir(exist_ok=True)
        (dist / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8"
        )
    return root


def measure() -> dict[str, Any]:
    """The T52 gate reading, as it is written to evidence."""
    simulations = simulate_first_runs()
    unbootstrapped = [s for s in simulations if s.report.reached_the_code_unbootstrapped]
    shortfalls = [
        {"arrival": s.name, "reasons": list(s.reasons)} for s in simulations if not s.passes
    ]
    return {
        "unbootstrapped_first_runs": len(unbootstrapped),
        "first_runs_simulated": len(simulations),
        "shortfalls": shortfalls,
        "arrivals": [
            {
                "arrival": s.name,
                "entry_point": s.entry_point,
                "action": s.report.action,
                "expected_action": s.expected_action,
                "missing": list(s.report.missing),
                "manager": s.report.manager,
                "command": list(s.report.command),
                "announced": s.report.spoke,
                "expected_to_speak": s.expected_to_speak,
                "detail": s.report.detail,
                "reasons": list(s.reasons),
            }
            for s in simulations
        ],
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T52.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.bootstrap [--check | --ensure | --write-evidence [PATH]]`.

    `--ensure` is what the hook and step 0 run: make the environment usable and
    say so once. Everything else measures.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="install missing dependencies if needed (what the SessionStart hook runs)",
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
        help="write evidence JSON to PATH (default: status/evidence/T52.json)",
    )
    args = parser.parse_args(argv[1:])

    if args.ensure:
        report = ensure_ready(entry_point=os.environ.get("INTEGRAL_ENTRY_POINT", "session-start"))
        # Exit 0 whatever happened: a hook that fails the session because the
        # network was down is worse than the ImportError it was avoiding, and
        # the candidate has already been told in words.
        print(json.dumps({"action": report.action, "missing": list(report.missing)}))
        return 0

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    if measured["first_runs_simulated"] == 0:
        print("no first runs were simulated — nothing was measured", file=sys.stderr)
        return 3
    for shortfall in measured["shortfalls"]:
        print(f"{shortfall['arrival']}: {'; '.join(shortfall['reasons'])}", file=sys.stderr)
    return 1 if measured["shortfalls"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
