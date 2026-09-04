"""T121: the local substitute for CI must still be a substitute.

Half of this file reads the script's text, and text-reading cannot tell you the
script *works*. The other half runs it — against a real commit, against a tree
whose gate genuinely fails, and against a repo that has an `origin` — because a
check on a check is worth nothing if nobody ever ran the thing being checked.

The cases marked `#333, F<n>` are the ones a second reader derived from the
report on PR #333 before the fixes were written. Each was measured red against
the shipped implementation, which is what makes them evidence rather than a
description of the code that is here now.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "tools" / "verified_gate.sh"
_SRC = _ROOT / "src" / "integral"

from integral import verified_gate as vg  # noqa: E402

_DELEGATING = "make host-gate\n"
_ENUMERATING = "make lint\nmake test\n"

# The whole point of F1: every occurrence of the aggregate's name is prose. A
# script like this runs no gate at all, and the shipped checker scored it clean.
_COMMENTS_ONLY = (
    "#!/usr/bin/env bash\n"
    "# It runs `make host-gate` and nothing else, deliberately.\n"
    "# rev-parse --verify, worktree add --detach, __pycache__, commit ${sha}\n"
)


def _mutate(find: str, replace: str) -> str:
    """The committed script with one substring replaced.

    Derived from the real file rather than written out, so a case cannot quietly
    stop describing the thing it is about.
    """
    script = _SCRIPT.read_text(encoding="utf-8")
    assert find in script, f"the script no longer contains {find!r}; this case is stale"
    return script.replace(find, replace)


def _measure_text(tmp_path: Path, script_text: str) -> dict[str, Any]:
    """Measure a script body as if it were the committed one.

    The instructions file is written to name it, so `undocumented` stays 0 and
    the only number that moves is the one the case is about.
    """
    script = tmp_path / "verified_gate.sh"
    script.write_text(script_text, encoding="utf-8")
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("Run `verified_gate.sh` before merging.\n", encoding="utf-8")
    return vg.measure(script_path=script, instructions=instructions)


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
    script = vg.executable_text(_SCRIPT.read_text(encoding="utf-8"))
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
    script = re.sub(pattern, "REMOVED", _SCRIPT.read_text(encoding="utf-8"))
    missing = vg.missing_properties(script)
    assert any(name in entry for entry in missing), f"dropping `{name}` went unreported"


# --------------------------------------------------------------------------
# #333, F1 — the properties are claims about CODE, and a comment is not code.
# All three of these scored `verified_gate_defects == 0` against the checker
# that shipped in fd933ec, because `make\s+host-gate` was searched over the
# whole file and the script's own header said it twice.
# --------------------------------------------------------------------------


def test_a_script_whose_only_gate_command_is_a_comment_is_reported(
    tmp_path: Path,
) -> None:
    """F1, the pure case: prose naming the aggregate, and no gate anywhere.

    Nothing here runs. The old checker read `make host-gate` out of the comments
    and returned an empty `host_gate_targets_not_run` — the field its own
    docstring called the drift guard.
    """
    measured = _measure_text(tmp_path, _COMMENTS_ONLY)
    assert measured["host_gate_targets_not_run"] == [
        "evidence",
        "lint",
        "test",
        "verify-gates",
    ]
    assert measured["verified_gate_defects"] > 0
    # Nothing executable was read, so nothing was evaluated — and a clean zero
    # over zero properties is what the floor exists to refuse.
    assert measured["verified_gate_properties_checked"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_declaring_the_aggregate_and_running_a_subset_is_reported(
    tmp_path: Path,
) -> None:
    """F1, mutation 1: the run line says `make lint`, the block still says the
    aggregate. Measured against fd933ec: 0 defects, and a verdict block that
    asserted it had run `make host-gate`."""
    measured = _measure_text(
        tmp_path,
        _mutate('( cd "${tree}" && ${gate_command} )', '( cd "${tree}" && make lint )'),
    )
    assert any(
        "runs that command, in the checked-out tree" in entry
        for entry in measured["missing_properties"]
    ), measured["missing_properties"]
    assert measured["verified_gate_defects"] > 0


def test_changing_the_declared_command_to_a_subset_is_counted(tmp_path: Path) -> None:
    """F1, mutation 1 at the declaration instead: what the script runs *and*
    what it reports both become `make lint`, so the drift guard has to be the
    thing that catches it — and now does, by naming the three dropped targets."""
    measured = _measure_text(
        tmp_path, _mutate('gate_command="make host-gate"', 'gate_command="make lint"')
    )
    assert measured["host_gate_targets_not_run"] == ["evidence", "test", "verify-gates"]
    assert any(
        "delegates to the aggregate target" in entry
        for entry in measured["missing_properties"]
    )


def test_deleting_the_gate_run_and_hard_coding_a_pass_is_reported(
    tmp_path: Path,
) -> None:
    """F1, mutation 2: no gate is ever run and every verdict prints PASS.

    The maximal failure this module exists to catch, and the shipped checker
    scored it `verified_gate_defects == 0`.
    """
    measured = _measure_text(
        tmp_path,
        _mutate(
            '( cd "${tree}" && ${gate_command} ) >"${log}" 2>&1\nstatus=$?',
            "status=0",
        ),
    )
    assert any(
        "runs that command, in the checked-out tree" in entry
        for entry in measured["missing_properties"]
    ), measured["missing_properties"]
    assert measured["verified_gate_defects"] > 0


def test_a_verdict_block_that_hard_codes_the_command_is_reported(
    tmp_path: Path,
) -> None:
    """F1, the compounding half: the block printed `make host-gate`
    unconditionally, so a mutated script pasted a verdict claiming it had run
    the aggregate. The block must echo the variable that actually ran."""
    measured = _measure_text(
        tmp_path,
        _mutate('echo "command   ${gate_command}', 'echo "command   make host-gate'),
    )
    assert any(
        "reports the command it actually ran" in entry
        for entry in measured["missing_properties"]
    ), measured["missing_properties"]


def test_enumerating_the_targets_instead_of_delegating_is_counted(
    tmp_path: Path,
) -> None:
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
    # …and the same four lines behind a `#` are prose, not a delegation.
    assert vg.host_gate_targets_not_run("# " + _DELEGATING, makefile) == [
        "evidence",
        "lint",
        "test",
        "verify-gates",
    ]


def test_a_missing_script_is_a_defect_and_not_an_honest_unmeasured(
    tmp_path: Path,
) -> None:
    # -1 rather than `unmeasured`, and `_main` exits 1 on it. "The substitute
    # CLAUDE.md tells sessions to merge on is gone" is the maximal failure, not
    # a gate that cannot be scored yet.
    measured = vg.measure(script_path=tmp_path / "absent.sh")
    assert measured["verified_gate_defects"] == -1
    # #333, F5: this used to record `unmeasured` while `_main` returned 1. In
    # this repository `unmeasured` means the check ran and cannot be scored yet,
    # it is signalled by exit 3, and `make evidence` records it and CONTINUES —
    # so the record asserted the opposite of what the code had decided. The
    # check DID run; its answer is that the script is gone.
    assert measured["gate_status"] == "measured"
    assert (
        vg._main(
            ["verified_gate", str(tmp_path / "out.json"), "--script", str(tmp_path / "absent.sh")]
        )
        == 1
    )


def test_prose_that_names_no_script_is_reported(tmp_path: Path) -> None:
    instructions = tmp_path / "CLAUDE.md"
    instructions.write_text("Run the gate locally before merging.\n", encoding="utf-8")
    measured = vg.measure(instructions=instructions)
    assert measured["undocumented"] != []
    assert measured["verified_gate_defects"] >= 1


# --------------------------------------------------------------------------
# #333, F3 — the floor was `x < x`.
# --------------------------------------------------------------------------


def test_the_floor_is_a_literal_the_table_cannot_drag() -> None:
    """`MINIMUM_PROPERTIES` was `len(REQUIRED_PROPERTIES)` and the number it
    guarded was `len(REQUIRED_PROPERTIES)` too, so the guard compared an
    expression to itself: unreachable, and deleting entries shrank both sides
    together. `naming.MINIMUM_SCANNED` is a literal for the same reason."""
    source = (_SRC / "verified_gate.py").read_text(encoding="utf-8")
    assert re.search(
        r"^MINIMUM_PROPERTIES = \d+$", source, re.MULTILINE
    ), "the floor must be a literal, not derived from the table it guards"
    assert len(vg.REQUIRED_PROPERTIES) >= vg.MINIMUM_PROPERTIES


def test_a_shrunken_table_trips_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting most of the table leaves a clean zero over three properties.

    Against fd933ec this was impossible to write: the floor moved with the
    table. `_main` returns 3 — `make evidence`'s "unmeasured (recorded)" — which
    is the honest verdict for a scan too thin to mean anything.
    """
    monkeypatch.setattr(vg, "REQUIRED_PROPERTIES", vg.REQUIRED_PROPERTIES[:3])
    measured = vg.measure()
    assert measured["verified_gate_defects"] == 0
    assert measured["verified_gate_properties_checked"] == 3
    out = tmp_path / "out.json"
    assert vg._main(["verified_gate", str(out)]) == 3
    assert json.loads(out.read_text(encoding="utf-8"))["verified_gate_properties_checked"] == 3


