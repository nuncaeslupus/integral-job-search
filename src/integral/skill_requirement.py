"""T229 — does this advert *require* a skill, or only mention it?

The candidate said "Nunca he usado Go, así que fuera." A text exclusion on
`golang` matched 128 stored adverts, many listing it as one option among several
(one employer alone: 32), and 299 more say bare `Go`, which no word match can
tell from the verb. So the statement was stored as evidence and applied by hand.

`skill:<technology>` is the facet that answers it, and it asks a different
question from a topic: not "is the word in the advert" but "does the advert
**hold the candidate to it**". Each mention of the technology is read in its
clause and is one of

- `required` — nothing in its clause or section softens it;
- `optional` — a nice-to-have, a plus, "se valora", "deseable", a section so headed;
- `alternative` — one of several (`Go or Java`, `one of: Go, Rust`, `Go o similar`)
  or an example of a kind (`languages such as Go`).

An advert is held only when at least one mention is `required`; one that names
the technology only as an option, a plus or an example is shown. The title is a
label, never a sentence, so a title naming the technology is always `required`.

Reading prose is not exact and the ceiling is stated here rather than discovered:
a cue binds to its clause (split at `;`, sentence ends and `, but` / `, pero`),
so `Python, Go (a plus)` softens Go alone but `Python and Go as a plus` softens
both; `/` is read as "or" (`Python/Go`); a bare cue after a list in parentheses
binds to the item before it. Every one of those choices is pinned by
`tests/test_skill_requirement.py`, in both directions, because a reader that
guesses silently is the failure this module is here to stop.

What the technology *is* comes from `stack_fit.VOCABULARY` (R1-R4: `Go` only as
spelled, never the verb, `Golang` anywhere), so the two modules cannot disagree
about whether an advert names Go. A value outside that vocabulary falls back to
the value and its terms read as whole words.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from integral import stack_fit

Reading = Literal["required", "optional", "alternative"]

FACET = "skill"


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


# ---------------------------------------------------------------------------
# vocabulary of softening, folded (no accents, lower case): English, Spanish, Catalan

_OPTIONAL_CUES = (
    r"nice[\s-]*to[\s-]*haves?",
    r"a\s+(?:big\s+|great\s+)?plus",
    r"bonus(?:\s+points)?",
    r"extra\s+points",
    r"desirable",
    r"desired",
    r"preferred",
    r"preferably",
    r"ideally",
    r"advantageous",
    r"an\s+advantage",
    r"a\s+benefit",
    r"would\s+be\s+(?:great|nice|good|a\s+plus)",
    r"is\s+welcome",
    r"are\s+welcome",
    r"optional",
    r"appreciated",
    r"valued",
    r"we\s+also\s+value",
    r"se\s+valor\w*",
    r"valorable\w*",
    r"valorad\w*",
    r"es\s+valor\w*",
    r"deseable\w*",
    r"desead\w*",
    r"opcional\w*",
    r"ventaja",
    r"preferiblemente",
    r"idealmente",
    r"apreciad\w*",
    r"apreciable\w*",
    r"tambien\s+valoramos",
    r"un\s+plus",
    r"suma\s+puntos",
    r"desitjable\w*",
    r"preferiblement",
    r"com\s+a\s+plus",
    r"es\s+valorara",
    r"es\s+tindra\s+en\s+compte",
    r"se\s+tendra\s+en\s+cuenta",
)
#: Phrases that are already a negation of the requirement: no flip applies.
_NOT_REQUIRED_CUES = (
    r"not\s+(?:strictly\s+)?(?:required|essential|mandatory|necessary)",
    r"no\s+es\s+(?:imprescindible|necesari\w*|obligatori\w*|excluyente)",
    r"no\s+(?:imprescindible|excluyente|obligatori\w*|necessari\w*)",
    r"no\s+es\s+un\s+requisito",
    r"sin\s+ser\s+(?:imprescindible|necesari\w*|obligatori\w*)",
)
_ALTERNATIVE_CUES = (
    r"one\s+of",
    r"any\s+of",
    r"at\s+least\s+one",
    r"either",
    r"alguno\s+de",
    r"alguna\s+de",
    r"cualquiera\s+de",
    r"cualquier\s+(?:lenguaje|tecnologia|stack)",
    r"uno\s+de",
    r"una\s+de",
    r"al\s+menos\s+(?:uno|una)",
    r"algun\s+de",
    r"qualsevol\s+de",
    r"un\s+dels",
    r"almenys\s+(?:un|una)",
)
_OPTIONAL = re.compile(r"(?<![0-9a-z])(?:" + "|".join(_OPTIONAL_CUES) + r")(?![0-9a-z])")
_NOT_REQUIRED = re.compile(r"(?<![0-9a-z])(?:" + "|".join(_NOT_REQUIRED_CUES) + r")(?![0-9a-z])")
_ALTERNATIVE = re.compile(r"(?<![0-9a-z])(?:" + "|".join(_ALTERNATIVE_CUES) + r")(?![0-9a-z])")
#: "not a plus", "no es deseable": the cue is denied, so it softens nothing.
_NEGATION_BEFORE = re.compile(
    r"(?<![0-9a-z])(?:not|no|never|nunca|non|ni)\s+(?:(?:es|is|are|a|an|un|una|just|only|solo|"
    r"simply|merely|se|be)\s+)*$"
)

# What precedes a list that is a set of examples, not a requirement.
_EXAMPLE_BEFORE = re.compile(
    r"(?:such\s+as|e\.\s?g\.?|eg|for\s+(?:example|instance)|por\s+ejemplo|p\.\s?ej\.?|"
    r"ej\.|tipo|(?:\w+s|etc)\s+(?:like|como)|i\s+com\s+ara)\s*[:,(]?\s*$"
)
# A mention directly joined by "or" to *something* — a name the vocabulary does
# not hold counts too (`COBOL or RPG`).
_JOINED_BY_OR = re.compile(
    r"(?<![0-9a-z])(?:or|o|u|and\s*/\s*or|y\s*/\s*o|o\s+bien)\s*[(]?\s*$|\w\s*/\s*$"
)
_OR_JOINED = re.compile(
    r"^\s*[,(]?\s*(?:(?:or|o|u|and\s*/\s*or|y\s*/\s*o|o\s+bien)(?![0-9a-z])\s*[(]?\s*[0-9a-z#+.]"
    r"|/\s*[0-9a-z#+.])"
)
# The text between two technologies in one run. A run holding any disjunctive
# gap is a set of alternatives; one of only conjunctive gaps is a list of needs.
_DISJUNCTIVE = re.compile(
    r"(?<![0-9a-z])(?:or|o|u|ó|and\s*/\s*or|y\s*/\s*o|o\s+bien|ni)(?![0-9a-z])|/", re.IGNORECASE
)
_RUN_GAP = re.compile(
    r"^[\s,/()&+]*(?:(?:and\s*/\s*or|y\s*/\s*o|o\s+bien|and|or|y|o|e|i|u|ó|ni|as\s+well\s+as)"
    r"(?![0-9A-Za-zÀ-ÿ])[\s,/()&+]*)*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# structure

_BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣>]|\d+[.)])\s+")
_MARKUP = re.compile(r"^[\s#>*_]+|[\s*_]+$")
_PAREN = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")
_STRONG = (
    "required",
    "essential",
    "mandatory",
    "must",
    "imprescindible",
    "obligatorio",
    "necesario",
    "requerido",
    "obligatori",
    "necessari",
)
_CLAUSE_BREAK = re.compile(
    r"(?<=[!?;])\s+|(?<=(?i:[a-z]{2})\.)(?<!ej\.)\s+(?=[A-Z¿¡])|"
    r"(?i:" + "|".join(f"(?<={w})" for w in _STRONG) + r"),\s+|"
    r",\s+(?=(?i:but|while|whereas|although|pero|mientras|aunque|sino|però)\b)"
)
#: A sentence-initial bare `Go` is the skill, not the verb, only when what follows
#: reads like a skill's predicate — "Go is required", "Go, Python y Docker".
_INITIAL_GO_SKILL = re.compile(
    r"^\s*(?:$|[,/;)]|(?:is|are|es|son|sera|seran|must|should|debe|will|can|and|y|or|o|i|e|as|"
    r"experience|experiencia|developer|desarrollador|engineer|ingeniero|expertise|skills?|"
    r"knowledge|conocimientos?|programming|no|not|required|mandatory|essential|needed|"
    r"necesario|imprescindible|obligatorio|preferred|valorable|deseable|opcional)\b)",
    re.IGNORECASE,
)
#: A line that opens a section whose bullets share its meaning.
_REQUIRED_HEADINGS = re.compile(
    r"(?<![0-9a-z])(?:requirements?|requisitos?|requeriments?|must[\s-]*haves?|"
    r"imprescindibles?|se\s+requiere|what\s+you(?:'ll)?\s+(?:bring|need|have)|you\s+have|"
    r"your\s+profile|tu\s+perfil|perfil|qualifications?|qu[eé]\s+buscamos|"
    r"responsibilit\w+|funciones|responsabilitats|about|sobre|we\s+offer|ofrecemos|"
    r"beneficios|benefits|oferim|el\s+que\s+busquem|que\s+necesitas|skills?|stack|"
    r"tecnolog\w+|experience|experiencia)(?![0-9a-z])"
)
_TERMINAL = re.compile(r"[.!?;,]$")


def _is_heading(line: str, folded: str) -> bool:
    if _BULLET.match(line):
        return False
    stripped = _MARKUP.sub("", line)
    if not stripped:
        return False
    if stripped.endswith((":", "\uff1a")):
        return True
    if len(stripped.split()) > 6 or _TERMINAL.search(stripped):
        return False
    if _clause_spans(stripped, Target(frozenset()), label=True):
        return False  # a short line naming technologies is content, not a heading
    return bool(
        _OPTIONAL.search(folded)
        or _NOT_REQUIRED.search(folded)
        or _ALTERNATIVE.search(folded)
        or _REQUIRED_HEADINGS.search(folded)
    )


def _softens(scope: str) -> bool:
    """Does this (folded) scope carry a non-negated optional cue?"""
    if _NOT_REQUIRED.search(scope):
        return True
    return any(
        not _NEGATION_BEFORE.search(scope[: match.start()]) for match in _OPTIONAL.finditer(scope)
    )


def _mode_of_heading(folded: str) -> str:
    if _softens(folded):
        return "optional"
    if _ALTERNATIVE.search(folded):
        return "alternative"
    return "required"


# ---------------------------------------------------------------------------
# what is being asked about


@dataclass(frozen=True)
class Target:
    """The technologies (and any literal words) one exclusion names."""

    technologies: frozenset[str]
    literals: tuple[re.Pattern[str], ...] = ()


def target_of(value: str, terms: Iterable[str] = ()) -> Target:
    """`value` and `terms` as vocabulary technologies where they resolve."""
    technologies: set[str] = set()
    literals: list[re.Pattern[str]] = []
    for word in (value, *terms):
        word = word.strip()
        if not word:
            continue
        try:
            technologies.add(stack_fit.resolve_technology(word))
        except stack_fit.StackFitError:
            literals.append(stack_fit._compile(word, False))
    return Target(frozenset(technologies), tuple(literals))


def _clause_spans(text: str, target: Target, *, label: bool) -> list[tuple[int, int, bool]]:
    found: list[tuple[int, int, bool]] = []
    lead = len(text) - len(text.lstrip(" \t#>*_-•·"))
    for technology in stack_fit.VOCABULARY:
        for start, end in stack_fit.spans_of(text, technology, label=True):
            if (
                technology == "go"
                and text[start:end] == "Go"
                and start == lead
                and not label
                and not _INITIAL_GO_SKILL.match(_fold(text[end:]))
            ):
                continue
            found.append((start, end, technology in target.technologies))
    for pattern in target.literals:
        found += [(m.start(), m.end(), True) for m in pattern.finditer(text)]
    found.sort()
    merged: list[tuple[int, int, bool]] = []
    for start, end, hit in found:  # overlapping names of one thing count once
        if merged and start < merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2] or hit)
        else:
            merged.append((start, end, hit))
    return merged


def _run_of(
    text: str, spans: list[tuple[int, int, bool]], index: int
) -> tuple[int, int, list[str]]:
    """The run of technologies joined by list words around `spans[index]`."""
    lo = hi = index
    gaps: list[str] = []
    while lo > 0 and _RUN_GAP.match(text[spans[lo - 1][1] : spans[lo][0]]):
        gaps.append(text[spans[lo - 1][1] : spans[lo][0]])
        lo -= 1
    while hi + 1 < len(spans) and _RUN_GAP.match(text[spans[hi][1] : spans[hi + 1][0]]):
        gaps.append(text[spans[hi][1] : spans[hi + 1][0]])
        hi += 1
    return lo, hi, gaps


def _read_clause(clause: str, target: Target, mode: str, *, label: bool) -> list[Reading]:
    spans = _clause_spans(clause, target, label=label)
    if not any(hit for _, _, hit in spans):
        return []
    groups = [(m.start(), m.end()) for m in _PAREN.finditer(clause)]
    blanked = list(clause)
    for start, end in groups:
        blanked[start:end] = " " * (end - start)
    outer = _fold("".join(blanked))
    readings: list[Reading] = []
    for index, (start, end, hit) in enumerate(spans):
        if not hit:
            continue
        lo, hi, gaps = _run_of(clause, spans, index)
        if hi > lo and any(_DISJUNCTIVE.search(_fold(g)) for g in gaps):
            readings.append("alternative")
            continue
        if _EXAMPLE_BEFORE.search(_fold(clause[: spans[lo][0]])):
            readings.append("alternative")
            continue
        if _JOINED_BY_OR.search(_fold(clause[: spans[lo][0]])) or _OR_JOINED.match(
            _fold(clause[spans[hi][1] :])
        ):
            readings.append("alternative")
            continue
        inside = next(((a, b) for a, b in groups if a <= start and end <= b), None)
        if inside is not None:
            scope = _fold(clause[inside[0] + 1 : inside[1] - 1])
        else:
            scope = outer
            tail = next(
                (g for g in groups if clause[end : g[0]].strip() == "" and g[0] >= end), None
            )
            if tail is not None:
                after = _fold(clause[tail[0] + 1 : tail[1] - 1])
                if not _clause_spans(clause[tail[0] : tail[1]], target, label=False) and _softens(
                    after
                ):
                    readings.append("optional")
                    continue
        if _softens(scope):
            readings.append("optional")
        elif _ALTERNATIVE.search(scope):
            readings.append("alternative")
        elif mode in ("optional", "alternative"):
            readings.append(mode)  # type: ignore[arg-type]
        else:
            readings.append("required")
    return readings


def read_mentions(title: str | None, text: str, target: Target) -> list[Reading]:
    """How the advert holds the candidate to the target, one entry per mention."""
    readings: list[Reading] = []
    if title and any(hit for _, _, hit in _clause_spans(title, target, label=True)):
        readings.append("required")
    mode = "required"
    for line in text.splitlines():
        if not line.strip():
            continue
        folded_line = _fold(line)
        if _is_heading(line, folded_line):
            mode = _mode_of_heading(folded_line)
        body = _BULLET.sub("", line, count=1)
        bulleted = body != line
        for sentence in _CLAUSE_BREAK.split(body):
            if not sentence.strip():
                continue
            readings += _read_clause(sentence, target, mode, label=bulleted and sentence == body)
    return readings


def requires(title: str | None, text: str, target: Target) -> bool:
    """True when at least one mention of the target is a requirement."""
    return "required" in read_mentions(title, text, target)
