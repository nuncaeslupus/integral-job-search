"""T146 — a denial and a count are claims, and a manifest that traces assertions never asked.

T45 makes every line of a generated document trace to a store entry, and
`cv_generation_traceability == 1.0` says it does. The first live run shipped two
claims that traced to nothing and the number was green for both:

* **A denial** — *"I have not used observability tools"* — false, the candidate
  had used Honeycomb for years. An assertion is backed by an entry that holds it;
  an absence has no entry to hold, so nothing demanded one, and the sentence was
  an invented fact about the candidate, in the direction of making him smaller.
* **A count** — *"~1,600 commits across seven repositories"* — true when typed,
  stale within the session. A number typed into prose has no source of truth and
  ages from the moment it is typed.

Both holes are one shape: **a claim whose truth-maker is not something the
manifest can point at.** Both close the same way, and the rule is closed rather
than enumerated.

**Where the text is.** Two places carry sentences about the candidate. A CV or
letter line the generator renders *is* a store entry, so the question there is
whether the entry stands behind a denial (`entry_denials`). A letter paragraph
that the candidate did not write word for word has no entry at all, only an
author in `trazabilidad.md`, so the question there is what its author's cited
words support (`paragraph_defects`, called by `application_authorship`). An
`assistant` paragraph cites nothing, which is exactly why a denial or a number
could pass through it: nothing was required of a paragraph that borrows no source.

* **A denial is backed only by the candidate's own denial.** The words behind it
  must resolve, be live (a retraction withdraws them), be something the candidate
  said, and be *themselves* a denial clause that holds every content word of the
  clause it backs. The check is per denial clause, never per paragraph: one backed
  denial covers itself and nothing else in the document. Where the store is
  silent the honest sentence is about the store ("nothing in what you told me
  covers X"), never about the person. A denial that *does* have such a row passes,
  so the check is not satisfiable by banning the word "not" — which would destroy
  the honest-gap paragraph that is one of the letter's better features.
* **A count is computed or it is not written.** There is no computing channel in
  a letter, so a quantity in a paragraph the candidate did not write word for word
  passes only if the very same number is already in the words that paragraph
  cites: the candidate's, not the assistant's. The same rule runs over a CV entry:
  each number in it must be in that entry's own live provenance, spent once
  (`entry_defects`). A number used as a date is not a count. A paragraph
  that is exactly the candidate's own cited sentences is theirs and is left alone
  (`application_authorship` already requires it to be exactly that).

**The one rule for "speaks of the same thing".** A denial clause is backed when some
denial clause the candidate said contains *every* content word of it (content word:
four or more letters, singular-ish, not a negation cue and not in `_FUNCTION`).
Sharing one word is not enough: "production" or "tools" is in a thousand unrelated
denials. The rule has no list of generic nouns to extend; a word the body adds that
the candidate never said is, by that, something they did not deny.

**The honest ceiling.** Negation and quantity are recognised from closed cue
vocabularies in English, Spanish and Catalan (`NEGATORS`, `NUMBER_WORDS`). A
denial that carries none of those words ("I am new to tracing") is not seen, and
neither is the bare word "one"; a digit string is always seen. That is a limit of
reading text, stated rather than hidden. Every cue the vocabulary lacks is
fail-open, and every cue it gains only adds refusals. Also stated: "I led 3 teams"
cites "I run 3 services" and passes (a number is matched, not the thing counted), and
"1 600" or "one hundred and twenty" read as two numbers (fail-closed).
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from integral.cv_store import ConversationTurn, CVMaster, DocumentSpan, SourcedEntry, _resolves
from integral.identity import ProfileStore
from integral.profile import EvidenceLog

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T146.json"

DefectKind = Literal["denial_without_backing_row", "hand_typed_count"]

# ---------------------------------------------------------------------------
# denial: closed cue vocabulary, three languages
#
# "without" / "sin" / "sense" and "zero" are not cues: "migrated it without downtime" and
# "zero-downtime cutover" assert something about the candidate, and reading them as
# denials would withhold the achievements a CV exists to state. They are a stated
# ceiling ("I worked without tracing tools" is not seen), not an oversight.

NEGATORS: frozenset[str] = frozenset(
    {
        # en
        "not", "no", "never", "none", "nobody", "nothing", "neither", "nor",
        "cannot", "lack", "lacks", "lacking", "unfamiliar", "inexperienced",
        "unable", "dont",
        # es
        "nunca", "jamás", "jamas", "ni", "nada", "ningún", "ninguno", "ninguna",
        "tampoco", "nadie", "carezco", "carece", "carecemos",
        "desconozco", "desconoce", "desconocemos",
        # ca
        "mai", "cap", "res", "tampoc", "ningú", "manco", "gens",
    }
)  # fmt: skip
_APOSTROPHES = "'" + chr(0x2019)  # straight and typographic
_TOKEN = re.compile(rf"[^\W_]+(?:[{_APOSTROPHES}][^\W_]+)*(?:-[^\W_]+)*")
# "haven't", "doesn't", "can't": a contraction of a negator, whatever the verb.
_CONTRACTED_NEGATION = re.compile(rf"[^\W_]n[{_APOSTROPHES}]t$")


# Cues that are two words, so no single word carries them: "have yet to", "sin experiencia",
# "gens d'experiència". "without" and "sin" alone stay non-cues (see above); only the pair
# that names an absence of experience is one.
_PHRASE_CUES = re.compile(
    rf"\byet to\b|\b(?:sin|sense) experi[eè]nci[aà]\b|\blittle (?:or no )?(?:experience|exposure)\b"
    rf"|\bgens d[{_APOSTROPHES}] ?experi[eè]ncia\b"
)


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _is_cue(word: str) -> bool:
    return word in NEGATORS or _CONTRACTED_NEGATION.search(word) is not None


def is_denial(text: str) -> bool:
    """Does `text` carry a negation cue? Over-reading is fail-closed: it demands a backing row."""
    return _PHRASE_CUES.search(text.lower()) is not None or any(
        _is_cue(word) for word in _words(text)
    )


# Words that do not say what a denial is about. A backing row must share a word that
# does, or any denial in the store would back every denial in a document.
_FUNCTION = frozenset(
    {
        "have", "has", "had", "with", "that", "this", "from", "used", "using", "work",
        "worked", "been", "were", "what", "your", "they", "them", "than", "then",
        "experience", "experiencia", "experiència", "exposure", "years", "year",
        "also", "very", "much", "more", "some", "any",
        "para", "como", "tengo", "tiene", "hecho", "hemos", "usado", "estoy", "esto",
        "d'experiència", "d\u2019experiència", "amb", "per", "que", "una", "uns", "unes",
        "tinc", "hem", "fet",
    }
)  # fmt: skip


def subject_words(text: str) -> frozenset[str]:
    """What a denial is about: its content words, singular-ish, cues and function words out."""
    out = set()
    for word in _words(text):
        if _is_cue(word) or word in _FUNCTION:
            continue
        stem = word[:-1] if word.endswith("s") and len(word) > 4 else word
        if len(stem) >= 4:
            out.add(stem)
    return frozenset(out)


_SENTENCE_END = re.compile(r"[.;:!?\n]+(?=\s|$)")
_CLAUSE_END = re.compile(r"[,]+(?=\s|$)")


def denial_clauses(text: str) -> list[str]:
    """Each denial in `text`, one per negated clause rather than one per paragraph.

    A sentence is cut at commas; a piece with a cue opens a clause, a piece without one
    continues the clause before it in the same sentence ("not used Kafka, Spark, Flink").
    A sentence with no cue has no denial in it.
    """
    out: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        clauses: list[str] = []
        for piece in _CLAUSE_END.split(sentence):
            if is_denial(piece):
                clauses.append(piece)
            elif clauses:
                clauses[-1] += " " + piece
        out.extend(c.strip() for c in clauses if c.strip())
    return out


def backs_clause(clause: str, said: Sequence[str]) -> bool:
    """Does one denial the candidate said hold every content word of this clause?"""
    about = subject_words(clause)
    return any(
        about <= subject_words(theirs) and (about or not subject_words(theirs))
        for text in said
        for theirs in denial_clauses(text)
    )


def unbacked_clauses(text: str, said: Sequence[str]) -> list[str]:
    """Every denial clause of `text` that no denial of `said` backs, each judged on its own."""
    return [c for c in denial_clauses(text) if not backs_clause(c, said)]


# ---------------------------------------------------------------------------
# count: digits, or a number word, that quantifies something

# Left out because each is also an everyday word or idiom ("zero-downtime"; "one", "un",
# "una", "uno": pronoun or article; "once", "set": English; "deu", "nou": Catalan "owes",
# "new"), so reading them as counts would refuse ordinary prose. A bare "one repository"
# is therefore not seen - the same stated ceiling as above.
NUMBER_WORDS: dict[str, int] = {
    **{"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8},
    **{"nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14},
    **{"fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20},
    **{"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80},
    **{"ninety": 90, "hundred": 100, "hundreds": 100, "thousand": 1000, "thousands": 1000},
    **{"dozen": 12, "dozens": 12, "million": 10**6},
    **{"dues": 2, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8},
    **{"nueve": 9, "diez": 10, "doce": 12, "trece": 13, "catorce": 14, "quince": 15},
    **{"veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100, "ciento": 100},
    **{"mil": 1000, "quatre": 4, "cinc": 5, "sis": 6, "vuit": 8, "onze": 11, "dotze": 12},
    **{"tretze": 13, "quinze": 15, "setze": 16, "disset": 17, "divuit": 18, "dinou": 19},
    **{"dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19},
    **{"veintiuno": 21, "veintiún": 21, "veintidós": 22, "veintidos": 22, "veintitrés": 23},
    **{"veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26},
    **{"veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29},
    **{"doscientos": 200, "trescientos": 300, "cuatrocientos": 400, "quinientos": 500},
    **{"seiscientos": 600, "setecientos": 700, "ochocientos": 800, "novecientos": 900},
    **{"vint": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, "cent": 100},
}

_DIGITS = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
_YEAR = re.compile(r"(?:19|20)\d\d")
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_DECIMAL = re.compile(r"\d+[.,]\d+")
# A 4-digit number is a date when it follows one of these, or when nothing countable follows it.
_DATE_PREPOSITIONS = frozenset(
    {"since", "in", "from", "until", "till", "to", "through", "during"}
    | {"desde", "en", "hasta", "des", "fins"}
)
Quantity = int | Decimal | str


def _digits_value(token: str) -> Quantity:
    """The number a digit string writes: by value, so 1.6 is 1.60 and never 1.7.

    A string that is not one number (a version, "1.2.3") is its own text, so it still
    matches itself and nothing else.
    """
    if token.isdigit():
        return int(token)
    if _THOUSANDS.fullmatch(token):
        return int(re.sub(r"[.,]", "", token))
    if _DECIMAL.fullmatch(token):
        return Decimal(token.replace(",", "."))
    return token


def _is_date(text: str, start: int, end: int) -> bool:
    """A year-shaped number used as a date: after a date word, or with nothing countable after."""
    if not _YEAR.fullmatch(text[start:end]):
        return False
    before = _words(text[:start])[-2:]
    if before and (before[-1] in _DATE_PREPOSITIONS or before[-2:] == ["des", "de"]):
        return True
    return re.match(r"\s*[^\W\d_]", text[end:]) is None


def quantities(text: str) -> list[Quantity]:
    """Every count `text` writes, in order: an int, a `Decimal`, or the raw text of a version.

    A year is not a count, and a year is a number *used as a date*: "Since 2019" and
    "2019-2021" are dates, "2000 commits" is two thousand of something. Everything else
    numeric is a count, because which noun it counts is not decidable from the text.
    """
    found: list[tuple[int, Quantity]] = []
    for match in _DIGITS.finditer(text):
        if not _is_date(text, match.start(), match.end()):
            found.append((match.start(), _digits_value(match.group())))
    for match in re.finditer(r"[^\W\d_]+", text.lower()):
        if (value := NUMBER_WORDS.get(match.group())) is not None:
            found.append((match.start(), value))
    return [value for _, value in sorted(found, key=lambda pair: pair[0])]


# ---------------------------------------------------------------------------
# the two places a sentence about the candidate can come from


@dataclass(frozen=True)
class Defect:
    kind: DefectKind
    text: str
    detail: str


# What the candidate said, as opposed to what a row records about someone else's reaction.
_SAID = frozenset({"statement", "candidate_statement", "episode"})


def _backing_texts(store: ProfileStore, entry: SourcedEntry) -> list[str]:
    """The words of every provenance item that resolves, is live, and was the candidate's."""
    log = EvidenceLog(store)
    rows = {row.id: row for row in log.rows()} if log.exists() else {}
    out: list[str] = []
    for item in entry.provenance:
        if _resolves(store, item) is not None:
            continue
        if isinstance(item, ConversationTurn):
            row = rows[item.evidence_id]
            if row.kind in _SAID:
                out.append(row.text)
        elif isinstance(item, DocumentSpan):
            source = store.read_text("cv", "source", f"{item.source_file}.txt")
            out.append(source[item.start : item.end])
    return out


