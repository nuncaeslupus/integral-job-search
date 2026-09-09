"""T159 — floors swept for the property that keeps a floor a floor.

Every constructed module below is written as a throwaway `.py` file and handed to
`floor_sweep.measure` directly, the same posture `test_repo_gate.py` takes toward its
own mutations: this pins the sweep's *classification rules* against fixtures shaped
like the real defects (`profile.MINIMUM_FIELDS_CHECKED`, `bodyless_post.MINIMUM_PROBES`,
`page_placeholder.MINIMUM_PROBES`, `review_reader`'s delegated floors), not against
whatever today's repository happens to contain — a fixture derived from the live tree
would only ever confirm what the sweep already believes. `test_the_live_tree_has_zero_findings`
is the separate, complementary check that today's actual tree is clean.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from integral import floor_sweep


def _write(tmp_path: Path, source: str, name: str = "mod") -> Path:
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The three named defects, reproduced as minimal fixtures.
# ---------------------------------------------------------------------------


def test_a_floor_derived_from_its_own_population_is_a_violation(tmp_path: Path) -> None:
    """`profile.MINIMUM_FIELDS_CHECKED`'s shape: `len(X) < len(X)` never fires."""
    _write(
        tmp_path,
        """
FIXTURE = (1, 2, 3, 4, 5)
MINIMUM_FIELDS_CHECKED = len(FIXTURE)


def probe():
    return {"fields_checked": len(FIXTURE)}


def check():
    measured = probe()
    if measured["fields_checked"] < MINIMUM_FIELDS_CHECKED:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "derived_from_its_own_population"
    assert measured["findings"][0]["name"] == "MINIMUM_FIELDS_CHECKED"


def test_a_literal_floor_with_an_undocumented_margin_is_a_violation(tmp_path: Path) -> None:
    """`bodyless_post.MINIMUM_PROBES`'s shape: 8 against a table of 9, no argument."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# A probe table.
MINIMUM_PROBES = 8


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["reason"] == "silent_margin"
    assert "margin 1" in finding["detail"]


def test_a_larger_undocumented_margin_is_also_a_violation(tmp_path: Path) -> None:
    """`page_placeholder.MINIMUM_PROBES`'s shape: four tolerated deletions."""
    _write(
        tmp_path,
        """
PROBES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24)
MINIMUM_PROBES = 21


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert "margin 4" in measured["findings"][0]["detail"]


# ---------------------------------------------------------------------------
# What a fixed-collection floor doing the right thing looks like.
# ---------------------------------------------------------------------------


def test_a_literal_floor_matching_its_population_exactly_is_compliant(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3)
MINIMUM_PROBES = 3


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


def test_a_margin_argued_in_writing_is_not_flagged(tmp_path: Path) -> None:
    """`salary_recovery.MINIMUM_WORDING_CASES`'s shape: below population, explained."""
    _write(
        tmp_path,
        """
CASES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)

# Raised from 5 when the audit landed more cases; deliberately kept some slack
# below the table because this floor is pinned to a third party's behaviour,
# not to this table's own size.
MINIMUM_CASES = 12


def measure(cases=CASES):
    if len(cases) < MINIMUM_CASES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


def test_a_floor_already_breaching_its_population_needs_no_argument(tmp_path: Path) -> None:
    """A floor set *above* today's population already refuses every deletion."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3)
MINIMUM_PROBES = 5


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


# ---------------------------------------------------------------------------
# The three named blind spots.
# ---------------------------------------------------------------------------


def test_the_at_least_spelling_is_recognised(tmp_path: Path) -> None:
    """Blind spot 1: `MINIMUM_`/`MIN_` alone misses `*_AT_LEAST`."""
    _write(
        tmp_path,
        """
CASES = (1, 2, 3, 4, 5)
CASES_AT_LEAST = 2


def measure(cases=CASES):
    if len(cases) < CASES_AT_LEAST:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "CASES_AT_LEAST"


def test_the_minimum_suffix_spelling_is_recognised(tmp_path: Path) -> None:
    """Blind spot 1, other half: `*_MINIMUM`."""
    _write(
        tmp_path,
        """
NEEDLES = (1, 2, 3)
NEEDLE_MINIMUM = 1


def measure(needles=NEEDLES):
    if len(needles) < NEEDLE_MINIMUM:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "NEEDLE_MINIMUM"


def test_an_equality_fingerprint_would_have_missed_a_floor_with_slack(tmp_path: Path) -> None:
    """Blind spot 2: a floor *below* its population, by construction, is still found.

    An equality-fingerprint sweep asks only "does the floor equal the population" and
    would read this floor (below, by 3, undocumented) as simply "not a match" rather
    than as a violation — the exact gap this module's arithmetic margin check exists
    to close.
    """
    _write(
        tmp_path,
        """
ITEMS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MINIMUM_ITEMS = 7


def measure(items=ITEMS):
    if len(items) < MINIMUM_ITEMS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert "margin 3" in measured["findings"][0]["detail"]


def test_a_comparison_delegated_to_a_helper_is_found(tmp_path: Path) -> None:
    """Blind spot 3: `review_reader._floor(observed, minimum)`'s shape."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5)
MINIMUM_PROBES = 2


def _floor(observed, minimum):
    return (minimum, False) if observed >= minimum else (observed, True)


def measure(probes=PROBES):
    _floor(len(probes), MINIMUM_PROBES)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["reason"] == "silent_margin"
    assert "margin 3" in finding["detail"]


def test_a_delegated_comparison_at_zero_margin_is_compliant(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3)
MINIMUM_PROBES = 3


def _floor(observed, minimum):
    return (minimum, False) if observed >= minimum else (observed, True)


def measure(probes=PROBES):
    _floor(len(probes), MINIMUM_PROBES)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


# ---------------------------------------------------------------------------
# What is deliberately out of scope: a threshold on one piece of content.
# ---------------------------------------------------------------------------


def test_a_scalar_content_threshold_is_out_of_scope_not_compliant(tmp_path: Path) -> None:
    """`elicit_extract.MIN_ANSWER_CHARS`'s shape: a single answer's length, not a
    population — read and set aside, never silently counted as a passing floor."""
    _write(
        tmp_path,
        """
MIN_ANSWER_CHARS = 12


def check(answer):
    stripped = answer.strip()
    if len(stripped) < MIN_ANSWER_CHARS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert measured["floors_swept"] == 0
    assert "mod.MIN_ANSWER_CHARS" in measured["bounds_read_and_out_of_scope"]


def test_a_per_group_business_threshold_is_out_of_scope(tmp_path: Path) -> None:
    """`corpus.MIN_ADS_PER_FAMILY`'s shape: compared to a per-group count, never a
    `len(...)` of the collection being swept."""
    _write(
        tmp_path,
        """
MIN_ADS_PER_FAMILY = 15


def qualifying(counts):
    return [family for family, n in counts.items() if n >= MIN_ADS_PER_FAMILY]
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert measured["floors_swept"] == 0


# ---------------------------------------------------------------------------
# The dynamic-population half: no single "first deletion", documentation instead.
# ---------------------------------------------------------------------------


def test_a_dynamic_population_with_no_comment_is_a_violation(tmp_path: Path) -> None:
    """The eleven scripted-probe floors this task also fixed share this shape:
    a running tally built by `+= 1`, never a collection literal."""
    _write(
        tmp_path,
        """
MINIMUM_TURNS = 3


def probe():
    turns = 0
    for _ in range(5):
        turns += 1
    return {"turns_evaluated": turns}


def check():
    measured = probe()
    if measured["turns_evaluated"] < MINIMUM_TURNS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "undocumented"


def test_a_dynamic_population_with_a_comment_is_compliant(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
# Deliberately small: the scripted scenario is expected to grow over time and
# this floor is raised alongside it, never derived from it.
MINIMUM_TURNS = 3


def probe():
    turns = 0
    for _ in range(5):
        turns += 1
    return {"turns_evaluated": turns}


def check():
    measured = probe()
    if measured["turns_evaluated"] < MINIMUM_TURNS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert len(measured["dynamic_population_floors"]) == 1


def test_a_delegated_dynamic_population_is_recognised(tmp_path: Path) -> None:
    """`review_reader`'s four floors: delegated, and over a population this module
    does not enumerate — recognised as in-scope without a spurious margin claim."""
    _write(
        tmp_path,
        """
MINIMUM_REPORTS = 3


def _floor(observed, minimum):
    return (minimum, False) if observed >= minimum else (observed, True)


def measure():
    reports_found = 0
    for _ in range(7):
        reports_found += 1
    _floor(reports_found, MINIMUM_REPORTS)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "undocumented"


# ---------------------------------------------------------------------------
# A floor declared but never checked anywhere is not a floor this sweep counts.
# ---------------------------------------------------------------------------


def test_a_never_compared_bound_is_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
MINIMUM_NEVER_USED = 3
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert measured["floors_swept"] == 0
    assert "mod.MINIMUM_NEVER_USED" in measured["bounds_read_and_out_of_scope"]


# ---------------------------------------------------------------------------
# Two constants sharing one comment block.
# ---------------------------------------------------------------------------


def test_two_floors_declared_together_both_read_the_shared_comment(tmp_path: Path) -> None:
    """`interview.MINIMUM_TRAIT_EPISODES` / `MINIMUM_TRAIT_OCCASIONS`'s shape: one
    comment above the first of a pair, nothing directly above the second."""
    _write(
        tmp_path,
        """
# Deliberately small design minimum, not derived from either collection below —
# raised together and explained once for both.
MINIMUM_A = 2
MINIMUM_B = 2


def probe():
    a = []
    for _ in range(5):
        a.append(1)
    b = []
    for _ in range(5):
        b.append(1)
    return {"a_count": len(a), "b_count": len(b)}


def check():
    measured = probe()
    if measured["a_count"] < MINIMUM_A:
        raise SystemExit(1)
    if measured["b_count"] < MINIMUM_B:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert len(measured["dynamic_population_floors"]) == 2


# ---------------------------------------------------------------------------
# This module's own diagnostics constants are not swept.
# ---------------------------------------------------------------------------


def test_this_modules_own_constants_are_not_swept(tmp_path: Path) -> None:
    (tmp_path / "floor_sweep.py").write_text("MINIMUM_SOMETHING = 1\n", encoding="utf-8")
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_swept"] == 0
    assert measured["bounds_read_and_out_of_scope"] == []


# ---------------------------------------------------------------------------
# The denominator: a committed literal, never the count of the day.
# ---------------------------------------------------------------------------


def test_the_denominator_is_swapped_for_a_committed_floor() -> None:
    measured: dict[str, Any] = {
        "floors_that_do_not_refuse_the_first_deletion": 0,
        "findings": [],
        "floors_swept": 999,
        "dynamic_population_floors": [],
        "bounds_read_and_out_of_scope": [],
        "gate_status": "measured",
    }
    committed = floor_sweep.record(measured)
    assert "floors_swept" not in committed
    assert committed["floors_swept_at_least"] == floor_sweep.MINIMUM_FLOORS_SWEPT
    # T122's finding, applied to this task's own gate: raising the floor to the
    # measured count would let it move with the sweep's own coverage. It must not.
    assert isinstance(floor_sweep.MINIMUM_FLOORS_SWEPT, int)


def test_write_evidence_refuses_when_too_few_floors_are_swept(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    evidence_path = tmp_path / "evidence.json"
    measured = floor_sweep.write_evidence(evidence_path, empty_dir)
    assert measured["floors_swept"] < floor_sweep.MINIMUM_FLOORS_SWEPT
    assert not evidence_path.exists()


def test_write_evidence_writes_even_when_findings_are_nonzero(tmp_path: Path) -> None:
    """A nonzero finding count must still be written — the whole point of a gate is
    to be able to fail with the finding visible, not to hide it by refusing to write."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for i in range(floor_sweep.MINIMUM_FLOORS_SWEPT):
        _write(
            src_dir,
            """
ITEMS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MINIMUM_ITEMS = 3

def measure(items=ITEMS):
    if len(items) < MINIMUM_ITEMS:
        raise SystemExit(1)
""",
            name=f"mod{i}",
        )
    evidence_path = tmp_path / "evidence.json"
    measured = floor_sweep.write_evidence(evidence_path, src_dir)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] > 0
    assert evidence_path.exists()


# ---------------------------------------------------------------------------
# The live tree.
# ---------------------------------------------------------------------------


def test_the_live_tree_has_zero_findings() -> None:
    """The gate this task ships: today's tree carries no such floor, and the sweep
    still examined at least as many as its own committed denominator promises."""
    measured = floor_sweep.measure()
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0, measured["findings"]
    assert measured["floors_swept"] >= floor_sweep.MINIMUM_FLOORS_SWEPT


def test_main_exits_zero_on_the_live_tree() -> None:
    assert floor_sweep._main([str(Path("/tmp/floor_sweep_test_evidence.json"))]) == 0


def test_main_exits_one_on_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for i in range(floor_sweep.MINIMUM_FLOORS_SWEPT):
        _write(
            src_dir,
            """
ITEMS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MINIMUM_ITEMS = 3

def measure(items=ITEMS):
    if len(items) < MINIMUM_ITEMS:
        raise SystemExit(1)
""",
            name=f"mod{i}",
        )
    monkeypatch.setattr(floor_sweep, "_SRC_DIR", src_dir)
    evidence_path = tmp_path / "evidence.json"
    assert floor_sweep._main([str(evidence_path)]) == 1
