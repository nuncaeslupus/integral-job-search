"""EU pay-transparency directive 2023/970: the range is asked for, current pay is never given.

An advert with no pay range gets one prompt (step 11 tells the candidate they may ask for the
range before the first interview; step 12's preparation carries the question). A form question
about the candidate's current or past pay is answered from the stated floor only, never from a
row that records what they earn or earned (`current_pay_defects`, called by `form_answers`).
"""

from __future__ import annotations

import re
from typing import Literal

from integral.candidate import OfferFacts

Language = Literal["en", "es", "ca"]

RANGE_PROMPT: dict[Language, str] = {
    "en": (
        "This advert gives no pay range. Under the EU pay-transparency directive (2023/970) you "
        "can ask the employer for it before the first interview."
    ),
    "es": (
        "Este anuncio no indica el rango salarial. Según la directiva europea de transparencia "
        "retributiva (2023/970) puedes pedírselo a la empresa antes de la primera entrevista."
    ),
    "ca": (
        "Aquest anunci no indica el rang salarial. Segons la directiva europea de transparència "
        "retributiva (2023/970) pots demanar-lo a l'empresa abans de la primera entrevista."
    ),
}


def range_prompt(offer: OfferFacts, language: Language) -> str | None:
    """The prompt in the candidate's language, or None when the advert publishes a range."""
    if offer.salary_stated and (offer.salary_min is not None or offer.salary_max is not None):
        return None
    return RANGE_PROMPT[language]


_PAY = (
    r"(?:salary|salaries|pay|wage|earn\w*|sueldo|salario|cobr\w+|gano|ganaba|sou|salari|guany\w*)"
)
_PAST = r"(?:current\w*|present|past|previous|last|former|now|actual\w*|anterior\w*|pasad\w+|ara)"
_ROW = re.compile(rf"\b{_PAST}\b.*\b{_PAY}\b|\b{_PAY}\b.*\b{_PAST}\b", re.I | re.S)
_QUESTION = re.compile(rf"\b{_PAST}\W+(?:\w+\W+)?{_PAY}\b|\b{_PAY}\W+(?:\w+\W+)?{_PAST}\b", re.I)


def asks_current_pay(question: str) -> bool:
    return _QUESTION.search(question) is not None


def current_pay_defects(question: str, cited_rows: list[str]) -> list[str]:
    """A current-pay question may rest only on rows that say nothing about current or past pay."""
    if asks_current_pay(question) and any(_ROW.search(row) for row in cited_rows):
        return [
            "pay: the question asks for current or past pay, which is never given; answer "
            "with the expected range from the stated floor"
        ]
    return []
