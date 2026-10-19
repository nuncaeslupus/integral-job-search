"""T250 — are these two adverts one vacancy, whichever board served them?

`lifecycle.posting_key` joins copies whose employer and title are equal after
normalisation. Boards do not word a title the same way (`Senior Python
Developer` / `Python Software Engineer (Senior) (m/f/d)`), so equality missed
the copies a candidate recognises at a glance, and a vacancy already seen,
applied to or rejected came back as new.

**The rule.** Two adverts are the same vacancy when

1. both name an employer (`offers.names_an_employer`) and the employers are
   equal once case, accents, punctuation and a *trailing* run of legal-form
   words (`S.L.`, `GmbH & Co. KG`, `Ltd`...) are removed. Employers are
   compared exactly, never fuzzily: two companies with similar names are two
   companies;
2. both titles have at least one significant word left, and the *level* words
   (`junior`, `senior`, `lead`, `principal`, `staff`, `head`, `intern`) of the
   two are the same set: a junior and a senior role at one employer are two
   vacancies, however much else they share. Numbers and roman numerals count
   the same way only when *both* titles carry one (`Engineer II` is not
   `Engineer III`); a number on one side alone is a salary, a year or a
   percentage a board appended, and is ignored (so are amounts such as
   `60.000€`, `$80k`, `10%` on both sides);
3. the Jaccard overlap of the titles' significant words is at least
   `TITLE_THRESHOLD` (0.75).

Significant words: NFKC, accents stripped, casefolded, split on non-letters;
gender markers (`m/f/d`), work-mode words (`remote`, `hybrid`), `software` and
function words dropped; `front-end`/`front end` read as `frontend` (likewise
`backend`, `fullstack`); `developer`/`desarrollador`/`ingeniero`... read as `engineer`.

**Why 0.75, and why every ambiguity resolves to "different".** Hiding an
advert the candidate never saw costs as much as re-showing one they did, but a
wrong match is silent while a miss is merely repeated, so doubt means show.
`tests/test_seen_before.py` carries real-looking pairs at one employer: the
lowest-scoring same-role pair and the highest-scoring different-role pair are
asserted, and so is the gap between them, so the threshold cannot be moved
into either population without a test going red. The largest value inside the
gap is taken to keep the over-merge direction narrow.

A blank employer or a title with no significant word matches nothing, not even
another blank one (`names_an_employer`'s rule).
"""

from __future__ import annotations

import re
import unicodedata

from integral.lifecycle import normalise_name
from integral.offers import names_an_employer

TITLE_THRESHOLD = 0.75

_LEGAL_FORMS = frozenset(
    {
        "sl", "slu", "sa", "sau", "gmbh", "ltd", "limited", "inc", "llc", "bv", "ag",
        "plc", "corp", "co", "srl", "ab", "oy", "kg", "sas", "sll", "pty", "as", "scoopform",
    }
)  # fmt: skip

_LEVELS = frozenset({"junior", "senior", "lead", "principal", "staff", "head", "intern"})
# Numbers and roman numerals (`Engineer II`, `Engineer 2`, a requisition number)
# are grades of the same family of roles and count with the level words.
_ROMAN = frozenset({"i", "ii", "iii", "iv", "v"})
_LEVEL_SPELLINGS = {"jr": "junior", "sr": "senior", "trainee": "intern", "becario": "intern"}

_NOISE = frozenset(
    {
        "remote", "remoto", "hybrid", "hibrido", "onsite", "presencial", "software",
        "de", "la", "el", "en", "of", "the", "a", "an", "and", "y", "e", "for", "at", "in",
        "con", "para", "to", "we", "are", "hiring",
    }
)  # fmt: skip

_SYNONYMS = {
    "developer": "engineer",
    "dev": "engineer",
    "programmer": "engineer",
    "desarrollador": "engineer",
    "desarrolladora": "engineer",
    "ingeniero": "engineer",
    "ingeniera": "engineer",
}

_COMPOUNDS = re.compile(r"\b(full|front|back)[\s-]*(stack|end)\b")

_G = r"(?:[mwfdhx]|divers[e]?)"
# Money, percentages, years and thousands-grouped figures a board appends to a
# title (`60.000€`, `$80k`, `10%`, `2026`) are not grades and are dropped.
# A currency beside a bare one- or two-digit number is a grade with a stray symbol
# (`Engineer 2 €`, `EUR 2 Engineer`), not an amount: an amount has three digits,
# a separator or a `k`. A range (`50-60k`) needs two digits on its left: `Engineer 3 - 50k`
# keeps its grade.
_FIGURE = r"(?:\d+(?=\s*k\b)|\d{3,}[\d.,]*|\d{1,2}[.,]\d[\d.,]*)"
_CURRENCY = r"(?:[€$£]|\b(?:eur|usd|gbp)(?![a-z]))"
_AMOUNT = re.compile(
    rf"\b\d{{2,}}\s*[-\u2013]\s*\d+\s*k\b"
    rf"|{_CURRENCY}\s*{_FIGURE}\s*k?"
    rf"|\b{_FIGURE}(?:\s*k\b|\s*%|\s*{_CURRENCY}(?!\s*\d))"
    r"|\b\d[\d.,]*\s*%"
    r"|\b\d{1,3}(?:[.,]\d{3})+\b",
    re.IGNORECASE,
)
_GENDER = re.compile(rf"\(?\b{_G}\s*[/\\-]\s*{_G}(?:\s*[/\\-]\s*{_G})?\b\)?|\(?\ball genders\b\)?")


def _ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _join_initials(words: list[str]) -> list[str]:
    """`S. L.` is `sl`: a run of single letters is one word."""
    joined: list[str] = []
    run = ""
    for word in words:
        if len(word) == 1:
            run += word
            continue
        if run:
            joined.append(run)
            run = ""
        joined.append(word)
    if run:
        joined.append(run)
    return joined


