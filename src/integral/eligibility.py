"""T76 — the eligibility gate: refuse to score an offer the candidate is barred from.

Every hard constraint this tool holds today filters on what the **candidate**
declared (`stated_constraints.py`, `constraints_step.py`). Nothing filters on
what the **advert demands**. So a beautifully ranked list can lead with a role
requiring a work permit, a citizenship or a security clearance the candidate
does not have — useless in the first reply
(`status/spec-v3-silent-success.md` §2).

This module is the hard filter that runs **before** the Pareto frontier
(`rank.py`). Three verdicts, spec §5.4:

- **FAIL** — a stated, role-level bar the candidate cannot meet. Excluded, not
  ranked.
- **FLAG** — stated but ambiguous, or the candidate's status is unclear.
  Ranked, marked, and the human is the tiebreaker.
- **PASS** — nothing stated (or something stated, and the candidate's own
  declared status shows they clear it).

Two rules govern what counts as *stated*, both load-bearing:

- **Silence is not permission.** An advert that says nothing about permits has
  said nothing — not "anyone may apply".
- **A company-wide "we welcome international applicants" is not role-level
  permission.** Spec §5.1's `applies_to` field exists for exactly this: a
  blanket diversity statement never overrides, and never substitutes for, a
  role-level bar found anywhere else in the same advert. `find_requirements`
  never treats boilerplate matched by `COMPANY_WIDE_WELCOME_RE` as a
  requirement of any kind — it grants nothing and cancels nothing.

**Prefer FLAG over a silent PASS, and prefer FLAG over a confident FAIL** — the
single most important constraint here. A false FAIL is invisible: an excluded
job is one the candidate never sees, so this module defaults to FLAG for
anything short of an explicit, role-level, stated bar. Concretely: soft
language ("preferred", "a plus", "may require"), a bar whose target this
module cannot extract *and* whose candidate status is anything but a stated
empty set, and a bar whose kind the candidate has never stated anything about
all resolve to FLAG, never FAIL.

**This gate is not accuracy-tested (D-23).** There are no corpus labels for
permit, citizenship or clearance language, so `measure()` below exercises the
*mechanism* — hand-built adversarial fixtures — never real adverts. Nothing
here, or in its evidence, claims accuracy on real-world text.

Adapted from `MadsLorentzen/ai-job-search` (MIT). Attribution lives in
`README.md` and `docs/METHODS.md` — T83's file, not this one.

Never reads `weights.json` or any `dimensions/*` score (spec §5.3's boundary —
that is `rank.py`/`scoring.py`'s side; T78 tests the boundary directly).

**T78** adds the fourth requirement kind, `"language"`, sourced not from a
regex scan of `text` like the other three but from `offer.language_requirement`
directly — spec §5.1/§5.3's own hard field, settled by the owner so the
language gate never has to read `dimensions/english_demand.yaml`'s soft,
scored preference for the same subject. `evaluate_text` (raw text, no
structured offer) therefore never sees a language requirement; only
`evaluate_offer` does, via `_language_as_requirement` below.
**T77 — every FAIL and every FLAG carries a real quote.** A veto with no quote
is unfalsifiable: if this module removes a job from someone's list, it must be
able to show the sentence it removed it for. The quote is a span of the
advert's own text, on the same terms `Candidate.spans` and `enrichment.py`
hold an evidence span to — nothing sourced outside the advert may appear here.
`_require_advert_span` checks every `Requirement.quote` this module finds
against the text it was matched from and raises `QuoteProvenanceError` on
anything that is not a byte-for-byte span: a fabricated justification for
excluding someone's job is worse than no gate at all, so this fails loudly
rather than warning.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.dimensions import Language
from integral.offers import LanguageApplication, LanguageRequirement, Offer, compute_offer_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T76.json"
DEFAULT_T78_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T78.json"
DEFAULT_EVIDENCE_PATH_T77 = _REPO_ROOT / "status" / "evidence" / "T77.json"

Verdict = Literal["FAIL", "FLAG", "PASS"]
RequirementKind = Literal["citizenship", "work_permit", "clearance", "language"]

_VERDICT_RANK: dict[Verdict, int] = {"PASS": 0, "FLAG": 1, "FAIL": 2}


@dataclass(frozen=True)
class CandidateEligibility:
    """What the candidate has stated about citizenship, work authorisation and
    clearances — nothing here is this module's own read of the advert, all of
    it is what the candidate themselves told the tool.

    Each field is `None` when the candidate has never stated anything for that
    kind — deliberately distinct from an empty tuple, which means the
    candidate stated they hold *none*. Collapsing the two would turn "nobody
    asked" into "the candidate has none of it", which is exactly the kind of
    invented fact this tool's constraint fields (`candidate.py`) refuse to
    hold. `None` is what keeps a stated hard bar at FLAG rather than a
    confident FAIL when the candidate's status is simply unknown.
    """

    citizenships: tuple[str, ...] | None = None
    work_authorisations: tuple[str, ...] | None = None
    clearances: tuple[str, ...] | None = None
    #: Languages the candidate has stated they can work in (free-form codes,
    #: compared case/punctuation-insensitively via `_normalize`, the same as
    #: every other held fact here). `None` means the candidate has never
    #: stated anything about languages — never "the candidate speaks none".
    languages: tuple[str, ...] | None = None


#: The candidate has stated nothing at all. Every hard bar against this
#: profile resolves to FLAG ("the candidate's status is unclear"), never FAIL —
#: there is nothing here to fail them against.
UNKNOWN_CANDIDATE = CandidateEligibility()

_CANDIDATE_FIELD: dict[
    RequirementKind, Callable[[CandidateEligibility], tuple[str, ...] | None]
] = {
    "citizenship": lambda c: c.citizenships,
    "work_permit": lambda c: c.work_authorisations,
    "clearance": lambda c: c.clearances,
    "language": lambda c: c.languages,
}


@dataclass(frozen=True)
class Requirement:
    """One eligibility statement `eligibility.py` found in an advert's text.

    `quote` is a verbatim slice of the advert `text` it was matched against —
    never paraphrased, on the same terms spec §5.1 states for the stored
    field: "nothing sourced outside the advert may appear here." `target` is
    the specific thing named (a country, a clearance level) when the pattern
    could extract one; `None` means the bar names nothing specific ("no
    sponsorship is available", naming no country) and is scored against
    whether the candidate holds *anything at all* of this kind — see
    `_verdict_for_requirement`. `ambiguous` is set only by soft language
    ("preferred", "a plus") — a generic, targetless *hard* bar is not
    ambiguous in this sense; it is simply less specific.
    """

    kind: RequirementKind
    quote: str
    target: str | None
    ambiguous: bool


@dataclass(frozen=True)
class Reading:
    """T76's verdict for one offer, and the single requirement that drove it.

    Spec §5.1 stores at most one `(verdict, reason, quote)` triple per offer —
    not a list — so when more than one requirement is found, the worst verdict
    wins (FAIL over FLAG over PASS) and `reason`/`quote` report the
    requirement that produced it. `requirements` keeps every requirement
    found, for auditability and for T77's follow-on quote assertions.
    """

    offer_id: str
    verdict: Verdict
    reason: RequirementKind | None
    quote: str | None
    requirements: tuple[Requirement, ...]


# ---------------------------------------------------------------------------
# T77 — a quote attributed to the advert must actually be the advert's words


class QuoteProvenanceError(ValueError):
    """A `Requirement.quote` is not a byte-for-byte span of the advert text it
    is attributed to.

    A schema violation, never a warning: the module docstring's "fabricated
    justification for excluding someone's job is worse than no gate at all"
    is the whole reason this raises instead of logging and continuing."""


def is_advert_span(quote: str, text: str) -> bool:
    """Is `quote` found, byte for byte, somewhere in `text`?

    The same bar `Candidate.spans` holds an evidence span to, and the one
    `enrichment.py` already draws for explanations (`outside_source_spans`).
    Deliberately no normalisation: collapsing whitespace, stripping an accent
    or matching across an inserted ellipsis would let a paraphrase — or a
    fabrication that merely resembles the text — pass as a quote.
    """
    return bool(quote) and quote in text


def _require_advert_span(quote: str | None, text: str, *, context: str) -> None:
    """Raise `QuoteProvenanceError` unless `quote` is a real span of `text`.

    Called for every `Requirement` this module finds, whichever verdict it
    ultimately contributes to: `Reading.quote` — the one shown to a
    candidate for a FAIL or a FLAG — is always one of these, so validating
    every requirement validates the one that reaches the candidate too.
    """
    if quote is None:
        raise QuoteProvenanceError(f"{context}: carries no quote at all")
    if not is_advert_span(quote, text):
        raise QuoteProvenanceError(
            f"{context}: quote {quote!r} is not a byte-for-byte span of the advert text"
        )


# ---------------------------------------------------------------------------
# text scanning

# A bar phrased as its own negation ("you do not need to hold X citizenship",
# "no need for a clearance") is good news, not a bar. Checked immediately
# before a match; without it, a naive keyword scan reads exactly the opposite
# of what the advert says.
_NEGATION_RE = re.compile(
    r"\b(?:do(?:es)?\s+not|don't|doesn't|no\s+need\s+for|not\s+necessar(?:y|ily)|"
    r"without\s+needing|need\s+not|is\s+not\s+(?:a\s+)?requirement)\b",
    re.IGNORECASE,
)

# Soft language turns an otherwise hard-looking bar into an ambiguous one:
# "clearance is a plus" is not "clearance required". Stated but ambiguous per
# the spec, so this resolves to FLAG rather than FAIL regardless of what the
# candidate has stated.
_SOFT_RE = re.compile(
    r"\b(?:preferred|nice[\s-]to[\s-]have|a\s+plus|ideally|may\s+require|"
    r"where\s+applicable|in\s+some\s+cases|some\s+roles|desirable|advantageous|"
    r"bonus|not\s+essential|willingness\s+to\s+obtain)\b",
    re.IGNORECASE,
)

# A company-wide welcome is never role-level permission (spec §5.1's
# `applies_to`). Recognised so a naive scan of "international" or
# "nationality" cannot mistake it for a stated permission — `find_requirements`
# never turns a match here into a `Requirement` of any kind, so it can neither
# grant anything nor cancel a bar found elsewhere in the same advert.
COMPANY_WIDE_WELCOME_RE = re.compile(
    r"\bwe\s+welcome\s+(?:international\s+)?applicants\b|"
    r"\bwelcome\s+applications?\s+from\s+(?:all\s+backgrounds|candidates?\s+of\s+all)\b|"
    r"\bequal\s+opportunit(?:y|ies)\s+employer\b|"
    r"\bregardless\s+of\s+nationality\b|"
    r"\bapplicants?\s+of\s+all\s+nationalities\b",
    re.IGNORECASE,
)


def is_company_wide_statement(text: str) -> bool:
    """Does `text` carry the boilerplate spec §5.1 names by example — "we
    welcome international applicants" and its siblings?

    Exposed as its own function (rather than folded silently into the scan)
    so a caller — and `test_a_company_wide_statement_is_not_role_level_permission`
    — can confirm the boilerplate was *recognised*, not merely absent from
    what `find_requirements` happened to match. Recognising it is what proves
    the gate could have been fooled by it and was not, rather than the gate
    simply never looking.
    """
    return bool(COMPANY_WIDE_WELCOME_RE.search(text))


# `target` is the phrase naming what is required — a country, a nationality, a
# clearance level (`TS/SCI`, hence digits/`/`/`-` in the character class). The
# repeat group is reluctant (`{0,3}?`): tried at its shortest first, so a
# trailing optional clause ("... in the EU without sponsorship") is not
# swallowed into the target itself. This gate is not a geography or
# clearance-taxonomy parser — see the module docstring on accuracy.
_TARGET = r"(?P<target>[A-Za-z0-9][A-Za-z0-9./-]*(?:\s+[A-Za-z0-9][A-Za-z0-9./-]*){0,3}?)"

_CITIZENSHIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b(?:must|needs?\s+to)\s+(?:be|hold|possess)\s+(?:a\s+|an\s+)?{_TARGET}\s+citizen(?:ship)?\b",
        re.I,
    ),
    re.compile(rf"\b{_TARGET}\s+citizenship\s+(?:is\s+)?required\b", re.I),
    re.compile(rf"\b{_TARGET}\s+citizens?\s+only\b", re.I),
    # Soft: a target is still named, but the wording is a preference, not a
    # bar — `ambiguous` (via `_SOFT_RE`) is what routes this to FLAG.
    re.compile(
        rf"\b{_TARGET}\s+citizenship\s+(?:is\s+)?(?:preferred|desirable|a\s+plus|advantageous)\b",
        re.I,
    ),
    # No target group: "citizenship is required" alone names no country, so it
    # is scored against whether the candidate has stated *any* citizenship at
    # all — see `_verdict_for_requirement`.
    re.compile(r"\bcitizenship\s+(?:is\s+)?required\b", re.I),
)

_WORK_PERMIT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\bmust\s+(?:already\s+)?(?:have|hold)\s+(?:the\s+)?(?:legal\s+)?right\s+to\s+work\s+in\s+"
        rf"(?:the\s+)?{_TARGET}\b",
        re.I,
    ),
    re.compile(
        rf"\bmust\s+be\s+(?:already\s+)?(?:authoris|authoriz)ed\s+to\s+work\s+in\s+(?:the\s+)?{_TARGET}\b"
        r"(?:\s+without\s+sponsorship)?",
        re.I,
    ),
    re.compile(
        rf"\bmust\s+(?:hold|have)\s+a\s+valid\s+work\s+permit\s+for\s+(?:the\s+)?{_TARGET}\b", re.I
    ),
    # Soft, no target: a preference, not a bar.
    re.compile(
        r"\b(?:existing\s+)?(?:work\s+permit|right\s+to\s+work|visa\s+sponsorship)\s+"
        r"(?:is\s+)?(?:preferred|desirable|a\s+plus|not\s+essential|advantageous)\b",
        re.I,
    ),
    # No target: these name a blanket policy, not a country, so they are
    # scored against whether the candidate has stated *any* authorisation at
    # all — see `_verdict_for_requirement`.
    re.compile(
        r"\bwe\s+(?:are\s+)?(?:unable|not\s+able)\s+to\s+(?:offer|provide)\s+sponsorship\b", re.I
    ),
    re.compile(
        r"\bno\s+(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided)\b", re.I
    ),
    re.compile(r"\bwill\s+not\s+sponsor\b", re.I),
    re.compile(r"\bsponsorship\s+is\s+not\s+(?:available|offered|provided)\b", re.I),
)

_CLEARANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\bmust\s+(?:hold|possess)\s+(?:an?\s+)?(?:active\s+)?{_TARGET}\s+clearance\b", re.I
    ),
    # Soft, with a target: a preference, not a bar.
    re.compile(
        rf"\b(?:an?\s+)?(?:active\s+)?{_TARGET}\s+clearance\s+(?:is\s+)?"
        r"(?:a\s+plus|preferred|desirable|advantageous|nice\s+to\s+have)\b",
        re.I,
    ),
    # No target: names no specific level, scored against whether the
    # candidate has stated holding *any* clearance at all.
    re.compile(r"\b(?:active\s+)?security\s+clearance\s+(?:is\s+)?required\b", re.I),
)

_PATTERNS_BY_KIND: tuple[tuple[RequirementKind, tuple[re.Pattern[str], ...]], ...] = (
    ("citizenship", _CITIZENSHIP_PATTERNS),
    ("work_permit", _WORK_PERMIT_PATTERNS),
    ("clearance", _CLEARANCE_PATTERNS),
)


def _normalize(value: str) -> str:
    """Fold a target phrase to a bare comparison key: lowercase, accents
    folded, punctuation and whitespace collapsed. This gate compares matched
    text against what a candidate stated in the same vocabulary — it is not a
    geography or clearance-taxonomy database, see the module docstring.

    Accents are decomposed and their combining marks dropped, so `alemán` and
    `aleman` fold together. Without that they do not merely fail to match: the
    non-ASCII character is *deleted*, so `alemán` becomes `alemn` — a key that
    matches neither spelling. Job adverts drop accents freely, and every
    comparison here runs both sides through this function, so folding cannot
    make two genuinely different terms collide without them already colliding
    unaccented.
    """
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in decomposed if not unicodedata.combining(c)))


# The requirement noun itself is never the thing required. `_TARGET` is
# deliberately greedy enough to catch "TS/SCI" in "must hold an active TS/SCI
# clearance", which also lets it capture "security" in "must hold an active
# security clearance" — where the advert has named no level at all. Treating
# that as a target compares "security" against the candidate's held clearances
# and returns FAIL for someone who holds one; folding it to `None` routes the
# phrase to the generic no-target branch, which is what it is.
_NOT_A_TARGET = frozenset({"security", "citizenship", "citizen", "work", "valid", "active"})

_SENTENCE_END = re.compile(r"[.!?;\n]")


# ── The scoped eligibility vocabulary ────────────────────────────────────────
#
# An advert says "German citizenship"; a candidate says "DE". Comparing the two
# normalized strings makes those unequal, so a qualifying candidate was FAILed —
# and `ES` against the same advert was FAILed identically, which is correct. The
# two cases were indistinguishable to the code, and a false FAIL is the invisible
# direction: an excluded job is one the candidate never sees.
#
# This is deliberately NOT a world gazetteer. A term outside the table resolves
# to `None` and its requirement goes to FLAG — a human decides — never FAIL. That
# is what makes incompleteness safe here: coverage is a quality dial, not a
# correctness precondition. Terms are derived from the languages and the market
# this tool searches (ES/EN/CA, Spain-focused), never from corpus misses, which
# would be fitting the vocabulary to an evaluation split.
#
# Clearances are out of scope by decision, not oversight: TS/SCI, SC, DV and
# `habilitación de seguridad` are national schemes with real level hierarchies,
# and modelling them is a taxonomy this market does not need. They keep the
# exact-match path below, which is what `_TABLE_KINDS` selects.

_EU_MEMBERS: frozenset[str] = frozenset(
    [
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    ]
)
_EEA_MEMBERS: frozenset[str] = _EU_MEMBERS | frozenset({"IS", "LI", "NO"})

#: Bloc code → the country codes whose holders are inside it.
_BLOCS: dict[str, frozenset[str]] = {"EU": _EU_MEMBERS, "EEA": _EEA_MEMBERS}

#: Canonical code → the ways an advert or a candidate spells it, across the
#: three languages this search runs in. Accented spellings are written here as
#: they appear; `_normalize` strips the accent from both sides identically, so
#: "alemán" and "aleman" fold to the same key without a second entry.
_COUNTRY_TERMS: dict[str, tuple[str, ...]] = {
    "ES": ("spain", "spanish", "españa", "español", "española", "espanya", "espanyol", "espanyola"),
    "DE": ("germany", "german", "alemania", "alemán", "alemana", "alemanya", "alemany"),
    "FR": ("france", "french", "francia", "francés", "francesa", "frança", "francès"),
    "IT": ("italy", "italian", "italia", "italiano", "italiana", "italià", "italiana"),
    "PT": ("portugal", "portuguese", "portugués", "portuguesa", "portuguès"),
    "NL": ("netherlands", "dutch", "holanda", "holandés", "holandesa", "països baixos"),
    "BE": ("belgium", "belgian", "bélgica", "belga"),
    "IE": ("ireland", "irish", "irlanda", "irlandés", "irlandesa", "irlandès"),
    "AT": ("austria", "austrian", "austriaco", "austriaca", "austríac"),
    "PL": ("poland", "polish", "polonia", "polaco", "polaca", "polonès"),
    "SE": ("sweden", "swedish", "suecia", "sueco", "sueca", "suec"),
    "DK": ("denmark", "danish", "dinamarca", "danés", "danesa", "danès"),
    "FI": ("finland", "finnish", "finlandia", "finlandés", "finlandesa"),
    "GR": ("greece", "greek", "grecia", "griego", "griega", "grec"),
    "CZ": ("czechia", "czech", "chequia", "checo", "checa"),
    "RO": ("romania", "romanian", "rumanía", "rumano", "rumana", "romanès"),
    "HU": ("hungary", "hungarian", "hungría", "húngaro", "húngara"),
    "BG": ("bulgaria", "bulgarian", "búlgaro", "búlgara"),
    "HR": ("croatia", "croatian", "croacia", "croata"),
    "SK": ("slovakia", "slovak", "eslovaquia", "eslovaco", "eslovaca"),
    "SI": ("slovenia", "slovenian", "eslovenia", "esloveno", "eslovena"),
    "LT": ("lithuania", "lithuanian", "lituania", "lituano", "lituana"),
    "LV": ("latvia", "latvian", "letonia", "letón", "letona"),
    "EE": ("estonia", "estonian", "estonio", "estonia"),
    "LU": ("luxembourg", "luxembourgish", "luxemburgo", "luxemburgués"),
    "MT": ("malta", "maltese", "maltés", "maltesa"),
    "CY": ("cyprus", "cypriot", "chipre", "chipriota"),
    "UK": (
        "uk",
        "gb",
        "united kingdom",
        "british",
        "britain",
        "reino unido",
        "británico",
        "británica",
        "regne unit",
        "britànic",
    ),
    "US": (
        "us",
        "usa",
        "united states",
        "american",
        "estados unidos",
        "estadounidense",
        "eeuu",
        "eua",
        "nord-americà",
    ),
    "CH": ("switzerland", "swiss", "suiza", "suizo", "suiza", "suïssa"),
    "NO": ("norway", "norwegian", "noruega", "noruego", "noruega"),
    "IS": ("iceland", "icelandic", "islandia", "islandés", "islandesa"),
    "LI": ("liechtenstein",),
}

#: The bloc terms an advert actually uses. `comunitario` is the Spanish market's
#: everyday word for "EU national" and is far more common in a Spanish advert
#: than any spelling of "European Union".
_BLOC_TERMS: dict[str, tuple[str, ...]] = {
    "EU": (
        "eu",
        "ue",
        "european union",
        "unión europea",
        "unio europea",
        "european",
        "europeo",
        "europea",
        "europeu",
        "comunitario",
        "comunitaria",
        "comunitari",
        "comunitària",
    ),
    "EEA": (
        "eea",
        "eee",
        "european economic area",
        "espacio económico europeo",
        "espai econòmic europeu",
    ),
}

#: Normalized term → canonical code. The codes resolve to themselves so a
#: candidate stating "DE" and an advert saying "German" meet in the same place.
_ELIGIBILITY_ALIASES: dict[str, str] = {
    _normalize(term): code
    for source in (_COUNTRY_TERMS, _BLOC_TERMS)
    for code, terms in source.items()
    for term in (*terms, code)
}

#: The kinds scored through the table. Clearance and language keep the exact
#: `_normalize` comparison: routing them here would resolve every one of their
#: terms to `None` and turn today's correct PASSes into FLAGs.
_TABLE_KINDS: frozenset[RequirementKind] = frozenset({"citizenship", "work_permit"})


def _resolve_eligibility_term(value: str) -> str | None:
    """The canonical code `value` names, or `None` when it is outside the
    scoped vocabulary above. `None` is the safe answer, not a failure: every
    caller routes it to FLAG."""
    return _ELIGIBILITY_ALIASES.get(_normalize(value))


def _vocabulary_verdict(kind: RequirementKind, target: str, held: tuple[str, ...]) -> Verdict:
    """One resolved requirement target against what the candidate holds.

    FAIL is reserved for the case where every term on both sides resolved and
    none of them satisfies the bar. Anything unresolved on either side is FLAG,
    because the unresolved term may be the very thing that satisfies it.

    Blocs run in one direction by default: holding `ES` satisfies a bar naming
    `EU`, because Spain is in it. The reverse — holding `EU` against a bar
    naming `ES` — is PASS only for `work_permit`, where the right to work in the
    EU really does carry the right to work in Spain. For `citizenship` it is
    FLAG: "an EU citizen" does not pin a nationality, and guessing one in either
    direction is exactly the confident answer this gate exists to avoid.
    """
    wanted = _resolve_eligibility_term(target)
    if wanted is None:
        return "FLAG"
    held_codes = {code for value in held if (code := _resolve_eligibility_term(value)) is not None}
    if wanted in held_codes:
        return "PASS"
    # The candidate holds a country inside the bloc the advert named.
    if held_codes & _BLOCS.get(wanted, frozenset()):
        return "PASS"
    # The candidate holds a bloc that contains the country the advert named.
    if any(wanted in _BLOCS.get(code, frozenset()) for code in held_codes):
        return "PASS" if kind == "work_permit" else "FLAG"
    if len(held_codes) < len(held):
        return "FLAG"
    return "FAIL"


def _sentence_around(text: str, start: int, end: int) -> tuple[str, str]:
    """The text before the match, and the whole window around it, both clipped
    to the sentence the match sits in.

    Fixed character slices read across sentence boundaries, and both windows
    decide whether a stated bar counts. A 30-character look-behind turned
    "Experience is not necessary. Must hold an active TS/SCI clearance." into
    PASS, because "not necessary" from the previous sentence negated a bar that
    sentence never mentioned — a fail-open on exactly what this gate counts.
    A 40-character look-behind turned "Relevant certifications are a plus.
    Applicants must hold German citizenship." into FLAG for the same reason.
    A sentence is the smallest unit in which "not" can honestly refer to the
    requirement, so it is the bound.
    """
    left = max((text.rfind(mark, 0, start) for mark in ".!?;\n"), default=-1)
    tail = _SENTENCE_END.search(text, end)
    right = tail.start() if tail else len(text)
    return text[left + 1 : start], text[left + 1 : right]


def _scan(
    text: str, kind: RequirementKind, patterns: tuple[re.Pattern[str], ...]
) -> list[Requirement]:
    """Every requirement of `kind` found in `text`. A negated match is
    dropped entirely (it is not a bar, ambiguous or otherwise); everything
    else becomes a `Requirement`, never a silently dropped match, since a
    dropped match cannot be reasoned about or shown to a reviewer."""
    found: list[Requirement] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            before, window = _sentence_around(text, match.start(), match.end())
            if _NEGATION_RE.search(before):
                continue
            target: str | None = None
            if "target" in pattern.groupindex:
                raw = match.group("target")
                target = _normalize(raw) if raw else None
                if target in _NOT_A_TARGET:
                    target = None
            ambiguous = bool(_SOFT_RE.search(window))
            found.append(
                Requirement(
                    kind=kind,
                    quote=match.group(0).strip(),
                    target=target,
                    ambiguous=ambiguous,
                )
            )
    return found


def find_requirements(text: str) -> tuple[Requirement, ...]:
    """Every eligibility requirement `text` states, across all three kinds."""
    found: list[Requirement] = []
    for kind, patterns in _PATTERNS_BY_KIND:
        found.extend(_scan(text, kind, patterns))
    return tuple(found)


def _verdict_for_requirement(
    requirement: Requirement, candidate: CandidateEligibility
) -> tuple[Verdict, RequirementKind, str]:
    """One requirement's verdict against what the candidate has stated.

    Soft language is FLAG regardless of the candidate — there is nothing
    concrete enough to check a stated fact against. Otherwise: the
    candidate's status for this `kind` is `None` (never stated) → FLAG,
    "status unclear" — never a confident FAIL over an absence of
    information. A requirement with no extractable `target` (a blanket "no
    sponsorship" or "citizenship is required" naming no country) is scored
    against whether the candidate has stated holding *anything at all* of
    this kind: holding nothing stated (an explicit empty tuple) still fails a
    bar that needs *something*, whatever it is; holding something leaves it
    genuinely unknowable whether it satisfies an unnamed target, so it stays
    FLAG rather than a guessed PASS or FAIL. With a target, the comparison is
    direct.
    """
    if requirement.ambiguous:
        return "FLAG", requirement.kind, requirement.quote
    held = _CANDIDATE_FIELD[requirement.kind](candidate)
    if held is None:
        return "FLAG", requirement.kind, requirement.quote
    if requirement.target is None:
        if not held:
            return "FAIL", requirement.kind, requirement.quote
        return "FLAG", requirement.kind, requirement.quote
    if requirement.kind in _TABLE_KINDS:
        verdict = _vocabulary_verdict(requirement.kind, requirement.target, held)
        return verdict, requirement.kind, requirement.quote
    normalized_held = {_normalize(value) for value in held}
    if requirement.target in normalized_held:
        return "PASS", requirement.kind, requirement.quote
    return "FAIL", requirement.kind, requirement.quote


def _reading_from_requirements(
    offer_id: str,
    requirements: tuple[Requirement, ...],
    candidate: CandidateEligibility,
    text: str,
) -> Reading:
    """Worst-verdict-wins over whatever requirements were found, regardless of
    where they came from — a regex scan of `text`, or (T78) a structured
    `offer.language_requirement` translated by `_language_as_requirement`.
    One reducer, so a language bar and a citizenship bar compete on exactly
    the same terms."""
    if not requirements:
        return Reading(offer_id=offer_id, verdict="PASS", reason=None, quote=None, requirements=())

    # T77: every requirement is checked against `text` here, once, before any
    # of them can become the quote a FAIL or a FLAG shows to a candidate — see
    # `_require_advert_span`. `text` is threaded in rather than closed over
    # because T78 added a second source of requirements: a language bar comes
    # from the structured `offer.language_requirement`, not from a regex over
    # the advert, so its quote is the one that could most easily be text the
    # advert never contained. Both sources are held to the same bar here.
    for requirement in requirements:
        _require_advert_span(
            requirement.quote, text, context=f"{offer_id}: {requirement.kind} requirement"
        )

    worst_verdict: Verdict = "PASS"
    worst_reason: RequirementKind | None = None
    worst_quote: str | None = None
    for requirement in requirements:
        verdict, reason, quote = _verdict_for_requirement(requirement, candidate)
        if _VERDICT_RANK[verdict] > _VERDICT_RANK[worst_verdict]:
            worst_verdict, worst_reason, worst_quote = verdict, reason, quote
    if worst_verdict == "PASS":
        worst_reason = None
        worst_quote = None
    return Reading(
        offer_id=offer_id,
        verdict=worst_verdict,
        reason=worst_reason,
        quote=worst_quote,
        requirements=requirements,
    )


def evaluate_text(
    offer_id: str, text: str, candidate: CandidateEligibility = UNKNOWN_CANDIDATE
) -> Reading:
    """T76's verdict for one advert's text. `offer_id` is carried through
    untouched — this function takes raw text so tests can probe it without
    constructing a full `Offer`.

    Never sees a language requirement: that field lives on `Offer`, not in
    `text`, so a caller reaching for this function alone gets exactly the
    three text-scanned kinds — `evaluate_offer` is what wires in the fourth.
    """
    return _reading_from_requirements(offer_id, find_requirements(text), candidate, text)


def _language_as_requirement(requirement: LanguageRequirement | None) -> Requirement | None:
    """`offer.language_requirement` translated into this module's own
    `Requirement` shape, so it flows through `_verdict_for_requirement`
    exactly like a citizenship, work-permit or clearance bar.

    Reads `requirement.language` — the language **the role** demands — never
    `Offer.language`, which only records what the advert happens to be
    written in (see `LanguageRequirement`'s docstring in `offers.py`; a
    Catalan advert for a role that needs only Spanish still requires
    Spanish). A company-wide statement (`applies_to == "company"`) is not
    evidence about *this* role — the same principle `COMPANY_WIDE_WELCOME_RE`
    applies to citizenship and permits — so it produces no `Requirement` at
    all, never a PASS and never a FAIL.
    """
    if requirement is None or requirement.applies_to != "role":
        return None
    return Requirement(
        kind="language",
        quote=requirement.quote,
        target=_normalize(requirement.language),
        ambiguous=False,
    )


def evaluate_offer(offer: Offer, candidate: CandidateEligibility = UNKNOWN_CANDIDATE) -> Reading:
    """`evaluate_text`'s three text-scanned kinds, plus (T78) the fourth:
    `offer.language_requirement`, the hard field spec §5.3 reserves to this
    gate alone. The verbatim `text` §5.2 guarantees every connector emits and
    the structured field only `Offer` carries — this is what every real
    caller uses; `evaluate_text` exists for tests that want the text-only
    three."""
    requirements = find_requirements(offer.text)
    language_requirement = _language_as_requirement(offer.language_requirement)
    if language_requirement is not None:
        requirements = (*requirements, language_requirement)
    return _reading_from_requirements(offer.id, requirements, candidate, offer.text)


def filter_eligible(
    offers: list[Offer], candidate: CandidateEligibility = UNKNOWN_CANDIDATE
) -> tuple[list[Offer], list[Reading]]:
    """The hard filter itself: every offer paired with its reading, and the
    subset that may reach the Pareto frontier — everything except a FAIL.

    A FLAG offer is **kept**, not excluded: spec §5.4, "ranked, marked, and
    the human is the tiebreaker." Only FAIL removes an offer from what
    `rank.py` ever sees.
    """
    readings = [evaluate_offer(offer, candidate) for offer in offers]
    ranked = [
        offer for offer, reading in zip(offers, readings, strict=True) if reading.verdict != "FAIL"
    ]
    return ranked, readings


# ---------------------------------------------------------------------------
# the gate — measures the mechanism over fixtures, never accuracy (D-23)


@dataclass(frozen=True)
class Probe:
    """One hand-built adversarial case: an advert's text, what the candidate
    has stated, and the verdict a correct implementation must reach.

    `is_disqualification` marks a probe as one where the gate's job is to
    refuse the offer outright — an explicit, role-level bar the stated
    candidate cannot meet. Those are the denominator and numerator of
    `offers_ranked_despite_a_stated_disqualification`: every other probe
    (silence, ambiguity, a bar the candidate clears, a false-FAIL trap) is
    also asserted directly by the unit tests, but is not counted toward this
    specific metric, since it does not describe a stated disqualification.
    """

    name: str
    text: str
    candidate: CandidateEligibility
    expected: Verdict
    is_disqualification: bool = False


PROBES: tuple[Probe, ...] = (
    Probe(
        name="stated-citizenship-bar-candidate-fails-it",
        text="Applicants must hold German citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("ES",)),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="stated-clearance-bar-candidate-has-none",
        text="Candidates must hold an active TS/SCI clearance before starting.",
        candidate=CandidateEligibility(clearances=()),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="company-wide-welcome-does-not-cancel-a-bar",
        text=(
            "No visa sponsorship is available for this position. "
            "We are proud to be an equal opportunities employer and welcome "
            "applications from candidates of all backgrounds and nationalities."
        ),
        candidate=CandidateEligibility(work_authorisations=()),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="silence-about-permits",
        text="Backend Engineer wanted. Python, remote, competitive salary.",
        candidate=UNKNOWN_CANDIDATE,
        expected="PASS",
    ),
    Probe(
        name="stated-authorisation-satisfies-the-bar",
        text="Must be authorised to work in the EU without sponsorship.",
        candidate=CandidateEligibility(work_authorisations=("EU",)),
        expected="PASS",
    ),
    Probe(
        name="soft-language-is-not-a-hard-bar",
        text="An active security clearance is a plus, but not required for most roles.",
        candidate=CandidateEligibility(clearances=()),
        expected="FLAG",
    ),
    Probe(
        name="generic-bar-with-no-extractable-target-and-candidate-holds-something",
        text="Citizenship is required for this government contract.",
        candidate=CandidateEligibility(citizenships=("ES",)),
        expected="FLAG",
    ),
    # Round-1 review, 2026-08-26. Three cases where the gate was wrong in both
    # directions and its evidence still read 0 violations, because no probe
    # paired a bar with text from a neighbouring sentence, or a requirement
    # noun with a candidate who holds one. Committed here so the denominator
    # counts them, not only the comment thread that found them.
    Probe(
        name="negation-in-a-neighbouring-sentence-does-not-cancel-a-bar",
        text="Experience is not necessary. Must hold an active TS/SCI clearance.",
        candidate=CandidateEligibility(clearances=()),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="soft-language-in-a-neighbouring-sentence-does-not-soften-a-bar",
        text=("Relevant certifications are a plus. Applicants must hold German citizenship."),
        candidate=CandidateEligibility(citizenships=()),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="the-requirement-noun-is-not-a-target",
        text="Must hold an active security clearance.",
        candidate=CandidateEligibility(clearances=("TS/SCI",)),
        expected="FLAG",
    ),
    Probe(
        name="hard-bar-candidate-status-unstated",
        text="Must hold an active security clearance.",
        candidate=UNKNOWN_CANDIDATE,
        expected="FLAG",
    ),
    Probe(
        name="negated-requirement-is-not-a-bar",
        text=(
            "You do not need to hold German citizenship to apply for this role "
            "— we provide full visa sponsorship."
        ),
        candidate=UNKNOWN_CANDIDATE,
        expected="PASS",
    ),
    Probe(
        name="company-wide-welcome-alone-is-not-a-stated-permission",
        text=(
            "We welcome international applicants. Equal opportunities employer, "
            "regardless of nationality."
        ),
        candidate=UNKNOWN_CANDIDATE,
        expected="PASS",
    ),
    # ── The scoped vocabulary ────────────────────────────────────────────────
    # Before these, the probe set paired a target with a candidate spelling it
    # the same way, so `offers_ranked_despite_a_stated_disqualification == 0`
    # held by coincidence rather than by construction: no probe could tell a
    # qualifying candidate from a disqualified one when the two sides used
    # different words for the same country.
    Probe(
        name="citizenship-bar-candidate-holds-it-under-another-spelling",
        text="Applicants must hold German citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("DE",)),
        expected="PASS",
    ),
    Probe(
        name="citizenship-bar-target-outside-the-vocabulary-is-flagged",
        text="Applicants must hold Ruritanian citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("ES",)),
        expected="FLAG",
    ),
    Probe(
        name="work-permit-bloc-bar-satisfied-by-a-member-state",
        text="You must already have the right to work in the EU.",
        candidate=CandidateEligibility(work_authorisations=("ES",)),
        expected="PASS",
    ),
    Probe(
        name="work-permit-country-bar-satisfied-by-the-bloc",
        text="You must already have the right to work in Spain.",
        candidate=CandidateEligibility(work_authorisations=("EU",)),
        expected="PASS",
    ),
    Probe(
        name="citizenship-bar-named-by-the-spanish-market-term",
        text="Applicants must be a comunitario citizen.",
        candidate=CandidateEligibility(citizenships=("ES",)),
        expected="PASS",
    ),
    Probe(
        name="citizenship-bloc-does-not-pin-a-nationality",
        text="Applicants must be a Spanish citizen.",
        candidate=CandidateEligibility(citizenships=("EU",)),
        expected="FLAG",
    ),
    Probe(
        name="citizenship-bar-candidate-resolves-and-lacks-it",
        text="Applicants must hold German citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("ES", "PT")),
        expected="FAIL",
        is_disqualification=True,
    ),
    Probe(
        name="citizenship-bar-with-one-unresolved-holding-is-flagged",
        text="Applicants must hold German citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("ES", "Ruritanian")),
        expected="FLAG",
    ),
    Probe(
        name="accented-and-unaccented-spellings-fold-together",
        text="Applicants must hold German citizenship at the time of application.",
        candidate=CandidateEligibility(citizenships=("alemán",)),
        expected="PASS",
    ),
)


def probe() -> list[dict[str, Any]]:
    """Run every `PROBES` case, returning what each produced beside what it
    should have — `measure()`'s only source of truth, since this gate has no
    corpus to run against (D-23)."""
    results = []
    for case in PROBES:
        reading = evaluate_text(case.name, case.text, case.candidate)
        results.append(
            {
                "name": case.name,
                "expected": case.expected,
                "actual": reading.verdict,
                "reason": reading.reason,
                "quote": reading.quote,
                "is_disqualification": case.is_disqualification,
                "match": reading.verdict == case.expected,
            }
        )
    return results


def _unmeasured(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0` — see
    `connector_health.py` for the same rule applied to a different gate."""
    return {
        "offers_ranked_despite_a_stated_disqualification": -1,
        "offers_ranked_despite_a_stated_disqualification_evaluated": 0,
        "probes_run": len(readings),
        "gate_status": "unmeasured",
        "unmeasured_reason": reason,
        "readings": readings,
    }


def measure(readings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """T76's gate reading: `offers_ranked_despite_a_stated_disqualification`.

    `readings=None` (every real caller) draws them from `probe()`; a caller
    may pass its own list to prove the empty-input case cannot pass — see
    `test_the_gate_does_not_pass_on_an_empty_input_set`.

    The denominator is the subset of readings marked `is_disqualification`
    True — an explicit, role-level bar the stated candidate cannot meet. A
    violation is one of those probes whose actual verdict was not FAIL: FLAG
    or PASS both mean the offer would still reach the candidate despite a bar
    it cannot meet, which is exactly the failure this gate exists to catch.

    A zero count over zero disqualification probes is not a pass — see the
    module docstring on the empty-input-set failure — so `gate_status` reads
    `"unmeasured"` whenever that denominator is empty, never a clean `0`.
    """
    if readings is None:
        readings = probe()
    disqualifications = [r for r in readings if r["is_disqualification"]]
    if not disqualifications:
        return _unmeasured(
            "no disqualification probe was run — a zero violation count over "
            "nothing evaluated is not a measurement",
            readings,
        )
    violations = [r for r in disqualifications if r["actual"] != "FAIL"]
    return {
        "offers_ranked_despite_a_stated_disqualification": len(violations),
        "offers_ranked_despite_a_stated_disqualification_evaluated": len(disqualifications),
        "probes_run": len(readings),
        "gate_status": "measured",
        "violations": [
            f"{r['name']}: expected FAIL, got {r['actual']} (quote: {r['quote']!r})"
            for r in violations
        ],
        "readings": readings,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T76.json`. This module owns that
    file outright — nothing else writes it (CA-12: a gate must never name a
    file no module produces)."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# T78 — the module-boundary gate (spec §5.3), measured over fixtures, never
# accuracy (D-23). `offers_ranked_despite_a_stated_disqualification` above
# measures whether *this* gate reaches the right verdict; this section
# measures something different — whether the boundary between this gate and
# `rank.py`/`scoring.py` holds at all. Two directions, per the owner's
# ruling (§4 open question 2), because the failure being prevented — a
# preference weight cancelling a legal or linguistic bar — is invisible in
# any output either layer produces:
#
#   1. the ranker must never read a gate-only offer field
#      (`language_requirement`, `eligibility`);
#   2. this gate's verdict must never move because a weight moved — it has
#      no path to see one in the first place.

#: Offer fields spec §5.3 reserves to the eligibility/language gate alone.
#: `rank.py` and `scoring.py` — named explicitly in the boundary table — must
#: never access either as an attribute.
GATE_ONLY_OFFER_FIELDS: tuple[str, ...] = ("language_requirement", "eligibility")

#: The two modules the boundary table names as "the ranker".
RANKER_MODULES: tuple[Path, ...] = (
    _REPO_ROOT / "src" / "integral" / "rank.py",
    _REPO_ROOT / "src" / "integral" / "scoring.py",
)


#: Builtins that reach a field by name at runtime rather than by syntax.
#: `getattr(offer, "language_requirement")` reads the gate-only field without
#: producing a single `ast.Attribute` node carrying that name.
_DYNAMIC_ACCESSORS: frozenset[str] = frozenset({"getattr", "setattr", "hasattr", "delattr"})

#: Ways to obtain a whole namespace at once. Neither names a field, so
#: neither can be resolved to one — and both would hand a ranker every
#: gate-only field there is.
_NAMESPACE_ESCAPES: frozenset[str] = frozenset({"__dict__", "vars"})


@dataclass(frozen=True)
class _FieldAccess:
    """What one module's source says about the fields it touches.

    `names` is what the scan could resolve; `unresolved` is what it could
    not. The split exists because those two are not the same answer: an
    empty `names` means no gate-only field was read, while a non-empty
    `unresolved` means the question was not answered at all, and reporting
    the first when the second holds is how a boundary gate reports a clean
    zero over a hole.
    """

    names: frozenset[str]
    unresolved: tuple[str, ...]


def _field_access(source: str) -> _FieldAccess:
    """Every field `source` reaches, by syntax or by name, plus whatever it
    reaches in a way this scan cannot resolve.

    An AST walk rather than a substring search on purpose: this module's own
    docstrings mention `language_requirement` by name, and a plain text
    search of `rank.py`/`scoring.py` would have to forbid that too, which
    would ban documenting the boundary in the very files it protects.

    Attribute syntax is not the only way in, which is the whole reason this
    returns more than a set of names. `getattr(offer, "language_requirement")`
    is an `ast.Call`; the field name sits in a `Constant` argument and no
    `ast.Attribute` node carries it. Counting only attribute nodes reports a
    clean boundary over exactly that read — fail-open in the one direction
    this gate exists to close. So a literal accessor call resolves to the
    name it names, and a non-literal one (`getattr(offer, key)`) or a whole
    namespace (`offer.__dict__`, `vars(offer)`) resolves to nothing and is
    recorded as unresolved instead of silently passing.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    unresolved: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
            if node.attr in _NAMESPACE_ESCAPES:
                unresolved.append(f"`.{node.attr}` exposes every field at once")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _DYNAMIC_ACCESSORS and len(node.args) >= 2:
                field = node.args[1]
                if isinstance(field, ast.Constant) and isinstance(field.value, str):
                    names.add(field.value)
                else:
                    unresolved.append(
                        f"`{node.func.id}(...)` names its field at runtime, "
                        "so this scan cannot say which one"
                    )
            elif node.func.id in _NAMESPACE_ESCAPES:
                unresolved.append(f"`{node.func.id}(...)` exposes every field at once")
    return _FieldAccess(names=frozenset(names), unresolved=tuple(unresolved))


@dataclass(frozen=True)
class WeightInvarianceCase:
    """One hand-built offer proving direction 2: this gate's verdict for a
    fixed offer and candidate is what it is regardless of any weight —
    because `evaluate_offer` takes no `weights` argument and has no path by
    which one could reach it. `test_a_dimension_weight_cannot_change_a_gate_verdict`
    varies `weights.json`-shaped mappings around this same fact directly.
    """

    name: str
    offer: Offer
    candidate: CandidateEligibility
    expected: Verdict


def _language_offer(
    text: str,
    *,
    requirement_language: str,
    applies_to: LanguageApplication = "role",
    quote: str | None = None,
    offer_language: Language | None = None,
) -> Offer:
    """A hand-built offer whose only interesting feature is its
    `language_requirement`. `offer_language` — what the advert is written
    in, `Offer.language` — is `None` unless a case supplies it explicitly:
    `test_the_role_language_is_read_not_the_adverts_own_language` is exactly
    the case that sets it to something *other* than `requirement_language`,
    to prove the gate reads the latter and not the former."""
    return Offer(
        id=compute_offer_id(text),
        source="manual",
        text=text,
        language=offer_language,
        language_requirement=LanguageRequirement(
            language=requirement_language,
            level_stated=None,
            quote=quote or text,
            applies_to=applies_to,
        ),
    )


#: Boundary-audit fixtures for direction 2. Not accuracy fixtures (D-23) —
#: every case here already has an obviously correct verdict; what is being
#: proven is that the verdict cannot be moved by a weight, not that the
#: mechanism is right on real adverts.
WEIGHT_INVARIANCE_CASES: tuple[WeightInvarianceCase, ...] = (
    WeightInvarianceCase(
        name="role-requires-german-candidate-lacks-it",
        offer=_language_offer(
            "Backend Engineer, remote. Verhandlungssicheres Deutsch ist Voraussetzung "
            "fuer diese Rolle.",
            requirement_language="de",
            quote="Verhandlungssicheres Deutsch ist Voraussetzung fuer diese Rolle.",
        ),
        candidate=CandidateEligibility(languages=("en",)),
        expected="FAIL",
    ),
    WeightInvarianceCase(
        name="role-requires-spanish-candidate-holds-it",
        offer=_language_offer(
            "Customer support role. Se requiere espanol fluido para el puesto.",
            requirement_language="es",
            quote="Se requiere espanol fluido para el puesto.",
        ),
        candidate=CandidateEligibility(languages=("es", "en")),
        expected="PASS",
    ),
    WeightInvarianceCase(
        name="company-wide-language-policy-does-not-gate-the-role",
        offer=_language_offer(
            "Data Analyst. Our company's internal working language is English.",
            requirement_language="en",
            applies_to="company",
            quote="Our company's internal working language is English.",
        ),
        candidate=CandidateEligibility(languages=()),
        expected="PASS",
    ),
)


def audit_boundary(
    modules: tuple[Path, ...] = RANKER_MODULES,
    cases: tuple[WeightInvarianceCase, ...] = WEIGHT_INVARIANCE_CASES,
) -> list[dict[str, Any]]:
    """Every audit point T78's boundary gate checks — `measure_boundary`'s
    only source of truth, since this gate has no corpus to run against
    (D-23). One entry per ranker module scanned for a gate-only field access
    (direction 1), one entry per `WeightInvarianceCase` proving the verdict
    is the offer's alone (direction 2)."""
    results: list[dict[str, Any]] = []
    for module in modules:
        if not module.exists():
            continue
        access = _field_access(module.read_text(encoding="utf-8"))
        hit = next((f for f in GATE_ONLY_OFFER_FIELDS if f in access.names), None)
        if hit is not None:
            detail = f"{module.name} reads .{hit}, a gate-only field (spec §5.3)"
        elif access.unresolved:
            detail = (
                f"{module.name} reaches fields this scan cannot resolve "
                f"({'; '.join(sorted(set(access.unresolved)))}), so whether it reads a "
                "gate-only field is unknown"
            )
        else:
            detail = None
        results.append(
            {
                "direction": "ranker_never_reads_a_gate_field",
                "name": module.name,
                # A scan that could not resolve every access has not cleared
                # the module; it has failed to look. `match` stays True so it
                # is never counted as a proven breach, and `resolved` carries
                # the difference to `measure_boundary`, which refuses to
                # report a number over it.
                "match": hit is None,
                "resolved": hit is not None or not access.unresolved,
                "detail": detail,
            }
        )
    # Named for what it does. These cases assert the verdict a fixed offer and
    # candidate produce; they do not vary a weight, and calling `evaluate_offer`
    # twice could not vary one — it takes no weights argument. The invariance
    # claim rests on that signature, and is pinned where it can actually fail:
    # `test_a_dimension_weight_cannot_change_a_gate_verdict` asserts the
    # parameter list, so growing a `weights=` parameter breaks the suite.
    for case in cases:
        actual = evaluate_offer(case.offer, case.candidate).verdict
        results.append(
            {
                "direction": "gate_verdict_matches_expectation",
                "name": case.name,
                "match": actual == case.expected,
                "detail": None
                if actual == case.expected
                else f"{case.name}: expected {case.expected}, got {actual}",
            }
        )
    return results


def _unmeasured_boundary(reason: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a boundary reading that could not happen takes: `-1`, never
    `0` — see `connector_health.py` for the same rule applied to a different
    gate."""
    return {
        "gate_fields_read_by_the_ranker": -1,
        "ranked_offers_evaluated": 0,
        "gate_status": "unmeasured",
        "unmeasured_reason": reason,
        "results": results,
    }


def measure_boundary(results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """T78's gate reading: `gate_fields_read_by_the_ranker`.

    `results=None` (every real caller) draws them from `audit_boundary`; a
    caller may pass its own list to prove the empty-input case cannot pass —
    see `test_the_gate_does_not_pass_on_an_empty_input_set`.

    A violation is any audit point whose `match` came back `False` — either
    direction counts identically toward the one asserted number, because
    both are the same failure from opposite sides: a preference weight and a
    hard bar sharing a channel neither output layer would ever show.

    A zero count over zero audit points is not a pass — see the module
    docstring on the empty-input-set failure — so `gate_status` reads
    `"unmeasured"` whenever nothing was evaluated, never a clean `0`.
    """
    if results is None:
        results = audit_boundary()
    if not results:
        return _unmeasured_boundary(
            "no boundary audit point was run — a zero violation count over "
            "nothing evaluated is not a measurement",
            results,
        )
    # Each direction is counted under its own name. Folding both into
    # `gate_fields_read_by_the_ranker` meant a verdict case failing its
    # expectation — a regression in this gate — was reported as the ranker
    # having read a gate-only field, sending the reader to inspect `rank.py`
    # for a breach that never happened. A metric that misnames its own failure
    # is worse than no metric: it costs the reader the time to disprove it.
    scans = [r for r in results if r["direction"] == "ranker_never_reads_a_gate_field"]
    offer_cases = [r for r in results if r["direction"] == "gate_verdict_matches_expectation"]
    violations = [r for r in results if not r["match"]]
    # A module whose accesses this scan could not resolve has not been
    # cleared — the question was never answered. Reporting
    # `gate_fields_read_by_the_ranker: 0` over it would be the empty-input
    # failure wearing a full denominator: a zero obtained by not looking.
    # `unmeasured` is the reading that says so, and exits 3 rather than 0.
    opaque = [r for r in scans if not r.get("resolved", True)]
    if opaque:
        return _unmeasured_boundary(
            "; ".join(str(r["detail"]) for r in opaque),
            results,
        )
    return {
        "gate_fields_read_by_the_ranker": len([r for r in scans if not r["match"]]),
        "gate_verdicts_mismatching_expectation": len([r for r in offer_cases if not r["match"]]),
        "ranked_offers_evaluated": len(offer_cases),
        "ranker_modules_scanned": len(scans),
        "audit_points_evaluated": len(results),
        "gate_status": "measured",
        "violations": [r["detail"] for r in violations if r["detail"]],
        "results": results,
    }


def write_boundary_evidence(evidence: Path = DEFAULT_T78_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/T78.json`. This module owns that
    file outright — nothing else writes it (CA-12: a gate must never name a
    file no module produces)."""
    measured = measure_boundary()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# T77's own gate — every disqualification verdict's quote is a real span


def _quote_provenance_readings() -> list[dict[str, Any]]:
    """`evaluate_text` over every `PROBES` case, reporting each verdict and
    whether its quote is a genuine span of that case's own text.

    Reads `PROBES` (T76's fixtures) but writes nothing to it — a second gate
    over the same cases, not a change to the first. `evaluate_text` already
    raises `QuoteProvenanceError` outright on a bad quote (see
    `_require_advert_span`), so a run that reaches the end of this loop has
    already proven the mechanism for every case evaluated; `quoted` below
    records that proof rather than re-deciding it.
    """
    readings = []
    for case in PROBES:
        reading = evaluate_text(case.name, case.text, case.candidate)
        quoted = reading.quote is not None and is_advert_span(reading.quote, case.text)
        readings.append(
            {
                "name": case.name,
                "verdict": reading.verdict,
                "quote": reading.quote,
                "quoted": quoted,
            }
        )
    return readings


def _unmeasured_quote_provenance(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The empty-input shape for T77's gate — `-1`, never a clean `0`, same
    rule `_unmeasured` applies to T76's own gate."""
    return {
        "disqualification_verdicts_without_quoted_wording": -1,
        # Both names on purpose: the task payload's body names the first, its
        # later `status-key` addendum names the second. Same count, so a
        # reader trusting either one finds it — the same convention
        # `connector_health.py` uses for `silent_connector_failures_evaluated`.
        "disqualification_verdicts_without_quoted_wording_evaluated": 0,
        "disqualification_verdicts_evaluated": 0,
        "gate_status": "unmeasured",
        "unmeasured_reason": reason,
        "readings": readings,
    }


def measure_quote_provenance(readings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """T77's gate reading: `disqualification_verdicts_without_quoted_wording`.

    `readings=None` (every real caller) draws them from `_quote_provenance_readings`;
    a caller may pass its own list to prove the empty-input case cannot pass —
    see `test_the_gate_does_not_pass_on_an_empty_input_set`.

    The denominator is every reading whose verdict is FAIL or FLAG — spec
    §5.4's two verdicts that remove or mark an offer, both named explicitly by
    the task ("every FAIL and every FLAG"). PASS carries no quote and is not
    part of this denominator. A zero count over zero such verdicts is not a
    pass, so `gate_status` reads `"unmeasured"` whenever that denominator is
    empty, never a clean `0`.
    """
    if readings is None:
        readings = _quote_provenance_readings()
    disqualification_verdicts = [r for r in readings if r["verdict"] in ("FAIL", "FLAG")]
    if not disqualification_verdicts:
        return _unmeasured_quote_provenance(
            "no FAIL or FLAG verdict was evaluated — a zero violation count over "
            "nothing evaluated is not a measurement",
            readings,
        )
    violations = [r for r in disqualification_verdicts if not r["quoted"]]
    evaluated = len(disqualification_verdicts)
    return {
        "disqualification_verdicts_without_quoted_wording": len(violations),
        "disqualification_verdicts_without_quoted_wording_evaluated": evaluated,
        "disqualification_verdicts_evaluated": evaluated,
        "gate_status": "measured",
        "violations": [
            f"{r['name']}: verdict {r['verdict']} quote={r['quote']!r}" for r in violations
        ],
        "readings": readings,
    }


def write_evidence_quote_provenance(evidence: Path = DEFAULT_EVIDENCE_PATH_T77) -> dict[str, Any]:
    """Measure and record `status/evidence/T77.json`. This module owns that
    file outright alongside `T76.json` — see the T77 task payload, and CA-12
    on a gate never naming a file no module produces."""
    measured = measure_quote_provenance()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# T86's own gate — a candidate who meets a stated bar is never FAILed


def _unmeasured_false_disqualifications(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The empty-input shape for T86's gate — `-1`, never a clean `0`, the same
    rule `_unmeasured` applies to T76's."""
    return {
        "false_disqualifications": -1,
        "false_disqualifications_evaluated": 0,
        "gate_status": "unmeasured",
        "unmeasured_reason": (
            "no probe pairs a stated bar with a candidate who meets it — a zero "
            "false-FAIL count over nothing evaluated is not a measurement"
        ),
        "readings": readings,
    }


def measure_false_disqualifications() -> dict[str, Any]:
    """T86's gate reading: `false_disqualifications`.

    T76 counts the offers ranked *despite* a bar — the visible direction. This
    counts the opposite one, which has no other gate: an offer excluded by a bar
    the candidate actually meets. That failure is invisible by construction,
    because the candidate never sees the job it removed, and it is the direction
    a vocabulary gap produces — `DE` against "German citizenship" read as a FAIL
    for want of a table entry.

    The denominator is every probe that states a real bar and whose expected
    verdict is not FAIL: the candidate either clears it or their status is
    unclear. A FAIL over any of those is a false disqualification. A denominator
    of zero is `unmeasured`, never a clean `0` — which is exactly the state this
    gate was in before it existed.
    """
    readings: list[dict[str, Any]] = []
    for case in PROBES:
        if not find_requirements(case.text):
            continue
        if case.expected == "FAIL":
            continue
        actual = evaluate_text(case.name, case.text, case.candidate).verdict
        readings.append(
            {
                "name": case.name,
                "expected": case.expected,
                "actual": actual,
                "false_disqualification": actual == "FAIL",
            }
        )
    if not readings:
        return _unmeasured_false_disqualifications(readings)
    violations = [r for r in readings if r["false_disqualification"]]
    return {
        "false_disqualifications": len(violations),
        "false_disqualifications_evaluated": len(readings),
        "gate_status": "measured",
        "violations": [
            f"{r['name']}: expected {r['expected']}, got FAIL — the candidate meets this bar"
            for r in violations
        ],
        "readings": readings,
    }


def write_false_disqualification_evidence(evidence: Path) -> dict[str, Any]:
    """Measure T86's gate and write it to `evidence`."""
    measured = measure_false_disqualifications()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.eligibility [T76-path [T77-path]]`.

    One module, four gates. T76's `offers_ranked_despite_a_stated_disqualification`,
    T77's `disqualification_verdicts_without_quoted_wording` and T78's
    `gate_fields_read_by_the_ranker` are all measured and written here, because
    all three task payloads name this same regeneration command.

    Paths: T77's second positional defaults to sitting beside the first, and
    T78's target is derived the same way, so a test pointing T76's evidence at
    a tmp directory gets all three isolated there rather than writing over the
    committed files; a caller passing nothing lands on `status/evidence/`.

    The violation count is checked **before** the unmeasured branch, for every
    gate: a run that found a real, known violation must fail (exit 1), never
    report `unmeasured` — a known bad result outranks "could not be scored
    yet". The overall exit code is the worst of the three, so no gate's
    failure can be masked by another's success.
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    t77_target = Path(positional[1]) if len(positional) > 1 else target.parent / "T77.json"

    exit_code = 0

    def _score(measured: dict[str, Any], key: str) -> None:
        """Fold one gate's reading into `exit_code`, violation before unmeasured."""
        nonlocal exit_code
        print(json.dumps(measured, ensure_ascii=False))
        if measured[key] > 0:
            for line in measured.get("violations", []):
                print(line, file=sys.stderr)
            exit_code = max(exit_code, 1)
        elif measured["gate_status"] == "unmeasured":
            print(
                f"{key}: UNMEASURED — {measured['unmeasured_reason']}. Not a pass and not a fail.",
                file=sys.stderr,
            )
            exit_code = max(exit_code, 3)

    _score(write_evidence(target), "offers_ranked_despite_a_stated_disqualification")
    _score(
        write_evidence_quote_provenance(t77_target),
        "disqualification_verdicts_without_quoted_wording",
    )
    # Both of T78's counts gate the exit code. `_score` folds in the one it is
    # given, so the second is checked here rather than left to be reported and
    # ignored — a verdict regression must fail the run as loudly as a boundary
    # breach does.
    boundary = write_boundary_evidence(target.parent / "T78.json")
    _score(boundary, "gate_fields_read_by_the_ranker")
    if boundary["gate_verdicts_mismatching_expectation"] > 0:
        exit_code = max(exit_code, 1)
    _score(
        write_false_disqualification_evidence(target.parent / "T86.json"),
        "false_disqualifications",
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
