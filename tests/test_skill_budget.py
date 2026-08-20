"""The listing budget this project accepts, and the ways a raised cap goes bad (S10).

Raising a threshold is the easy half. The hard half is that a raised threshold
is indistinguishable from a threshold that was fitted to whatever the code
happened to measure — and the second one protects nothing while reporting the
same clean zero as the first.

So most of what follows is not "is the library inside the budget". It is:

* the declared number is **round**, so a budget silently reset to the current
  total (11,686, say) fails mechanically rather than passing;
* the declared number leaves **headroom**, so a cap the library exactly fills
  is a failure now instead of a raise next week;
* the reading records **where its budget came from**, and the committed
  evidence says `declared` — a gate an environment variable can satisfy for one
  run is not a gate;
* the total agrees with `audit_library.py`'s own, because a measurement that
  restates upstream's formula agrees with a formula upstream has changed (D-11).

And the S10 requirement that is not about characters at all:
`steps_with_a_skill_fraction` must still be 1.0, so the saving cannot have come
from dropping a step.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from jobsearch.skill_budget import (
    BUDGET_GRANULARITY,
    DEFAULT_SKILLS_DIR,
    ENV_OVERRIDE,
    LISTING_BUDGET_CHARS,
    MIN_HEADROOM_CHARS,
    UPSTREAM_DEFAULT_BUDGET_CHARS,
    SkillBudgetError,
    check_declaration,
    effective_budget,
    listing_cost,
    measure,
    skill_costs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "status" / "evidence" / "S10.json"
AUDIT = REPO_ROOT / ".claude" / "skills" / "skill-creator" / "scripts" / "audit_library.py"


def write_skill(root: Path, name: str, description: str) -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody.\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# the gate


def test_the_library_is_within_its_listing_budget() -> None:
    measured = measure()
    assert measured["skill_listing_budget_overage_chars"] == 0
    assert measured["budget_declaration_reasons"] == []


def test_every_step_is_still_reachable_after_the_change() -> None:
    """Whichever option was taken, the saving must not come from dropping a
    step — so the fraction is asserted here, next to the budget it could have
    been traded against."""
    assert measure()["steps_with_a_skill_fraction"] == 1.0


def test_the_committed_evidence_matches_what_the_code_measures_now() -> None:
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    measured = measure()
    assert committed["skill_listing_budget_overage_chars"] == (
        measured["skill_listing_budget_overage_chars"]
    )
    assert committed["description_chars_total"] == measured["description_chars_total"]


def test_committed_evidence_was_measured_against_the_declared_budget() -> None:
    """A gate an environment variable can satisfy for one run is not a gate."""
    assert json.loads(EVIDENCE.read_text(encoding="utf-8"))["budget_source"] == "declared"


def test_the_evidence_still_reports_the_overage_against_upstreams_default() -> None:
    """We are over upstream's 8,000 deliberately. Raising our own cap must not
    make that fact invisible — it is the number the next person needs to decide
    whether the decision still holds."""
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert committed["upstream_default_budget_chars"] == UPSTREAM_DEFAULT_BUDGET_CHARS
    assert committed["overage_against_upstream_default"] > 0


# ---------------------------------------------------------------------------
# the declaration


def test_the_declared_budget_is_a_number_somebody_chose() -> None:
    assert LISTING_BUDGET_CHARS % BUDGET_GRANULARITY == 0
    assert LISTING_BUDGET_CHARS > UPSTREAM_DEFAULT_BUDGET_CHARS


def test_a_budget_fitted_to_the_measurement_is_refused() -> None:
    """The failure a configurable cap invites and a hardcoded one cannot have:
    the knob turned to exactly what the library measures."""
    total = measure()["description_chars_total"]
    fitted = check_declaration(total, "override", total)
    assert not fitted.passes
    assert any("not a multiple" in reason for reason in fitted.reasons)


def test_a_budget_with_no_headroom_is_refused() -> None:
    total = 11_686
    snug = check_declaration(12_000, "override", 11_800)
    assert not snug.passes
    assert any("headroom" in reason for reason in snug.reasons)
    assert check_declaration(13_000, "declared", total).passes


def test_the_declared_budget_leaves_room_for_at_least_one_more_skill() -> None:
    measured = measure()
    assert measured["headroom_chars"] >= MIN_HEADROOM_CHARS


def test_the_reading_says_where_its_budget_came_from() -> None:
    assert effective_budget() == (LISTING_BUDGET_CHARS, "declared")
    assert effective_budget(20_000) == (20_000, "override")
    assert effective_budget(None, {ENV_OVERRIDE: "20000"}) == (20_000, "override")
    assert effective_budget(None, {}) == (LISTING_BUDGET_CHARS, "declared")


def test_an_unusable_budget_is_refused_rather_than_guessed_at() -> None:
    with pytest.raises(SkillBudgetError):
        effective_budget(0)
    with pytest.raises(SkillBudgetError):
        effective_budget(None, {ENV_OVERRIDE: "lots"})


# ---------------------------------------------------------------------------
# the measurement


def test_the_measurement_agrees_with_the_upstream_audit() -> None:
    """The per-skill formula is upstream's, mirrored. If it changes there, this
    fails here — rather than leaving two numbers nobody compares."""
    result = subprocess.run(
        [sys.executable, str(AUDIT), str(DEFAULT_SKILLS_DIR)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    # The audit reports on stderr; read both so a future move does not silently
    # turn this into a test that finds nothing and asserts nothing.
    reported = [
        line
        for line in (result.stdout + result.stderr).splitlines()
        if "listing-budget total:" in line
    ]
    assert reported, f"the audit printed no budget total:\n{result.stdout}\n{result.stderr}"
    upstream_total = int(reported[0].split("listing-budget total:")[1].split("chars")[0].strip())
    assert measure()["description_chars_total"] == upstream_total


def test_one_skills_listing_cost_is_its_description_its_name_and_the_line() -> None:
    assert listing_cost("abc", "name") == 3 + 4 + 4


def test_a_skill_without_a_description_costs_nothing(tmp_path: Path) -> None:
    """Matching upstream exactly: counting it differently would put our total
    and the audit's out of step for a file neither can read."""
    write_skill(tmp_path, "with-one", "a description")
    (tmp_path / "no-frontmatter").mkdir()
    (tmp_path / "no-frontmatter" / "SKILL.md").write_text("no front matter here\n")
    (tmp_path / "not-a-skill").mkdir()

    assert [cost.skill for cost in skill_costs(tmp_path)] == ["with-one"]


