"""T227 — which part of an advert a topic exclusion may read.

`sourcing_exclusions.matches` used to look for the stated value, and every term
beside it, anywhere in title, employer and text. Seen in test session 658fcce2:
a payroll startup held as `sector:fintech` because it *values* a "Background in
FinTech"; a firmware engineer held as `sector:advertising`; and
`restaurante` matching 58 adverts through "ticket restaurant" among the perks.

A topic the candidate rules out is about **the employer or the job** — what the
company does, what the role is. It is not about what the advert asks of a
candidate, what it would be nice for them to know, what the company pays out in
perks, or the boilerplate around the posting. So the text a topic is matched in
is the advert **minus** four regions, and the title and the employer are always
read in full:

* a *section* whose heading is a perk, benefit, requirement, qualification or
  nice-to-have heading (`_OFF_TOPIC_HEADING`), up to the next heading;
* a *sentence or bullet* that asks something of the candidate or prefers it
  (`_CANDIDATE_CUE`: "background in", "experience with", "se valora", "a plus");
* a sentence that lists a perk (`_PERK`: "ticket restaurant", "seguro médico");
* a sentence of posting boilerplate (`_BOILERPLATE`: "this role was advertised",
  "equal opportunity employer").

A sentence in which the **employer describes itself** ("We are a payroll
platform for fintech teams") is read even when it also contains a cue, a perk or
boilerplate, unless it addresses the candidate (`_ADDRESSES_CANDIDATE`): "We are looking for someone
with a background in FinTech" is a requirement and stays out.

Deliberate asymmetry, third kind: an employer *sentence* straight after a perks
list, with no heading ("Benefits\nPaid Time Off\nAcme operates in six countries as
a casino group.", employer "Acme Inc.") is swallowed, because it cannot be told
from "Acme pays for lunch" without listing verbs. The reverse, a perk item that is
the employer's name plus a word or two ("Acme Card"), ends the skip. Both are
declared trade-offs.

Deliberate asymmetry, second kind: inside a skipped perks section a plain
sub-heading with no off-topic word ("Benefits\nHealth:\nPrivate cover\nFood:\nLunch at
partner restaurants", or `**Food**`, or `FOOD`) looks exactly like "Tech stack:",
which must end the skip, so it ends it and the perk under it is read. That is a
fail-closed trade-off: no rule on shape alone separates the two.

Deliberate asymmetry: a topic mentioned only in a stripped region is **shown**,
which is fail-open for an advert that really is on the topic but says so only in
a requirements bullet. The candidate was told which words held every advert that
*is* held (`sourcing_exclusions.held_in_words`), so the cost of a wrong strip is
one advert shown that the candidate can rule out by name, whereas the cost of a
wrong keep was a whole search silently emptied (58 adverts through one perk).
"""

from __future__ import annotations

import re
import unicodedata

_SEPARATED = re.compile(r"(?<=[.!?;])\s+|\n+")
#: Where a sentence turns from what it asks of the candidate to what the job is
#: for: "valorable que aporte React **para formar parte del equipo de nuestro
#: cliente del sector bancario**". Each side is judged alone, so a cue in the
#: first half does not strip the employer's sector in the second.
_PURPOSE = re.compile(
    r"\b(?:para|so that|in order to|con el fin de|a fin de|to (?:join|work|be part))\b",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-*•·▪●>]|\d{1,2}[.)])\s+")


