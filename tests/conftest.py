"""Session-wide guard: no test may modify the committed evidence.

The evidence files are the repository's committed measurements, so a test that
rewrites one -- even with identical bytes -- can race another worker's read, and
one that leaves different bytes dirties a committed record (issue #671).
The rule is closed rather than listed: every file under `status/evidence/` is
snapshotted (bytes and mtime) when the session starts, and the session fails at
its end naming each file that changed, appeared or vanished. Under xdist the
controller does the check, so a write by any worker is seen.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from pathlib import Path

import pytest

from integral import connectors

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


@pytest.fixture(scope="module")
def memoised_connector_parsing() -> Iterator[None]:
    """Parse each distinct connector YAML and each distinct captured page once.

    Opt-in per test module (`pytestmark = pytest.mark.usefixtures(...)`), never
    suite-wide: a file that tests `parse_connector` or `parse_html` themselves
    (error paths, call counts, patching them, or editing a returned `Node`)
    must not use it. Files that drive `source()` or the connector library over
    the whole installed set re-parsed ~30 connector YAMLs and re-tokenised the
    same recorded list pages on every call; profiling showed that, not any
    wait, was most of their time. Both steps are pure functions of their text,
    memoised on it. `parse_connector` returns a frozen `Connector`.
    `parse_html` returns a `Node` tree that is mutable in type but only read
    after the builder returns it, and no file that opts in touches a `Node`.
    An input that raises is never cached. The memo is module-scoped and removed
    at module teardown, so it cannot reach another file.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(connectors, "parse_connector", functools.cache(connectors.parse_connector))
        patch.setattr(connectors, "parse_html", functools.cache(connectors.parse_html))
        yield