# `S.p.A.` / `SpA` is the Italian legal form, but a bare `Spa` is a word
# (`Hotel Spa`): only the dotted or mixed-case spelling is a legal form.
_SPA_FORM = re.compile(r"\b[sS]\.\s*[pP]\.\s*[aA]\b|\bSpA\b")
# `S. Coop.` / `S.Coop`; a bare `Scoop` is a word (`Ice Cream Scoop`).
# `Bob's Coop` is a possessive and a name, not `S Coop`.
_SCOOP = re.compile(r"(?<!['\u2019])\bs(?:\.\s*|\s+)coop\b", re.IGNORECASE)
_TRAILING_PARENS = re.compile(r"\s*\(([^()]*)\)\s*$")
# A trailing parenthesis is dropped only when it is a place (`Foo GmbH (Berlin)`);
# `Deloitte (Consulting)` and `Deloitte (Tax)` are different units. A closed
# list, so an unlisted place is kept as part of the name: that shows the advert
# again, which is the safe direction.
_PLACES = frozenset(
    """spain espana madrid barcelona valencia sevilla seville bilbao malaga zaragoza
    germany deutschland berlin munich munchen hamburg frankfurt cologne koln stuttgart
    dusseldorf united kingdom uk london manchester edinburgh birmingham ireland dublin
    france paris lyon italy italia milan milano rome roma netherlands amsterdam
    rotterdam portugal lisbon lisboa porto belgium brussels switzerland zurich geneva
    austria vienna wien sweden stockholm denmark copenhagen norway oslo finland helsinki
    poland warsaw krakow usa us united states new york san francisco boston chicago
    seattle austin los angeles canada toronto vancouver remote emea europe eu dach
    latam apac""".split()  # noqa: SIM905
)


def _is_place(text: str) -> bool:
    parts = [p for p in re.split(r"[,/;|\-]+", _ascii_fold(text).replace(".", "")) if p.strip()]
    if not parts:
        return False
    for part in parts:
        words = part.split()
        if not (part.strip() in _PLACES or (words and all(w in _PLACES for w in words))):
            return False
    return True


def _strip_trailing_places(name: str) -> str:
    while match := _TRAILING_PARENS.search(name):
        if not _is_place(match.group(1)):
            break
        name = name[: match.start()]
    return name


def employer_key(company: str | None) -> tuple[str, ...] | None:
    """The comparable form of an employer name, or `None` when it names no one
    (or only a legal form, e.g. `S.L.`). The words are run together so that
    `J.P. Morgan` and `JPMorgan` are one key; a trailing parenthesis
    (`GmbH (Berlin)`) is a location, not part of the name."""
    if not names_an_employer(company):
        return None
    raw = normalise_name(company)
    spa_is_form = bool(_SPA_FORM.search(str(company)))
    raw = _strip_trailing_places(raw)
    text = _ascii_fold(_SCOOP.sub("scoopform", raw)).replace(".", "")
    words = _join_initials([w for w in re.split(r"[\W_]+", text) if w])
    # Legal forms count only as a trailing run (`Foo GmbH & Co. KG`): `Spa
    # Resort Group`, `SA Power Networks` and `Co-op` name their employer with
    # the word, and stripping it would merge them with a different company.
    while words and (words[-1] in _LEGAL_FORMS or (spa_is_form and words[-1] == "spa")):
        words.pop()
    return ("".join(words),) if words else None


def title_words(title: str | None) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(significant words, level words, numbers) of a title. Numbers and roman
    numerals are kept apart from the words: whether they matter depends on the
    other title (see `title_similarity`)."""
    text = _ascii_fold(normalise_name(title))
    text = _AMOUNT.sub(" ", text)
    text = _GENDER.sub(" ", text)
    text = _COMPOUNDS.sub(r"\1\2", text)
    words: set[str] = set()
    levels: set[str] = set()
    numbers: set[str] = set()
    for word in re.split(r"[\W_]+", text):
        word = _LEVEL_SPELLINGS.get(word, word)
        if not word or word in _NOISE:
            continue
        if word.isdigit() or word in _ROMAN:
            numbers.add(word)
        elif word in _LEVELS:
            levels.add(word)
        else:
            words.add(_SYNONYMS.get(word, word))
    return frozenset(words), frozenset(levels), frozenset(numbers)


def _is_year(number: str) -> bool:
    return len(number) == 4 and number[:2] in ("19", "20")


def title_similarity(a: str | None, b: str | None) -> float:
    """Jaccard overlap of the significant words; 0.0 when either has none or
    the level words differ."""
    words_a, levels_a, numbers_a = title_words(a)
    words_b, levels_b, numbers_b = title_words(b)
    if not words_a or not words_b or levels_a != levels_b:
        return 0.0
    # A number is a grade (`Engineer II`, `Engineer 3`) when both titles carry
    # one, and then they must agree; when only one does it is a salary, a year
    # or a percentage appended by one board, and says nothing about the role.
    # A year is likewise ignored when only one title has it, but two different
    # years (`Graduate Programme 2025` / `2026`) are two intakes.
    for is_year in (False, True):
        part_a = {n for n in numbers_a if _is_year(n) == is_year}
        part_b = {n for n in numbers_b if _is_year(n) == is_year}
        if part_a and part_b and part_a != part_b:
            return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def same_vacancy(
    company_a: str | None, title_a: str | None, company_b: str | None, title_b: str | None
) -> bool:
    """Whether two (employer, title) pairs are one vacancy under the rule above."""
    employer_a = employer_key(company_a)
    if employer_a is None or employer_a != employer_key(company_b):
        return False
    return title_similarity(title_a, title_b) >= TITLE_THRESHOLD
