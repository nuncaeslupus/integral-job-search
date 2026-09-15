"""T56's second-reader fixtures, asserted one case at a time.

`integral.cue_audit` holds the table; this holds the failure. Parametrised rather
than looped so a regression names the advert it broke on, not a count.

Why this file exists at all is the whole of `CLAUDE.md`'s "Fixtures for a
correctness-critical gate are written by a second session": T56's own gate,
`extraction_macro_f1 >= 0.75`, is binary over "the advert asserts this dimension"
and cannot see which rung a cue chose — and on the eight dimensions
`extraction.measure` names in `dimensions_with_no_negative_class` it cannot fall
for over-firing at all. Nineteen findings were all consistent with 0.774, and a
second independent read of the diff that answered them found nineteen more. A
green gate was necessary and was not sufficient, which is the section's own
sentence — twice now, on the same diff.
"""

from __future__ import annotations

import pytest

from integral.cue_audit import (
    CASES,
    MINIMUM_CASES,
    MINIMUM_CITABLE_FIELDS_CITED,
    MINIMUM_CITATIONS_CHECKED,
    MINIMUM_FAIL_OPEN_CASES,
    MINIMUM_MECHANISM_PINNED_CASES,
    UNCITED_FIELDS_ACKNOWLEDGED,
    AuditCase,
    audit,
    citation_check,
    resolve,
)
from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions


@pytest.fixture(scope="module")
def dimensions() -> list[Dimension]:
    return load_dimensions(DEFAULT_DIMENSIONS_DIR)


@pytest.fixture(scope="module")
def dimensions_by_id(dimensions: list[Dimension]) -> dict[str, Dimension]:
    return {dimension.id: dimension for dimension in dimensions}


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

    assert got.value == case.expected, (
        f"{case.dimension}[{case.language}] {case.text!r}\n"
        f"  {case.cites}\n"
        f"  requires {case.expected!r}, cue set returns {got.value!r} ({case.direction})"
    )
    if case.negated is not None:
        assert got.negated == case.negated, (
            f"{case.dimension}[{case.language}] {case.text!r}\n"
            f"  {case.cites}\n"
            f"  requires negated={case.negated!r}, cue set returns {got.negated!r}"
        )
    if case.matches is not None:
        assert got.matches == case.matches, (
            f"{case.dimension}[{case.language}] {case.text!r}\n"
            f"  {case.cites}\n"
            f"  requires {case.matches} raw cue match(es), cue set finds {got.matches}"
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
    assert audited["cue_audit_cases_pinning_mechanism"] >= MINIMUM_MECHANISM_PINNED_CASES
    assert audited["cue_audit_cases_pinning_mechanism_at_least"] == MINIMUM_MECHANISM_PINNED_CASES
    assert audited["cue_audit_citations_checked"] >= MINIMUM_CITATIONS_CHECKED
    assert audited["cue_audit_citations_checked_at_least"] == MINIMUM_CITATIONS_CHECKED


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c.dimension}-{c.language}-{c.text[:40]}")
def test_every_case_cites_the_text_it_was_decided_from(
    case: AuditCase, dimensions_by_id: dict[str, Dimension]
) -> None:
    """A verdict argued from what the code does is the circularity this breaks.

    Not a style check: the citation is the only thing separating this table from
    a transcript of the extractor's current behaviour, which would pass forever
    and protect nothing. Each `cites` names a `definition:` or a rung's `tell:`,
    and — the part nothing checked until T176 round 2's second reader — that
    quote must still occur, verbatim, in the field of the YAML it claims. A
    citation that stopped quoting its source (the `schedule_flexibility` spec
    corruption: `async\\w*hronous work…` written into the 0.7 rung's own
    `tell:`) is a citation of nothing, and `expected` alone never catches it —
    `expected` is asserted against the code, this is asserted against the YAML.
    """
    assert case.cites.strip(), case
    checked, mismatches = citation_check(case, dimensions_by_id)
    assert checked >= 1, f"{case.cites!r} names no definition/tell/label to verify"
    assert not mismatches, "\n".join(mismatches)


