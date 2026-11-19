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
    r"(?:salary|salaries|pay|wages?|compensation|earnings|income|sueldo|salario|ingresos|"
    r"retribuci\w+|remuneraci\w+|sou|salari)"
)
_WHEN = (
    r"(?:current\w*|present|now|today|past|previous|prior|last|former|actual\w*|anterior\w*|"
    r"pasad\w+|[uú]ltim\w+|ara|avui|hoy|passat)"
)
# A money figure: a thousands number, a "38k", a figure in words (mil / thousand) or a currency.
_MONEY = re.compile(
    r"\d[\d.,]*\s?k\b|\b\d{1,3}(?:[.,]\d{3})+\b|\b\d{5,}\b|\b(?:mil|thousand)\b|"
    r"[€$£]|\b(?:euros?|eur|usd|dollars?|bruts?|brutos?|gross)\b",
    re.I,
)
# What the candidate asks for, in ES, EN and CA. "target", "objetivo" and "suelo" are not here:
# a target bonus sits beside a current salary, and "suelo cobrar" means "I usually earn".
_WANT = re.compile(
    r"\b(?:floor|minimum|expect\w*|looking for|seeking|desired|ideal|"
    r"busco|m[ií]nim\w*|espero|expectativ\w*|dese\w+|pretens\w*|aspir\w+|"
    r"cerco|desitj\w*|vull)\b",
    re.I,
)
_SENTENCE = re.compile(r"[.!?;]+(?:\s+|$)|\n")


def states_own_pay(text: str) -> bool:
    """A sentence with a pay figure that is not clearly an expectation or a floor.

    The default is refusal: a sentence that talks pay with a figure is sendable only when a want
    word is in it and no current or past marker is, whatever else it says.
    """
    for sentence in _SENTENCE.split(text):
        talks_pay = _MONEY.search(sentence) or (
            re.search(rf"\b{_PAY}\b", sentence, re.I) and any(c.isdigit() for c in sentence)
        )
        if talks_pay and not (
            _WANT.search(sentence) and not re.search(rf"\b{_WHEN}\b", sentence, re.I)
        ):
            return True
    return False


def current_pay_defects(text: str, cited_rows: list[str]) -> list[str]:
    """No form answer rests on, or says, the candidate's own current or past pay."""
    if states_own_pay(text) or any(states_own_pay(row) for row in cited_rows):
        return [
            "pay: current or past pay is never given in a form answer; use the expected "
            "range from the stated floor"
        ]
    return []
