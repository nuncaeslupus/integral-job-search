"""T58 — no subtree, and the skills committed rather than installed.

Two counts that sound alike and must not be confused: the **subtree** must be
zero, and the **vendored skills** must not be. A cloud session runs on a fresh
clone, never sees `~/.claude/`, and installs no plugins the repo asks for
(`claude-arsenal#200`, verified against a live session), so a skill that is not
committed does not exist there at all.
"""

from __future__ import annotations

from pathlib import Path

from integral.arsenal_source import (
    SUBTREE_MARKERS,
    VENDOR_MARKER,
    measure,
    subtree_machinery,
    vendored_files,
    vendored_skills,
)


def test_no_upstream_subtree_is_maintained() -> None:
    measured = measure()
    assert measured["upstream_subtree_files"] == 0
    assert measured["subtree_machinery_in_makefile"] == []
    # The bundle is generated, not a subtree, and removing it would break every
    # protocol step. A zero above must not have been bought by deleting it.
    assert measured["bundle_files"] > 0


def test_the_skills_are_committed_not_installed() -> None:
    """The half of this that is not a removal.

    `/init` vendors upstream's skills into `.claude/skills/` and marks each one.
    Reading the marker rather than a name list is what lets a skill this repo
    authored sit beside them without being counted as upstream's.
    """
    measured = measure()
    assert measured["vendored_skills"] > 0
    marked = vendored_skills()
    assert "specify" in marked, "an /init-owned skill should carry the marker"
    assert not any(name.startswith("step-") for name in marked), (
        "this repo's own step skills must never be marked as arsenal-vendored"
    )


def test_re_adding_a_subtree_is_counted() -> None:
    """The gate metric cannot pass by having no teeth."""
    assert vendored_files(["src/integral/x.py", "vendor/claude-arsenal/Makefile"]) == [
        "vendor/claude-arsenal/Makefile"
    ]


def test_subtree_machinery_coming_back_is_named(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text("arsenal-upgrade:\n\tgit subtree pull\n", encoding="utf-8")
    assert set(subtree_machinery(makefile)) == {"git subtree", "arsenal-upgrade"}
    assert set(SUBTREE_MARKERS) >= set(subtree_machinery(makefile))


def test_an_unmarked_skill_directory_is_not_counted_as_vendored(tmp_path: Path) -> None:
    skills = tmp_path / ".claude" / "skills"
    (skills / "mine").mkdir(parents=True)
    (skills / "theirs").mkdir()
    (skills / "theirs" / VENDOR_MARKER).write_text("", encoding="utf-8")
    assert vendored_skills(tmp_path) == ["theirs"]
