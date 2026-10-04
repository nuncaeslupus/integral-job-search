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
   percentage a board appended, and is ignored;
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
        "plc", "corp", "co", "srl", "spa", "ab", "oy", "kg", "sas", "sll", "pty",
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


def employer_key(company: str | None) -> tuple[str, ...] | None:
    """The comparable form of an employer name, or `None` when it names no one
    (or only a legal form, e.g. `S.L.`)."""
    if not names_an_employer(company):
        return None
    text = _ascii_fold(normalise_name(company)).replace(".", "")
    words = _join_initials([w for w in re.split(r"[\W_]+", text) if w])
    # Legal forms count only as a trailing run (`Foo GmbH & Co. KG`): `Spa
    # Resort Group`, `SA Power Networks` and `Co-op` name their employer with
    # the word, and stripping it would merge them with a different company.
    while words and words[-1] in _LEGAL_FORMS:
        words.pop()
    return tuple(words) or None


def title_words(title: str | None) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(significant words, level words, numbers) of a title. Numbers and roman
    numerals are kept apart from the words: whether they matter depends on the
    other title (see `title_similarity`)."""
    text = _ascii_fold(normalise_name(title))
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
    if numbers_a and numbers_b and numbers_a != numbers_b:
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
