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
EXCLUDABLE = frozenset(["consultancy", "agency"])  # `unknown` would exclude every cue-less advert

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
# "client" is a placement only as the head noun: not before a hyphen ("client-facing"),
# and in English not before another noun ("client success team"), which is a modifier.
# Spanish and Catalan put modifiers after the noun, so only the hyphen rule applies.
_FN = "in|at|of|for|on|to|with|from|and|or|who|whose|which|that|where|is|are|seeks|by|as|will|can"
_PART = r"\w{3,}ed\b"  # "client based in", "client located in": a participle is not a noun
_END = r"(?![\w-])"
_END_EN = rf"(?![\w-])(?![ ]+(?!(?:{_FN})\b)(?!{_PART})[a-z])"
_NOT_PAST = r"(?![ ]+(?:in|en) (?:19|20)\d\d)"  # "built X for a client in 2019"
_CONSULTANCY_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    # for a client
    (
        rf"para {_ES_D}{_ES_M}(?:empresa )?cliente{_END}{_NOT_PAST}",
        rf"for (?:a|an|our) {_EN_M}(?:end )?client{_END_EN}{_NOT_PAST}",
        rf"per (?:a (?:un|una)|al nostre) {_CA_M}(?:empresa )?client{_END}{_NOT_PAST}",
    ),
    # joining a client
    (
        rf"incorporacion a {_ES_D}{_ES_M}(?:empresa )?cliente{_END}"
        rf"|incorporar(?:te|se)? a (?:un|nuestro) {_ES_M}cliente{_END}",
        rf"join(?:ing)? (?:a|an|our|the) {_EN_M}client{_END_EN}",
        rf"incorporacio a {_CA_D}{_CA_M}(?:empresa )?client{_END}"
        rf"|incorporar-(?:te|se) a(?:l nostre| un) {_CA_M}client{_END}",
    ),
    # the advert is written in the client's voice
    (
        r"nuestro cliente (?:busca|es (?:un|una)\b)",
        r"our client (?:seeks|is (?:a|an|looking|seeking|hiring)\b)",
        r"el nostre client (?:busca|es (?:un|una)\b)",
    ),
    # a self-description
    (
        r"somos una consultor(?:a|ia)\b",
        r"we are a (?:consultancy|consulting (?:firm|company))\b",
        r"som una consultor(?:a|ia)\b",
    ),
    # working at the client
    (
        rf"trabajar(?:as)? en {_ES_D}{_ES_M}cliente{_END}",
        rf"(?:placed|work|working|based) (?:with|at|for) {_EN_D}{_EN_M}(?:end )?client{_END_EN}",
        rf"treballar(?:as)? (?:a|en) {_CA_D}{_CA_M}client{_END}",
    ),
    # on behalf of a client
    (
        rf"en nombre de (?:un|nuestro) cliente{_END}",
        rf"on behalf of (?:a|our) client{_END_EN}",
        rf"en nom (?:d'un|del nostre) client{_END}",
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


_JOINER = re.compile(r"\b(?:ni|or|nor|o)\b")
_ASIDE = re.compile(r"\s*(?:and|y|i|or|o)\b")


def _cue(pattern: re.Pattern[str], folded: str) -> bool:
    """A cue counts unless a negator sits in the few words before it ("sin ETT").

    A negation runs through a comma list ("no X, ETT ni Y") or aside ("not, and never
    will be, a staffing agency"); any other comma ends it ("No cal angles, treballaras a").
    """
    for match in pattern.finditer(folded):
        parts = re.split(r"[.;:!?\n]", folded[: match.start()])[-1].split(",")
        tail = folded[match.end() :].split(",")[0]
        words = re.findall(r"\w+", parts[-1])
        # ponytail: one-word list items and joiner-led asides only; add shapes as they appear
        for part in reversed(parts[:-1]):
            if len(words) > 1 or not (_JOINER.search(tail) or _ASIDE.match(part)):
                break
            words = re.findall(r"\w+", part) + words
        if not _NEGATORS & set(words[-_NEGATION_WINDOW:]):
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