@dataclass(frozen=True)
class EntryReport:
    """What `inspect_entry` looked at and refused: the denominators ride with the verdict."""

    defects: tuple[Defect, ...]
    denials_checked: int
    counts_checked: int


def _spend(wanted: Sequence[Quantity], held: Sequence[Quantity]) -> list[Quantity]:
    """The numbers in `wanted` that `held` does not supply, each held number used once."""
    unspent = list(held)
    missing: list[Quantity] = []
    for value in wanted:
        if value in unspent:
            unspent.remove(value)
        else:
            missing.append(value)
    return missing


def _count_defect(text: str, value: Quantity, where: str) -> Defect:
    return Defect(
        "hand_typed_count",
        text,
        f"{'a number' if isinstance(value, str) else value} is not in {where}, and "
        "a document has nothing to compute it from",
    )


# An episode is a story the candidate told and then approved for one letter (T46); what
# it says is theirs, so only its denials are traced here. Every other section is a line the
# generator renders on its own, and its numbers must come from somewhere. Stated scope, not
# an oversight: an episode's own figures are T46's to defend.
COUNT_EXEMPT_SECTIONS: frozenset[str] = frozenset({"episodes"})


def counts_apply(section: str) -> bool:
    return section not in COUNT_EXEMPT_SECTIONS


