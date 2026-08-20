"""T55 — the rename to `integral-job-search`, measured rather than believed.

The four tests the task payload names, plus the ones that keep the counter
honest: a reference counter reaches zero either by finishing the sweep or by
looking in the wrong place, and only the second kind is silent.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from integral.naming import (
    ALLOWLIST,
    DISTRIBUTION_NAME,
    NEW_PACKAGE,
    NEW_REPOSITORY,
    OLD_PACKAGE,
    OLD_REPOSITORY,
    WHEEL_PACKAGE,
    NamingError,
    measure,
    write_evidence,
)
from integral.naming import (
    _main as main,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def measured() -> dict[str, object]:
    return measure(REPO_ROOT)


def test_no_module_imports_the_old_package_name(measured: dict[str, object]) -> None:
    """The package is `integral`. Nothing outside the allowlist still says otherwise."""
    assert measured["old_package_references"] == 0, measured["package_reference_sites"]
    assert not (REPO_ROOT / "src" / OLD_PACKAGE).exists()
    assert (REPO_ROOT / "src" / NEW_PACKAGE / "__init__.py").is_file()


def test_no_document_names_the_old_repository(measured: dict[str, object]) -> None:
    """The worse half of a half-finished rename: prose pointing at a dead URL."""
    assert measured["old_repository_references"] == 0, measured["repository_reference_sites"]
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"github.com/nuncaeslupus/{NEW_REPOSITORY}.git" in readme


def test_the_console_entry_point_matches_the_distribution_name() -> None:
    """The distribution, the wheel's package, and any script all name the same thing.

    There is no `[project.scripts]` table yet — `docs/distribution.md` §1 installs
    the project and invokes modules with `python -m`. The assertion is written to
    cover the table rather than to assume it stays empty, so the first entry
    point somebody adds is checked on the commit that adds it.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == DISTRIBUTION_NAME
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [WHEEL_PACKAGE]
    for name, target in pyproject["project"].get("scripts", {}).items():
        assert target.split(":")[0].split(".")[0] == NEW_PACKAGE, name


def test_the_preserved_names_are_not_swept() -> None:
    """Four names spelled like the old one that the rename must leave alone."""
    # `$INTEGRAL_HOME` was written under the settled name by T51, before this.
    assert "INTEGRAL_HOME" in (REPO_ROOT / "src" / NEW_PACKAGE / "state_home.py").read_text(
        encoding="utf-8"
    )
    # The vendored bundle keeps its own name.
    assert (REPO_ROOT / "claude-arsenal" / "AGENTS.md").is_file()
    # The thirteen step skills are named after the process, not the project.
    steps = sorted((REPO_ROOT / ".claude" / "skills").glob("step-*"))
    assert len(steps) == 13
    assert all(step.is_dir() for step in steps)
    # And the external precedent `status/specification.md` compares against.
    assert "ai-job-search" in (REPO_ROOT / "status" / "specification.md").read_text(
        encoding="utf-8"
    )


def test_the_process_name_is_not_a_repository_reference(tmp_path: Path) -> None:
    """`job-search process` is the process, and survives the sweep unchanged."""
    _git_init(tmp_path)
    text = "step 3 of the job-search process\nthe job-search\nprocess again\n"
    _commit(tmp_path, "SKILL.md", text)
    assert measure(tmp_path)["old_repository_references"] == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Extend ai-job-search in place", 0),  # a different project
        ("var NS = 'job-search-spec-v1:';", 0),  # a localStorage key, not a name
        ("clone https://github.com/nuncaeslupus/job-search.git", 1),
        ("cd job-search", 1),
        ("import jobsearch.harness", 1),
    ],
)
def test_the_counter_separates_the_name_from_its_lookalikes(
    tmp_path: Path, text: str, expected: int
) -> None:
    _git_init(tmp_path)
    _commit(tmp_path, "doc.md", text + "\n")
    assert measure(tmp_path)["old_name_references"] == expected


def test_an_allowlisted_path_is_not_counted(tmp_path: Path) -> None:
    """The ledger's historical rows keep saying what they said at the time."""
    _git_init(tmp_path)
    _commit(tmp_path, "arsenal/tasks/_history/lo-0000.md", "ran `python -m jobsearch.harness`\n")
    assert measure(tmp_path)["old_name_references"] == 0
    assert all(entry.rstrip("/") for entry in ALLOWLIST)


def test_a_tree_git_cannot_read_raises_rather_than_measuring_zero(tmp_path: Path) -> None:
    """The failure #189 taught: an unmeasurable gate must not report a clean pass."""
    with pytest.raises(NamingError):
        measure(tmp_path)


def test_main_writes_the_evidence_and_reports_the_count(tmp_path: Path) -> None:
    evidence = tmp_path / "T55.json"
    assert main(["naming", str(evidence), "--repo", str(REPO_ROOT)]) == 0
    assert evidence.is_file()

    dirty = tmp_path / "checkout"
    dirty.mkdir()
    _git_init(dirty)
    _commit(dirty, "README.md", "cd job-search\n")
    assert main(["naming", str(tmp_path / "dirty.json"), "--repo", str(dirty)]) == 1
    assert main(["naming", "--repo", str(tmp_path / "absent")]) == 3
    assert main(["naming", "--repo"]) == 2


def test_write_evidence_records_what_measure_found(tmp_path: Path) -> None:
    written = write_evidence(tmp_path / "nested" / "T55.json", REPO_ROOT)
    assert written == measure(REPO_ROOT)
    assert OLD_PACKAGE not in NEW_PACKAGE
    assert OLD_REPOSITORY in NEW_REPOSITORY  # the new name contains the old word


def _git_init(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)


def _commit(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", relative], check=True)
