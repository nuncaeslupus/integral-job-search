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
    r"(?:current\w*|present|now|today|past|previous|prior|last|former|actual(?!iz)\w*|anterior\w*|"
    r"pasad\w+|[uú]ltim\w+|ara|avui|ahora|hoy|passat)"
)
_PERIOD = (
    r"(?:al mes|a month|per month|/\s?mes|/\s?month|mensual\w*|monthly|al año|a year|per year|"
    r"per annum|anual\w*|annual\w*|yearly|a l'any|al any|l'any|an hour|per hour|hourly|la hora|"
    r"por hora|per hora|a l'hora|a day|per day|daily|al d[ií]a|por d[ií]a|al dia|per dia)"
)
_CURRENCY = r"(?:[€$£]|\b(?:euros?|eur|usd|dollars?)\b)"
# Words that may sit between a figure and its period or follow a bare number as pay talk (net,
# gross, currency, connectors). Any other word after a number is a unit noun: "3 releases a week".
_PAY_TAIL = r"(?:net\w*|nets|brut\w*|gross|euros?|eur|usd|dollars?)"
_TAIL_WORDS = re.compile(
    rf"{_PAY_TAIL}|now|and|per|pero|but|the|for|ara|ahora|hoy|avui|m[aeé]s|plus|amb|con|with|"
    r"before|after|antes|abans|today|still|a[uú]n|ya",
    re.I,
)
# One money figure: "38k", a thousands number (dot, comma or space separated), five digits or
# more, a figure beside a currency or a pay period, or a figure in words (mil / thousand / grand).
_FIGURE = re.compile(
    rf"\d[\d.,]*\s?k\b|\b\d{{1,3}}(?:[.,\u00a0\u202f ]\d{{3}})+\b|\b\d{{5,}}\b|"
    rf"\b\d+(?:[.,]\d+)?\s?{_CURRENCY}|[€$£]\s?\d|\b\d{{2,4}}(?:\s+{_PAY_TAIL}){{0,2}}\s*{_PERIOD}|"
    r"\b(?:mil|thousand|grand)\b",
    re.I,
)
_TALKS_PAY = re.compile(rf"{_CURRENCY}|\b(?:bruts?|brutos?|gross)\b", re.I)
# The low end of a range is dropped, so "45-50k" or "entre 45 y 50k" is one figure. "de/from 38k a
# 45k" is not a range to drop: it says where the candidate stands now, so both figures count.
_RANGE_LOW = re.compile(
    r"(?<![\d.,])(?<!de )(?<!from )"
    r"\d[\d.,\u00a0\u202f ]*\s?k?\s*(?:-|\u2013|\bto\b|\ba\b|\bal\b)\s*(?=[€$£]?\d)|"
    r"\b(?:entre|between)\s+\d[\d.,\u00a0\u202f ]*\s?k?\s*(?:y|and|i)\s+(?=[€$£]?\d)",
    re.I,
)
# What the candidate asks for, in ES, EN and CA. "target", "objetivo" and "suelo" are not here:
# a target bonus sits beside a current salary, and "suelo cobrar" means "I usually earn".
_WANT_WORDS = (
    r"(?:floor|minimum|expect\w*|looking for|seeking|desired|ideal|(?:'d|would) like|"
    r"busco|m[ií]nim\w*|espero|expectativ\w*|dese\w+|pretens\w*|aspir\w+|"
    r"cerco|desitj\w*|vull)"
)
_WANT = re.compile(rf"\b{_WANT_WORDS}\b", re.I)
# Earning verbs in any tense, ES/EN/CA: a sentence with one states pay the candidate has or had.
_EARNS = re.compile(
    r"\b(?:cobr\w*|gan(?:o|aba|[aá]s|a)|guany(?:o|ava|es|a)|earn(?:s|ed|ing)?|make|makes|made|"
    r"paid|pays?|takes? home|taking home|took home|pagan|paguen|perc[ei]b\w*|recib\w*|rebo)\b",
    re.I,
)
# Rate words and "I am on": a bare number after them is pay too ("Day rate 300", "I am on 38").
_RATE = r"\b(?:rates?|tarifa\w*)\b|\bI(?:'m|\s+am)\s+on\b"
_CTX = re.compile(rf"{_EARNS.pattern}|\b{_WHEN}\b|{_RATE}", re.I)
_STRONG_CTX = re.compile(rf"{_EARNS.pattern}|{_RATE}", re.I)
# Comparison with what they have now, and past tense: "same as I have", "mínimo era 38k".
_SAME = re.compile(
    r"\b(?:same as|igual que|lo mismo|el mateix|como en mi|com (?:al|en el) meu|como (?:en )?mi)\b",
    re.I,
)
_PAST = re.compile(r"\b(?:was|were|had|era|eren|fue|fueron|ten[ií]a)\b", re.I)
_TOKEN = re.compile(r"\d+(?:[.,]\d+)?(?:\s?k\b)?|[^\W\d]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
# "my salary" with no want word right beside it ("my ideal salary", "salario deseado" are fine).
_OWN_PAY = re.compile(
    rf"\b(?:my|mi|mis|el meu|la meva|els meus|les meves)\s+{_PAY}\b(?!\s+{_WANT_WORDS}\b)",
    re.I,
)
_SENTENCE = re.compile(r"[.!?;]+(?:\s+|$)|\n")


def _bare_pay_number(text: str) -> bool:
    """A bare number within three words after an earning, payer, time or rate word, unless a unit
    noun follows it ("3 releases") or it is a year."""
    for ctx in _CTX.finditer(text):
        toks = list(_TOKEN.finditer(text, ctx.end()))[:4]
        for i, tok in enumerate(toks):
            n = tok.group()
            if not n[0].isdigit() or n[-1] == "k" or _YEAR.fullmatch(n):
                continue
            nxt = toks[i + 1].group() if i + 1 < len(toks) else ""
            if not (len(nxt) >= 3 and nxt[0].isalpha() and not _TAIL_WORDS.fullmatch(nxt)):
                return True
    return False


def _sendable(sentence: str) -> bool:
    """Clearly an expectation or a floor: one figure (or range), a want word before it, and no
    current or past marker anywhere in the sentence."""
    if re.search(rf"\b{_WHEN}\b", sentence, re.I) or _EARNS.search(sentence):
        return False
    if _OWN_PAY.search(sentence) or _SAME.search(sentence) or _PAST.search(sentence):
        return False
    flat = _RANGE_LOW.sub("", sentence)
    # A pay word with only a bare number ("floor is not under 50") counts that number.
    figures = list(_FIGURE.finditer(flat)) or list(re.finditer(r"\d[\d.,]*", flat))
    if len(figures) != 1:
        return False
    want = _WANT.search(flat)
    return want is not None and want.start() < figures[0].start()


def states_own_pay(text: str) -> bool:
    """A sentence with a pay figure that is not clearly an expectation or a floor.

    The default is refusal. A sentence that talks pay with a figure is sendable only when it
    holds one figure (a range counts as one), a want word governs it from before, and no current
    or past marker is in it. So "I earn 38k, looking for 45k" (two figures) and "I'm paid 38k,
    looking for more" (want word after the figure) are refused.
    """
    sentences = _SENTENCE.split(text)
    for i, sentence in enumerate(sentences):
        # "I earn well. It is 38.": an earning word with no number looks into the next sentence.
        if (
            i + 1 < len(sentences)
            and _STRONG_CTX.search(sentence)
            and not any(c.isdigit() for c in sentence)
            and _bare_pay_number(f"{sentence} {sentences[i + 1]}")
        ):
            return True
        talks_pay = (
            _FIGURE.search(sentence)
            or _TALKS_PAY.search(sentence)
            or (re.search(rf"\b{_PAY}\b", sentence, re.I) and any(c.isdigit() for c in sentence))
            # A bare number after an earning, time or rate word states pay: "Gano 38".
            or _bare_pay_number(sentence)
        )
        if talks_pay and not _sendable(sentence):
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
