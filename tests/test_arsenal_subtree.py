"""`claude-arsenal/` is assembled from a real subtree, and stays that way.

The conversion (S9) exists to remove one specific failure: a vendored copy can
be hand-edited, the edit works perfectly, and the next upgrade silently reverts
it with nothing to say so. A subtree removes it only if the assembled bundle is
still checked against its source — otherwise the same drift returns with extra
directories.

So these hold three things: the bundle matches the subtree, the subtree is a
real one rather than a directory that looks like it, and the host-owned queue
never ends up inside a prefix an upgrade would overwrite. The negative cases
are exercised against a fixture tree, because a checker that only ever runs
against the real repository can only be tested on a state that already passes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = REPO_ROOT / "tools" / "verify_arsenal_subtree.py"

SUBTREE_PREFIX = Path("vendor/claude-arsenal")
ASSETS_SUBPATH = Path("plugins/core/skills/init/assets")
BUNDLE = Path("claude-arsenal")
HOST_OWNED = ("queue", "session", "project")
MINIMUM_ASSETS = 20


def _run(root: Path | None = None) -> tuple[int, dict[str, object]]:
    """Drive the verifier as CI does — through its CLI, not its internals."""
    argv = [sys.executable, str(VERIFIER)]
    if root is not None:
        argv += ["--root", str(root)]
    result = subprocess.run(argv, capture_output=True, text=True, cwd=REPO_ROOT)
    payload = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, payload


def _fixture_repo(tmp_path: Path) -> Path:
    """A miniature repo with a subtree prefix and an assembled bundle."""
    assets = tmp_path / SUBTREE_PREFIX / ASSETS_SUBPATH
    assets.mkdir(parents=True)
    bundle = tmp_path / BUNDLE
    (bundle / "bin").mkdir(parents=True)
    for index in range(MINIMUM_ASSETS + 2):
        name = Path("bin") / f"script_{index:02d}.sh"
        (assets / name).parent.mkdir(parents=True, exist_ok=True)
        (assets / name).write_text(f"#!/bin/sh\necho {index}\n", encoding="utf-8")
        (bundle / name).write_text(f"#!/bin/sh\necho {index}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "fixture"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def test_every_bundle_file_matches_the_subtree_source() -> None:
    """The real repository: `claude-arsenal/` is a faithful copy of the
    subtree's assets. A hand-edit to a bundled script would pass every test in
    this suite and then vanish at the next upgrade — this is the check that
    notices."""
    _, measured = _run()
    assert measured["diverging"] == []
    assert measured["missing_from_bundle"] == []
    assert measured["vendored_files_diverging_from_subtree"] == 0


def test_the_subtree_is_recorded_in_history_not_merely_copied() -> None:
    """A directory copied in by hand satisfies every file comparison while
    `git subtree pull` has nothing to pull. The history is the whole point of
    the conversion, so the history is what is asserted."""
    _, measured = _run()
    assert measured["subtree_recorded_in_history"] is True


def test_no_host_owned_path_is_inside_the_subtree_prefix() -> None:
    """`claude-arsenal/queue/` is the task ledger and every payload. Inside a
    subtree prefix, an upgrade would take it with them — losing the board."""
    _, measured = _run()
    assert measured["host_owned_inside_subtree"] == []
    for name in HOST_OWNED:
        assert not (REPO_ROOT / SUBTREE_PREFIX / name).exists()


def test_the_live_handover_is_excluded_and_says_so() -> None:
    """Upstream ships a template; this repo's copy is live session state
    rewritten every session. It is the one asset meant to diverge, and
    comparing it would make the check permanently red — a check that never
    passes is one nobody reads. Excluded deliberately, and recorded in the
    evidence so the exclusion is visible rather than silent."""
    _, measured = _run()
    assert measured["excluded"] == ["session/handover.md"]


def test_a_hand_edited_bundle_file_is_caught(tmp_path: Path) -> None:
    """The failure the whole check exists for. Without it the edit survives
    until an upgrade reverts it, and nothing anywhere reports either event."""
    root = _fixture_repo(tmp_path)
    assert _run(root)[1]["vendored_files_diverging_from_subtree"] == 0
    (root / BUNDLE / "bin" / "script_00.sh").write_text("#!/bin/sh\necho EDITED\n", "utf-8")
    _, measured = _run(root)
    assert measured["diverging"] == ["bin/script_00.sh"]
    assert measured["vendored_files_diverging_from_subtree"] == 1


def test_a_file_missing_from_the_bundle_is_caught(tmp_path: Path) -> None:
    """An asset that never got assembled is as broken as one that drifted, and
    is not visible by reading `claude-arsenal/` — only by comparison."""
    root = _fixture_repo(tmp_path)
    (root / BUNDLE / "bin" / "script_01.sh").unlink()
    assert _run(root)[1]["missing_from_bundle"] == ["bin/script_01.sh"]


def test_host_state_inside_the_prefix_is_caught(tmp_path: Path) -> None:
    """If the queue ever lands inside the subtree prefix, the next upgrade
    overwrites the ledger. Cheap to check, unrecoverable to miss."""
    root = _fixture_repo(tmp_path)
    (root / SUBTREE_PREFIX / "queue").mkdir(parents=True)
    _, measured = _run(root)
    assert measured["host_owned_inside_subtree"] == [f"{SUBTREE_PREFIX}/queue"]
    assert measured["vendored_files_diverging_from_subtree"] == 1


def test_a_missing_subtree_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """No subtree must exit 2, distinctly from 0. Reporting "nothing diverged"
    when there is nothing to compare against is how a check goes inert."""
    root = _fixture_repo(tmp_path)
    shutil.rmtree(root / SUBTREE_PREFIX)
    code, _ = _run(root)
    assert code == 2


def test_a_hand_added_bundle_file_upstream_never_heard_of_is_caught(tmp_path: Path) -> None:
    """`compare()` used to walk only source -> bundle, so a script hand-added to
    `claude-arsenal/bin/` (or one upstream deleted but that still lingers here)
    was invisible: every forward comparison passes, and the file keeps running
    forever, silently dropped by the next real upgrade. The reverse walk
    (bundle -> source) is what catches it."""
    root = _fixture_repo(tmp_path)
    (root / BUNDLE / "bin" / "rogue.sh").write_text("#!/bin/sh\necho rogue\n", "utf-8")
    _, measured = _run(root)
    assert measured["extra_in_bundle"] == ["bin/rogue.sh"]
    assert measured["vendored_files_diverging_from_subtree"] == 1


def test_host_owned_bundle_files_are_not_flagged_as_extra(tmp_path: Path) -> None:
    """`claude-arsenal/queue/`, `session/`, and `project/` legitimately hold
    dozens of files upstream has never heard of — the task ledger, live
    handover, workspace plans. The reverse walk must not treat host-owned
    content as a stray/hand-added file, or the check is permanently red on
    every real repository."""
    root = _fixture_repo(tmp_path)
    for name in HOST_OWNED:
        owned_dir = root / BUNDLE / name
        owned_dir.mkdir(parents=True, exist_ok=True)
        (owned_dir / "host-file.txt").write_text("host state\n", "utf-8")
    _, measured = _run(root)
    assert measured["extra_in_bundle"] == []
    assert measured["vendored_files_diverging_from_subtree"] == 0


def test_the_makefile_no_longer_pins_a_bare_sha() -> None:
    """`ARSENAL_SHA` existed because the old target ran upstream code straight
    from a fetched checkout, and a movable tag could not vouch for it. The
    subtree records the commit in this repository's own history, so a
    hand-copied hash is redundant — and a redundant pin is one that goes stale
    and starts lying."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "ARSENAL_SHA     ?=" not in makefile
    assert "ARSENAL_PREFIX" in makefile
    assert "git subtree pull" in makefile


