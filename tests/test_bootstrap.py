"""T52 — a clone installs its own dependencies, and says so once.

`docs/distribution.md` §1 makes the install `git clone`, `cd`, `claude`. What
these tests hold to is the sentence that makes that honest: a candidate never
meets an `ImportError`, and never has a package manager run silently on their
machine.

The subtle one is `test_bootstrap_imports_without_third_party_dependencies`. It
looks redundant in a developed checkout — where pydantic is installed, an
accidental import of it works fine — and that is exactly why it is here: the
regression it catches is invisible everywhere except on the first run of a fresh
clone, which is the only run this module exists for.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from integral.bootstrap import (
    UV_INSTALLER,
    CommandResult,
    _run,
    announcement_for,
    claim_announcement,
    declared_dependencies,
    declared_requirements,
    ensure_ready,
    environment_is_current,
    install_commands,
    installation_lock,
    measure,
    missing_dependencies,
    package_manager,
    simulate_first_runs,
    venv_interpreter,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _clone(root: Path, *, installed: Sequence[str] = ()) -> Path:
    """A clone carrying this project's real dependency list, and the given packages."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    if installed:
        floors = dict(declared_requirements(root))
        packages = root / ".venv" / "lib" / "python3.12" / "site-packages"
        packages.mkdir(parents=True, exist_ok=True)
        for name in installed:
            floor = floors.get(name, ())
            version = ".".join(str(part) for part in floor) if floor else "1.0"
            dist = packages / f"{name}-{version}.dist-info"
            dist.mkdir(exist_ok=True)
            (dist / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", encoding="utf-8"
            )
    return root


def _recorder() -> tuple[list[tuple[str, ...]], object]:
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], cwd: Path) -> CommandResult:
        calls.append(tuple(argv))
        return CommandResult(tuple(argv), 0)

    return calls, run


def _run_via(
    raiser: Callable[[Sequence[str], Path], CommandResult], argv: Sequence[str], cwd: Path
) -> CommandResult:
    """Route a raising fake through the same conversion `_run` performs."""
    try:
        return raiser(argv, cwd)
    except OSError as exc:
        return CommandResult(tuple(argv), 127, f"{argv[0]} could not be started: {exc}")


def _has_uv(name: str) -> str | None:
    return "/usr/bin/uv" if name == "uv" else None


def _no_uv(name: str) -> str | None:
    return None if name == "uv" else "/usr/bin/python3"


# ---------------------------------------------------------------------------
# the two entry points


def test_a_clone_without_dependencies_installs_them_before_step_zero(tmp_path: Path) -> None:
    """The arrival T52 exists for: no hook fired, and step 0 is about to need the code."""
    root = _clone(tmp_path / "clone")
    calls, run = _recorder()
    spoken: list[str] = []

    report = ensure_ready(
        root,
        entry_point="step-0",
        run=run,  # type: ignore[arg-type]
        announce=spoken.append,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(tmp_path / "home")},
    )

    assert report.action == "installed"
    assert report.dependencies_ready
    assert not report.reached_the_code_unbootstrapped
    assert calls == [("uv", "sync", "--extra", "dev")]
    assert spoken


def test_bootstrap_is_silent_when_the_environment_is_current(tmp_path: Path) -> None:
    """A returning candidate pays nothing — no command, no words."""
    root = _clone(tmp_path / "clone", installed=declared_dependencies(_REPO_ROOT))
    calls, run = _recorder()
    spoken: list[str] = []

    report = ensure_ready(
        root,
        run=run,  # type: ignore[arg-type]
        announce=spoken.append,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(tmp_path / "home")},
    )

    assert report.action == "current"
    assert environment_is_current(root)
    assert calls == []
    assert spoken == []


def test_both_entry_points_take_the_same_path(tmp_path: Path) -> None:
    """The hook and step 0 differ only in what they call themselves — idempotence by design."""
    outcomes = []
    for entry_point in ("session-start", "step-0"):
        root = _clone(tmp_path / entry_point)
        calls, run = _recorder()
        report = ensure_ready(
            root,
            entry_point=entry_point,
            run=run,  # type: ignore[arg-type]
            announce=lambda _message: None,
            which=_has_uv,
            env={"INTEGRAL_HOME": str(tmp_path / f"home-{entry_point}")},
        )
        outcomes.append((report.action, report.command, tuple(calls)))
    assert outcomes[0] == outcomes[1]


# ---------------------------------------------------------------------------
# when it cannot install


