"""T229 — does this advert *require* a skill, or only mention it?

The candidate said "Nunca he usado Go, así que fuera." A text exclusion on
`golang` matched 128 stored adverts, many listing it as one option among several
(one employer alone: 32), and 299 more say bare `Go`, which no word match can
tell from the verb. So the statement was stored as evidence and applied by hand.

`skill:<technology>` is the facet that answers it, and it asks a different
question from a topic: not "is the word in the advert" but "does the advert
**hold the candidate to it**". The polarity is the point: a mention is shown
unless it is *positively* a requirement. Reading it the other way round — required
unless a list of softeners catches it — held 27 of a second reader's 105 cases
open, including a stored advert that says "we don't expect you to be an expert".

A mention holds only when all of these are so:

1. It is in a **requirement context**: the title; a section whose last heading
   is a requirements one (`Requirements`, `Requisitos`, `Qualifications`, `Must
   have`, `What we are looking for`…); or a clause with an explicit requirement
   cue ("required", "must", "imprescindible", "need"). Narrative, an offer, a
   stack, a benefit, an unknown heading — all shown. *Every* heading resets the
   section, so an advert's last heading decides, not the last one known here.
2. It is not a **negated need** ("no … needed", "no se requiere", "don't
   need", "sin experiencia", "don't expect … expert").
3. It is not **learning wording** ("willing to learn", "aprenderás", "we will
   teach you").
4. It is not the **verb** (`Go above and beyond`, `Ready to Go?`, `Go!`) and
   not **softened** (a plus, "se valora", a section so headed), **one of
   several** (`Go or Java`, `one of: Go, Rust`, `Python/Go`) or an **example**
   (`languages such as Go`).
5. It is not a **conditional** ("if you also know…") resting on its section.

The cost is stated, and chosen: plain prose with no heading and no cue
("Experience with Go.") is shown. A heading or cue this module does not know
therefore *shows* an advert and can never hold one — the safe side of an
enumeration. The title is a label, so a title naming the skill always holds.

Remaining ceilings: a cue binds to its clause (split at `;`, sentence ends,
`, but`, and after "required"), so `Python and Go as a plus` softens both; `/`
and a bare `or`/`o` joined to any word read as alternatives; a bare cue in
parentheses binds to the item before it; all-caps `GO` is not named at all
(`stack_fit` R3). All pinned by `tests/test_skill_requirement.py`.

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

Reading = Literal["required", "optional", "alternative", "negated", "learning", "unframed"]

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
    r"(?i:" + "|".join(f"(?<={w})" for w in _STRONG) + r")(?:,\s+|\s+(?:and|y|e|i)\s+)|"
    r",\s+(?=(?i:but|while|whereas|although|pero|mientras|aunque|sino|però)\b)"
)
#: Rule 1. A mention holds the candidate to the skill only in a requirement
#: context: the title, a section headed by one of these, or a clause carrying an
#: explicit requirement cue. Anything else — narrative, an offer, a stack, a
#: benefit — is shown. A heading or cue this list lacks therefore *shows* an
#: advert; it can never hold one, which is the safe side of an enumeration.
_REQUIREMENT_HEADING = re.compile(
    r"(?<![0-9a-z])(?:requirements?|requisit\w*|requeriments?|qualifications?|must[\s-]*haves?|"
    r"imprescindibles?|se\s+requiere|what\s+(?:we\s+are|we're|were|i\s+am)\s+looking\s+for|"
    r"what\s+you(?:'ll)?\s+(?:bring|need|have)|you\s+have|your\s+profile|tu\s+perfil|"
    r"qu[eé]\s+buscamos|el\s+que\s+busquem|que\s+necesitas)(?![0-9a-z])"
)
_REQUIREMENT_CUE = re.compile(
    r"(?<![0-9a-z])(?:required|requires?|requirements?|requerid\w*|requisit\w*|mandatory|"
    r"essential|must|needs?|needed|imprescindibles?|obligatori\w*|necesari\w*|necessari\w*|"
    r"necesit\w+|se\s+requiere|hace\s+falta)(?![0-9a-z])"
)
#: Rule 2. A negated need never holds: a negator, then within a few words the
#: word for needing, requiring, expecting or having experience.
_NEED_WORD = (
    r"(?:need\w*|requir\w*|requiere\w*|necesit\w*|necesari\w*|necessari\w*|"
    r"expect\w*|essential|mandatory|imprescindible|obligatori\w*|experience|experiencia|"
    r"previ[oa]|prior|knowledge|conocimientos?|exigim\w*|exigid\w*|hace\s+falta)"
)
_NEGATED_NEED = re.compile(
    r"(?<![0-9a-z])(?:no|not|never|nunca|sin|without|don'?t|doesn'?t|do\s+not|does\s+not|"
    r"won'?t|ningun[ao]?|cap|sense)(?![0-9a-z])(?:\s+[0-9a-z']+){0,4}?\s+" + _NEED_WORD
)
#: Rule 5. A conditional ("if you also know…", "si además conoces…") is an
#: invitation, not a requirement: it never holds on its section alone.
_CONDITIONAL = re.compile(r"(?<![0-9a-z])(?:if|si|when|cuando|quan)(?![0-9a-z])")
#: Rule 3. Learning wording never holds: the advert says the skill is picked up
#: here, not brought.
_LEARNING = re.compile(
    r"(?<![0-9a-z])(?:learn\w*|aprend\w*|apren\w*|ramp(?:ing)?\s+up|"
    r"we(?:'ll|\s+will)?\s+(?:train|teach)|train\s+you|te\s+(?:formamos|ensenamos)|"
    r"formaci[oa]n?|training\s+(?:budget|programme?|provided)|mentor\w*|onboard\w*)"
    r"(?![0-9a-z])"
)
#: A sentence-initial bare `Go` is the skill, not the verb, only when what follows
#: reads like a skill's predicate — "Go is required", "Go, Python y Docker".
_INITIAL_GO_SKILL = re.compile(
    r"^\s*(?:$|[,/;)(]|(?:is|are|es|son|sera|seran|must|should|debe|will|can|and|y|or|o|i|e|as|"
    r"experience|experiencia|developer|desarrollador|engineer|ingeniero|expertise|skills?|"
    r"knowledge|conocimientos?|programming|no|not|required|mandatory|essential|needed|"
    r"necesario|imprescindible|obligatorio|preferred|valorable|deseable|opcional)\b)",
    re.IGNORECASE,
)
_TERMINAL = re.compile(r"[.!?;,]$")
_INLINE_HEAD = re.compile(r"^([^:\uff1a]{1,60})[:\uff1a]\s*(\S.*)$")


def _head_has_no_technology(head: str) -> bool:
    return not _clause_spans(head, Target(frozenset()), label=False)


def _heading_of(line: str) -> tuple[str, str] | None:
    """`(heading, rest)` when `line` opens a section, else `None`.

    A heading ends in a colon, is a short unpunctuated line, or is `Head: text`
    with a short head naming no technology. `rest` is what follows the head on
    the same line. *Every* heading resets the section: an advert's last heading
    before a mention decides its context, not the last one this module knows.
    """
    if _BULLET.match(line):
        return None
    stripped = _MARKUP.sub("", line)
    if not stripped:
        return None
    if stripped.endswith((":", "\uff1a")):
        return stripped[:-1], ""
    inline = _INLINE_HEAD.match(stripped)
    if inline and len(inline.group(1).split()) <= 6 and _head_has_no_technology(inline.group(1)):
        return inline.group(1), inline.group(2)
    short = len(stripped.split()) <= 6 and not _TERMINAL.search(stripped)
    if short and _head_has_no_technology(stripped):
        return stripped, ""
    return None


def _softens(scope: str) -> bool:
    """Does this (folded) scope carry a non-negated optional cue?"""
    if _NOT_REQUIRED.search(scope):
        return True
    return any(
        not _NEGATION_BEFORE.search(scope[: match.start()]) for match in _OPTIONAL.finditer(scope)
    )


def _mode_of_heading(folded: str) -> str:
    """`required` for a requirements heading, else `none`.

    A softened heading ("Preferred qualifications") or a conditional one ("Even
    better if you have") is `none` though it names qualifications or "you have".
    """
    if _softens(folded) or _ALTERNATIVE.search(folded) or _CONDITIONAL.search(folded):
        return "none"
    return "required" if _REQUIREMENT_HEADING.search(folded) else "none"


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
            if technology == "go" and text[start:end] == "Go" and not label:
                if start == lead and not _INITIAL_GO_SKILL.match(_fold(text[end:])):
                    continue
                if re.search(r"\bto\s+$", text[:start], re.IGNORECASE) or text[end : end + 1] in (
                    "?",
                    "!",
                ):
                    continue  # "Ready to Go?", "Go!": the verb
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


def _read_clause(clause: str, target: Target, mode: str) -> list[Reading]:
    spans = _clause_spans(clause, target, label=False)
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
        scope_extra = ""
        if inside is not None:
            scope = _fold(clause[inside[0] + 1 : inside[1] - 1])
        else:
            scope = outer
            tail = next(
                (g for g in groups if clause[end : g[0]].strip() == "" and g[0] >= end), None
            )
            if tail is not None and not _clause_spans(
                clause[tail[0] : tail[1]], target, label=False
            ):
                scope_extra = _fold(clause[tail[0] + 1 : tail[1] - 1])
                if _softens(scope_extra):
                    readings.append("optional")
                    continue
        if _softens(scope):
            readings.append("optional")
        elif _ALTERNATIVE.search(scope):
            readings.append("alternative")
        elif _NEGATED_NEED.search(scope) or _NEGATED_NEED.search(scope_extra):
            readings.append("negated")
        elif _LEARNING.search(scope) or _LEARNING.search(scope_extra):
            readings.append("learning")
        elif _REQUIREMENT_CUE.search(f"{scope} {scope_extra}") or (
            mode == "required" and not _CONDITIONAL.search(scope)
        ):
            readings.append("required")
        else:
            readings.append("unframed")
    return readings


def read_mentions(title: str | None, text: str, target: Target) -> list[Reading]:
    """How the advert holds the candidate to the target, one entry per mention."""
    readings: list[Reading] = []
    if title and any(hit for _, _, hit in _clause_spans(title, target, label=True)):
        readings.append("required")
    mode = "none"
    for line in text.splitlines():
        if not line.strip():
            continue
        body = _BULLET.sub("", line, count=1)
        heading = _heading_of(line)
        if heading is not None:
            mode = _mode_of_heading(_fold(heading[0]))
            body = heading[1]
        for sentence in _CLAUSE_BREAK.split(body):
            if sentence.strip():
                readings += _read_clause(sentence, target, mode)
    return readings


def requires(title: str | None, text: str, target: Target) -> bool:
    """True when at least one mention of the target is a requirement."""
    return "required" in read_mentions(title, text, target)