def test_a_missing_library_is_refused_not_measured_as_zero(tmp_path: Path) -> None:
    """An empty measurement is the most dangerous reading available: nothing
    costs anything, so nothing is ever over budget."""
    with pytest.raises(SkillBudgetError):
        skill_costs(tmp_path / "nowhere")
    assert measure(tmp_path / "nowhere")["skill_listing_budget_overage_chars"] == -1


def test_a_library_over_its_budget_reports_the_overage(tmp_path: Path) -> None:
    write_skill(tmp_path, "big", "x" * 500)
    measured = measure(tmp_path, budget=100)
    assert measured["skill_listing_budget_overage_chars"] > 0
    assert measured["budget_source"] == "override"


def test_the_cli_exits_nonzero_when_the_library_is_over(tmp_path: Path) -> None:
    write_skill(tmp_path, "big", "x" * 500)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "jobsearch.skill_budget",
            "--check",
            "--skills-dir",
            str(tmp_path),
            "--budget",
            "100",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 1
    assert "over budget by" in result.stderr


def test_the_cli_prints_the_budget_in_force_and_its_source() -> None:
    """The line the upstream issue asks for: a raise nobody can see is a raise
    nobody can question."""
    result = subprocess.run(
        [sys.executable, "-m", "jobsearch.skill_budget", "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert f"listing budget: {LISTING_BUDGET_CHARS} chars (declared)" in result.stderr
    assert f"above upstream's {UPSTREAM_DEFAULT_BUDGET_CHARS}-char default" in result.stderr


def test_nothing_under_vendor_was_patched_to_achieve_this() -> None:
    """The sequence S10's payload forbids short-cutting: a subtree edit works
    perfectly until the next `git subtree pull` reverts it, silently."""
    upstream = (
        REPO_ROOT
        / "vendor"
        / "claude-arsenal"
        / "plugins"
        / "skill-creator"
        / "skills"
        / "skill-creator"
        / "scripts"
        / "audit_library.py"
    )
    assert f"LISTING_BUDGET_CHARS = {UPSTREAM_DEFAULT_BUDGET_CHARS}" in upstream.read_text(
        encoding="utf-8"
    )
