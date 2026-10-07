"""T233 — a ranking that does not order offers names the input that bears on them."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from integral.rank import (
    _FIXTURE_DIMENSIONS,
    ASKS_EMPLOYER,
    DEFAULT_T233_EVIDENCE_PATH,
    MINIMUM_UNSEPARATED_RANKINGS,
    NON_ORDERING_FIELDS,
    _t233_candidates,
    _t233_cases,
    _t233_rank,
    measure_missing_inputs,
    missing_inputs,
    order_readings,
    t233_discrepancies,
    unseparated_units,
)

CASES = _t233_cases()
RANKS = [_t233_rank(c) for c in CASES]
(
    IDENTICAL,
    L1_TIED,
    L1_NO_SALARY,
    UNKNOWN_PRICED,
    L2_NO_SALARY,
    BARE,
    TRAIT,
    TRAIT_UNSCORED,
    GENUINE_TIE,
    FIT_ONLY,
) = range(10)


def entries(index: int) -> list[dict[str, Any]]:
    return missing_inputs(RANKS[index], _t233_candidates(CASES[index]))


def names(index: int) -> list[str]:
    return [e["input"] for e in entries(index)]


def test_every_case_leaves_offers_unseparated() -> None:
    assert all(unseparated_units(r) for r in RANKS)
    assert len(RANKS) == MINIMUM_UNSEPARATED_RANKINGS


# --- F1: every field that says "not ordered" is read -----------------------------------------


def test_the_listed_fields_are_exactly_the_non_ordering_fields_order_readings_publishes() -> None:
    published = set(order_readings([], {}))
    assert published - {"order_basis"} == set(NON_ORDERING_FIELDS)


@pytest.mark.parametrize(
    ("field", "index"),
    [("ties", IDENTICAL), ("incomparable", UNKNOWN_PRICED), ("unordered", L1_NO_SALARY)],
)
def test_blanking_any_non_ordering_field_changes_what_is_unseparated(field: str, index: int) -> None:
    ranking = RANKS[index]
    assert ranking[field], "the example must publish this field"
    assert unseparated_units({**ranking, field: []}) < unseparated_units(ranking)


def test_an_unknown_priced_dimension_is_named_on_the_incomparable_pair() -> None:
    assert not RANKS[UNKNOWN_PRICED]["ties"]
    assert RANKS[UNKNOWN_PRICED]["incomparable"]
    assert names(UNKNOWN_PRICED) == ["unknown:remote"]


def test_an_unpublished_salary_on_an_incomparable_pair_is_named() -> None:
    assert RANKS[L2_NO_SALARY]["incomparable"]
    assert names(L2_NO_SALARY) == ["salary"]


# --- F5: the salary path, and whose answer it is ---------------------------------------------


def test_salary_is_named_for_the_offer_without_one_and_is_the_employers_to_give() -> None:
    assert RANKS[L1_NO_SALARY]["unordered"]
    [entry] = entries(L1_NO_SALARY)
    assert entry["input"] == "salary"
    assert entry["asked_of"] == "employer"
    assert entry["answer_would"] == ASKS_EMPLOYER


def test_a_candidate_input_is_asked_of_the_candidate() -> None:
    [entry] = entries(L1_TIED)
    assert (entry["input"], entry["offers"], entry["asked_of"]) == ("weights", 2, "candidate")


# --- F2: an input is named only if it bears on an unseparated offer --------------------------


def test_identical_offers_are_unseparated_and_nothing_would_separate_them() -> None:
    assert unseparated_units(RANKS[IDENTICAL])
    assert entries(IDENTICAL) == []


def test_a_trait_no_offer_scores_is_not_named() -> None:
    assert RANKS[TRAIT_UNSCORED]["unpriced_trait_dimensions"]["dimensions"] == ["company_kind"]
    assert entries(TRAIT_UNSCORED) == []


def test_a_trait_that_is_not_a_ranked_dimension_is_not_named() -> None:
    case = {k: v for k, v in CASES[TRAIT].items() if k != "extra_dimensions"}
    candidates = [
        replace(c, scores={k: v for k, v in c.scores.items() if k in _FIXTURE_DIMENSIONS})
        for c in CASES[TRAIT]["candidates"]
    ]
    case["candidates"] = candidates
    ranking = _t233_rank(case)
    assert "company_kind" in ranking["unpriced_trait_dimensions"]["dimensions"]
    assert "company_kind" not in ranking["dimensions"]
    assert missing_inputs(ranking, _t233_candidates(case)) == []


def test_a_real_tie_with_everything_priced_and_known_reports_nothing_missing() -> None:
    assert unseparated_units(RANKS[GENUINE_TIE])
    assert entries(GENUINE_TIE) == []


def test_an_axis_read_from_the_cv_is_never_asked_of_the_candidate() -> None:
    assert entries(FIT_ONLY) == []


def test_a_ranked_dimension_nothing_prices_is_a_preference_and_a_said_one_a_weight() -> None:
    assert names(BARE) == ["preference:company_kind"]
    assert names(TRAIT) == ["weight:company_kind"]


# --- F6: the gate measures both directions ---------------------------------------------------


def test_the_measure_is_clean_and_each_direction_can_rise() -> None:
    measured = measure_missing_inputs()
    assert measured["rankings_with_unordered_ties_and_no_named_missing_input"] == 0
    assert measured["inputs_named_that_bear_on_no_unseparated_offer"] == 0
    assert measured["nothing_missing_controls"] == 4
    assert measured["silent_when_reporter_is_empty"] == 6
    assert measured["spurious_when_reporter_always_names_weights"] > 0


def test_a_reporter_reduced_to_one_fallback_is_caught_in_both_directions() -> None:
    found = t233_discrepancies(CASES, lambda _r, _c: [{"input": "preferences"}])
    assert found["silent"] > 0
    assert found["spurious"] > 0


def test_committed_evidence_matches_the_measure() -> None:
    committed = json.loads(Path(DEFAULT_T233_EVIDENCE_PATH).read_text(encoding="utf-8"))
    assert committed == measure_missing_inputs()


# --- F7: the instruction itself is pinned, not a keyword -------------------------------------

ROOT = Path(__file__).resolve().parents[1]
TEXTS = {
    "step-07": ROOT / ".claude/skills/step-07-sourcing/SKILL.md",
    "step-09": ROOT / ".claude/skills/step-09-ranking/SKILL.md",
    "spec": ROOT / "status/spec-v2-steps.md",
}
#: The passage each file gives to the T233 instruction: from its start marker to its end marker.
REGION = {
    "step-07": ("```text\n\"Fourteen new", "Writes `last_activity`."),
    "step-09": ("## Say what the order could not use (T233)", "## Say what is working"),
    "spec": ("**Boundary.** *\"Fourteen new", "**Gate.** `offer_schema"),
}
RULE = {
    "step-07": "never ask whether they want it ranked",
    "step-09": "never ask whether to rank before showing the list",
    "spec": "The ranked view follows at once, with no question first",
}
ASKING = re.compile(r"\b(ask|asks|asking|want|wants|shall|should)\b", re.I)
RANKING = re.compile(r"\brank(?:ed|ing)?\b", re.I)
BEFORE = re.compile(r"\b(whether|if|before)\b", re.I)
EXEMPT = re.compile(r"\b(never|no question|not|without|nor|only after|comes last)\b", re.I)


def instruction_defects(name: str, text: str) -> list[str]:
    """The rule sentence must be present, and no sentence may ask before ranking."""
    start, end = REGION[name]
    if start not in text or end not in text:
        return [f"{name}: the T233 passage is missing"]
    flat = " ".join(text[text.index(start) : text.index(end, text.index(start))].split())
    defects = [] if RULE[name] in flat else [f"{name}: the rule sentence is missing"]
    for sentence in re.split(r"(?<=[.?!])\s+", flat):
        if (
            ASKING.search(sentence)
            and RANKING.search(sentence)
            and BEFORE.search(sentence)
            and not EXEMPT.search(sentence)
        ):
            defects.append(f"{name}: asks before ranking: {sentence[:80]}")
        if "Want to see them" in sentence:
            defects.append(f"{name}: the old question is back")
    return defects


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_the_instruction_is_present_and_no_ask_before_ranking_wording_remains(name: str) -> None:
    assert instruction_defects(name, TEXTS[name].read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("name", sorted(TEXTS))
def test_the_check_refuses_an_inverted_instruction(name: str) -> None:
    inverted = "Ask the candidate whether they want the list ranked before showing it."
    assert instruction_defects(name, inverted)
    assert instruction_defects(name, "Want to see them?")


def test_the_step_9_section_caps_what_is_said_and_does_not_claim_a_separation() -> None:
    text = " ".join(TEXTS["step-09"].read_text(encoding="utf-8").split())
    assert "no more than two" in text
    assert "never" in text and "would separate" in text
    assert "are not currently separated" in text


def test_the_step_7_close_puts_the_list_before_the_question() -> None:
    text = TEXTS["step-07"].read_text(encoding="utf-8")
    assert text.index("[the ranked list follows]") < text.index("Want to?")