# --------------------------------------------------------------------------
# #333, F4 — `--script X` wrote the evidence JSON over X.
# --------------------------------------------------------------------------


def test_naming_a_script_does_not_overwrite_it(tmp_path: Path) -> None:
    """The invocation the module's own docstring documents.

    Measured against fd933ec: a 4189-byte copy of the script became a 230-byte
    JSON file, rc 0, no warning — because the flag's VALUE was left standing as
    the first positional, and the first positional is the evidence path.
    `naming.py` removes the flag and its value, and defaults the target to None
    when it is measuring another tree; this now does both.
    """
    script = tmp_path / "verified_gate.sh"
    script.write_bytes(_SCRIPT.read_bytes())
    before = script.read_bytes()

    assert vg._main(["verified_gate", "--script", str(script)]) == 0

    assert script.read_bytes() == before, "the measurement overwrote its own subject"
    assert list(tmp_path.iterdir()) == [script], (
        "measuring another tree recorded evidence about this repository"
    )


def test_measuring_another_tree_records_nothing_about_this_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half of `naming --repo`'s rule that F4's fix has to carry too.

    `naming.py:361-362` sets `default_target = None` when it is measuring some
    other checkout, because a measurement of another tree is not evidence about
    this repository and recording it unconditionally is how a committed number
    gets replaced by the answer to a different question. This module took only
    the flag idiom, and not that.
    """
    script = tmp_path / "verified_gate.sh"
    script.write_text(
        _mutate('gate_command="make host-gate"', 'gate_command="make lint"'),
        encoding="utf-8",
    )
    stand_in = tmp_path / "T121.json"
    monkeypatch.setattr(vg, "DEFAULT_EVIDENCE_PATH", stand_in)

    assert vg._main(["verified_gate", "--script", str(script)]) == 1

    assert not stand_in.exists(), (
        "a measurement of some other script was recorded as this repository's evidence"
    )


def test_an_explicit_target_still_records_when_a_script_is_named(tmp_path: Path) -> None:
    # The other half of `naming`'s rule: writing is refused by default, not
    # forbidden. A caller that says where may still record.
    script = tmp_path / "verified_gate.sh"
    script.write_bytes(_SCRIPT.read_bytes())
    out = tmp_path / "out.json"
    assert vg._main(["verified_gate", str(out), "--script", str(script)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["verified_gate_defects"] == 0


@pytest.mark.parametrize("flag", ["--script", "--instructions"])
def test_a_trailing_flag_with_no_value_exits_2(
    flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # `argv[argv.index(name) + 1]` raised IndexError. `naming.py:353-356`
    # returns 2 with a message, and 2 is this repository's "nothing measured".
    assert vg._main(["verified_gate", flag]) == 2
    assert "needs a path" in capsys.readouterr().err


# --------------------------------------------------------------------------
# #333, F6 — the header credited a module that never mentions this script.
# --------------------------------------------------------------------------


def test_the_header_credits_a_module_that_actually_reads_this_script() -> None:
    header = _SCRIPT.read_text(encoding="utf-8")
    credited = re.findall(r"`integral\.(\w+)` asserts", header)
    assert credited, "the header names no module as checking this file"
    for module in credited:
        source = (_SRC / f"{module}.py").read_text(encoding="utf-8")
        assert "verified_gate" in source, (
            f"the header says `integral.{module}` asserts this file's shape, and "
            f"integral/{module}.py does not mention it"
        )


# --------------------------------------------------------------------------
# Functional. A grep is not a proof.
# --------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _throwaway_repo(tmp_path: Path, gate_body: str) -> Path:
    """A git repo of one file whose `host-gate` does whatever we say.

    Running the script against *this* repository takes 162 seconds and proves
    only that this tree is green, which `make host-gate` already says. What
    needs proving is the script's own logic, and that is cheap.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Makefile").write_text(f"host-gate:\n{gate_body}\n", encoding="utf-8")
    _git("git", "init", "-q", "-b", "main", cwd=root)
    _git("git", "config", "user.email", "t@example.invalid", cwd=root)
    _git("git", "config", "user.name", "t", cwd=root)
    _git("git", "add", "-A", cwd=root)
    _git("git", "commit", "-qm", "initial", cwd=root)
    return root