def inspect_entry(store: ProfileStore, entry: SourcedEntry, *, counts: bool = True) -> EntryReport:
    """Every denial clause and every number in a store entry that nothing the candidate said backs.

    All string fields are read, identifiers included: a denial typed into a skill name
    is still a denial. A denial clause needs a denial of the candidate's own that holds
    all of its content words; a number must be in the entry's live provenance texts,
    spent once across the whole entry, the same rule a letter paragraph is held to.
    """
    values = [
        v for v in entry.model_dump(exclude={"provenance"}).values() if isinstance(v, str) and v
    ]
    said = _backing_texts(store, entry)
    defects: list[Defect] = []
    denials = 0
    for text in values:
        denials += len(denial_clauses(text))
        defects.extend(
            Defect(
                "denial_without_backing_row",
                clause,
                "no live provenance of the candidate's own denial of the same thing",
            )
            for clause in unbacked_clauses(text, said)
        )
    if not counts:
        return EntryReport(tuple(defects), denials, 0)
    held = [q for text in said for q in quantities(text)]
    written = [(text, q) for text in values for q in quantities(text)]
    unspent = list(held)
    for text, value in written:
        if value in unspent:
            unspent.remove(value)
        else:
            defects.append(_count_defect(text, value, "the entry's live provenance"))
    return EntryReport(tuple(defects), denials, len(written))


