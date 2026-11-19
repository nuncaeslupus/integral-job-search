"""Pay transparency (directive 2023/970): ask for the range, never give current pay."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.candidate import OfferFacts
from integral.form_answers import FormAnswer, answer_defects
from integral.identity import ProfileStore, create_profile
from integral.pay_transparency import RANGE_PROMPT, range_prompt
from integral.profile import EvidenceLog

NO_RANGE = OfferFacts(offer_id="o1", country="ES", delivery="remote")
WITH_RANGE = NO_RANGE.model_copy(
    update={"salary_stated": True, "salary_min": 40000, "salary_max": 50000}
)


@pytest.mark.parametrize("lang", ["es", "en", "ca"])
def test_no_range_advert_prompts_in_each_language(lang: str) -> None:
    text = range_prompt(NO_RANGE, lang)  # type: ignore[arg-type]
    assert text == RANGE_PROMPT[lang] and "2023/970" in text  # type: ignore[index]
    assert len({RANGE_PROMPT[k] for k in ("es", "en", "ca")}) == 3


@pytest.mark.parametrize("lang", ["es", "en", "ca"])
def test_advert_with_a_range_does_not_prompt(lang: str) -> None:
    assert range_prompt(WITH_RANGE, lang) is None  # type: ignore[arg-type]


def _row(store: ProfileStore, kind: str, text: str) -> str:
    return (
        EvidenceLog(store)
        .append(
            recorded_at="2026-10-17T09:00:00Z",
            step="constraints",
            kind=kind,  # type: ignore[arg-type]
            text=text,
            source="conversation",
        )
        .id
    )


CURRENT_PAY_QUESTIONS = [
    "What is your current salary?",
    "What is your current compensation?",
    "What is your current annual base salary?",
    "Previous compensation",
    "Salary history",
    "¿Cuál es tu salario actual?",
    "¿Cuál es tu retribución actual?",
    "Indica tu remuneración actual",
    "¿Cuál es tu salario bruto anual actual?",
    "Quin és el teu sou actual?",
    "Quina és la teva retribució actual?",
    "Sou brut anual actual",
]
OWN_PAY_ROWS = [
    "My current salary is 38000 euros.",
    "I earn 38000 euros.",
    "Cobro 38000 euros.",
    "Guanyo 38000 euros.",
    "Mi sueldo es 38000 euros",
    "El meu sou és 38000 euros.",
    "Mi salario actual es 38000 euros.",
]


def _defects(tmp_path: Path, question: str, row: str, kind: str = "statement") -> list[str]:
    root = tmp_path / "p"
    store = ProfileStore(root, create_profile(root, "Ada", handle="a").handle)
    ev = _row(store, kind, row)
    live = {r.id: r for r in EvidenceLog(store).effective_rows()}
    answer = FormAnswer(question=question, text=row, evidence_ids=(ev,))
    return [d for d in answer_defects(answer, live, ()) if d.startswith("pay:")]


@pytest.mark.parametrize("row", OWN_PAY_ROWS)
@pytest.mark.parametrize("question", CURRENT_PAY_QUESTIONS)
def test_own_pay_is_refused_for_a_current_pay_question(
    tmp_path: Path, question: str, row: str
) -> None:
    assert _defects(tmp_path, question, row)


@pytest.mark.parametrize(
    "question", ["What are your salary expectations?", "¿Expectativa salarial?"]
)
def test_own_pay_is_refused_whatever_the_question_asks(tmp_path: Path, question: str) -> None:
    assert _defects(tmp_path, question, "My current salary is 38000 euros.")


@pytest.mark.parametrize(
    ("question", "row"),
    [
        ("What are your salary expectations?", "I am looking for 45000 to 50000 euros."),
        ("¿Expectativa salarial?", "Busco entre 45000 y 50000 euros"),
        ("Expectativa salarial?", "My salary floor is 45000 euros."),
        ("Quines són les teves expectatives salarials?", "Vull entre 45000 i 50000 euros"),
    ],
)
def test_an_expectation_or_floor_is_sendable(tmp_path: Path, question: str, row: str) -> None:
    assert not _defects(tmp_path, question, row, "constraint")