def _repo_with_an_origin(tmp_path: Path) -> tuple[Path, str, str]:
    """A clone whose `origin` carries a PASSING gate on its default branch, and
    whose checked-out branch carries a FAILING one.

    Every functional test before #333 used a repo with no remote at all, so
    `git fetch origin …` always failed there and the `FETCH_HEAD` branch of the
    resolution — the branch that produced F2 — was never once executed.

    Returns `(clone, origin's main SHA, the local branch's SHA)`.
    """
    bare = tmp_path / "upstream.git"
    _git("git", "init", "-q", "--bare", str(bare), cwd=tmp_path)
    # `git init --bare` points HEAD at `master`; GitHub points it at the default
    # branch, and `git fetch origin HEAD` only resolves when it does.
    _git("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=bare)

    seed = _throwaway_repo(tmp_path, "\t@echo 'evidence: no drift'")
    _git("git", "remote", "add", "origin", str(bare), cwd=seed)
    _git("git", "push", "-q", "origin", "main", cwd=seed)
    upstream_sha = _git("git", "rev-parse", "HEAD", cwd=seed)

    clone = tmp_path / "clone"
    _git("git", "clone", "-q", str(bare), str(clone), cwd=tmp_path)
    _git("git", "config", "user.email", "t@example.invalid", cwd=clone)
    _git("git", "config", "user.name", "t", cwd=clone)
    _git("git", "checkout", "-qb", "feature", cwd=clone)
    (clone / "Makefile").write_text("host-gate:\n\t@echo boom; exit 1\n", encoding="utf-8")
    _git("git", "add", "-A", cwd=clone)
    _git("git", "commit", "-qm", "a gate that genuinely fails", cwd=clone)
    return clone, upstream_sha, _git("git", "rev-parse", "HEAD", cwd=clone)


def _run_script(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT), *args], cwd=root, capture_output=True, text=True
    )


