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
    # #977 round 1: a year-shaped figure, a slang unit or a far figure after an earning word.
    "I earn 2000 net.",
    "Gano 2000 netos.",
    "Guanyo 2000 nets.",
    "Cobro unos 2000.",
    "I take home 2050.",
    "Me pagan 1990.",
    "Em paguen 2000.",
    "Actualmente 2000.",
    "Currently on 2000.",
    "Day rate 2000.",
    "I earn 25 bucks an hour.",
    "Gano 9 pavos la hora.",
    "Guanyo 38 milers.",
    "Cobro 1500 limpios al mes.",
    "Cobro 1500 nets nets al mes.",
    "Currently 1500 clean a month.",
    "Mi tarifa: 1500 limpios al mes.",
    "I earn, at the moment, around 38.",
    "Cobro cada mes más o menos 1800.",
    "Guanyo cada mes més o menys 1800.",
    "I earn well. Really well. It is 38.",
    "Gano bien. Muy bien. Son 38.",
    "Guanyo bé. Molt bé. Són 38.",
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
    "I earn 25 an hour.",
    "Cobro 20 la hora.",
    "Guanyo 20 per hora.",
    "I make 300 a day.",
    "Cobro 150 al día.",
    "Gano 38.",
    "Looking for 45k. Earn 38 now.",
    "Minimum: what my employer pays me, 38k.",
    "Busco pasar desde 38k a 45k.",
    # Leftovers from #971 round 2: a range start, a possessive, past tense, figures with words
    # between the number and its period.
    "Busco pasar de 38k a 45k.",
    "Vull passar de 38k a 45k.",
    "Expecting a raise from 38k to 45k.",
    "Looking for more than the 38k I make.",
    "Espero mantener mi sueldo de 38k.",
    "Vull mantenir el meu sou de 38k.",
    "Busco lo mismo que cobraba en 2023: 38k.",
    "Minimum is what I was paid in 2022, 38k.",
    "Busco el que cobrava, 38k.",
    "Busco 45k, cobro 38.",
    "Busco 45k i cobro 38.",
    "Looking for 45k, I make 38 at the moment.",
    "Cobro 1800 netos al mes.",
    "Cobro 1800 nets al mes.",
    "I take home 2500 net a month.",
    "Gano 38 al año.",
    "Minimum 40k, I earned 38k.",
    "Mi sueldo es 38k.",
    "1800 netos al mes.",
    "2500 net a month.",
    # Leftovers from #974: pay across sentences, payer verbs and time or rate words with a bare
    # number, and "the same as now" / past tense.
    "I earn well. It is 38.",
    "Gano bien. Son 38.",
    "Guanyo bé. Són 38.",
    "Me pagan 38.",
    "Em paguen 38.",
    "Percibo 38.",
    "Percebo 38.",
    "Actualmente 38.",
    "Currently on 38.",
    "I am on 38.",
    "Ara 38.",
    "Actualment 38.",
    "My rate is 9 an hour.",
    "Hourly rate: 25.",
    "Day rate 300.",
    "Tarifa diaria 300.",
    "Tarifa diària 300.",
    "La meva tarifa és 9 per hora.",
    "Looking for 38k, same as I have.",
    "Busco 38k, como en mi puesto.",
    "Cerco 38k, com al meu lloc.",
    "Cerco 38k, igual que ara.",
    "Mi sueldo mínimo era 38k.",
    "My salary minimum was 38k.",
    "El meu sou mínim era 38k.",
    # #977 leftovers: a year word right after the earning word, and past earning forms.
    "Gano el 2000.",
    "Cobro el 1990.",
    "Me pagan el 1950.",
    "Em paguen el 1950.",
    "Cobro durante 2000",
    "I get paid until 2000",
    "Guanyo fins 2000.",
    "Gané 2000.",
    "Vaig guanyar 2000.",
    "En 2024 gané 2000.",
    "El 2024 vaig guanyar 2000.",
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
    "I'd like 45k.",
    "Mi expectativa actualizada es 45k.",
    "My expected salary is 45k.",
    # Earning words beside a count or a year, not a pay figure (#974 fail-closed).
    "I make 3 releases a week.",
    "I make 10 deploys a day.",
    "Made 3 PRs per day.",
    "I made 4 hires in 2023.",
    "I earned 2 certifications.",
    "Earned a promotion in 2022.",
    "Cobro desde 2019 en la empresa.",
    "Guanyo 2 hores al dia en desplaçaments.",
    "Gano 2 certificaciones.",
    "Guanyo 2 certificacions.",
    "Hago 10 despliegues al día.",
    "Faig 10 desplegaments al dia.",
    "I earn trust. I led 12 people.",
    "Gano experiencia. Lideré 5 equipos.",
    "Guanyo experiència. Vaig liderar 5 equips.",
    "Currently leading 5 engineers.",
    "Actualmente lidero 5 ingenieros.",
    "Ara lidero 5 enginyers.",
    "Hago 3 lanzamientos a la semana.",
    "Faig 3 llançaments a la setmana.",
    # #981 review: a year after a time word, expectations, a word between earning word and year.
    "Ahora hasta 2026 trabajo en remoto.",
    "Ara fins 2025 treballo a Barcelona.",
    "Currently until 2025 I work in Madrid.",
    "Actualmente durante 2023 lideré 5 ingenieros.",
    "Vull guanyar 45k.",
    "Espero que gane 45k.",
    "Vaig guanyar el premi el 2019.",
    "Gano 3 lanzamientos a la semana.",
    "Guanyo 3 llançaments a la setmana.",
]


@pytest.mark.parametrize("row", MIXED_OR_MISSED_ROWS)
def test_a_current_figure_beside_a_want_word_is_refused(row: str) -> None:
    assert states_own_pay(row)


@pytest.mark.parametrize("row", STILL_SENDABLE_ROWS)
def test_a_lone_expectation_stays_sendable(row: str) -> None:
    assert not states_own_pay(row)
