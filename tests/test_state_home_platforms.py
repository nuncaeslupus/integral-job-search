"""T193 — `candidate_root()` has per-OS defaults, and `$INTEGRAL_HOME` has a backup.

Platforms are simulated by patching `sys.platform` and the environment the OS
data dir is read from; nothing here depends on the host OS. The backup script is
only ever pointed at directories under `tmp_path`, with `HOME` also redirected
there, so a bug in it cannot reach a real home directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import platformdirs.windows
import pytest

from integral.state_home import APP_DIR, HOME_ENV, XDG_ENV, StateHomeRefused, candidate_root

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "backup_state_home.sh"
PLATFORMS = ("linux", "darwin", "win32")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No state-home variables set; HOME and LOCALAPPDATA point into tmp_path."""
    for var in (HOME_ENV, XDG_ENV, "INTEGRAL_DEV"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    # platformdirs picks its Windows folder resolver at import time (ctypes), which a
    # patched `sys.platform` on a non-Windows host cannot run. Its own env-var
    # fallback reads the same %LOCALAPPDATA% a real Windows host reports.
    monkeypatch.setattr(
        platformdirs.windows,
        "_resolve_win_folder",
        platformdirs.windows.get_win_folder_from_env_vars,
    )
    return home


def test_candidate_root_windows_default_uses_platformdirs(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    root = candidate_root()
    assert root == tmp_path / "localappdata" / APP_DIR
    assert root != clean_env / f".{APP_DIR}"


def test_candidate_root_macos_default_uses_platformdirs(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    root = candidate_root()
    assert root == clean_env / "Library" / "Application Support" / APP_DIR
    assert root != clean_env / f".{APP_DIR}"


def test_candidate_root_linux_default_unchanged(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert candidate_root() == clean_env / f".{APP_DIR}"
    xdg = tmp_path / "xdg"
    monkeypatch.setenv(XDG_ENV, str(xdg))
    assert candidate_root() == xdg / APP_DIR


@pytest.mark.parametrize("platform", PLATFORMS)
def test_candidate_root_integral_home_still_wins(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, tmp_path: Path, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv(XDG_ENV, str(tmp_path / "xdg"))
    chosen = tmp_path / "chosen"
    monkeypatch.setenv(HOME_ENV, str(chosen))
    assert candidate_root() == chosen.resolve()


@pytest.mark.parametrize("platform", ("darwin", "win32"))
def test_xdg_data_home_still_outranks_the_os_default(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, tmp_path: Path, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv(XDG_ENV, str(xdg))
    assert candidate_root() == xdg / APP_DIR


@pytest.mark.parametrize("platform", ("darwin", "win32"))
def test_os_default_inside_a_work_tree_is_still_refused(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, platform: str
) -> None:
    """The containment rule applies to the new defaults too, not only the old one."""
    subprocess.run(["git", "init", "--quiet", str(clean_env)], check=True)
    monkeypatch.setenv("LOCALAPPDATA", str(clean_env / "AppData"))
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(StateHomeRefused):
        candidate_root()


def _backup(
    target: Path, home: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        HOME_ENV: str(target),
        **(extra_env or {}),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(target: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(target), *args], capture_output=True, check=True)
    return done.stdout.decode()


def test_backup_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)


def test_backup_commits_profiles_without_altering_them(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state"
    profile = state / "profiles" / "alice" / "cv.json"
    profile.parent.mkdir(parents=True)
    payload = b'{"name": "Alice"}\r\n  trailing   \n'
    profile.write_bytes(payload)

    done = _backup(state, home)
    assert done.returncode == 0, done.stderr

    assert (state / ".git").is_dir()
    assert profile.read_bytes() == payload
    assert "profiles/alice/cv.json" in _git(state, "ls-files")
    committed = subprocess.run(
        ["git", "-C", str(state), "show", "HEAD:profiles/alice/cv.json"],
        capture_output=True,
        check=True,
    ).stdout
    assert committed == payload
    assert not (home / ".git").exists()


def test_backup_is_idempotent_and_picks_up_changes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "a.txt").write_text("one")
    assert _backup(state, home).returncode == 0
    assert _backup(state, home).returncode == 0
    assert _git(state, "rev-list", "--count", "HEAD").strip() == "1"
    (state / "a.txt").write_text("two")
    assert _backup(state, home).returncode == 0
    assert _git(state, "rev-list", "--count", "HEAD").strip() == "2"


def test_backup_refuses_a_directory_inside_another_repository(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    outer = tmp_path / "outer"
    inner = outer / "state"
    inner.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(outer)], check=True)
    (inner / "x.txt").write_text("x")

    done = _backup(inner, home)
    assert done.returncode != 0
    assert not (inner / ".git").exists()
    assert _git(outer, "status", "--porcelain").strip().startswith("?? state/")


def test_backup_refuses_a_missing_directory(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    missing = tmp_path / "nope"
    done = _backup(missing, home)
    assert done.returncode == 2
    assert "does not exist" in done.stderr
    assert not missing.exists()


def _commit_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--all", "--count").strip())


def _repo_with_origin(base: Path, name: str) -> tuple[Path, Path]:
    """A work repository with one commit pushed to a bare origin; returns both."""
    origin = base / f"{name}-origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(origin)], check=True)
    work = base / name
    work.mkdir()
    subprocess.run(["git", "-C", str(work), "init", "--quiet", "-b", "main"], check=True)
    (work / "seed.txt").write_text("seed")
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(work), *ident, "commit", "-q", "-m", "seed"], check=True)
    subprocess.run(["git", "-C", str(work), "remote", "add", "origin", str(origin)], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "main"], check=True)
    return work, origin


def test_backup_ignores_an_inherited_git_dir(tmp_path: Path) -> None:
    """GIT_DIR (set inside hooks) must not redirect the commit into another repo."""
    home = tmp_path / "home"
    home.mkdir()
    other, other_origin = _repo_with_origin(tmp_path, "other")
    before = (_commit_count(other), _commit_count(other_origin))
    state = tmp_path / "state A"
    (state / "data").mkdir(parents=True)
    (state / "data" / "cv.json").write_text("{}")

    done = _backup(state, home, extra_env={"GIT_DIR": str(other / ".git")})
    assert done.returncode == 0, done.stderr

    assert (state / ".git").is_dir()
    assert (_commit_count(other), _commit_count(other_origin)) == before
    assert "data/cv.json" in _git(state, "ls-files")


def test_backup_refuses_a_git_file_above_the_directory(tmp_path: Path) -> None:
    """A linked-worktree `.git` is a file; it still marks an enclosing repository."""
    home = tmp_path / "home"
    home.mkdir()
    outer = tmp_path / "outer"
    inner = outer / "deep" / "state"
    inner.mkdir(parents=True)
    (outer / ".git").write_text("gitdir: /nonexistent\n")
    (inner / "x.txt").write_text("x")

    done = _backup(inner, home)
    assert done.returncode == 2
    assert "inside the repository" in done.stderr
    assert not (inner / ".git").exists()


def test_backup_refuses_when_git_discovery_is_blinded(tmp_path: Path) -> None:
    """GIT_CEILING_DIRECTORIES hides the outer repository from git, not from us."""
    home = tmp_path / "home"
    home.mkdir()
    outer = tmp_path / "outer"
    inner = outer / "state"
    inner.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(outer)], check=True)
    (inner / "x.txt").write_text("x")

    done = _backup(inner, home, extra_env={"GIT_CEILING_DIRECTORIES": str(tmp_path)})
    assert done.returncode == 2
    assert not (inner / ".git").exists()


