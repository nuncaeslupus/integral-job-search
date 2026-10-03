"""Session-wide guard: no test may modify the committed evidence.

`floor_sweep`'s cache key hashes every `status/evidence/*.json`, and the
evidence files are the repository's committed measurements, so a test that
rewrites one -- even with identical bytes -- can race another worker's read and
key a second analysis of the same tree, and one that leaves different bytes
dirties a committed record (issue #671). The rule is closed rather than listed:
every file under `status/evidence/` is snapshotted (bytes and mtime) when the
session starts, and the session fails at its end naming each file that changed,
appeared or vanished. Under xdist the controller does the check, so a write by
any worker is seen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_EVIDENCE = Path(__file__).resolve().parents[1] / "status" / "evidence"
_SNAPSHOT_KEY = pytest.StashKey[dict[str, tuple[int, bytes]]]()


def _snapshot(directory: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(path.relative_to(directory)): (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def changed_files(
    before: dict[str, tuple[int, bytes]], after: dict[str, tuple[int, bytes]]
) -> list[str]:
    """Every name whose bytes or mtime differ, plus added and removed names."""
    names = before.keys() | after.keys()
    return sorted(name for name in names if before.get(name) != after.get(name))


def _is_controller(config: pytest.Config) -> bool:
    return not hasattr(config, "workerinput")


def pytest_sessionstart(session: pytest.Session) -> None:
    if _is_controller(session.config) and _EVIDENCE.is_dir():
        session.config.stash[_SNAPSHOT_KEY] = _snapshot(_EVIDENCE)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_SNAPSHOT_KEY, None)
    if before is None or not _is_controller(session.config):
        return
    changed = changed_files(before, _snapshot(_EVIDENCE))
    if not changed:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    lines = ["tests modified committed evidence under status/evidence/ (bytes or mtime):"]
    lines += [f"  {name}" for name in changed]
    for line in lines:
        if reporter is not None:
            reporter.write_line(line, red=True)
        else:
            print(line)
    session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)
