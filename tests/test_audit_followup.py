"""T102's gate: an audit finding stays red until a gate holds it.

Every case below is written against `audit_followup`'s stated rule and not
against its output — the anti-vacuity direction matters more here than usual,
because the module's whole subject is a check that reported success over work it
had not done.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral import audit_followup
from integral.robots import FIXTURES

_A_REAL_FIXTURE = "a_prefix_file_token_does_not_displace_the_wildcard_group"

_PREAMBLE = "# An audit\n\nSome prose that mentions § and no defect, outside any case.\n\n"


def _audit(tmp_path: Path, body: str) -> Path:
    (tmp_path / "one.md").write_text(_PREAMBLE + body, encoding="utf-8")
    return tmp_path


def test_a_real_fixture_name_is_still_in_the_committed_table() -> None:
    # The rest of this file is vacuous if this drifts: a "settled" case would be
    # settled by a name that matches nothing.
    assert _A_REAL_FIXTURE in {fixture.name for fixture in FIXTURES}


def test_an_open_discrepancy_is_counted(tmp_path: Path) -> None:
    d = _audit(tmp_path, "### 1. `x` — **DISCREPANCY (fail-open)**\n- required: blocked\n")
    measured = audit_followup.measure(d)
    assert measured["uncommitted_audit_cases"] == 1
    assert "open discrepancy" in measured["open_cases"][0]["why"]


def test_a_match_is_not_owed(tmp_path: Path) -> None:
    d = _audit(tmp_path, "### 1. `x` — MATCH\n- required: blocked\n")
    assert audit_followup.measure(d)["uncommitted_audit_cases"] == 0


def test_a_case_that_is_neither_a_match_nor_a_discrepancy_is_not_owed(tmp_path: Path) -> None:
    # The round-2 audit's case 35, whose heading declares itself out of the
    # fail-open/fail-closed vocabulary. Excluded by what it says it is.
    d = _audit(tmp_path, "### 35. `x` — **NEITHER pass nor a fail-open/fail-closed defect**\n")
    assert audit_followup.measure(d)["uncommitted_audit_cases"] == 0


def test_a_resolved_case_that_cites_no_section_is_still_counted(tmp_path: Path) -> None:
    d = _audit(tmp_path, f"### 1. `x` — **RESOLVED**\n\n> no defect, {_A_REAL_FIXTURE}\n")
    measured = audit_followup.measure(d)
    assert measured["uncommitted_audit_cases"] == 1
    assert "citing a section" in measured["open_cases"][0]["why"]


def test_a_resolved_case_naming_neither_a_fixture_nor_no_defect_is_counted(
    tmp_path: Path,
) -> None:
    d = _audit(tmp_path, "### 1. `x` — **RESOLVED**\n\n> Settled per RFC 9309 §2.2.1. Trust me.\n")
    measured = audit_followup.measure(d)
    assert measured["uncommitted_audit_cases"] == 1
    assert "committed fixture" in measured["open_cases"][0]["why"]


def test_naming_a_fixture_that_is_not_in_the_table_does_not_settle_a_case(
    tmp_path: Path,
) -> None:
    # The failure mode the module is built against: a resolution that points at
    # a gate nobody wrote reads exactly like one that points at a gate that
    # exists, until the names are checked against the table.
    d = _audit(
        tmp_path,
        "### 1. `x` — **RESOLVED**\n\n> Per RFC 9309 §2.2.1, held by "
        "`a_fixture_that_was_never_committed`.\n",
    )
    assert audit_followup.measure(d)["uncommitted_audit_cases"] == 1


@pytest.mark.parametrize("closing", ["no defect", f"`{_A_REAL_FIXTURE}`"])
def test_a_resolved_case_that_cites_a_section_and_closes_honestly_is_settled(
    tmp_path: Path, closing: str
) -> None:
    d = _audit(tmp_path, f"### 1. `x` — **RESOLVED**\n\n> Per RFC 9309 §2.2.1: {closing}.\n")
    assert audit_followup.measure(d)["uncommitted_audit_cases"] == 0


def test_an_empty_audits_dir_reports_unmeasured(tmp_path: Path) -> None:
    measured = audit_followup.measure(tmp_path)
    assert measured["uncommitted_audit_cases_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_floor_is_below_what_the_committed_audits_actually_carry() -> None:
    # A floor above the real count would be red on every checkout; a floor of
    # zero would let the directory empty out silently.
    measured = audit_followup.measure()
    assert audit_followup.CASES_AT_LEAST > 0
    assert measured["uncommitted_audit_cases_evaluated"] >= audit_followup.CASES_AT_LEAST


def test_the_committed_audits_carry_no_unheld_finding() -> None:
    measured = audit_followup.measure()
    assert measured["open_cases"] == []
    assert measured["gate_status"] == "measured"


def test_the_main_entry_point_exits_nonzero_while_a_finding_is_unheld(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "audits").mkdir()
    audits = _audit(tmp_path / "audits", "### 1. `x` — **DISCREPANCY (fail-open)**\n")
    evidence = tmp_path / "T102.json"
    measured = audit_followup.write_evidence(evidence, audits)
    assert measured["uncommitted_audit_cases"] == 1
    assert evidence.exists()