def test_a_missing_package_manager_is_reported_not_raised(tmp_path: Path) -> None:
    """No uv, no interpreter: a sentence with the fix in it, not a traceback."""
    root = _clone(tmp_path / "clone")
    spoken: list[str] = []

    report = ensure_ready(
        root,
        announce=spoken.append,
        which=lambda _name: None,
        executable="",
        env={"INTEGRAL_HOME": str(tmp_path / "home")},
    )

    assert report.action == "unavailable"
    assert not report.dependencies_ready
    assert report.spoke
    assert not report.reached_the_code_unbootstrapped, "silence is the only real failure"
    assert UV_INSTALLER in spoken[0]


def test_a_failing_install_is_reported_not_raised(tmp_path: Path) -> None:
    root = _clone(tmp_path / "clone")
    spoken: list[str] = []

    def failing(argv: Sequence[str], cwd: Path) -> CommandResult:
        return CommandResult(tuple(argv), 1, "network unreachable")

    report = ensure_ready(
        root,
        run=failing,
        announce=spoken.append,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(tmp_path / "home")},
    )

    assert report.action == "failed"
    assert "network unreachable" in report.detail
    assert any("network unreachable" in message for message in spoken)


def test_uv_is_preferred_and_pip_is_the_fallback(tmp_path: Path) -> None:
    root = _clone(tmp_path / "clone")
    assert package_manager(_has_uv) == "uv"
    assert package_manager(_no_uv) == "pip"
    assert package_manager(lambda _name: None, executable="") is None
    assert install_commands("uv", root) == (("uv", "sync", "--extra", "dev"),)


def test_the_pip_fallback_creates_the_venv_it_will_be_checked_against(tmp_path: Path) -> None:
    """Installing into the host interpreter would be invisible to the readiness check."""
    root = _clone(tmp_path / "clone")
    commands = install_commands("pip", root, executable="/usr/bin/python3")

    assert commands[0] == ("/usr/bin/python3", "-m", "venv", ".venv")
    assert commands[-1][1:] == ("-m", "pip", "install", "-e", ".[dev]")
    assert str(venv_interpreter(root)) == commands[-1][0], "pip must be the venv's own pip"

    # With the venv already there, creating it again is not in the plan.
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    assert len(install_commands("pip", root, executable="/usr/bin/python3")) == 1


def test_a_windows_venv_interpreter_is_found(tmp_path: Path) -> None:
    root = _clone(tmp_path / "clone")
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")
    assert venv_interpreter(root).name == "python.exe"


def test_a_command_that_cannot_start_is_reported_not_raised(tmp_path: Path) -> None:
    """`which` said it was there; between then and now it can vanish."""
    root = _clone(tmp_path / "clone")
    spoken: list[str] = []

    def cannot_start(argv: Sequence[str], cwd: Path) -> CommandResult:
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    report = ensure_ready(
        root,
        run=lambda argv, cwd: _run_via(cannot_start, argv, cwd),
        announce=spoken.append,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(tmp_path / "home")},
    )

    assert report.action == "failed"
    assert "could not be started" in report.detail
    assert report.spoke


def test_the_runner_itself_converts_a_launch_failure(tmp_path: Path) -> None:
    """The real `_run`, against a binary that is genuinely not there."""
    result = _run(("/nonexistent/uv", "sync"), tmp_path)
    assert result.returncode == 127
    assert "could not be started" in result.stderr


def test_an_installed_version_below_the_declared_floor_counts_as_missing(tmp_path: Path) -> None:
    """`pydantic 1.x` does not satisfy `pydantic>=2.9`, and reporting it current is worse
    than the ImportError, because nothing then tries to fix it."""
    root = tmp_path / "clone"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["pydantic>=2.9"]\n', encoding="utf-8"
    )
    packages = root / ".venv" / "lib" / "python3.12" / "site-packages"
    packages.mkdir(parents=True)
    dist = packages / "pydantic-1.10.13.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pydantic\nVersion: 1.10.13\n", encoding="utf-8"
    )

    assert declared_requirements(root) == (("pydantic", (2, 9)),)
    assert missing_dependencies(root) == ("pydantic",)
    assert not environment_is_current(root)

    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pydantic\nVersion: 2.9.1\n", encoding="utf-8"
    )
    assert missing_dependencies(root) == ()


