"""Who publishes an advert: a consultancy placing someone, or a temp agency.

Read from cue phrases in Spanish, English and Catalan. `unknown` is the default
and a guess is never `direct`: an advert that says nothing is not shown to be
the employer's own. The cues name the *placement* ("for our client", "empresa
cliente"), not the word "client" alone, so a product company describing its own
customers ("our clients use the app") is not read as a consultancy.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

PublisherKind = Literal["direct", "consultancy", "agency", "unknown"]

FACET = "publisher"

# One row per concept, its Spanish, English and Catalan form side by side, so a
# placement cannot be recognised in one language and missed in the others.
# Every consultancy form is a placement (a preposition or verb + client), never
# the noun phrase alone: "experiencia del cliente final" is a product company.
_ES_M = r"(?:(?:importante|gran) )?"
_EN_M = r"(?:(?:important|major|leading|large) )?"
_CA_M = r"(?:(?:important|gran) )?"
_ES_D = r"(?:(?:un|una|nuestro|nuestra) )?"
_EN_D = r"(?:(?:a|an|our|the) )?"
_CA_D = r"(?:(?:un|una|el nostre|el) )?"
_CONSULTANCY_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    # for a client
    (
        rf"(?:para {_ES_D}|a (?:un|nuestro) ){_ES_M}(?:empresa )?cliente\b",
        rf"for (?:a|an|our) {_EN_M}(?:end )?client\b",
        rf"per (?:a (?:un|una)|al nostre) {_CA_M}(?:empresa )?client\b",
    ),
    # joining a client
    (
        rf"incorporacion a {_ES_D}{_ES_M}(?:empresa )?cliente\b"
        rf"|incorporar(?:te|se)? a (?:un|nuestro) {_ES_M}cliente\b",
        rf"join(?:ing)? (?:a|an|our|the) {_EN_M}client\b",
        rf"incorporacio a {_CA_D}{_CA_M}(?:empresa )?client\b"
        rf"|incorporar-(?:te|se) a(?:l nostre| un) {_CA_M}client\b",
    ),
    # the advert is written in the client's voice
    (
        r"nuestro cliente (?:es|busca)\b",
        r"our client (?:is|seeks)\b",
        r"el nostre client (?:es|busca)\b",
    ),
    # working at the client
    (
        rf"trabajar(?:as)? en {_ES_D}{_ES_M}cliente\b",
        rf"(?:placed|work|working|based) (?:with|at|for) {_EN_D}{_EN_M}(?:end )?client\b",
        rf"treballar(?:as)? (?:a|en) {_CA_D}{_CA_M}client\b",
    ),
    # on behalf of a client
    (
        r"en nombre de (?:un|nuestro) cliente\b",
        r"on behalf of (?:a|our) client\b",
        r"en nom (?:d'un|del nostre) client\b",
    ),
)
_AGENCY_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    (
        r"\bett\b|empresa de trabajo temporal",
        r"temporary staffing|staffing agency|temporary (?:work|employment) agency",
        r"\bett\b|empresa de treball temporal",
    ),
    (r"agencia de seleccion", r"recruitment agency", r"agencia de seleccio"),
)
# ponytail: closed phrase list; add a row when a real advert slips through as unknown.


def _compile(concepts: tuple[tuple[str, str, str], ...]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{form})" for concept in concepts for form in concept))


_CONSULTANCY = _compile(_CONSULTANCY_CONCEPTS)
_AGENCY = _compile(_AGENCY_CONCEPTS)
_NEGATORS = frozenset(["sin", "ni", "no", "nunca", "sense", "mai", "not", "never", "without"])
_NEGATION_WINDOW = 4  # words before a cue, within its sentence


def _cue(pattern: re.Pattern[str], folded: str) -> bool:
    """A cue counts unless a negator sits in the few words before it ("sin ETT")."""
    for match in pattern.finditer(folded):
        sentence = re.split(r"[.;:!?\n]", folded[: match.start()])[-1]
        if not _NEGATORS & set(re.findall(r"\w+", sentence)[-_NEGATION_WINDOW:]):
            return True
    return False


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in plain if not unicodedata.combining(c))


def publisher_kind(text: str) -> PublisherKind:
    folded = _fold(text)
    if _cue(_AGENCY, folded):
        return "agency"
    if _cue(_CONSULTANCY, folded):
        return "consultancy"
    return "unknown"