def _plain(text: str) -> str:
    """Lowercased, accent-free, punctuation-light: what a cue is matched against."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


#: Words and phrases that name an off-topic region. A heading is off-topic only
#: when EVERY word in it is one of these or a function word (`_HEADING_FUNCTION`):
#: "Company profile", "About us and what we offer" and "Player Experience" each
#: carry one such word and are still the employer describing itself. Matched on
#: the plain (folded) heading, so "Requisitos" and "What we offer:" qualify and
#: "Offering fintech payroll" does not.
_HEADING_VOCAB = (
    r"benefits?|perks?|what we offer|we offer|que ofrecemos|te ofrecemos|ofrecemos|"
    r"beneficios|ventajas|retribucion|compensation|salary|salario|"
    r"nice[- ]to[- ]haves?|bonus points|bonus|plus(?:es)?|deseables?|"
    r"se valorara|valorables?|preferred|required|requeridos?|must haves?|"
    r"imprescindibles?|essentials?|"
    r"requirements?|requisitos|requerimientos|qualifications?|cualificaciones|"
    r"your profile|tu perfil|perfil|profile|who you are|about you|sobre ti|"
    r"what you bring|what you(?:'ll| will) bring|what we(?:'re| are) looking for|"
    r"lo que buscamos|que buscamos|you have|tienes|skills|habilidades|conocimientos|"
    r"minimum|minimos|experience|experiencia"
)
_HEADING_FUNCTION = r"and|or|of|the|to|a|an|for|y|e|o|u|de|del|la|las|los|el|para|con|en|que|lo"
_HEADING_WORDS = re.compile(rf"\b(?:{_HEADING_VOCAB}|{_HEADING_FUNCTION})\b")
_HEADING_VOCAB_ONLY = re.compile(rf"\b(?:{_HEADING_VOCAB})\b")
#: Vocabulary that is also an ordinary noun of the employer's story ("Player
#: Experience", "Company profile", "The Essentials"). Alone it never makes a
#: heading off-topic; it needs a strong word beside it.
_WEAK_VOCAB = re.compile(
    r"(?:experience|experiencia|profile|perfil|essentials?|required|requeridos?|plus(?:es)?|bonus)"
)


def _off_topic_heading(plain_heading: str) -> bool:
    """Is every word of this heading off-topic vocabulary or a function word?

    Delete every vocabulary phrase and function word; the heading is off-topic
    when a strong one was deleted and no letter is left, so emoji, brackets and
    punctuation never matter.
    """
    vocab = _HEADING_VOCAB_ONLY.findall(plain_heading)
    if any(c.isalpha() for c in _HEADING_WORDS.sub(" ", plain_heading)):
        return False
    return any(not _WEAK_VOCAB.fullmatch(v) for v in vocab)


def _mentions_off_topic_word(plain_heading: str) -> bool:
    """Does the heading hold strong off-topic vocabulary (a sub-heading of a perks section)?

    Weak words ("profile", "experience") do not: "Company profile:" is the
    employer, and must not be swallowed by the perks above it.
    """
    return any(not _WEAK_VOCAB.fullmatch(v) for v in _HEADING_VOCAB_ONLY.findall(plain_heading))


#: A line whose wording names the employer or the job: it ends a skipped section
#: wherever it stands, whatever its shape.
_SECTION_WORDING = (
    r"(?:(?:about|sobre)(?:\s+.*)?|who we are(?: and what we do)?|quienes somos|"
    r"our company|our story|our mission|the company|company overview|overview|the role|"
    r"la empresa|nuestra empresa|el puesto|el rol|your role|tu rol|responsibilities|"
    r"responsabilidades|duties|funciones|tasks|tareas|what you(?:'ll| will) do)"
)
#: A wording, optionally joined by a connective to anything else ("Our Story &
#: Our Mission", "Who We Are & What We Do"; the heading length limit bounds it):
#: "Tasks are flexible" is not one, there is no connective.
_SECTION_OF_THE_ADVERT = re.compile(rf"{_SECTION_WORDING}(?:(?:\s*[&,]\s*|\s+(?:and|y)\s+)[^&,]+)*")
_EDGE_PUNCTUATION = "\u00bf\u00a1.?!\u2026 \t"
_LEGAL_SUFFIX = re.compile(r"\b(?:inc|llc|ltd|gmbh|sl|sa|corp|co|plc|bv)\b")


def _employer_key(employer: str | None) -> str:
    """The employer's name as it is likely to be repeated in the advert."""
    plain = _LEGAL_SUFFIX.sub(" ", re.sub(r"[^\w\s]", "", _plain(employer or "")))
    return " ".join(plain.split())


#: What makes a line a heading: markup, a trailing colon, ALL CAPS, or a short
#: unpunctuated line (checked in `_is_heading`).
_MARKUP = re.compile(r"^\s*(?:#{1,6}\s+|\*\*.+\*\*\s*:?\s*$|__.+__\s*:?\s*$)")

