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
lives in the candidate store (`jobsearch.state_home`), never in the clone: it is
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
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
# specifier, extra marker, or environment marker.
_DIST_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

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


def declared_dependencies(root: Path = _REPO_ROOT) -> tuple[str, ...]:
    """The runtime distribution names from `pyproject.toml`, never a second copy.

    Read rather than restated: a hardcoded list here would keep reporting a
    clean environment after somebody adds a dependency, which is the same
    self-counting mistake this repo's gates document at length.
    """
    manifest = root / "pyproject.toml"
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapError(f"{manifest} could not be read: {exc}") from exc

    requirements = data.get("project", {}).get("dependencies", [])
    names: list[str] = []
    for requirement in requirements:
        match = _DIST_NAME.match(str(requirement))
        if match:
            names.append(_normalise(match.group(1)))
    return tuple(names)


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
    """Declared distributions with nothing installed to satisfy them, in declared order.

    Read out of the venv's own `site-packages` rather than by importing:
    importing works only from inside the environment being checked, and the
    `SessionStart` hook runs outside it.
    """
    declared = declared_dependencies(root)
    if not declared:
        return ()

    packages = site_packages(root)
    if packages is None:
        return declared

    installed = {
        _normalise(str(dist.metadata["Name"]))
        for dist in importlib.metadata.Distribution.discover(path=[str(packages)])
        if dist.metadata is not None and dist.metadata["Name"]
    }
    return tuple(name for name in declared if name not in installed)


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


def install_command(manager: str, root: Path = _REPO_ROOT) -> tuple[str, ...]:
    """The argv this bootstrap would run — returned, so it can be shown before it runs."""
    if manager == "uv":
        return ("uv", "sync", "--extra", "dev")
    interpreter = sys.executable or "python3"
    venv_python = root / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else interpreter
    return (python, "-m", "pip", "install", "-e", ".[dev]")


def _run(argv: Sequence[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(  # fixed argv, no shell
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
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
        from jobsearch.state_home import candidate_root

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


def record_announcement(
    installed: Sequence[str],
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    now: str | None = None,
) -> Path | None:
    """Write the marker, best effort. A store we cannot write is not a reason to stop."""
    marker = _marker_path(env)
    if marker is None:
        return None
    payload = {
        "announced_at": now or datetime.now(UTC).isoformat(),
        "installed": list(installed),
        "command": list(command),
    }
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return None
    return marker


def announcement_for(missing: Sequence[str], command: Sequence[str]) -> str:
    """What the candidate reads, the first time this happens.

    Names what is being installed and what is running it. "Setting things
    up…" would technically be an announcement and would tell them nothing.
    """
    what = ", ".join(missing)
    return (
        "First run: this tool needs a few Python packages that a clone does not carry "
        f"({what}), so it is installing them now with `{' '.join(command)}`. "
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

    command = install_command(manager, root)
    message: str | None = None
    if not already_announced(env):
        message = announcement_for(missing, command)
        announce(message)

    result = (run or _run)(command, root)
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

    if message is not None:
        record_announcement(missing, command, env=env, now=now)
    return Report(
        action="installed",
        entry_point=entry_point,
        missing=missing,
        manager=manager,
        command=command,
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
    for name in declared_dependencies(root):
        dist = packages / f"{name}-0.0.0.dist-info"
        dist.mkdir(exist_ok=True)
        (dist / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.0.0\n", encoding="utf-8"
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
    """`python -m jobsearch.bootstrap [--check | --ensure | --write-evidence [PATH]]`.

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