def test_the_audit_reaches_every_dimension_the_pr_widened() -> None:
    """T56 widened ten dimensions, and every one of them now carries a case.

    This docstring used to say `talking_clients` was deliberately absent because
    "the independent read passed its `atención al público` / `atenció al pacient`
    widening as clean". That was true of the **ES and CA** halves and of nothing
    else: the English rung was added in the same commit, was never read by
    anybody, and carried `help\\s?desk` at 1.0 — the rung whose tell is "the role
    IS the interface" — so "Helpdesk ticketing experience" scored a support job.

    A dimension recorded as *deliberately* uncovered is the cheapest place for a
    hole to sit, because the sentence excusing it reads like diligence. The
    second read found the hole; the cases are here now.
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
        "talking_clients",
        "travel_requirement",
    }

    assert widened_with_findings <= covered, sorted(widened_with_findings - covered)
    # And the two dimensions a finding *moved a statement to*, which is the half
    # of a "this belongs elsewhere" finding that a deletion alone never proves.
    assert {"commute_burden", "career_progression"} <= covered


def test_a_none_verdict_says_which_kind_of_none_it_is() -> None:
    """At least one case must pin `matches` on each side of the `None` fork.

    `None` has two causes — the cue set is silent, and the cue set read something
    the bipolar corroboration rule then withheld — and the rounded value cannot
    tell them apart. The Arelance boilerplate is the second kind: with the
    `nuestros candidatos` register cue removed it still matches the clause the
    owner's own label cites, once, and one match does not settle a bipolar
    dimension. A future edit that deleted the surviving legitimate cue would
    leave the value at `None` and look identical here without this.
    """
    silent = [c for c in CASES if c.expected is None and c.matches == 0]
    withheld = [c for c in CASES if c.expected is None and c.matches == 1]

    assert silent, "no case pins a None that means 'nothing matched'"
    assert withheld, "no case pins a None that means 'a reading was withheld'"


def test_every_definition_and_tell_is_cited_or_acknowledged() -> None:
    """T178 round 3, finding 4 — a rule over the *fields*, not a count of citations.

    `MINIMUM_CITATIONS_CHECKED` moves whenever any case cites anything, so one
    case double-citing an already-protected field inflates it without covering
    anything new — which is exactly how `schedule_flexibility.definition` sat
    uncited while the floor kept climbing. This asserts the population instead:
    every `definition:`/`tell:` in the committed model is either cited by some
    case in `CASES` or named in `UNCITED_FIELDS_ACKNOWLEDGED`, and the
    acknowledgement list contains nothing that is not — both directions, so it
    cannot silently grow stale in either one.
    """
    audited = audit()
    assert audited["cue_audit_unacknowledged_uncited_fields"] == 0, audited["cue_audit_failing_cases"]
    assert audited["cue_audit_stale_acknowledgements"] == 0, audited["cue_audit_failing_cases"]
    assert audited["cue_audit_citable_fields"] == len(UNCITED_FIELDS_ACKNOWLEDGED) + audited["cue_audit_fields_cited"]
    assert audited["cue_audit_fields_cited"] >= MINIMUM_CITABLE_FIELDS_CITED
    assert audited["cue_audit_fields_cited_at_least"] == MINIMUM_CITABLE_FIELDS_CITED


def test_the_field_coverage_rule_actually_fires() -> None:
    """The rule above reads 0/0 today; this proves that is coverage, not vacuity.

    Three constructed states, each a real defect shape: a case whose citation is
    quietly dropped (the exact accident that hid the `schedule_flexibility`
    corruption), an acknowledgement removed while its field is still uncited
    (the same hole, arrived at from the allowlist side), and a stale
    acknowledgement left in place after its field became genuinely cited (the
    allowlist rotting the other direction). Each must turn up as a named
    failure, not as a silently-passing 0.
    """
    dropped = tuple(
        AuditCase(
            c.dimension,
            c.language,
            c.text,
            c.expected,
            "0.7 tell: 'asynchronous work, compressed weeks, or hours the person genuinely sets'",
            c.direction,
            c.negated,
            c.matches,
        )
        if c.dimension == "schedule_flexibility" and c.text == "We support an asynchronous company culture."
        else c
        for c in CASES
    )
    result = audit(cases=dropped)
    assert result["cue_audit_unacknowledged_uncited_fields"] == 1
    assert any(
        "schedule_flexibility.definition" in failure and "not listed in UNCITED_FIELDS_ACKNOWLEDGED" in failure
        for failure in result["cue_audit_failing_cases"]
    )

    import integral.cue_audit as cue_audit_module

    original = cue_audit_module.UNCITED_FIELDS_ACKNOWLEDGED
    try:
        cue_audit_module.UNCITED_FIELDS_ACKNOWLEDGED = frozenset(
            original - {("ai_in_the_work", "definition", None)}
        )
        result = audit()
        assert result["cue_audit_unacknowledged_uncited_fields"] == 1
        assert any("ai_in_the_work.definition" in failure for failure in result["cue_audit_failing_cases"])

        cue_audit_module.UNCITED_FIELDS_ACKNOWLEDGED = frozenset(
            original | {("mission_alignment", "definition", None)}
        )
        result = audit()
        assert result["cue_audit_stale_acknowledgements"] == 1
        assert any(
            "mission_alignment.definition" in failure and "remove the stale entry" in failure
            for failure in result["cue_audit_failing_cases"]
        )
    finally:
        cue_audit_module.UNCITED_FIELDS_ACKNOWLEDGED = original
