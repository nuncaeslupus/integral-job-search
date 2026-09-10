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

import json
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
# Round 2, finding 4: the gate no longer exempts itself by module identity.
# ---------------------------------------------------------------------------


def test_a_floor_in_a_module_named_floor_sweep_is_swept_like_any_other(tmp_path: Path) -> None:
    """Round 1 excluded `floor_sweep.py` from its own sweep by identity — the
    reader's fourth finding: the one committed floor (`MINIMUM_FLOORS_SWEPT`)
    that rule structurally could not classify. Round 2 does not special-case the
    module: a real, undocumented, dynamic-population floor shaped exactly like
    the live one is found and flagged wherever it lives, this filename included.
    """
    _write(
        tmp_path,
        """
def measure():
    swept = 0
    for _ in range(5):
        swept += 1
    return {"floors_swept": swept}


MINIMUM_FLOORS_SWEPT = 3


def write_evidence():
    measured = measure()
    if measured["floors_swept"] < MINIMUM_FLOORS_SWEPT:
        raise SystemExit(1)
    return measured
""",
        name="floor_sweep",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "MINIMUM_FLOORS_SWEPT"


def test_an_uncompared_constant_in_a_module_named_floor_sweep_is_just_out_of_scope(
    tmp_path: Path,
) -> None:
    """Not privileged either way: a constant nothing compares is excluded exactly
    like it would be anywhere else, never silently dropped by identity."""
    (tmp_path / "floor_sweep.py").write_text("MINIMUM_SOMETHING = 1\n", encoding="utf-8")
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_swept"] == 0
    assert "floor_sweep.MINIMUM_SOMETHING" in measured["bounds_read_and_out_of_scope"]


# ---------------------------------------------------------------------------
# Round 2, finding 2: discovery is by use, never by spelling.
# ---------------------------------------------------------------------------


def test_a_non_conventionally_spelled_floor_is_still_found(tmp_path: Path) -> None:
    """`bulk_filter.MUST_KEEP_ROWS`'s own name: no `MINIMUM_`/`MIN_`/`_AT_LEAST`/
    `_MINIMUM` spelling at all. Renaming a floor out of the old name filter must
    not hide it — the reader's own prescribed regression."""
    _write(
        tmp_path,
        """
PROBES_FLOOR = 2

PROBES = (1, 2, 3, 4, 5)


def measure(probes=PROBES):
    if len(probes) < PROBES_FLOOR:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["name"] == "PROBES_FLOOR"
    assert finding["reason"] == "silent_margin"


def test_a_bare_collection_literal_is_never_swept_merely_for_being_capitalised(
    tmp_path: Path,
) -> None:
    """Broadening the name filter to this repository's whole constant convention
    must not turn every fixed-collection table into a false "derived from its own
    population" finding — `PROBES` is the population, not a count of one."""
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
    assert measured["floors_swept"] == 1
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert "mod.PROBES" not in measured["bounds_read_and_out_of_scope"]
    assert "mod.MINIMUM_PROBES" not in measured["bounds_read_and_out_of_scope"]
    assert "mod.MINIMUM_PROBES" not in measured["bounds_read_and_out_of_scope"]


def test_a_floor_boxed_in_a_dict_is_still_found(tmp_path: Path) -> None:
    """`bulk_filter.MUST_KEEP_ROWS`'s *actual* shape: the floor's own name never
    appears in a `Compare` at all — it is boxed into a dict a few lines below and
    read back out through a subscript on both sides
    (`measured["...evaluated"] < measured["...at_least"]`)."""
    _write(
        tmp_path,
        """
MUST_KEEP_ROWS = 3


def measure():
    kept = [1, 2, 3, 4, 5]
    return {
        "kept_evaluated": len(kept),
        "kept_at_least": MUST_KEEP_ROWS,
    }


def _main():
    measured = measure()
    if measured["kept_evaluated"] < measured["kept_at_least"]:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["name"] == "MUST_KEEP_ROWS"
    assert "margin 2" in finding["detail"]


def test_a_two_hop_delegated_comparison_is_found(tmp_path: Path) -> None:
    """A floor passed to a helper that itself passes it on, unchanged, to a
    *second* helper that does the actual comparison — one hop further than
    `review_reader._floor`'s shape, and the reader's named "silently dropped"
    two-hop case."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5)
MINIMUM_PROBES = 2


def _innermost(observed, minimum):
    return (minimum, False) if observed >= minimum else (observed, True)


def _outer(observed, minimum):
    return _innermost(observed, minimum)


def measure(probes=PROBES):
    _outer(len(probes), MINIMUM_PROBES)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["reason"] == "silent_margin"
    assert "margin 3" in finding["detail"]


def test_a_two_hop_delegated_comparison_at_zero_margin_is_compliant(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3)
MINIMUM_PROBES = 3


def _innermost(observed, minimum):
    return (minimum, False) if observed >= minimum else (observed, True)


def _outer(observed, minimum):
    return _innermost(observed, minimum)


def measure(probes=PROBES):
    _outer(len(probes), MINIMUM_PROBES)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_swept"] == 1
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


# ---------------------------------------------------------------------------
# Round 2: `len(X) + N` / `len(X) - N` is counted arithmetically.
# ---------------------------------------------------------------------------


def test_a_length_plus_a_literal_offset_is_counted(tmp_path: Path) -> None:
    """`gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s own reasoning: "the
    list this is read against is `len(ARRANGEMENTS) + 1`"."""
    _write(
        tmp_path,
        """
ARRANGEMENTS = (1, 2, 3, 4)
MINIMUM_PROBED = 5


def measure(arrangements=ARRANGEMENTS):
    if len(arrangements) + 1 < MINIMUM_PROBED:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    # Not just "no finding" — that is equally true of "silently excluded". The
    # `BinOp` must actually have been counted, or this would pass just as well
    # with the arithmetic support deleted outright.
    assert measured["floors_swept"] == 1
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


def test_a_length_plus_a_literal_offset_with_slack_is_a_violation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
ARRANGEMENTS = (1, 2, 3, 4)
MINIMUM_PROBED = 3


def measure(arrangements=ARRANGEMENTS):
    if len(arrangements) + 1 < MINIMUM_PROBED:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert "margin 2" in measured["findings"][0]["detail"]


def test_a_length_minus_a_literal_offset_is_counted(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
ARRANGEMENTS = (1, 2, 3, 4, 5)
MINIMUM_PROBED = 4


def measure(arrangements=ARRANGEMENTS):
    if len(arrangements) - 1 < MINIMUM_PROBED:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_swept"] == 1
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


def test_two_lengths_combined_are_not_guessed_at(tmp_path: Path) -> None:
    """Never two collections combined — this sweep has no business counting
    that, and must not silently accept a `BinOp` merely because it resembles the
    offset shape above."""
    _write(
        tmp_path,
        """
A = (1, 2, 3)
B = (1, 2)
MINIMUM_TOTAL = 1


def measure(a=A, b=B):
    if len(a) + len(b) < MINIMUM_TOTAL:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert measured["floors_swept"] == 0


# ---------------------------------------------------------------------------
# Round 2, finding 1: a "zero slack" claim is falsifiable, not just present.
# ---------------------------------------------------------------------------


def test_a_stale_zero_slack_claim_in_the_arithmetic_branch_is_a_violation(tmp_path: Path) -> None:
    """The reader's own attack: drop a swept floor to 1 and leave the comment
    alone. Every one of round 1's fourteen fixed floors reads "Raised to what the
    probe/table carries — N, zero slack" — `_MARGIN_ARGUED_RE` still matches
    `raised` and `slack` after the drop; only re-checking the claimed number
    catches it."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# Raised to what PROBES carries — 9, zero slack — because 8 tolerated the first
# deleted probe silently.
MINIMUM_PROBES = 1


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["reason"] == "stale_margin_claim"


def test_a_genuine_zero_slack_claim_in_the_arithmetic_branch_is_compliant(tmp_path: Path) -> None:
    """The same comment, undropped: margin is actually zero, so the claim is
    true, and margin `<= 0` clears it before the claim is even read."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# Raised to what PROBES carries — 9, zero slack — because 8 tolerated the first
# deleted probe silently.
MINIMUM_PROBES = 9


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_swept"] == 1
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


def test_a_stale_zero_slack_claim_in_the_dynamic_branch_is_a_violation(tmp_path: Path) -> None:
    """The same attack, on a dynamic-population floor (eleven of round 1's
    fourteen fixed floors are this shape). Round 1 required only a nonempty
    comment — any comment, forever — so this drop cleared it before round 2."""
    _write(
        tmp_path,
        """
# Raised to what the probe carries — 19, zero slack — because 10 had drifted
# nine checks under with no margin argued for the gap.
MINIMUM_CASES = 1


def probe():
    checks = 0
    for _ in range(19):
        checks += 1
    return {"cases_checked": checks}


def check():
    measured = probe()
    if measured["cases_checked"] < MINIMUM_CASES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["name"] == "MINIMUM_CASES"
    assert finding["reason"] == "stale_margin_claim"


def test_a_genuine_zero_slack_claim_in_the_dynamic_branch_is_compliant(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
# Raised to what the probe carries — 19, zero slack — because 10 had drifted
# nine checks under with no margin argued for the gap.
MINIMUM_CASES = 19


def probe():
    checks = 0
    for _ in range(19):
        checks += 1
    return {"cases_checked": checks}


def check():
    measured = probe()
    if measured["cases_checked"] < MINIMUM_CASES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert len(measured["dynamic_population_floors"]) == 1


def test_a_zero_slack_claim_wrapped_across_comment_lines_is_still_checked(tmp_path: Path) -> None:
    """`elicit_extract.MINIMUM_CHECKS`'s own comment wraps "zero" and "slack"
    onto separate `#:`-prefixed lines — a phrase check over the raw comment text
    sees an unmatched `#: ` between them and silently misses the claim."""
    _write(
        tmp_path,
        """
# Raised to what the probe carries — 19, zero
# slack — because 10 had drifted nine checks under.
MINIMUM_CASES = 1


def probe():
    checks = 0
    for _ in range(19):
        checks += 1
    return {"cases_checked": checks}


def check():
    measured = probe()
    if measured["cases_checked"] < MINIMUM_CASES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "stale_margin_claim"


def test_a_spelled_out_zero_slack_claim_is_checked(tmp_path: Path) -> None:
    """`profile.MINIMUM_FIELDS_CHECKED`'s own comment: "Ten today ... zero
    slack" — spelled out, not a digit. A digit-only check would miss this
    exactly the way it missed one of the task's three named floors."""
    _write(
        tmp_path,
        """
# Ten today, matching the fixture exactly: zero slack, so deleting the first
# row breaches this immediately.
MINIMUM_FIELDS_CHECKED = 1


def probe():
    checked = 0
    for _ in range(10):
        checked += 1
    return {"fields_checked": checked}


def check():
    measured = probe()
    if measured["fields_checked"] < MINIMUM_FIELDS_CHECKED:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "stale_margin_claim"


def test_a_zero_slack_claim_with_no_adjacent_number_is_not_accused(tmp_path: Path) -> None:
    """`connector_transport.MINIMUM_RECORD_KEYS_COMPARED`'s own comment: "the
    record carries twelve keys and this is twelve — no slack" — describing a
    *different* number in words this parser does not need to resolve for the
    check to be honest: no number this check can extract means no claim this
    check can falsify, so it is not one it accuses either."""
    _write(
        tmp_path,
        """
# The record carries some other count of keys and this is one of them,
# unrelated — no slack, but not stated as a specific figure.
MINIMUM_TRAITS = 1


def probe():
    checked = 0
    for _ in range(4):
        checked += 1
    return {"traits_checked": checked}


def check():
    measured = probe()
    if measured["traits_checked"] < MINIMUM_TRAITS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert len(measured["dynamic_population_floors"]) == 1
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0


# ---------------------------------------------------------------------------
# Round 2, finding 6: a value only known through a caller's own argument.
# ---------------------------------------------------------------------------


def test_a_population_read_through_a_functions_own_parameter_is_traced(tmp_path: Path) -> None:
    """`gate_reader_agreement.floor_breaches(measured)`'s own shape: the
    function that does the comparison never builds `measured` itself — every
    call site in the module passes it in, each having built it the same way a
    line above."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6)
MINIMUM_PROBES = 5


def measure(probes=PROBES):
    return {"probes_evaluated": len(probes)}


def floor_breaches(measured):
    if measured["probes_evaluated"] < MINIMUM_PROBES:
        return ["breach"]
    return []


def write_evidence():
    measured = measure()
    if floor_breaches(measured):
        raise SystemExit(1)
    return measured


def _main():
    measured = measure()
    if floor_breaches(measured):
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert "margin 1" in measured["findings"][0]["detail"]


def test_a_parameter_bound_differently_by_different_callers_is_not_guessed_at(
    tmp_path: Path,
) -> None:
    """Two call sites binding `floor_breaches`'s parameter to *different*
    expressions is genuinely ambiguous — this must not pick the first one it
    finds and guess."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5)
OTHER_PROBES = (1, 2)
MINIMUM_PROBES = 6


def measure(probes=PROBES):
    return {"probes_evaluated": len(probes)}


def measure_other(probes=OTHER_PROBES):
    return {"probes_evaluated": len(probes)}


def floor_breaches(measured):
    if measured["probes_evaluated"] < MINIMUM_PROBES:
        return ["breach"]
    return []


def write_evidence():
    measured = measure()
    if floor_breaches(measured):
        raise SystemExit(1)


def write_other_evidence():
    measured = measure_other()
    if floor_breaches(measured):
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert "mod.MINIMUM_PROBES" in measured["bounds_read_and_out_of_scope"]


def test_a_return_ambiguous_between_two_dict_literals_is_not_guessed_at(tmp_path: Path) -> None:
    """`measure`'s own bail-out shape (`gate_reader_agreement.measure` returns
    four different things, three of them early `_unmeasured(...)` calls) is only
    resolvable when exactly one of several returns is a `Dict` literal. Two
    literal-dict returns is exactly as ambiguous as it looks and must not be
    guessed at either."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5)
MINIMUM_PROBES = 6


def measure(ok=True, probes=PROBES):
    if ok:
        return {"probes_evaluated": len(probes)}
    return {"probes_evaluated": 0}


def floor_breaches(measured):
    if measured["probes_evaluated"] < MINIMUM_PROBES:
        return ["breach"]
    return []


def write_evidence():
    measured = measure()
    if floor_breaches(measured):
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert "mod.MINIMUM_PROBES" in measured["bounds_read_and_out_of_scope"]


def test_a_return_unambiguous_among_several_bailouts_is_resolved(tmp_path: Path) -> None:
    """Exactly one `Dict`-literal return among several — the rest calls to a
    differently-named bail-out helper — is not ambiguous, and reading it is what
    let round 2 find `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` at all."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6)
MINIMUM_PROBES = 5


def _unmeasured(reason):
    return {"probes_evaluated": 0, "status": reason}


def measure(ok=True, probes=PROBES):
    if not ok:
        return _unmeasured("no probes")
    return {"probes_evaluated": len(probes)}


def floor_breaches(measured):
    if measured["probes_evaluated"] < MINIMUM_PROBES:
        return ["breach"]
    return []


def write_evidence():
    measured = measure()
    if floor_breaches(measured):
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert "margin 1" in measured["findings"][0]["detail"]


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


# ---------------------------------------------------------------------------
# Round 3 — the second reader's nine findings on PR #436, round 2, reproduced
# as fixtures. Findings 1-3 are one root cause (dynamic was an exemption, not
# a classification); the rest are separate blind spots in the sweep itself.
# ---------------------------------------------------------------------------


def test_dropping_a_zero_slack_dynamic_floor_to_zero_is_caught(tmp_path: Path) -> None:
    """The reader's headline finding: `_zero_slack_claim_contradicts` used to
    scan a window that *included* the matched phrase, and "zero slack" always
    contains the word "zero" — so `literal_value == 0` could never contradict
    the claim, for any floor using this repository's own idiom. Every one of
    round 1's fourteen fixed floors could be set to `0` with the metric still
    reading `0`."""
    _write(
        tmp_path,
        """
# Raised to what the probe carries — 19, zero slack — because 10 had drifted
# nine checks under with no margin argued for the gap.
MINIMUM_CASES = 0


def probe():
    checks = 0
    for _ in range(19):
        checks += 1
    return {"cases_checked": checks}


def check():
    measured = probe()
    if measured["cases_checked"] < MINIMUM_CASES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "stale_margin_claim"


def test_dropping_a_zero_slack_arithmetic_floor_to_zero_is_caught(tmp_path: Path) -> None:
    """The same attack in the arithmetic branch, where the margin itself already
    settles it (`margin <= 0` never even reaches the claim-parsing code) — kept
    as a fixture because F1's fix touches the shared parser both branches read."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# Raised to what PROBES carries — 9, zero slack — because 8 tolerated the first
# deleted probe silently.
MINIMUM_PROBES = 0


def measure(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "stale_margin_claim"


def test_a_digit_inside_a_backtick_identifier_is_not_read_as_the_claim(tmp_path: Path) -> None:
    """`profile.MINIMUM_FIELDS_CHECKED`'s real comment: "Ten today, matching
    `_D6_FIXTURE` exactly: zero slack." The `6` inside the identifier must not
    enter the claimed set — dropping the floor to `6` must still be caught."""
    _write(
        tmp_path,
        """
# Ten today, matching `_D6_FIXTURE` exactly: zero slack, so deleting the
# first row breaches this immediately.
MINIMUM_FIELDS_CHECKED = 6


def probe():
    checked = 0
    for _ in range(10):
        checked += 1
    return {"fields_checked": checked}


def check():
    measured = probe()
    if measured["fields_checked"] < MINIMUM_FIELDS_CHECKED:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "stale_margin_claim"


def test_an_issue_reference_after_the_phrase_is_not_read_as_the_claim(tmp_path: Path) -> None:
    """A trailing `(T159)` issue reference must not be read as the claimed
    number — dropping the floor to `159` must still be caught, and the claim
    window must not extend past the matched phrase at all."""
    _write(
        tmp_path,
        """
# Raised — 36, zero slack (T159).
MINIMUM_CHECKS = 159


def probe():
    checks = 0
    for _ in range(36):
        checks += 1
    return {"checks_run": checks}


def check():
    measured = probe()
    if measured["checks_run"] < MINIMUM_CHECKS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["reason"] == "stale_margin_claim"


def test_a_leading_underscore_floor_is_swept(tmp_path: Path) -> None:
    """`approval._SHINGLE`, `plan_v2._MIN_TASK_CELLS`,
    `extraction._CONFIRMING_MATCHES_FOR_BIPOLAR`: real, `len(...)`-compared
    floors on `main`, invisible to round 2's `_CONSTANT_NAME_RE` for no reason
    but the leading underscore — the same "the name filter is still a filter"
    defect one character narrower."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)
_MINIMUM_PROBES = 1


def probe_one(probes=PROBES):
    if len(probes) < _MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    finding = measured["findings"][0]
    assert finding["name"] == "_MINIMUM_PROBES"
    assert finding["reason"] == "silent_margin"


def test_a_leading_underscore_non_floor_constant_stays_off_the_candidate_list(
    tmp_path: Path,
) -> None:
    """Widening the name pattern must not sweep every module-private constant —
    only the value shape (`_is_len_derived`) decides, exactly as it already does
    for the public spelling."""
    _write(
        tmp_path,
        """
_REPO_ROOT = "/not/a/floor"
_ID_WIDTH = 6
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    assert measured["floors_swept"] == 0


def test_split_on_a_string_is_recognised_as_a_real_population(tmp_path: Path) -> None:
    """`approval._SHINGLE`'s actual shape: `len(_words(episode))` where `_words`
    returns `...split()`. Before this, `.split()` fell through to `unknown` (not
    a count-preserving wrapper, not a scalar method), and the floor was
    invisible for a reason that had nothing to do with its name."""
    _write(
        tmp_path,
        """
MINIMUM_WORDS = 1


def _words(text):
    return text.split()


def carries(text):
    words = _words(text)
    if len(words) <= MINIMUM_WORDS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "MINIMUM_WORDS"


def test_an_annotated_initial_assignment_is_traced_the_same_as_a_plain_one(
    tmp_path: Path,
) -> None:
    """`second_reader.STDLIB_DISAGREEMENTS_AT_LEAST`'s real shape:
    `stdlib_disagreements: list[dict[str, str]] = []`, appended to in a loop.
    An `AnnAssign` initial binding is a distinct AST node from `Assign`, and
    was invisible to `_assignments_to_name` until this round taught it to read
    both."""
    _write(
        tmp_path,
        """
MINIMUM_DISAGREEMENTS = 1


def probe():
    disagreements: list[str] = []
    for i in range(5):
        disagreements.append(str(i))
    if len(disagreements) < MINIMUM_DISAGREEMENTS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "MINIMUM_DISAGREEMENTS"


def test_a_floors_own_value_as_a_binop_of_two_literals_is_resolved(tmp_path: Path) -> None:
    """`MINIMUM_PROBES = 1 + 0` — a `BinOp` of two literals: neither
    `_literal_int` (not a bare `Constant`) nor `_is_len_derived` (no `len(...)`
    operand) recognised this as a hand-written number, so it was invisible."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)
MINIMUM_PROBES = 1 + 0


def probe_one(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "MINIMUM_PROBES"


def test_a_floor_aliased_through_a_sibling_constant_is_resolved(tmp_path: Path) -> None:
    """`_FLOOR = 1` then `MINIMUM_PROBES = _FLOOR` — a hand-written number one
    hop away through another module-level constant, not a derived one."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)
_FLOOR = 1
MINIMUM_PROBES = _FLOOR


def probe_one(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    names = {f["name"] for f in measured["findings"]}
    # Both the alias and the constant it resolves through are real, swept
    # floors — `_FLOOR` is itself a legal, capitalised module constant whose
    # value happens to be read as a floor too, which is desirable rather than
    # a duplicate: a session that "fixes" `MINIMUM_PROBES` alone and leaves
    # `_FLOOR` at 1 has not actually fixed anything downstream of `_FLOOR`.
    assert {"MINIMUM_PROBES", "_FLOOR"} <= names


def test_a_three_hop_delegated_comparison_is_found(tmp_path: Path) -> None:
    """Round 2 answered the reader's two-hop finding by writing exactly two
    hops in by hand. A third hop still defeated it — the closed form is
    recursion, not a fourth remedy naming a fourth hop."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)
MINIMUM_PROBES = 1


def _innermost(floor, other):
    if other < floor:
        raise SystemExit(1)


def _mid2(floor, other):
    _innermost(floor, other)


def _mid1(floor, other):
    _mid2(floor, other)


def outer(probes=PROBES):
    _mid1(MINIMUM_PROBES, len(probes))
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "MINIMUM_PROBES"


def test_a_four_hop_delegated_comparison_is_also_found(tmp_path: Path) -> None:
    """One hop further than the reader's own constructed attack — pinned as a
    rule (bounded recursion) rather than as a count, so this is not the fixture
    that ends the enumeration, only evidence that the rule has no hard-coded
    stopping point at three."""
    _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5, 6, 7, 8, 9)
MINIMUM_PROBES = 1


def _innermost(floor, other):
    if other < floor:
        raise SystemExit(1)


def _mid3(floor, other):
    _innermost(floor, other)


def _mid2(floor, other):
    _mid3(floor, other)


def _mid1(floor, other):
    _mid2(floor, other)


def outer(probes=PROBES):
    _mid1(MINIMUM_PROBES, len(probes))
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 1
    assert measured["findings"][0]["name"] == "MINIMUM_PROBES"


# ---------------------------------------------------------------------------
# Round 3's structural fix: a dynamic floor's population read from this
# repository's own committed `status/evidence/*.json`, checked by the exact
# arithmetic every counted-collection floor already gets. This is what closes
# the round-2 reader's diagnosis — "dynamic is not a classification, it is an
# exemption" — for every floor shaped like this repository's own scripted
# probes, rather than only patching the comment parser those floors used to be
# checked by instead.
# ---------------------------------------------------------------------------


def _write_evidence(tmp_path: Path, relative: str, data: dict[str, Any]) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_a_dynamic_floor_backed_by_committed_evidence_is_checked_arithmetically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No comment at all — the floor is still caught, because its real
    population is read from the committed evidence file rather than argued in
    prose. This is the fixture a keyword- or digit-parser could never pass:
    there is no comment here for any parser to misread."""
    monkeypatch.setattr(floor_sweep, "_REPO_ROOT", tmp_path)
    _write_evidence(tmp_path, "status/evidence/T900.json", {"checks_run": 19})
    _write(
        tmp_path,
        """
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T900.json"

MINIMUM_CHECKS = 1


def probe():
    checks = 0
    for _ in range(19):
        checks += 1
    return {"checks_run": checks}


def write_evidence(evidence=DEFAULT_EVIDENCE_PATH):
    measured = probe()
    return measured


def _main():
    measured = write_evidence()
    if measured["checks_run"] < MINIMUM_CHECKS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    pinned = [p for p in measured["evidence_pinned_floors"] if p["name"] == "MINIMUM_CHECKS"]
    assert pinned == []  # not pinned *compliant* — it is a real breach
    finding = measured["findings"][0]
    assert finding["name"] == "MINIMUM_CHECKS"
    assert finding["reason"] == "silent_margin"
    assert "population is 19" in finding["detail"]


def test_a_correctly_pinned_floor_is_reported_compliant_with_its_population(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(floor_sweep, "_REPO_ROOT", tmp_path)
    _write_evidence(tmp_path, "status/evidence/T900.json", {"checks_run": 19})
    _write(
        tmp_path,
        """
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T900.json"

MINIMUM_CHECKS = 19


def probe():
    checks = 0
    for _ in range(19):
        checks += 1
    return {"checks_run": checks}


def write_evidence(evidence=DEFAULT_EVIDENCE_PATH):
    measured = probe()
    return measured


def _main():
    measured = write_evidence()
    if measured["checks_run"] < MINIMUM_CHECKS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    pinned = [p for p in measured["evidence_pinned_floors"] if p["name"] == "MINIMUM_CHECKS"]
    assert len(pinned) == 1
    assert pinned[0]["population"] == 19
    assert measured["dynamic_population_floors"] == []


def test_a_pinnable_population_read_through_a_dispatchers_own_parameter_is_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`lifecycle.MINIMUM_SCENARIOS`'s real shape: the comparison lives in a
    `_s5_report(measured)`-style helper, where `measured` is that function's own
    *parameter*, bound by its one caller — not a local assignment at all."""
    monkeypatch.setattr(floor_sweep, "_REPO_ROOT", tmp_path)
    _write_evidence(tmp_path, "status/evidence/T900.json", {"scenarios_checked": 72})
    _write(
        tmp_path,
        """
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T900.json"

MINIMUM_SCENARIOS = 20


def probe():
    scenarios = 0
    for _ in range(72):
        scenarios += 1
    return {"scenarios_checked": scenarios}


def write_evidence(evidence=DEFAULT_EVIDENCE_PATH):
    return probe()


def _report(measured):
    if measured["scenarios_checked"] < MINIMUM_SCENARIOS:
        raise SystemExit(1)


def _main():
    measured = write_evidence()
    _report(measured)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    finding = measured["findings"][0]
    assert finding["name"] == "MINIMUM_SCENARIOS"
    assert "population is 72" in finding["detail"]


def test_a_parameter_with_two_call_sites_is_not_pinned_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-caller hop is followed only when there genuinely is a single
    caller — with two, which one's evidence file is the right one to read is
    not this sweep's to guess, so this stays an unpinned dynamic floor rather
    than a wrong number silently believed."""
    monkeypatch.setattr(floor_sweep, "_REPO_ROOT", tmp_path)
    _write_evidence(tmp_path, "status/evidence/T900.json", {"checks_run": 3})
    _write(
        tmp_path,
        """
# Argued so this stays a compliant, merely-unpinned floor rather than an
# undocumented one — the property under test is the refusal to pin through
# two callers, not the separate "no comment at all" check.
MINIMUM_CHECKS = 1


def probe_a():
    checks = 0
    for _ in range(3):
        checks += 1
    return {"checks_run": checks}


def probe_b():
    checks = 0
    for _ in range(5):
        checks += 1
    return {"checks_run": checks}


def _report(measured):
    if measured["checks_run"] < MINIMUM_CHECKS:
        raise SystemExit(1)


def _main_a():
    measured = probe_a()
    _report(measured)


def _main_b():
    measured = probe_b()
    _report(measured)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    names = {d["name"] for d in measured["dynamic_population_floors"]}
    pinned_names = {p["name"] for p in measured["evidence_pinned_floors"]}
    assert "MINIMUM_CHECKS" in names
    assert "MINIMUM_CHECKS" not in pinned_names


def test_an_evidence_path_chosen_by_an_untraceable_condition_is_not_guessed_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`profile_capture`'s real shape: `default_path = DEFAULT_D8_EVIDENCE_PATH
    if args.subject_gate else DEFAULT_EVIDENCE_PATH` — *both* branches resolve,
    to two different real files, and which one is live depends on a condition
    this sweep does not evaluate. Refusing to guess is the point: picking
    either would be a coin flip on which probe's number gets read."""
    monkeypatch.setattr(floor_sweep, "_REPO_ROOT", tmp_path)
    _write_evidence(tmp_path, "status/evidence/T900.json", {"checks_run": 5})
    _write_evidence(tmp_path, "status/evidence/D900.json", {"checks_run": 9})
    _write(
        tmp_path,
        """
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T900.json"
DEFAULT_D900_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D900.json"

# Argued so this stays a compliant, merely-unpinned floor — the property
# under test is the refusal to guess between two live evidence files, not
# the separate "no comment at all" check.
MINIMUM_CHECKS = 1


def probe():
    checks = 0
    for _ in range(5):
        checks += 1
    return {"checks_run": checks}


def write_evidence(evidence=DEFAULT_EVIDENCE_PATH):
    return probe()


def _main(subject_gate):
    default_path = DEFAULT_D900_EVIDENCE_PATH if subject_gate else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(default_path)
    if measured["checks_run"] < MINIMUM_CHECKS:
        raise SystemExit(1)
""",
    )
    measured = floor_sweep.measure(tmp_path)
    names = {d["name"] for d in measured["dynamic_population_floors"]}
    pinned_names = {p["name"] for p in measured["evidence_pinned_floors"]}
    assert "MINIMUM_CHECKS" in names
    assert "MINIMUM_CHECKS" not in pinned_names


# ---------------------------------------------------------------------------
# The sweep's own denominator, checked arithmetically against this run's own
# true `swept` — not classified `dynamic` (self-exemption by classification,
# the reader's third/fourth finding) and not skipped by module identity
# (round 1's original defect).
# ---------------------------------------------------------------------------


def test_the_sweeps_own_floor_is_a_real_arithmetic_check_not_an_exemption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2 classified `MINIMUM_FLOORS_SWEPT` `dynamic`, which put it in the
    one branch that never computes a margin — self-exemption by classification
    rather than by identity (the reader's third/fourth finding). Matched by
    *identity* (`_THIS_FILE`) against a tiny synthetic tree standing in for the
    real one, so this run's own `swept` and the floor's own (missing) comment
    can be controlled without touching the real `floor_sweep.py`: a floor left
    with no argued margin, sitting below this tiny tree's own true count, is a
    real, computed breach — not a name-shaped candidate nodded through."""
    fixture = _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5)
MINIMUM_PROBES = 1
MINIMUM_FLOORS_SWEPT = 1


def probe_one(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
        name="floor_sweep",
    )
    monkeypatch.setattr(floor_sweep, "_THIS_FILE", fixture.resolve())
    # In reality `_THIS_FILE` and `MINIMUM_FLOORS_SWEPT` always name the same
    # file's own constant; kept in sync here too, or the self-check would be
    # comparing the fixture's declared value against the *real* module's own
    # (unrelated) floor rather than against itself.
    monkeypatch.setattr(floor_sweep, "MINIMUM_FLOORS_SWEPT", 1)
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_swept"] == 2  # MINIMUM_PROBES, and the deferred self-floor
    finding = next(
        f
        for f in measured["findings"]
        if f["module"] == "floor_sweep" and f["name"] == "MINIMUM_FLOORS_SWEPT"
    )
    assert finding["reason"] == "silent_margin"


def test_the_sweeps_own_floor_argued_in_writing_is_compliant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same shape, with the same margin argued in the same words this
    module's own comment already uses — checked the same way any other
    floor's argued margin is."""
    fixture = _write(
        tmp_path,
        """
PROBES = (1, 2, 3, 4, 5)
MINIMUM_PROBES = 5

# One point of slack: this tiny tree sweeps two floors, and one is enough to
# leave a module edit unnoticed.
MINIMUM_FLOORS_SWEPT = 1


def probe_one(probes=PROBES):
    if len(probes) < MINIMUM_PROBES:
        raise SystemExit(1)
""",
        name="floor_sweep",
    )
    monkeypatch.setattr(floor_sweep, "_THIS_FILE", fixture.resolve())
    monkeypatch.setattr(floor_sweep, "MINIMUM_FLOORS_SWEPT", 1)
    measured = floor_sweep.measure(tmp_path)
    assert measured["floors_that_do_not_refuse_the_first_deletion"] == 0
    pinned = next(
        p
        for p in measured["evidence_pinned_floors"]
        if p["module"] == "floor_sweep" and p["name"] == "MINIMUM_FLOORS_SWEPT"
    )
    assert pinned["population"] == 2


def test_the_sweeps_own_floor_is_pinned_compliant_on_the_live_tree() -> None:
    measured = floor_sweep.measure()
    pinned = next(
        p
        for p in measured["evidence_pinned_floors"]
        if p["module"] == "floor_sweep" and p["name"] == "MINIMUM_FLOORS_SWEPT"
    )
    assert pinned["population"] == measured["floors_swept"]
    assert not any(
        d["module"] == "floor_sweep" and d["name"] == "MINIMUM_FLOORS_SWEPT"
        for d in measured["dynamic_population_floors"]
    )
