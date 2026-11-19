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

_AGENCY = re.compile(
    r"\bett\b|empresa de trabajo temporal|temporary staffing|staffing agency"
    r"|temporary (?:work|employment) agency|empresa de treball temporal"
)
# ponytail: closed phrase list; add a cue when a real advert slips through as unknown.
_CONSULTANCY = re.compile(
    r"importante cliente|empresa cliente|cliente final|(?:para|a) (?:nuestro|un) cliente\b"
    r"|for (?:our|a) client\b|our client is|end client|client company"
    r"|per a (?:un|important) client\b|per al nostre client\b|empresa client\b|client final"
)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in plain if not unicodedata.combining(c))


def publisher_kind(text: str) -> PublisherKind:
    folded = _fold(text)
    if _AGENCY.search(folded):
        return "agency"
    if _CONSULTANCY.search(folded):
        return "consultancy"
    return "unknown"
