"""T22 — `undocumented_methods == 0`, checked in both directions.

§1's criterion is *"every technique that scores, weights or ranks, and every
formula producing a number the candidate sees, has an entry in
`docs/METHODS.md`"*, and §5.1 says how: *"walk every dimension file and every
scoring function, resolve each `methods_ref` anchor against `docs/METHODS.md`,
and fail on any that does not resolve"*.

Resolving refs forwards is only half of that. §5.1 also says `methods_ref` is
**required on every computation site**, and a forward-only check cannot see a
computation site that declares nothing — a scoring function with no ref is
invisible to it, so the half of the criterion about code would be enforced by
discipline, which is the thing §5.1 refuses. The reverse direction is the
`## 4. Formula register`: every `### 4.x` heading is by its own words a number
that reaches the candidate, so each one must be claimed by a site.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.dimensions import DimensionError
from integral.methods_links import (
    DEFAULT_METHODS_PATH,
    citations,
    formula_anchors,
    measure,
    undocumented,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_methods_ref_resolves_to_an_anchor() -> None:
    """The named gate test: no citation in the repo points at a missing heading."""
    unresolved = [problem for problem in undocumented(_REPO_ROOT) if "resolves to no" in problem]
    assert unresolved == []


def test_every_registered_formula_is_claimed_by_a_computation_site() -> None:
    """The reverse direction — a formula in the register with no code citing it."""
    problems = undocumented(_REPO_ROOT)
    assert [problem for problem in problems if "no computation site" in problem] == []


def test_the_committed_repo_measures_zero() -> None:
    assert measure(_REPO_ROOT)["undocumented_methods"] == 0


def test_both_dimension_files_and_python_sites_are_walked() -> None:
    """A check that only reached the YAML would pass while the code drifted."""
    suffixes = {path.suffix for path, _ in citations(_REPO_ROOT)}
    assert suffixes == {".yaml", ".py"}


def test_a_dangling_ref_in_a_python_site_is_counted(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "METHODS.md").write_text(
        "## 4. Formula register\n\n### 4.1 Real heading\n", encoding="utf-8"
    )
    (tmp_path / "src" / "integral").mkdir(parents=True)
    (tmp_path / "src" / "integral" / "thing.py").write_text(
        'METHODS_REF = "METHODS.md#41-real-heading"\n'
        'OTHER = dict(methods_ref="METHODS.md#no-such-heading")\n',
        encoding="utf-8",
    )
    (tmp_path / "dimensions").mkdir()

    assert measure(tmp_path)["undocumented_methods"] == 1
    assert any("no-such-heading" in problem for problem in undocumented(tmp_path))


def test_an_unclaimed_formula_is_counted(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "METHODS.md").write_text(
        "## 4. Formula register\n\n### 4.1 Claimed\n\n### 4.2 Orphan\n", encoding="utf-8"
    )
    (tmp_path / "src" / "integral").mkdir(parents=True)
    (tmp_path / "src" / "integral" / "thing.py").write_text(
        'METHODS_REF = "METHODS.md#41-claimed"\n', encoding="utf-8"
    )
    (tmp_path / "dimensions").mkdir()

    assert measure(tmp_path)["undocumented_methods"] == 1
    assert any("42-orphan" in problem for problem in undocumented(tmp_path))


def test_a_dimension_yaml_claim_does_not_satisfy_a_formula(tmp_path: Path) -> None:
    """A dimension citing a formula is a reader of it, not its implementation.

    Dimension files are data. If a YAML `methods_ref` could discharge a formula
    heading, pointing twenty dimension files at §4.1 would report the weighted
    mean as implemented while no code computed it.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "METHODS.md").write_text(
        "## 4. Formula register\n\n### 4.1 Only formula\n", encoding="utf-8"
    )
    (tmp_path / "dimensions").mkdir()
    (tmp_path / "dimensions" / "d.yaml").write_text(
        "methods_ref: METHODS.md#41-only-formula\n", encoding="utf-8"
    )
    (tmp_path / "src" / "integral").mkdir(parents=True)

    assert measure(tmp_path)["undocumented_methods"] == 1


def test_only_headings_under_the_formula_register_are_required(tmp_path: Path) -> None:
    """`### 2.1` is a technique, not a number the candidate sees."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "METHODS.md").write_text(
        "## 2. Techniques used\n\n### 2.1 A technique\n\n## 4. Formula register\n", encoding="utf-8"
    )
    (tmp_path / "dimensions").mkdir()
    (tmp_path / "src" / "integral").mkdir(parents=True)

    assert formula_anchors(tmp_path / "docs" / "METHODS.md") == set()
    assert measure(tmp_path)["undocumented_methods"] == 0


def test_a_ref_inside_a_generated_template_is_not_a_citation(tmp_path: Path) -> None:
    """`suggestions.py` writes a `methods_ref: METHODS.md#TODO` line into a file
    it says outright does not load as written. Reading that placeholder as a
    citation would make the gate fail on a string the author already marked as
    unfinished — so a citation must be a Python assignment, not any occurrence
    of the word in a source file."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "METHODS.md").write_text("## 4. Formula register\n", encoding="utf-8")
    (tmp_path / "dimensions").mkdir()
    (tmp_path / "src" / "integral").mkdir(parents=True)
    (tmp_path / "src" / "integral" / "gen.py").write_text(
        'LINES = ["methods_ref: METHODS.md#TODO"]\n', encoding="utf-8"
    )

    assert measure(tmp_path)["undocumented_methods"] == 0


def test_a_missing_methods_register_is_an_error(tmp_path: Path) -> None:
    """The same `DimensionError` the YAML half already raises — one failure type
    for "the register is not readable", whichever end of the link found out."""
    (tmp_path / "dimensions").mkdir()
    (tmp_path / "src" / "integral").mkdir(parents=True)
    with pytest.raises(DimensionError):
        measure(tmp_path)


def test_the_default_register_is_the_committed_one() -> None:
    assert DEFAULT_METHODS_PATH == _REPO_ROOT / "docs" / "METHODS.md"
