"""T56's second-reader fixtures, asserted one case at a time.

`integral.cue_audit` holds the table; this holds the failure. Parametrised rather
than looped so a regression names the advert it broke on, not a count.

Why this file exists at all is the whole of `CLAUDE.md`'s "Fixtures for a
correctness-critical gate are written by a second session": T56's own gate,
`extraction_macro_f1 >= 0.75`, is binary over "the advert asserts this dimension"
and cannot see which rung a cue chose — and on the eight dimensions
`extraction.measure` names in `dimensions_with_no_negative_class` it cannot fall
for over-firing at all. Nineteen findings were all consistent with 0.774. A green
gate was necessary and was not sufficient, which is the section's own sentence.
"""

from __future__ import annotations

import pytest

from integral.cue_audit import (
    CASES,
    MINIMUM_CASES,
    MINIMUM_FAIL_OPEN_CASES,
    AuditCase,
    audit,
    resolve,
)
from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions


@pytest.fixture(scope="module")
def dimensions() -> list[Dimension]:
    return load_dimensions(DEFAULT_DIMENSIONS_DIR)


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.dimension}-{c.language}-{c.text[:40]}")
def test_a_cue_reads_what_its_own_rung_describes(
    case: AuditCase, dimensions: list[Dimension]
) -> None:
    """The verdict is the dimension's text; the cue set is what is on trial.

    `expected=None` asserts that **nothing settles** the advert — the wording
    states nothing any rung describes, so `cue_findings` must return None and
    stage 3 must be asked. A cue answering it is the fail-open this table exists
    to hold shut.
    """
    got = resolve(case, dimensions)

    assert got == case.expected, (
        f"{case.dimension}[{case.language}] {case.text!r}\n"
        f"  {case.cites}\n"
        f"  requires {case.expected!r}, cue set returns {got!r} ({case.direction})"
    )


def test_the_audit_denominator_is_a_floor_and_never_falls() -> None:
    """The measured count must rise, or at worst hold, never shrink.

    A finding answered in a comment and not committed as a case leaves the code
    exactly as unprotected as it was — so the count of cases, and separately the
    count of *fail-open* cases, are floors. Deleting a case to make an edit pass
    fails here rather than silently narrowing what the audit covers.
    """
    audited = audit()

    assert audited["cue_audit_failures"] == 0, audited["cue_audit_failing_cases"]
    assert audited["cue_audit_cases"] >= MINIMUM_CASES
    assert audited["cue_audit_fail_open_cases"] >= MINIMUM_FAIL_OPEN_CASES
    assert audited["cue_audit_cases_at_least"] == MINIMUM_CASES
    assert audited["cue_audit_fail_open_cases_at_least"] == MINIMUM_FAIL_OPEN_CASES


def test_every_case_cites_the_text_it_was_decided_from() -> None:
    """A verdict argued from what the code does is the circularity this breaks.

    Not a style check: the citation is the only thing separating this table from
    a transcript of the extractor's current behaviour, which would pass forever
    and protect nothing. Each `cites` names a `definition:` or a rung's `tell:`.
    """
    for case in CASES:
        assert case.cites.strip(), case
        assert "tell" in case.cites or "definition" in case.cites or "label" in case.cites, case


def test_the_audit_reaches_every_dimension_the_pr_widened() -> None:
    """T56 widened ten dimensions; a finding landed on nine of them.

    `talking_clients` is the tenth and is deliberately absent: the independent
    read passed its `atención al público` / `atenció al pacient` widening as
    clean on inspection, and inventing a case for it would record coverage this
    audit did not do.
    """
    covered = {case.dimension for case in CASES}
    widened_with_findings = {
        "compensation_transparency",
        "contract_stability",
        "english_demand",
        "learning_support",
        "product_vs_services",
        "remote_arrangement",
        "schedule_flexibility",
        "seniority_expectation",
        "travel_requirement",
    }

    assert widened_with_findings <= covered, sorted(widened_with_findings - covered)
    # And the two dimensions a finding *moved a statement to*, which is the half
    # of a "this belongs elsewhere" finding that a deletion alone never proves.
    assert {"commute_burden", "career_progression"} <= covered
