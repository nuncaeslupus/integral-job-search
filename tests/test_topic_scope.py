"""T227 — a topic exclusion reads the employer and the job, not any sentence.

The verdicts live in `tests/fixtures/topic_scope/cases.json`, each with the reason
it is the one it is, derived from the task text (a payroll startup that values a
"Background in FinTech", a firmware engineer held as advertising, 58 adverts held
through "ticket restaurant"). The tests below run every case and pin the pieces
the cases cannot name on their own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral import sourcing_exclusions as se
from integral import topic_scope as ts
from integral import topic_scope_gate as gate

CASES: list[dict[str, Any]] = json.loads(gate.DEFAULT_CASES_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_every_case_has_the_verdict_its_reason_requires(case: dict[str, Any]) -> None:
    candidate, exclusion = gate._parts(case)
    assert se.matches(candidate, exclusion) is case["held"], case["why"]


def test_every_case_carries_a_reason_and_ids_are_unique() -> None:
    assert all(c["why"].strip() for c in CASES)
    assert len({c["id"] for c in CASES}) == len(CASES)


def test_both_populations_clear_their_floors() -> None:
    assert sum(c["held"] for c in CASES) >= gate.FEWEST_HELD_CASES
    assert sum(not c["held"] for c in CASES) >= gate.FEWEST_SHOWN_CASES


def _exclusion(value: str = "fintech") -> se.Exclusion:
    return se.Exclusion(about=f"sector:{value}", stated_at_cycle=1, words="no")


def test_a_title_hit_is_named_with_its_words_and_place() -> None:
    candidate = se.Candidate(offer_id="x", title="Engineer, FinTech", text="plain")
    (said,) = se.held_in_words(candidate, [_exclusion()])
    assert said == "sector:fintech — «fintech» en el título"


def test_a_text_hit_is_named_as_the_advert_text() -> None:
    candidate = se.Candidate(offer_id="x", text="We are a fintech.")
    (said,) = se.held_in_words(candidate, [_exclusion()])
    assert "«fintech» en el texto del anuncio" in said


def test_an_employer_hold_names_no_words() -> None:
    employer = se.Exclusion(about="employer:acme", stated_at_cycle=1, words="no acme")
    candidate = se.Candidate(offer_id="x", title="Dev", text="t", employer="Acme S.L.")
    assert se.held_in_words(candidate, [employer]) == ("employer:acme",)


def test_held_in_words_agrees_with_ruled_out_by_on_what_is_held() -> None:
    candidate = se.Candidate(offer_id="x", title="Fintech dev", text="Requirements:\n- banking")
    exclusions = [_exclusion(), _exclusion("banking")]
    said = se.held_in_words(candidate, exclusions)
    assert [s.partition(" — ")[0] for s in said] == list(se.ruled_out_by(candidate, exclusions))
    assert said and all(s.startswith("sector:fintech") for s in said)


# --- the closed rule, not the cases -------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "Benefits:",
        "## What we offer",
        "**Requirements**",
        "NICE TO HAVE",
        "Qué ofrecemos:",
        "Requisitos valorables:",
        "Your profile:",
    ],
)
def test_a_section_under_an_off_topic_heading_is_not_read(heading: str) -> None:
    text = f"We make sensors.\n\n{heading}\n- fintech\n- more fintech\n\nAbout the team\nPlain."
    kept = ts.topic_text(text)
    assert "fintech" not in kept and "sensors" in kept and "Plain" in kept


def test_a_section_ends_at_the_next_heading() -> None:
    kept = ts.topic_text("Benefits:\n- gym\n\nAbout us:\nWe are a fintech.")
    assert "fintech" in kept


def test_removed_text_never_joins_the_fragments_either_side() -> None:
    text = "We are a fin\nBackground in X\ntech company."
    assert not se.matches(se.Candidate(offer_id="x", text=text), _exclusion())


def test_the_gate_measures_zero_and_is_unmeasured_over_too_few_cases(tmp_path: Path) -> None:
    measured = gate.measure()
    assert measured["status"] == "measured"
    assert measured["adverts_excluded_on_a_perk_or_nice_to_have"] == 0
    assert measured["adverts_on_the_topic_shown"] == 0
    assert measured["held_without_the_words"] == 0
    few = tmp_path / "cases.json"
    few.write_text(json.dumps(CASES[:3]), encoding="utf-8")
    thin = gate.measure(few)
    assert thin["status"] == "unmeasured"
    assert thin["adverts_excluded_on_a_perk_or_nice_to_have"] == -1


def test_a_matcher_that_reads_the_whole_advert_turns_the_gate_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old behaviour, restored, must be caught by the gate and not only the cases."""
    monkeypatch.setattr(ts, "topic_text", lambda text: text)
    measured = gate.measure()
    assert measured["adverts_excluded_on_a_perk_or_nice_to_have"] >= 10