def entry_defects(store: ProfileStore, entry: SourcedEntry, *, counts: bool = True) -> list[Defect]:
    return list(inspect_entry(store, entry, counts=counts).defects)


def entry_denials(store: ProfileStore, entry: SourcedEntry) -> list[Defect]:
    """The denial half of `entry_defects`."""
    return [d for d in entry_defects(store, entry) if d.kind == "denial_without_backing_row"]


def paragraph_defects(author: str, body: str, cited: Sequence[str]) -> list[Defect]:
    """What a letter paragraph asserts that the words it cites do not.

    `candidate` is the candidate's own sentences untouched, so nothing here is
    anyone's invention. For `edited` and `assistant` (which cites nothing, so
    everything it carries is new) every denial clause needs a cited denial that holds
    all of its content words, and each number must be one the cited words already contain.
    """
    if author == "candidate":
        return []
    defects = [
        Defect(
            "denial_without_backing_row",
            clause,
            "an absence about the candidate that none of the cited words states",
        )
        for clause in unbacked_clauses(body, cited)
    ]
    held = [value for text in cited for value in quantities(text)]
    defects.extend(
        _count_defect(body, value, "the words this paragraph cites")
        for value in _spend(quantities(body), held)
    )
    return defects


# ---------------------------------------------------------------------------
# the document-level check, over what generate.py wrote


