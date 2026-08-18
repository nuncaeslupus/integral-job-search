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


def test_the_verifier_exits_zero_on_the_real_repository() -> None:
    """Asserted last: a verifier returning 0 unconditionally would satisfy the
    positive tests above on its own."""
    result = subprocess.run(
        [sys.executable, str(VERIFIER)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert result.returncode == 0, result.stderr