#: A sentence that asks something of the candidate, or merely prefers it.
_CANDIDATE_CUE = re.compile(
    r"\b(?:background in|background on|backgrounds? en|"
    r"(?:experience|experienced|expertise|exposure)\s+(?:in|with|of|on|working)|"
    r"experiencia\s+(?:en|con|previa|de)|knowledge of|knowledge in|conocimientos?\s+(?:de|en)|"
    r"familiar(?:ity)? with|familiarizad[oa]s? con|proficien\w+|"
    r"nice[- ]to[- ]have|a plus|as a plus|is a plus|bonus|desirable|desired|deseable|"
    r"se valora\w*|valorable|valorad[oa]s?|valued|preferred|preferably|preferible|"
    r"ideally|idealmente|worked (?:in|at|for|with)|has trabajado|have worked|"
    r"years of|anos de|you(?:'ve| have| are| bring| know)\b|"
    r"your\s+(?:background|experience|profile|skills)|"
    r"tienes|eres|tu\s+(?:perfil|experiencia)|"
    r"must have|should have|debes|se requiere|requerid[oa]s?|required|imprescindible)\b"
)

#: A sentence in which the employer describes itself. It rescues a sentence from
#: `_CANDIDATE_CUE` ("we have 10 years of experience in payments") but never one
#: that addresses or seeks the candidate (`_ADDRESSES_CANDIDATE`).
_EMPLOYER_SELF = re.compile(
    r"\b(?:we are an?|we are the|we're an?|we're the|we build|we provide|"
    r"we (?:sell|run|operate|make|create|develop)|we offer? (?:a|an) "
    r"(?:platform|product|service)|our (?:company|platform|product|products|mission|clients|"
    r"customers|business)|somos (?:una?|el|la)|(?:vendemos|operamos|gestionamos|desarrollamos)|"
    r"nuestra (?:empresa|plataforma|mision|compania)|"
    r"nuestros? (?:producto|productos|clientes)|about us|sobre nosotros)\b"
)
_ADDRESSES_CANDIDATE = re.compile(
    r"\b(?:looking for|seeking|searching for|we need|buscamos|busca|necesitamos|"
    r"you|your|tu|tus|tienes|candidate|candidato|candidata)\b"
)

#: Perks: what the employer pays out. Not what the employer *is*.
_PERK = re.compile(
    r"\b(?:tickets?\s+restaurantes?|tickets?\s+restaurants?|cheques?\s+(?:restaurante|guarderia|"
    r"comida)|vales?\s+(?:de\s+)?(?:comida|restaurante)|(?:meal|restaurant|lunch|food)\s+"
    r"(?:vouchers?|allowance|cards?|tickets?|subsid\w+)|"
    r"seguro\s+(?:medico|de\s+salud|privado)|(?:private\s+)?(?:health|medical)\s+insurance|"
    r"gympass|gym\s+(?:membership|allowance)|cuota\s+de\s+gimnasio|stock\s+options|flexible\s+(?:hours|schedule|working)|"
    r"horario\s+flexible|(?:paid\s+)?(?:vacation|holiday)s?\s+days?|dias\s+de\s+vacaciones|"
    r"plan\s+de\s+pensiones|pension\s+plan|retribucion\s+flexible|flexible\s+compensation|"
    r"(?:employee|staff)\s+discounts?|descuentos\s+(?:para\s+empleados|en\s+gimnasios)|"
    r"team[- ](?:events|building\s+(?:events|activities|days?))|"
    r"free\s+(?:snacks|fruit|coffee)|fruta\s+gratis|cafe\s+gratis)\b"
)

#: Boilerplate about the posting itself, which is about nothing the job does.
_BOILERPLATE = re.compile(
    r"\b(?:(?:this|the)\s+(?:role|job|position|vacancy|post)\s+(?:was|is|has been)\s+"
    r"(?:advertised|posted|published)|advertis(?:ed|ement|ing)\s+(?:this|the)\s+"
    r"(?:role|job|position|vacancy)|(?:job|vacancy)\s+advert(?:isement)?s?|"
    r"equal\s+opportunit(?:y|ies)|igualdad\s+de\s+oportunidades|"
    r"publicad[oa]\s+(?:en|por)|oferta\s+publicada|privacy\s+(?:policy|notice)|"
    r"politica\s+de\s+privacidad|data\s+protection|proteccion\s+de\s+datos|"
    r"insurance\s+coverage\s+issues|apply\s+(?:now|here)|how\s+to\s+apply|aplica\s+ahora|inscribete)\b"
)