def section_entries(master: CVMaster, section: str) -> tuple[SourcedEntry, ...]:
    value = getattr(master, section)
    if isinstance(value, tuple):
        return value
    return () if value is None else (value,)


def check_version(
    store: ProfileStore, master: CVMaster, offer_id: str, version: int
) -> dict[str, Any]:
    """T45's untraced lines plus every unbacked denial and number its backed lines carry."""
    from integral.generate import claim_is_backed, read_manifest, traceability, withdrawn_turn_ids

    traced = traceability(store, master, offer_id, version)
    withdrawn = withdrawn_turn_ids(store)
    defects: list[Defect] = []
    denials = counts = 0
    for claim in read_manifest(store, offer_id, version).claims:
        if claim_is_backed(master, claim, withdrawn):
            entry = section_entries(master, claim.section)[claim.entry_index]
            report = inspect_entry(store, entry, counts=counts_apply(claim.section))
            defects.extend(report.defects)
            denials += report.denials_checked
            counts += report.counts_checked
    return {
        "denials_checked": denials,
        "counts_checked": counts,
        "claims_total": traced["claims_total"],
        "claims_untraced": traced["claims_untraced"],
        "defects": defects,
        "untraced_claim_defects": len(traced["claims_untraced"]) + len(defects),
    }


# ---------------------------------------------------------------------------
# fixture support: a probe master whose lines carry figures needs a source for them

FIXTURE_SOURCE_FILE = "doc-000900"
FIXTURE_SOURCE_CHARS = 20_000
FIXTURE_SOURCE = DocumentSpan(source_file=FIXTURE_SOURCE_FILE, start=0, end=FIXTURE_SOURCE_CHARS)


