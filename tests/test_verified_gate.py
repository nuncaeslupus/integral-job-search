"""T121: the local substitute for CI must still be a substitute.

Half of this file reads the script's text, and text-reading cannot tell you the
script *works*. The other half runs it — against a real commit, and against a
tree whose gate genuinely fails — because a check on a check is worth nothing if
nobody ever ran the thing being checked.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from integral import verified_gate as vg

_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "verified_gate.sh"

_DELEGATING = "make host-gate\n"
_ENUMERATING = "make lint\nmake test\n"


def test_the_script_exists_and_is_executable() -> None:
    assert _SCRIPT.exists()
    assert _SCRIPT.stat().st_mode & 0o111, "a script nobody can run is not a substitute"


def test_the_committed_script_has_no_defects() -> None:
    measured = vg.measure()
    assert measured["host_gate_targets_not_run"] == []
    assert measured["missing_properties"] == []
    assert measured["undocumented"] == []
    assert measured["verified_gate_defects"] == 0
    assert measured["gate_status"] == "measured"


def test_every_required_property_is_present_in_the_real_script() -> None:
    # Named individually so a failure says which claim the script stopped
    # supporting, rather than only that the count moved.
    script = _SCRIPT.read_text(encoding="utf-8")
    for name, pattern, _why in vg.REQUIRED_PROPERTIES:
        assert re.search(pattern, script), f"the script no longer {name}"


@pytest.mark.parametrize(
    ("name", "pattern", "why"),
    vg.REQUIRED_PROPERTIES,
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_removing_any_one_property_is_reported_by_name(
    name: str, pattern: str, why: str
) -> None:
    # The anti-vacuity direction: a checker that reports zero over a script it
    # cannot actually read would pass `test_the_committed_script_has_no_defects`
    # exactly as well as a working one.
    # Every occurrence, not the first: two of these patterns appear in the
    # script's own explanatory comments as well as in its code, and removing one
    # of two leaves the checker able to find the other — a mutation that proves
    # nothing while looking like it passed.
    script = re.sub(pattern, "REMOVED", _SCRIPT.read_text(encoding="utf-8"))
    missing = vg.missing_properties(script)
    assert any(name in entry for entry in missing), f"dropping `{name}` went unreported"


def test_enumerating_the_targets_instead_of_delegating_is_counted(tmp_path: Path) -> None:
    """The drift D-22 is about, one layer out.

    `make host-gate` reaches four targets. A script that lists two of them is a
    second definition of the gate, free to fall behind the Makefile — so the two
    it dropped are the measurement.
    """
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "host-gate: lint test evidence verify-gates\n\t@true\n"
        "lint:\n\t@true\ntest:\n\t@true\nevidence:\n\t@true\nverify-gates:\n\t@true\n",
        encoding="utf-8",
    )
    assert vg.host_gate_targets_not_run(_DELEGATING, makefile) == []
    dropped = vg.host_gate_targets_not_run(_ENUMERATING, makefile)
    assert dropped == ["evidence", "verify-gates"]


def test_a_missing_script_is_a_defect_and_not_an_honest_unmeasured(tmp_path: Path) -> None:
    # -1 rather than `unmeasured`, and `_main` exits 1 on it. "The substitute
    # CLAUDE.md tells sessions to merge on is gone" is the maximal failure, not
    # a gate that cannot be scored yet.
    measured = vg.measure(script_path=tmp_path / "absent.sh")
    assert measured["verified_gate_defects"] == -1
    assert measured["gate_status"] == "unmeasured"
    assert (
        vg._main(
            ["verified_gate", str(tmp_path / "out.json"), "--script", str(tmp_path / "absent.sh")]
        )
        != 0
    )


def test_prose_that_names_no_script_is_reported(tmp_path: Path) -> None:
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("Run the gate locally before merging.\n", encoding="utf-8")
    measured = vg.measure(instructions=instructions)
    assert measured["undocumented"] != []
    assert measured["verified_gate_defects"] >= 1


def test_the_floor_matches_the_properties_actually_declared() -> None:
    # A floor written as a literal drifts from the table it guards; this is the
    # one place both can be compared.
    assert len(vg.REQUIRED_PROPERTIES) == vg.MINIMUM_PROPERTIES
    assert vg.measure()["verified_gate_properties_checked"] >= vg.MINIMUM_PROPERTIES


def _throwaway_repo(tmp_path: Path, gate_body: str) -> Path:
    """A git repo of one file whose `host-gate` does whatever we say.

    Running the script against *this* repository takes four minutes and proves
    only that this tree is green, which `make host-gate` already says. What
    needs proving is the script's own logic, and that is cheap.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Makefile").write_text(f"host-gate:\n{gate_body}\n", encoding="utf-8")

    def run(*args: str) -> None:
        subprocess.run(args, cwd=root, capture_output=True, text=True, check=True)

    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@example.invalid")
    run("git", "config", "user.name", "t")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "initial")
    return root


def _run_script(root: Path, ref: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(_SCRIPT), ref], cwd=root, capture_output=True, text=True)


def test_it_measures_the_committed_commit_and_not_the_working_tree(tmp_path: Path) -> None:
    """The property the whole script exists for, asserted rather than argued.

    The committed `host-gate` passes. The working tree is then edited so that a
    `make host-gate` run *where the caller stands* would fail. The script must
    still report PASS, because it measures the commit — and it must name that
    commit, so the verdict can be checked against the pull request head later.
    """
    root = _throwaway_repo(tmp_path, "\t@echo 'evidence: no drift'")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()

    (root / "Makefile").write_text("host-gate:\n\t@exit 1\n", encoding="utf-8")
    (root / "untracked_junk.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    assert subprocess.run(["make", "host-gate"], cwd=root, capture_output=True).returncode != 0

    ran = _run_script(root, head)

    assert ran.returncode == 0, f"the dirty working tree leaked into the run:\n{ran.stdout}"
    assert "PASS" in ran.stdout
    assert head in ran.stdout, "the verdict must name the commit it measured"


def test_a_failing_gate_fails_the_script(tmp_path: Path) -> None:
    # Without this, the test above is satisfied by a script that always says PASS.
    root = _throwaway_repo(tmp_path, "\t@echo boom; exit 1")
    ran = _run_script(root, "HEAD")
    assert ran.returncode == 1
    assert "FAIL" in ran.stdout
    assert "failing output" in ran.stdout, "a failure must carry the output that caused it"


def test_an_unresolvable_ref_refuses_rather_than_measuring_something_else(
    tmp_path: Path,
) -> None:
    # The fail-open direction: falling through to a gate run over whatever tree
    # the script landed in would produce a green verdict for a commit that does
    # not exist.
    root = _throwaway_repo(tmp_path, "\t@true")
    ran = _run_script(root, "refs/heads/no-such-branch-anywhere")
    assert ran.returncode == 2
    assert "cannot resolve" in ran.stderr
    assert "PASS" not in ran.stdout


def test_it_leaves_no_worktree_behind(tmp_path: Path) -> None:
    root = _throwaway_repo(tmp_path, "\t@true")
    _run_script(root, "HEAD")
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    assert listed.count("\n") == 1, f"a worktree survived the run:\n{listed}"