def test_it_measures_the_committed_commit_and_not_the_working_tree(tmp_path: Path) -> None:
    """The property the whole script exists for, asserted rather than argued.

    The committed `host-gate` passes. The working tree is then edited so that a
    `make host-gate` run *where the caller stands* would fail. The script must
    still report PASS, because it measures the commit — and it must name that
    commit, so the verdict can be checked against the pull request head later.
    """
    root = _throwaway_repo(tmp_path, "\t@echo 'evidence: no drift'")
    head = _git("git", "rev-parse", "HEAD", cwd=root)

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
    listed = _git("git", "worktree", "list", cwd=root)
    assert listed.count("\n") == 0, f"a worktree survived the run:\n{listed}"


# --------------------------------------------------------------------------
# #333, F2 — the no-argument default measured origin's default branch.
# These are the first cases in this file to run against a repo with a remote.
# --------------------------------------------------------------------------


def test_the_no_argument_default_measures_the_caller_not_origins_default_branch(
    tmp_path: Path,
) -> None:
    """Measured against fd933ec, standing on a branch whose committed gate
    genuinely fails: `bash tools/verified_gate.sh` printed
    `commit <origin/main>` and `verdict PASS`, exit 0.

    `git fetch origin HEAD` SUCCEEDS — it resolves to the remote's default
    branch — and the old resolution preferred `FETCH_HEAD` over the local ref.
    """
    clone, upstream_sha, local_sha = _repo_with_an_origin(tmp_path)
    ran = _run_script(clone)
    assert upstream_sha not in ran.stdout, (
        "the no-argument form measured origin's default branch:\n" + ran.stdout
    )
    assert local_sha in ran.stdout
    assert "FAIL" in ran.stdout and "PASS" not in ran.stdout
    assert ran.returncode == 1


def test_an_explicit_remote_ref_is_resolved_by_fetching_it(tmp_path: Path) -> None:
    """The `FETCH_HEAD` branch of the resolution, which no test reached before.

    `main` is not checked out in the clone and its content differs from the
    working tree, so a PASS here can only come from the fetched commit.
    """
    clone, upstream_sha, local_sha = _repo_with_an_origin(tmp_path)
    ran = _run_script(clone, "main")
    assert ran.returncode == 0, ran.stdout
    assert upstream_sha in ran.stdout
    assert local_sha not in ran.stdout
    assert "PASS" in ran.stdout
    assert "resolved  origin, fetched just now" in ran.stdout


def test_the_block_says_whether_the_commit_is_on_origin(tmp_path: Path) -> None:
    """F2b: `|| true` swallows a failed fetch and the script falls back to the
    local ref, while the block went on describing "the pushed commit". A commit
    that is on no `origin/*` ref must be labelled as one."""
    clone, _upstream, _local = _repo_with_an_origin(tmp_path)
    unpushed = _run_script(clone)
    assert "on origin NO" in unpushed.stdout

    pushed = _run_script(clone, "main")
    assert "on origin yes — reachable from origin/main" in pushed.stdout