def seed_fixture_source(store: ProfileStore, master: CVMaster) -> None:
    """Write a stored source holding every figure `master`'s lines carry, for `FIXTURE_SOURCE`.

    A fixture whose headline says "six hours to forty minutes" would otherwise be withheld
    as a hand-typed count and the case it exists to plant would never reach the document.
    The span is fixed, so a master can be built before its store exists. A document
    span rather than an evidence row, so no probe's evidence-row arithmetic moves.
    """
    lines = []
    for section in ("headline", "residence_claim", "experience", "education", "skills"):
        for entry in section_entries(master, section):
            lines.extend(
                v for v in entry.model_dump(exclude={"provenance"}).values() if isinstance(v, str)
            )
    text = "\n".join(lines)
    if len(text) > FIXTURE_SOURCE_CHARS:
        raise ValueError("the fixture master outgrew its fixed source span")
    store.path("cv", "source").mkdir(parents=True, exist_ok=True)
    store.path("cv", "source", f"{FIXTURE_SOURCE_FILE}.txt").write_text(
        text.ljust(FIXTURE_SOURCE_CHARS), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# the gate: the corpus, then one probe per hole and per honest counter-case

_DENIAL = "I have not used observability tools in production."
RUNS3 = "I run 3 services."
RUNS4 = "I run 4 services."
_COUNT = "About 1,600 commits across seven repositories, six published."
_KUBE = "I have not used Kubernetes in production."
_TWO_DENIALS = (
    "I have not used Kubernetes in production, and I have never used observability tools."
)
_RAN4 = "Ran 4 services for the permits API."


def _letter_defects(author: str, paragraph: str, store: ProfileStore, cites: Sequence[str]) -> int:
    """Claim defects `check_authorship` raises for a one-paragraph letter by `author`."""
    from integral.application_authorship import check_authorship

    cell = " ".join(cites) if author != "assistant" else ""
    table = (
        "## Authorship\n| paragraph | author | evidence | changes |\n|---|---|---|---|\n"
        f"| 1 | {author} | {cell} | reworded |\n"
    )
    report = check_authorship(paragraph, table, EvidenceLog(store))
    return sum(1 for d in report.defects if "hand_typed_count" in d or "denial_without" in d)


def probe_cases() -> list[dict[str, Any]]:
    """Each hole once, each honest counter-case once, with the verdict the rule requires."""
    from integral.cv_store import Skill, SourcedText
    from integral.identity import create_profile

    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Probe", handle="probe", language="en")
        store = ProfileStore(root, identity.handle)
        log = EvidenceLog(store)

        def record(kind: Any, text: str, source: Any = "conversation") -> str:
            return log.append(
                recorded_at="2026-10-06T10:00:00Z", step="history", kind=kind, text=text,
                source=source,
            ).id  # fmt: skip

        denies = record("statement", _DENIAL)
        used = record("statement", "I used Honeycomb at Flanks for years.")
        draft = record("candidate_statement", _DENIAL, "application_draft")
        ran4 = record("statement", "I ran 4 services for the permits API.")
        counted = record("candidate_statement", RUNS3, "application_draft")
        gapped = record(
            "candidate_statement", "I have never deployed Kafka to production.", "application_draft"
        )
        kubed = record("candidate_statement", _KUBE, "application_draft")
        dec = record("candidate_statement", "It took 2.5 seconds.", "application_draft")

        kube = record("statement", _KUBE)
        both = record("statement", _TWO_DENIALS)
        ran3 = record("statement", "I run 3 services for the permits API.")
        gap = record("statement", "I have never deployed Kafka to production.")

        def stored(body: str, backing: str | None) -> int:
            turns = () if backing is None else (ConversationTurn(evidence_id=backing),)
            return len(entry_defects(store, SourcedText(text=body, provenance=turns)))

        skill = Skill(name="Never Kafka")

        def letter(author: str, body: str, *cites: str) -> int:
            return _letter_defects(author, body, store, cites)

        cases: list[tuple[str, int, int]] = [
            ("stored denial with no backing row", 1, stored(_DENIAL, None)),
            ("stored denial the candidate made", 0, stored(_DENIAL, denies)),
            ("stored denial the candidate contradicted", 1, stored(_DENIAL, used)),
            ("stored assertion", 0, stored("Used Honeycomb at Flanks.", None)),
            ("stored skill named as a denial", 1, len(entry_denials(store, skill))),
            ("stored denial backed by a denial of another thing", 1, stored(_DENIAL, gap)),
            ("stored second denial beside a backed one", 1, stored(_TWO_DENIALS, kube)),
            ("stored denial whose clauses are each backed", 0, stored(_TWO_DENIALS, both)),
            ("stored hand-typed count", 1, stored(_RAN4, None)),
            ("stored count the candidate's words hold", 0, stored(_RAN4, ran4)),
            ("stored count the candidate's words differ on", 1, stored(_RAN4, ran3)),
            ("stored count spent twice", 1, stored("Ran 4 and 4 services.", ran4)),
            ("assistant denial", 1, letter("assistant", _DENIAL)),
            ("edited denial the candidate cited", 0, letter("edited", _DENIAL, draft)),
            ("edited denial the candidate did not", 1, letter("edited", _DENIAL, counted)),
            ("edited denial about another thing", 1, letter("edited", _DENIAL, gapped)),
            ("edited second denial beside a backed one", 1, letter("edited", _TWO_DENIALS, kubed)),
            ("assistant dont", 1, letter("assistant", "I dont use Kafka.")),
            ("assistant yet to", 1, letter("assistant", "I have yet to use Kafka.")),
            ("assistant sin experiencia", 1, letter("assistant", "Sin experiencia en Kafka.")),
            ("assistant hand-typed count", 3, letter("assistant", _COUNT)),
            ("edited count the candidate wrote", 0, letter("edited", RUNS3, counted)),
            ("edited count the candidate did not", 1, letter("edited", RUNS4, counted)),
            ("assistant year", 0, letter("assistant", "Since 2019 at Flanks.")),
            ("assistant year-shaped count", 1, letter("assistant", "I wrote 2000 commits.")),
            ("edited same decimal", 0, letter("edited", "It took 2.50 seconds.", dec)),
            ("edited other decimal", 1, letter("edited", "It took 1.6 seconds.", dec)),
            ("candidate's own count", 0, letter("candidate", RUNS3, counted)),
        ]  # fmt: skip
    return [{"case": label, "expected": want, "found": got} for label, want, got in cases]


def _with_sourced_claims(store: ProfileStore, master: CVMaster) -> CVMaster:
    """The fixture master plus one backed denial and one sourced count, fictional throughout.

    The labelled fixture holds neither, so over it alone this task's two rules judge
    nothing and the corpus run is green by having nothing to refuse. These two entries
    give it a denial and a count that must *pass*, and the zero-checked guard in `_main`
    turns the denominators into a gate rather than a report.
    """
    from integral.cv_store import Experience

    log = EvidenceLog(store)

    def say(text: str) -> tuple[ConversationTurn, ...]:
        row = log.append(
            recorded_at="2026-10-06T10:00:00Z", step="history", kind="statement", text=text,
            source="conversation",
        )  # fmt: skip
        return (ConversationTurn(evidence_id=row.id),)

    extra = (
        Experience(
            title="Platform engineer",
            organisation="Fictional Works",
            description="I have not used observability tools in production.",
            provenance=say("I have not used observability tools in production, only logs."),
        ),
        Experience(
            title="Integration developer",
            organisation="Fictional Works",
            description="Ran 4 services for the permits API.",
            provenance=say("I ran 4 services for the permits API."),
        ),
    )
    return master.model_copy(update={"experience": (*master.experience, *extra)})


def measure(fixture_master: Path | None = None, store_path: Path | None = None) -> dict[str, Any]:
    """`untraced_claim_defects` over the labelled corpus, and the probes that keep it honest."""
    from integral.cv_store import write_master
    from integral.generate import _FIXTURE_ASKS, DEFAULT_FIXTURE_MASTER, generate
    from integral.harness import DEFAULT_STORE_PATH, load_store
    from integral.identity import create_profile

    master = CVMaster.model_validate_json(
        (fixture_master or DEFAULT_FIXTURE_MASTER).read_text(encoding="utf-8")
    )
    ads = load_store(store_path or DEFAULT_STORE_PATH)
    defects = 0
    claims = 0
    denials = 0
    counts = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        master = _with_sourced_claims(store, master)
        write_master(store, master)
        for ad in ads:
            manifest = generate(store, master, offer_id=ad.id, advert=ad.text, asks=_FIXTURE_ASKS)
            checked = check_version(store, master, ad.id, manifest.version)
            defects += checked["untraced_claim_defects"]
            claims += checked["claims_total"]
            denials += checked["denials_checked"]
            counts += checked["counts_checked"]
    probes = probe_cases()
    return {
        "untraced_claim_defects": defects,
        "claims_checked": claims,
        "denials_checked": denials,
        "counts_checked": counts,
        "adverts_generated": len(ads),
        "probe_cases": len(probes),
        "probe_cases_misjudged": sum(1 for p in probes if p["expected"] != p["found"]),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T146's evidence. Exit 1 on any untraced claim or misjudged probe, 3 if nothing ran.

    "Nothing ran" includes a corpus that carried no denial or no count: the rules this
    task adds would then have judged nothing, and a clean zero over that is not a pass.
    """
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if 0 in (
        measured["claims_checked"],
        measured["denials_checked"],
        measured["counts_checked"],
        measured["probe_cases"],
    ):
        print("nothing was measured: a clean zero over no claims is not a pass", file=sys.stderr)
        return 3
    if measured["untraced_claim_defects"] or measured["probe_cases_misjudged"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
