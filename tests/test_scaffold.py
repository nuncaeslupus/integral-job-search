"""T1 — the scaffold exists and the package is importable.

Written RED before the package existed, per the task payload.
"""

from __future__ import annotations

import re

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def test_package_imports_cleanly_exposes_version() -> None:
    """Importing `jobsearch` yields a semver `__version__`."""
    import jobsearch

    assert SEMVER.match(jobsearch.__version__), (
        f"__version__ is {jobsearch.__version__!r}, which is not semver"
    )


def test_profiles_directory_is_gitignored() -> None:
    """`profiles/` holds candidate data and must never be committed.

    Asserted here rather than left to review: the spec calls the profile store
    the most sensitive artefact in the system, and a gitignore entry is the only
    thing standing between a story bank and a public repository.
    """
    from pathlib import Path

    ignored = Path(__file__).resolve().parent.parent / ".gitignore"
    patterns = {
        line.strip()
        for line in ignored.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "profiles/" in patterns, "profiles/ is not gitignored"
