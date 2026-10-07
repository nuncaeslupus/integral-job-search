"""T233 — a ranking the data does not separate says which input is missing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integral.rank import (
    DEFAULT_T233_EVIDENCE_PATH,
    MINIMUM_UNSEPARATED_RANKINGS,
    _t233_cases,
    _t233_rank,
    measure_missing_inputs,
    missing_inputs,
    silent_unseparated_rankings,
)

CASES = [_t233_rank(c) for c in _t233_cases()]
L1_TIED, NO_SALARY, L2_TIED, UNPRICED, L1_SEPARATED = CASES


def names(ranking: dict[str, Any]) -> list[str]:
    return [e["input"] for e in missing_inputs(ranking)]


def test_no_weights_and_tied_names_weights_with_the_count() -> None:
    assert missing_inputs(L1_TIED) == [
        {"input": "weights", "offers": 2, "answer_would": "price_dimensions"}
    ]


def test_a_separated_ranking_reports_nothing() -> None:
    assert not (L1_SEPARATED["ties"] or L1_SEPARATED["unordered"])
    assert missing_inputs(L1_SEPARATED) == []


def test_a_ranked_dimension_with_no_price_is_named_as_a_preference() -> None:
    assert "preference:company_kind" in names(NO_SALARY)


def test_a_dimension_with_trait_evidence_but_no_price_is_named_as_a_weight() -> None:
    assert "weight:company_kind" in names(UNPRICED)
    assert "preference:company_kind" not in names(UNPRICED)


def test_a_tie_nothing_explains_still_names_preferences() -> None:
    assert L2_TIED["ties"]
    assert names(L2_TIED) == ["preferences"]


def test_every_unseparated_case_is_named_and_the_audit_can_rise() -> None:
    assert silent_unseparated_rankings(CASES) == 0
    assert silent_unseparated_rankings(CASES, lambda _r: []) == 4
    assert MINIMUM_UNSEPARATED_RANKINGS == 4


def test_committed_evidence_matches_the_measure() -> None:
    committed = json.loads(Path(DEFAULT_T233_EVIDENCE_PATH).read_text(encoding="utf-8"))
    assert committed == measure_missing_inputs()


ROOT = Path(__file__).resolve().parents[1]
SOURCING = (ROOT / ".claude/skills/step-07-sourcing/SKILL.md").read_text(encoding="utf-8")
RANKING = (ROOT / ".claude/skills/step-09-ranking/SKILL.md").read_text(encoding="utf-8")
SPEC = (ROOT / "status/spec-v2-steps.md").read_text(encoding="utf-8")


def test_sourcing_closes_on_the_ranked_view_without_asking() -> None:
    assert "Want to see them" not in SOURCING
    assert "Want to see them" not in SPEC
    assert "never ask\nwhether they want it ranked" in SOURCING
    assert "missing_inputs(ranking)" in SOURCING


def test_ranking_step_says_the_missing_inputs() -> None:
    assert "from integral.rank import missing_inputs" in RANKING