def test_two_sessions_do_not_install_over_each_other(tmp_path: Path) -> None:
    """One .venv, two package managers, is corruption nobody enjoys diagnosing."""
    root = _clone(tmp_path / "clone")
    calls, run = _recorder()
    spoken: list[str] = []

    with installation_lock(root) as held:
        assert held
        report = ensure_ready(
            root,
            run=run,  # type: ignore[arg-type]
            announce=spoken.append,
            which=_has_uv,
            env={"INTEGRAL_HOME": str(tmp_path / "home")},
        )

    assert report.action == "in-progress"
    assert calls == [], "the second session must not run a package manager"
    assert spoken, "and it must say why it did nothing"


def test_the_announcement_is_claimed_atomically(tmp_path: Path) -> None:
    """Check-then-write is a race; exclusive creation lets the filesystem pick one."""
    env = {"INTEGRAL_HOME": str(tmp_path / "home")}
    assert claim_announcement(
        ("pydantic",), [("uv", "sync")], env=env, now="1970-01-01T00:00:00+00:00"
    )
    assert not claim_announcement(
        ("pydantic",), [("uv", "sync")], env=env, now="1970-01-01T00:00:00+00:00"
    )


# ---------------------------------------------------------------------------
# what the candidate is told


def test_the_first_install_is_announced_to_the_candidate(tmp_path: Path) -> None:
    """Named packages and the actual command — not "setting things up…"."""
    root = _clone(tmp_path / "clone")
    _calls, run = _recorder()
    spoken: list[str] = []

    ensure_ready(
        root,
        run=run,  # type: ignore[arg-type]
        announce=spoken.append,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(tmp_path / "home")},
    )

    assert len(spoken) == 1
    message = spoken[0]
    for package in declared_dependencies(root):
        assert package in message
    assert "uv sync" in message


def test_the_announcement_happens_once(tmp_path: Path) -> None:
    """Told the first time, and only the first time — a banner at every start goes unread."""
    root = _clone(tmp_path / "clone")
    _calls, run = _recorder()
    env = {"INTEGRAL_HOME": str(tmp_path / "home")}

    first: list[str] = []
    ensure_ready(root, run=run, announce=first.append, which=_has_uv, env=env)  # type: ignore[arg-type]
    second: list[str] = []
    ensure_ready(root, run=run, announce=second.append, which=_has_uv, env=env)  # type: ignore[arg-type]

    assert first and not second


def test_the_marker_after_a_first_run_bootstrap_is_written_outside_the_clone(
    tmp_path: Path,
) -> None:
    """T51's rule holds here too: this is per-person state, so it is not in the repository."""
    root = _clone(tmp_path / "clone")
    _calls, run = _recorder()
    home = tmp_path / "home"

    ensure_ready(
        root,
        run=run,  # type: ignore[arg-type]
        announce=lambda _message: None,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(home)},
    )

    assert (home / "bootstrap.json").is_file()
    assert not list(root.glob("**/bootstrap.json"))


def test_an_unwritable_store_does_not_stop_the_bootstrap(tmp_path: Path) -> None:
    """No marker means "announce again", never "refuse to start"."""
    root = _clone(tmp_path / "clone")
    _calls, run = _recorder()

    report = ensure_ready(
        root,
        run=run,  # type: ignore[arg-type]
        announce=lambda _message: None,
        which=_has_uv,
        env={"INTEGRAL_HOME": str(_REPO_ROOT / "inside-a-work-tree")},  # the resolver refuses this
    )

    assert report.action == "installed"


def test_the_announcement_names_every_command_that_will_run() -> None:
    message = announcement_for(
        ("pydantic", "pyyaml"), [("python3", "-m", "venv", ".venv"), ("uv", "sync")]
    )
    assert "pydantic" in message and "pyyaml" in message
    assert "python3 -m venv .venv" in message and "uv sync" in message


# ---------------------------------------------------------------------------
# the module's own constraint


