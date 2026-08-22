"""T58 — the repo carries no copy of upstream, and still carries its bundle."""

from __future__ import annotations

from pathlib import Path

from integral.arsenal_source import (
    SUBTREE_MARKERS,
    measure,
    subtree_machinery,
    vendored_files,
)


def test_no_upstream_tree_is_vendored() -> None:
    measured = measure()
    assert measured["vendored_upstream_files"] == 0
    assert measured["subtree_machinery_in_makefile"] == []
    # The bundle is generated, not vendored, and removing it would break every
    # protocol step. A zero above must not have been bought by deleting it.
    assert measured["bundle_files"] > 0


def test_re_adding_a_vendored_tree_is_counted() -> None:
    """The gate metric cannot pass by having no teeth."""
    assert vendored_files(["src/integral/x.py", "vendor/claude-arsenal/Makefile"]) == [
        "vendor/claude-arsenal/Makefile"
    ]


def test_subtree_machinery_coming_back_is_named(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    makefile.write_text("arsenal-upgrade:\n\tgit subtree pull\n", encoding="utf-8")
    assert set(subtree_machinery(makefile)) == {"git subtree", "arsenal-upgrade"}
    assert set(SUBTREE_MARKERS) >= set(subtree_machinery(makefile))
