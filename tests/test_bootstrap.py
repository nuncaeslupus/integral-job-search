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
from collections.abc import Sequence
from pathlib import Path

import pytest

from jobsearch.bootstrap import (
    UV_INSTALLER,
    CommandResult,
    announcement_for,
    declared_dependencies,
    ensure_ready,
    environment_is_current,
    install_command,
    measure,
    missing_dependencies,
    package_manager,
    simulate_first_runs,
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
        packages = root / ".venv" / "lib" / "python3.12" / "site-packages"
        packages.mkdir(parents=True, exist_ok=True)
        for name in installed:
            dist = packages / f"{name}-0.0.0.dist-info"
            dist.mkdir(exist_ok=True)
            (dist / "METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.0.0\n", encoding="utf-8"
            )
    return root


def _recorder() -> tuple[list[tuple[str, ...]], object]:
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], cwd: Path) -> CommandResult:
        calls.append(tuple(argv))
        return CommandResult(tuple(argv), 0)

    return calls, run


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
    assert install_command("uv", root)[:2] == ("uv", "sync")
    assert install_command("pip", root)[1:] == ("-m", "pip", "install", "-e", ".[dev]")


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


def test_the_marker_lives_outside_the_clone(tmp_path: Path) -> None:
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


def test_the_announcement_names_what_is_installed() -> None:
    message = announcement_for(("pydantic", "pyyaml"), ("uv", "sync"))
    assert "pydantic" in message and "pyyaml" in message
    assert "uv sync" in message


# ---------------------------------------------------------------------------
# the module's own constraint


def test_bootstrap_imports_without_third_party_dependencies() -> None:
    """It cannot need the packages it installs — checked statically and by running it.

    The static half catches an import added anywhere in the module; the
    subprocess half proves the whole import actually completes with `src/` on
    the path and nothing else, which is the situation on a fresh clone.
    """
    source = (_REPO_ROOT / "src" / "jobsearch" / "bootstrap.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    third_party = imported - set(sys.stdlib_module_names) - {"jobsearch"}
    assert not third_party, f"bootstrap must be stdlib-only, but imports {sorted(third_party)}"

    completed = subprocess.run(
        [sys.executable, "-c", "import jobsearch.bootstrap as b; print(b.MARKER_NAME)"],
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
    bootstrap_at = script.index("from jobsearch.bootstrap import ensure_ready")
    ensure_at = script.index("ensure_ready(_REPO_ROOT")
    identity_at = script.index("from jobsearch.identity import")
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
    assert "/tmp/" not in json.dumps(first)


@pytest.mark.parametrize("flag", ["--check", "--ensure"])
def test_the_command_line_exits_zero_on_a_working_checkout(flag: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "jobsearch.bootstrap", flag],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
