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
_MINE = r"(?:my|mi|mis|meu|meva|el meu|la meva)"
_VERB = (
    r"(?:\bi\s+(?:earn\w*|make|made|am\s+paid|was\s+paid|get\s+paid|am\s+making)\b|"
    r"\b(?:cobro|cobraba|gano|ganaba|percibo|guanyo|guanyava|cobraré)\b)"
)
# What the candidate wants, not what they get: a floor or an expectation stays sendable.
_WANT = re.compile(
    r"floor|minimum|expect\w*|looking for|seeking|target|desired|busco|m[ií]nim\w*|suelo|"
    r"espero|expectativ\w*|deseo|objetivo|objectiu|cerco|aspir\w+|pretens\w*|desitj\w*|vull",
    re.I,
)
_OWN_PAY = re.compile(
    rf"{_VERB}|\b{_PAY}\b.*\b{_WHEN}\b|\b{_WHEN}\b.*\b{_PAY}\b|\b{_MINE}\W+(?:\w+\W+){{0,2}}{_PAY}\b",
    re.I,
)
# ponytail: clause cut by punctuation and a few conjunctions; a figure joined by other words
# can still slip, then the candidate reads the staged answer.
_CLAUSE = re.compile(r"[.!?;:]\s|[.!?;:]$|,\s|\n|\b(?:but|and|pero|però|y)\b", re.I)


def states_own_pay(text: str) -> bool:
    """A clause with a figure that gives the candidate's own pay (not a floor or expectation)."""
    return any(
        any(c.isdigit() for c in clause) and not _WANT.search(clause) and _OWN_PAY.search(clause)
        for clause in _CLAUSE.split(text)
    )


def current_pay_defects(text: str, cited_rows: list[str]) -> list[str]:
    """No form answer rests on, or says, the candidate's own current or past pay."""
    if states_own_pay(text) or any(states_own_pay(row) for row in cited_rows):
        return [
            "pay: current or past pay is never given in a form answer; use the expected "
            "range from the stated floor"
        ]
    return []
