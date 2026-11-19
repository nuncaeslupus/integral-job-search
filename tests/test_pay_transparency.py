"""Pay transparency (directive 2023/970): ask for the range, never give current pay."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.candidate import OfferFacts
from integral.form_answers import FormAnswer, answer_defects
from integral.identity import ProfileStore, create_profile
from integral.pay_transparency import RANGE_PROMPT, range_prompt, states_own_pay
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
        ("Salary?", "My ideal salary is 45k."),
        ("¿Salario?", "Mi salario deseado es 45000 euros."),
        ("Sou?", "El meu sou ideal és 45.000 €."),
        ("¿Salario?", "Mi mínimo son cuarenta y cinco mil euros."),
        ("Sou?", "El meu sou mínim és quaranta-cinc mil euros."),
    ],
)
def test_an_expectation_or_floor_is_sendable(tmp_path: Path, question: str, row: str) -> None:
    assert not _defects(tmp_path, question, row, "constraint")


LEAKING_ROWS = [
    # a label and its figure split across clauses
    "Current salary: 38k",
    "Salario actual: 38.000 €",
    "Sou actual: 38.000 €",
    "My current salary, 38000 euros.",
    "My current salary and bonus total 45000 euros.",
    # first-person phrasings
    "I'm paid 38k.",
    "I currently earn 38k.",
    "I was earning 38000 euros.",
    "My base is 38k.",
    "Me pagan 38000 euros.",
    "Suelo cobrar 38000 euros.",
    "Em paguen 38.000 €.",
    "Cobrava 38.000 euros.",
    "Percebo 38.000 euros.",
    # a bonus word is not an expectation
    "Mi salario actual es 38000 euros con variable por objetivos.",
    "I earn 38000 plus a target bonus.",
    "El meu sou actual és 38000 euros amb variable per objectius.",
    # figures in words
    "Treinta y ocho mil euros es mi salario actual.",
    "My current salary is thirty-eight thousand euros.",
    "Trenta-vuit mil euros és el meu sou actual.",
    # a want word beside a current one does not launder it
    "My current salary is 38000 euros and I am looking for 45000.",
]


@pytest.mark.parametrize("row", LEAKING_ROWS)
def test_a_pay_figure_that_is_not_an_expectation_is_refused(tmp_path: Path, row: str) -> None:
    assert _defects(tmp_path, "Anything", row)


# Round-1 review of #971: a want word beside a current figure, and figures the old money
# pattern missed. Each must be refused.
MIXED_OR_MISSED_ROWS = [
    "I'm paid 38k, looking for 45k.",
    "I earn 38k and I'm looking for 45k.",
    "I make 38,000 and expect 45,000.",
    "My expected salary is 45k, I get 38k.",
    "Cobro 38k y busco 45k.",
    "Cobro 38.000 € y busco 45.000 €.",
    "Gano 38.000 euros, espero 45.000.",
    "Busco 45k pero cobro 38k",
    "Expectativa 45k (cobro 38k)",
    "Guanyo 38.000 € i busco 45.000 €.",
    "Guanyo 38.000 € i vull 45.000 €.",
    "I earn 38 000.",
    "I earn 38 000 a year.",
    "Cobro 38 000 al año.",
    "I make 38 000 and expect 45 000.",
    "I earn 3200 a month.",
    "Cobro 3200 al mes.",
    "Guanyo 3200 al mes.",
    "I earn 3.200 per month, looking for more.",
    "I earn thirty eight grand.",
    "Expectativa 45k (ahora 38k).",
]

STILL_SENDABLE_ROWS = [
    "Mi salario deseado es 45000 euros.",
    "My ideal salary is 45k.",
    "El meu sou ideal és 45.000 €.",
    "Minimum 40k.",
    "My floor is 40.000 €.",
    "Busco 45.000 € brutos.",
    "Expectativa salarial: 45k.",
    "Expected salary: 45k",
    "Salario mínimo: 40.000 €",
    "Sou mínim: 40.000 €",
    "Desitjo 45.000 €.",
    "Looking for 45-50k.",
    "Expected range 45,000-50,000 EUR.",
    "I have 5 years of experience.",
]


@pytest.mark.parametrize("row", MIXED_OR_MISSED_ROWS)
def test_a_current_figure_beside_a_want_word_is_refused(row: str) -> None:
    assert states_own_pay(row)


@pytest.mark.parametrize("row", STILL_SENDABLE_ROWS)
def test_a_lone_expectation_stays_sendable(row: str) -> None:
    assert not states_own_pay(row)