def test_bootstrap_imports_without_third_party_dependencies() -> None:
    """It cannot need the packages it installs — checked statically and by running it.

    The static half catches an import added anywhere in the module; the
    subprocess half proves the whole import actually completes with `src/` on
    the path and nothing else, which is the situation on a fresh clone.
    """
    source = (_REPO_ROOT / "src" / "integral" / "bootstrap.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    third_party = imported - set(sys.stdlib_module_names) - {"integral"}
    assert not third_party, f"bootstrap must be stdlib-only, but imports {sorted(third_party)}"

    completed = subprocess.run(
        [sys.executable, "-c", "import integral.bootstrap as b; print(b.MARKER_NAME)"],
        cwd=_REPO_ROOT,
        env={"PYTHONPATH": str(_REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "bootstrap.json"


def test_step_zero_bootstraps_before_it_imports_anything_that_needs_pydantic() -> None:
    """The pre-flight is only a pre-flight if it runs first."""
    script = (
        _REPO_ROOT / ".claude" / "skills" / "step-00-identify" / "scripts" / "run_checkpoint.py"
    ).read_text(encoding="utf-8")
    bootstrap_at = script.index("from integral.bootstrap import ensure_ready")
    ensure_at = script.index("ensure_ready(_REPO_ROOT")
    identity_at = script.index("from integral.identity import")
    assert bootstrap_at < ensure_at < identity_at


def test_the_session_start_hook_is_registered() -> None:
    settings = json.loads((_REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"] for entry in settings["hooks"]["SessionStart"] for hook in entry["hooks"]
    ]
    assert any("bootstrap_hook.sh" in command for command in commands)
    assert (_REPO_ROOT / "tools" / "bootstrap_hook.sh").is_file()


def test_the_hook_does_not_use_uv_run_to_ask_whether_uv_is_needed() -> None:
    """`uv run` would install as a side effect, and the announcement would never be made."""
    hook = (_REPO_ROOT / "tools" / "bootstrap_hook.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in hook.splitlines() if not line.lstrip().startswith("#"))
    assert "uv run" not in code


def test_the_hook_does_not_discard_the_announcement() -> None:
    """The announcement goes to stderr, so a hook that silences stderr silences it.

    This is the gap the in-process gate could not see: it exercises `ensure_ready`
    with an injected announcer and never the plumbing the candidate actually gets.
    """
    hook = (_REPO_ROOT / "tools" / "bootstrap_hook.sh").read_text(encoding="utf-8")
    invocation = next(
        line for line in hook.splitlines() if "integral.bootstrap" in line and "python" in line
    )
    assert ">/dev/null" in invocation, "stdout is a machine status line and may go"
    assert "2>&1" not in invocation and "2>/dev/null" not in invocation


def test_step_zero_re_execs_into_the_venv_after_installing() -> None:
    """Installing does not put the packages on a running interpreter's path."""
    script = (
        _REPO_ROOT / ".claude" / "skills" / "step-00-identify" / "scripts" / "run_checkpoint.py"
    ).read_text(encoding="utf-8")
    assert "os.execv" in script
    assert "INTEGRAL_BOOTSTRAP_REEXEC" in script, "and it must not be able to loop"
    assert script.index("os.execv") < script.index("from integral.identity import")


# ---------------------------------------------------------------------------
# what is declared, and the gate


def test_the_dependency_list_is_read_not_restated(tmp_path: Path) -> None:
    root = tmp_path / "clone"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["Some-Package>=1.0", "other"]\n', encoding="utf-8"
    )
    assert declared_dependencies(root) == ("some-package", "other")
    assert missing_dependencies(root) == ("some-package", "other")


def test_every_arrival_is_simulated_and_none_is_silent() -> None:
    simulations = simulate_first_runs()
    assert len(simulations) >= 6, "the arrival set shrank — a gate that checks less is not the same"
    failing = [s for s in simulations if not s.passes]
    assert not failing, [f"{s.name}: {'; '.join(s.reasons)}" for s in failing]


def test_the_gate_is_met_and_was_measured_over_a_non_empty_set() -> None:
    measured = measure()
    assert measured["first_runs_simulated"] > 0
    assert measured["unbootstrapped_first_runs"] == 0, measured["shortfalls"]


def test_the_evidence_is_a_function_of_the_repository_not_of_the_run(tmp_path: Path) -> None:
    """The T51 lesson, applied here before CI has to teach it again."""
    target = tmp_path / "T52.json"
    first = write_evidence(target)
    second = json.loads(target.read_text(encoding="utf-8"))
    assert first == second
    assert first == measure()

    # Not just temp paths: anything absolute and machine-specific makes the file
    # differ from itself on the next machine, which is how CI caught this.
    serialised = json.dumps(first)
    assert "/tmp/" not in serialised
    assert str(_REPO_ROOT) not in serialised
    assert sys.executable not in serialised


@pytest.mark.parametrize("flag", ["--check", "--ensure"])
def test_the_command_line_exits_zero_on_a_working_checkout(flag: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "integral.bootstrap", flag],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