def test_ci_runs_the_subtree_check() -> None:
    """A check nothing invokes protects nothing."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "\nverify-subtree:" in makefile
    assert "verify-subtree" in makefile.split("ci:", 1)[1].split("\n", 1)[0]


def _recipe(makefile: str, target: str) -> str:
    """The tab-indented recipe lines that follow a `target:` line, joined."""
    lines = makefile.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    recipe_lines: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            recipe_lines.append(line)
        else:
            break
    return "\n".join(recipe_lines)


def test_arsenal_upgrade_reassembles_the_bundle_before_verifying() -> None:
    """`update-skills` only rebuilds `.claude/skills/` — it never touches
    `claude-arsenal/`, which is exactly what `verify-subtree` then compares
    against. Without an explicit bundle-reassembly step, ANY upstream change to
    a bundle asset makes the advertised pull-reassemble-verify sequence fail at
    the verify step with the user having done nothing wrong. `update-skills`
    and `verify-subtree` alone are not enough — the reassembly step itself must
    run, and it must run after the pull and before the verify."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = _recipe(makefile, "arsenal-upgrade")
    pull_at = recipe.index("git subtree pull")
    # Not merely "does update-skills or verify-subtree appear" (both already
    # did on the broken Makefile) — a THIRD step, distinct from both, that
    # actually reassembles claude-arsenal/, positioned between the pull and
    # the verify.
    assert "update-skills" in recipe
    reassemble_at = recipe.index("assemble-bundle")
    verify_at = recipe.index("verify-subtree")
    assert pull_at < reassemble_at < verify_at
    # The reassembly target itself must run the real bundle-refresh logic
    # (init.py's own refresh, not a re-implementation of it) — otherwise the
    # name could exist while doing nothing.
    assemble_recipe = _recipe(makefile, "assemble-bundle")
    assert "init.py" in assemble_recipe
    assert "--repo-path" in assemble_recipe