#: The longest line that can be a heading.
_HEADING_LIMIT = 70


def _is_heading(line: str, *, previous_blank: bool) -> bool:
    stripped = _BULLET.sub("", line).strip()
    if not stripped or len(stripped) > _HEADING_LIMIT or _BULLET.match(line):
        return False
    if _MARKUP.match(line) or stripped.endswith(":"):
        return True
    letters = [c for c in stripped if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) >= 3:
        return True
    return previous_blank and len(stripped.split()) <= 5 and stripped[-1] not in ".;,!?"


def _heading_text(line: str) -> str:
    return _plain(re.sub(r"[#*_:]+", " ", line)).strip()


def _ends_skip(line: str, employer_key: str) -> bool:
    """Does `line` end the off-topic section being skipped?

    The shape of a plain short line never does: a perks list written without
    bullets is a run of short lines of any length. What ends it is markup, a
    trailing colon or ALL CAPS (unless the heading still holds an off-topic
    strong word, as a sub-heading of the perks does), a heading whose wording
    opens a section about the employer or the job, or a heading line that names
    the employer.
    """
    # "Who we are." and "¿Quiénes somos?" are headings once the edge punctuation goes.
    line_clean = line.strip().strip(_EDGE_PUNCTUATION)
    plain = _heading_text(line_clean)
    shaped = _is_heading(line_clean, previous_blank=True)
    # A wording needs no more shape than the heading length limit: "About <long
    # company name>" has more than five words.
    if 0 < len(line_clean) <= _HEADING_LIMIT and _SECTION_OF_THE_ADVERT.fullmatch(plain):
        # ...unless what follows the wording is itself a perks word
        # ("About our benefits:", "Duties & perks").
        return not _mentions_off_topic_word(plain)
    if shaped and _mentions_off_topic_word(plain):
        return False
    if _is_heading(line, previous_blank=False):
        return True
    # The employer's name ends a skip only on a line that is itself a heading
    # ("Acme"), never on a sentence that happens to mention it.
    return (
        shaped
        and bool(employer_key)
        and re.search(rf"\b{re.escape(employer_key)}\b", _plain(line)) is not None
    )


def _drop_sections(text: str, employer: str | None = None) -> list[str]:
    """The lines of `text` outside any off-topic section."""
    employer_key = _employer_key(employer)
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        if skipping and line.strip() and _ends_skip(line, employer_key):
            skipping = False
        if not skipping and _is_heading(line, previous_blank=True):
            # An off-topic heading opens a section whether or not a blank line
            # precedes it; the strict all-words rule is what decides.
            skipping = _off_topic_heading(_heading_text(line))
        if not skipping:
            kept.append(line)
    return kept


def _stripped(sentence: str) -> bool:
    """Is this sentence one a topic is not read in?"""
    plain = _plain(sentence)
    # One rescue for every reason to strip: the employer describing itself, to
    # nobody in particular, is read whichever pattern would have removed it.
    if _EMPLOYER_SELF.search(plain) and not _ADDRESSES_CANDIDATE.search(plain):
        return False
    return bool(_PERK.search(plain) or _BOILERPLATE.search(plain) or _CANDIDATE_CUE.search(plain))


def topic_text(text: str, employer: str | None = None) -> str:
    """`text` with the regions a topic exclusion is not read in removed.

    Removed regions become line breaks, never nothing, so two kept fragments are
    not joined into a phrase neither said.
    """
    kept: list[str] = []
    for line in _drop_sections(text, employer):
        for sentence in _SEPARATED.split(line):
            # A purpose connector opens a new clause and is kept with it.
            clauses = re.split(f"(?={_PURPOSE.pattern})", sentence, flags=re.IGNORECASE)
            kept.extend(c for c in clauses if c.strip() and not _stripped(c))
    return "\n".join(kept)