def test_a_matcher_that_reads_no_text_turns_the_gate_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opposite failure: strip everything and the on-topic adverts are shown."""
    monkeypatch.setattr(ts, "topic_text", lambda text: "")
    assert gate.measure()["adverts_on_the_topic_shown"] >= 5


def test_main_exits_zero_on_the_committed_cases(tmp_path: Path) -> None:
    assert gate._main(["x", str(tmp_path / "T227.json")]) == 0


def test_the_gate_counts_a_hold_that_names_no_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """`held_without_the_words` must be able to fire, not only read zero."""
    monkeypatch.setattr(se, "held_in_words", lambda candidate, exclusions: ("sector:x",))
    assert gate.measure()["held_without_the_words"] >= 1


def test_a_line_of_two_sentences_is_read_sentence_by_sentence() -> None:
    kept = ts.topic_text("We run a sports betting exchange. Kubernetes is a plus.")
    assert "betting" in kept and "Kubernetes" not in kept


@pytest.mark.parametrize(
    "heading",
    [
        "Company profile:",
        "Perfil de la empresa:",
        "About us and what we offer:",
        "Player Experience",
        "Strong communication and collaboration skills",
    ],
)
def test_a_heading_with_one_off_topic_word_is_not_off_topic(heading: str) -> None:
    assert not ts._off_topic_heading(ts._heading_text(heading))


@pytest.mark.parametrize(
    "heading",
    [
        "Required Skills & Experience",
        "Nice-to-Have Skills",
        "Minimum requirements",
        "Perks and benefits",
    ],
)
def test_a_heading_made_only_of_off_topic_words_is_off_topic(heading: str) -> None:
    assert ts._off_topic_heading(ts._heading_text(heading))


def test_a_skipped_section_ends_at_a_heading_with_no_blank_line_before_it() -> None:
    kept = ts.topic_text("Benefits\n- Gym\nAbout Acme\nWe run casinos.")
    assert "casinos" in kept and "Gym" not in kept


@pytest.mark.parametrize("heading", ["The", "Y la", "de los"])
def test_a_heading_of_function_words_only_is_not_off_topic(heading: str) -> None:
    assert not ts._off_topic_heading(ts._heading_text(heading))


@pytest.mark.parametrize(
    "heading", ["Perks 🎁", "Requirements (must have)", "Requisitos imprescindibles"]
)
def test_decoration_and_brackets_do_not_stop_a_heading_being_off_topic(heading: str) -> None:
    assert ts._off_topic_heading(ts._heading_text(heading))


def test_a_run_of_short_lines_under_a_perks_heading_is_a_list() -> None:
    kept = ts.topic_text("Build APIs.\n\nBenefits\nGym\nRestaurant discounts\nRemote work")
    assert "Restaurant" not in kept and "APIs" in kept


@pytest.mark.parametrize("verb", ["Vendemos", "Operamos", "Gestionamos", "Desarrollamos"])
def test_each_spanish_self_verb_rescues_a_sentence(verb: str) -> None:
    assert "seguro" in ts.topic_text(f"{verb} seguro médico privado.")
