"""T55 — the rename to `integral-job-search`, measured rather than believed.

The four tests the task payload names, plus the ones that keep the counter
honest: a reference counter reaches zero either by finishing the sweep or by
looking in the wrong place, and only the second kind is silent.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from integral import naming
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


def test_a_live_task_file_is_counted_even_though_its_archive_is_not(tmp_path: Path) -> None:
    """The allowlist covers the ledger's archive, never its live rows.

    It first read `arsenal/`, which also hid `arsenal/tasks/*.md` and
    `arsenal/config.toml`. Eight live task files still named `jobsearch.*`
    after T55, two of them inside fenced gate blocks — commands that no longer
    run — and this counter reported zero. A gate block is not history.
    """
    _git_init(tmp_path)
    _commit(tmp_path, "arsenal/tasks/t-0000.md", "uv run python -m jobsearch.extraction\n")
    _commit(tmp_path, "arsenal/config.toml", "# jobsearch.skill_budget reads this key\n")
    assert measure(tmp_path)["old_name_references"] == 2


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


def test_a_recorded_capture_is_evidence_and_is_never_swept() -> None:
    """A connector fixture is somebody else's page, recorded. Remotive serves a
    `job-search.css` and a `/job-search-tips/` blog tag; editing a capture so it
    stops saying so would falsify what the fixture exists to prove, and this
    rename has nothing to do with what a third party names its own URLs."""
    assert naming._is_allowlisted("connectors/remotive_en/probe/list.html")
    assert naming._is_allowlisted("connectors/remotive_en/fixture/detail.html")
    # …and the connector's own files are still swept, because those are ours.
    assert not naming._is_allowlisted("connectors/remotive_en/connector.yaml")
    assert not naming._is_allowlisted("connectors/remotive_en/meta.yaml")
    assert not naming._is_allowlisted("docs/fixture/notes.md")


# ---------------------------------------------------------------------------
# T100 — a denominator committed as an exact value.
#
# `files_scanned` counts tracked files, `arsenal/tasks/_history/` is
# allowlisted, and archiving a task file therefore moves the count by one.
# `open_task_pr.sh` archives the task file and then runs the host gate, so the
# committed evidence had to hold the value from before the move *and* the
# value from after it. It could not, and no task PR opened between #257 and
# #282 without the number being hand-corrected first.
# ---------------------------------------------------------------------------


def test_files_scanned_is_asserted_as_a_floor_not_a_census() -> None:
    """The record carries a denominator, and it is the floor that was
    checked rather than the count of the day.

    A census is not a measurement of anything about the code — it moves when
    any tracked file is added, which is drift with no finding behind it. What
    the denominator is *for* is stopping a clean zero resting on an empty
    scan, and a floor does that job without moving.
    """
    measured = naming.measure()
    record = naming.record(measured)

    assert record["files_scanned_at_least"] == naming.MINIMUM_SCANNED
    # The live count is not lost — it is simply not the thing committed.
    assert measured["files_scanned"] >= naming.MINIMUM_SCANNED
    assert "files_scanned" not in record


def test_an_empty_scan_still_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The dishonest-zero guard survives the change — it is the whole reason
    the denominator exists, and replacing an exact value with a floor must not
    quietly replace it with nothing."""
    _git_init(tmp_path)
    _commit(tmp_path, "claude-arsenal/note.md", "everything here is allowlisted\n")

    exit_code = naming._main(["naming", str(tmp_path / "T55.json"), "--repo", str(tmp_path)])

    assert exit_code == 3
    assert "floor" in capsys.readouterr().err


def test_archiving_a_task_file_does_not_change_any_asserted_value() -> None:
    """The property the whole task exists for, measured without moving
    anything: a file under `arsenal/tasks/_history/` is allowlisted, so
    archiving is exactly "this path stops being scanned"."""
    live = naming.record(naming.measure())
    one = naming.first_task_file()
    assert one is not None
    archived = naming.record(naming.measure(archived=frozenset({one})))

    assert live == archived


def test_a_census_committed_as_an_exact_value_is_reported_sensitive() -> None:
    """The gate, shown failing. Put the count back and the metric finds it —
    otherwise `archive_sensitive_evidence_keys == 0` would hold over a record
    that simply stopped carrying the sensitive key rather than fixing it."""
    census = dict(naming.record(naming.measure()))
    census["files_scanned"] = 623

    assert naming.sensitive_keys(census, {**census, "files_scanned": 622}) == ["files_scanned"]


def test_the_archive_gate_counts_the_keys_it_compared() -> None:
    """A zero over nothing compared is the failure this repository's gates are
    built around. The denominator is asserted here too."""
    measured = naming.measure_archive_sensitivity()

    assert measured["archive_sensitive_evidence_keys"] == 0
    assert measured["evidence_keys_compared"] >= len(naming.record(naming.measure()))
    assert measured["gate_status"] == "measured"


def test_which_file_was_archived_is_reported_but_not_committed(tmp_path: Path) -> None:
    """`first_task_file` returns the sorted-first *live* task, so committing its
    name made T100's own record go stale the moment that task merged — the very
    defect T100 measures. The caller still gets the name for its message."""
    target = tmp_path / "T100.json"
    # Non-null, and the file the gate actually picked. `in measured` passed
    # over the `None` a repository with no live task file returns, so the test
    # proved a key rather than a filename — D-3's tautology, one file over.
    expected = naming.first_task_file()
    assert expected is not None
    measured = naming.write_archive_sensitivity_evidence(target)

    assert measured["archived_for_the_comparison"] == expected
    assert "archived_for_the_comparison" not in json.loads(target.read_text(encoding="utf-8"))


def test_the_archive_gate_is_unmeasured_when_there_is_no_task_file_to_archive(
    tmp_path: Path,
) -> None:
    """No task file, nothing to move, nothing proved. Not a pass."""
    _git_init(tmp_path)
    _commit(tmp_path, "docs/readme.md", "nothing to archive here\n")

    measured = naming.measure_archive_sensitivity(tmp_path)

    assert measured["evidence_keys_compared"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_file_chosen_for_the_comparison_is_one_the_sweep_actually_scans() -> None:
    """`arsenal/tasks/_migrated-history.md` is allowlisted already, so
    archiving it moves nothing and the comparison compares a tree with itself
    — `measured` over a no-op, which is the one thing a gate here may not do."""
    chosen = naming.first_task_file()

    assert chosen is not None
    assert not naming._is_allowlisted(chosen)
    assert naming.measure(archived=frozenset({chosen}))["files_scanned"] == (
        naming.measure()["files_scanned"] - 1
    )


def test_main_does_not_pass_when_nothing_could_be_archived(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Found by review on #284, and it is this task's own subject turned on
    its own exit code: zero sensitive keys over no comparison is zero, so a
    checkout with no live task file reported success over a check that never
    ran. Exit 3 — not a pass and not a fail."""
    _git_init(tmp_path)
    for n in range(naming.MINIMUM_SCANNED + 1):
        _commit(tmp_path, f"docs/page-{n}.md", "nothing to archive here\n")

    exit_code = naming._main(["naming", str(tmp_path / "T55.json"), "--repo", str(tmp_path)])

    assert exit_code == 3
    assert "UNMEASURED" in capsys.readouterr().err
    assert (tmp_path / "T100.json").is_file()