def test_a_hand_copied_directory_is_not_accepted_as_a_subtree(tmp_path: Path) -> None:
    """`_fixture_repo` is exactly the failure `subtree_is_real`'s own docstring
    claims to catch: a plain `git init` plus an ordinary commit, with no real
    `git subtree add/pull --squash` anywhere in its history. The old check
    accepted any commit that merely touched the prefix path, so this fixture
    passed as a "real" subtree — proving the check did not do what it claimed.
    A hand-copied directory must read as not-a-subtree."""
    root = _fixture_repo(tmp_path)
    _, measured = _run(root)
    assert measured["subtree_recorded_in_history"] is False


def test_every_ci_job_checks_out_full_history() -> None:
    """The one place these checks must run is the one place they would silently
    not run.

    Two of them answer their question by reading git history, and a shallow
    checkout does not make either fail — it makes them stop measuring:

    - `subtree_is_real` proves a subtree by finding a `git-subtree-dir:`
      trailer in a commit message. At depth 1 there is no such commit, so it
      reports "cannot tell" and skips, which is correct for a developer's
      shallow clone and useless in CI.
    - `reader_notes` (T31) resolves each note back to the commit that last set
      its text and reparses the spec there. At depth 1 the walk finds only the
      tip, so every note trivially resolves to today's title and all 28 report
      `unchanged` — a clean result over nothing.

    Both reproduced by cloning this repository `--depth 1`, which
    `git rev-parse --is-shallow-repository` confirms is what `actions/checkout`
    produces by default. Asserted over *every* job rather than the two that
    need it today, because the next history-reading check will be added by
    somebody who has never read this docstring, and because both failure modes
    leave the job green.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    checkouts = workflow.count("uses: actions/checkout@")
    assert checkouts > 0, "no checkout steps found — has the workflow been restructured?"
    assert workflow.count("fetch-depth: 0") == checkouts, (
        f"{checkouts} checkout step(s) but "
        f"{workflow.count('fetch-depth: 0')} with full history — "
        "a shallow job silently stops measuring rather than failing"
    )


def test_the_verifier_exits_zero_on_the_real_repository() -> None:
    """Asserted last: a verifier returning 0 unconditionally would satisfy the
    positive tests above on its own."""
    result = subprocess.run(
        [sys.executable, str(VERIFIER)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert result.returncode == 0, result.stderr


def test_compiled_bytecode_in_the_bundle_is_not_reported_as_a_hand_edit(
    tmp_path: Path,
) -> None:
    """Importing any vendored script leaves a `__pycache__/` behind — the
    migration path does it, and so do several tests. Reporting that as an
    undocumented bundle edit turns a required gate red over a file git already
    ignores, which is how a real divergence ends up dismissed as noise."""
    root = _fixture_repo(tmp_path)
    before_code, before = _run(root)
    cache = root / BUNDLE / "bin" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "stale.cpython-312.pyc").write_bytes(b"\x00")
    after_code, after = _run(root)
    assert after["extra_in_bundle"] == []
    assert (after_code, after) == (before_code, before)