def test_backup_never_force_pushes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    state, origin = _repo_with_origin(tmp_path, "state")
    # Someone else advances origin so the state repository has diverged.
    rival = tmp_path / "rival"
    subprocess.run(["git", "clone", "-q", str(origin), str(rival)], check=True)
    (rival / "other.txt").write_text("theirs")
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "-C", str(rival), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(rival), *ident, "commit", "-q", "-m", "rival"], check=True)
    subprocess.run(["git", "-C", str(rival), "push", "-q", "origin", "main"], check=True)
    theirs = _git(origin, "rev-parse", "main").strip()

    (state / "mine.txt").write_text("mine")
    done = _backup(state, home)

    assert done.returncode != 0
    assert _git(origin, "rev-parse", "main").strip() == theirs
    assert "mine.txt" in _git(state, "ls-files")


def test_backup_never_deletes_or_alters_candidate_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    state, origin = _repo_with_origin(tmp_path, "state")
    (state / ".gitignore").write_text("*.secret\n")
    ignored = state / "profiles" / "alice" / "notes.secret"
    untracked = state / "profiles" / "alice" / "new.txt"
    ignored.parent.mkdir(parents=True)
    ignored.write_bytes(b"ignored\r\n")
    untracked.write_bytes(b"untracked")

    done = _backup(state, home)
    assert done.returncode == 0, done.stderr

    assert ignored.read_bytes() == b"ignored\r\n"
    assert untracked.read_bytes() == b"untracked"
    assert "new.txt" in _git(origin, "ls-tree", "-r", "--name-only", "main")


@pytest.mark.parametrize(("platform", "var"), (("darwin", "HOME"), ("win32", "LOCALAPPDATA")))
def test_injected_env_decides_the_os_default(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, platform: str, var: str
) -> None:
    """`env=` must mean the same on every OS, not fall through to os.environ."""
    monkeypatch.setattr(sys, "platform", platform)
    root = candidate_root(env={var: "/injected"})
    assert root.parts[:2] == ("/", "injected")
    assert str(clean_env) not in str(root)
