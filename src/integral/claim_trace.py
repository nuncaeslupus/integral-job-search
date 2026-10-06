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
  said, be *themselves* a denial, and speak of the same thing. Where the store is
  silent the honest sentence is about the store ("nothing in what you told me
  covers X"), never about the person. A denial that *does* have such a row passes,
  so the check is not satisfiable by banning the word "not" — which would destroy
  the honest-gap paragraph that is one of the letter's better features.
* **A count is computed or it is not written.** There is no computing channel in
  a letter, so a quantity in a paragraph the candidate did not write word for word
  passes only if the very same number is already in the words that paragraph
  cites: the candidate's, not the assistant's. Years are not counts. A paragraph
  that is exactly the candidate's own cited sentences is theirs and is left alone
  (`application_authorship` already requires it to be exactly that).

**The honest ceiling.** Negation and quantity are recognised from closed cue
vocabularies in English, Spanish and Catalan (`NEGATORS`, `NUMBER_WORDS`). A
denial that carries none of those words ("I am new to tracing") is not seen, and
neither is the bare word "one"; a digit string is always seen. That is a limit of
reading text, stated rather than hidden. Every cue the vocabulary lacks is
fail-open, and every cue it gains only adds refusals.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
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
        # es
        "nunca", "jamás", "jamas", "ni", "nada", "ningún", "ninguno", "ninguna",
        "tampoco", "nadie", "carezco", "carece", "carecemos",
        # ca
        "mai", "cap", "res", "tampoc", "ningú", "manco",
    }
)  # fmt: skip
_APOSTROPHES = "'" + chr(0x2019)  # straight and typographic
_TOKEN = re.compile(rf"[^\W_]+(?:[{_APOSTROPHES}][^\W_]+)*(?:-[^\W_]+)*")
# "haven't", "doesn't", "can't": a contraction of a negator, whatever the verb.
_CONTRACTED_NEGATION = re.compile(rf"[^\W_]n[{_APOSTROPHES}]t$")


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _is_cue(word: str) -> bool:
    return word in NEGATORS or _CONTRACTED_NEGATION.search(word) is not None


def is_denial(text: str) -> bool:
    """Does `text` carry a negation cue? Over-reading is fail-closed: it demands a backing row."""
    return any(_is_cue(word) for word in _words(text))


# Words that do not say what a denial is about. A backing row must share a word that
# does, or any denial in the store would back every denial in a document.
_FUNCTION = frozenset(
    {
        "have", "has", "had", "with", "that", "this", "from", "used", "using", "work",
        "worked", "been", "were", "what", "your", "they", "them", "than", "then",
        "experience", "years", "year", "also", "very", "much", "more", "some", "any",
        "para", "como", "tengo", "tiene", "hecho", "hemos", "usado", "estoy", "esto",
        "amb", "per", "que", "una", "uns", "unes", "tinc", "hem", "fet",
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


def backs_denial(denial: str, said: Sequence[str]) -> bool:
    """Is some one of `said` the candidate's own denial about what `denial` is about?"""
    about = subject_words(denial)
    return any(is_denial(text) and about & subject_words(text) for text in said)


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
    **{"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8},
    **{"nueve": 9, "diez": 10, "doce": 12, "trece": 13, "catorce": 14, "quince": 15},
    **{"veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100, "ciento": 100},
    **{"mil": 1000, "quatre": 4, "cinc": 5, "sis": 6, "vuit": 8, "onze": 11, "dotze": 12},
    **{"tretze": 13, "quinze": 15, "setze": 16, "disset": 17, "divuit": 18, "dinou": 19},
    **{"vint": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, "cent": 100},
}

_DIGITS = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
_YEAR = re.compile(r"(?:19|20)\d\d")
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


def _digits_value(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    if _THOUSANDS.fullmatch(token):
        return int(re.sub(r"[.,]", "", token))
    return None  # a decimal: no integer reading


def quantities(text: str) -> list[int | None]:
    """Every count `text` writes, in order; `None` is one with no integer reading.

    A year is not a count. Everything else numeric is, because a count written
    next to a noun is the claim, and which noun is not decidable from the text.
    """
    found: list[tuple[int, int | None]] = []
    for match in _DIGITS.finditer(text):
        if not _YEAR.fullmatch(match.group()):
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


def entry_denials(store: ProfileStore, entry: SourcedEntry) -> list[Defect]:
    """Every denial in a store entry's own text that nothing the candidate said backs.

    All string fields are read, identifiers included: a denial typed into a skill name
    is still a denial. Whether *numbers* in stored text are claims is not asked here;
    the store is the candidate's own words with provenance, and T45 is its gate.
    """
    values = entry.model_dump(exclude={"provenance"})
    said = _backing_texts(store, entry)
    return [
        Defect(
            "denial_without_backing_row",
            text,
            "no live provenance of the candidate's own denial about the same thing",
        )
        for text in (v for v in values.values() if isinstance(v, str) and v)
        if is_denial(text) and not backs_denial(text, said)
    ]


def paragraph_defects(author: str, body: str, cited: Sequence[str]) -> list[Defect]:
    """What a letter paragraph asserts that the words it cites do not.

    `candidate` is the candidate's own sentences untouched, so nothing here is
    anyone's invention. For `edited` and `assistant` (which cites nothing, so
    everything it carries is new) a denial needs a cited denial about the same
    thing, and each number must be one the cited words already contain.
    """
    if author == "candidate":
        return []
    defects: list[Defect] = []
    if is_denial(body) and not backs_denial(body, cited):
        defects.append(
            Defect(
                "denial_without_backing_row",
                body,
                "an absence about the candidate that none of the cited words states",
            )
        )
    unspent = [value for text in cited for value in quantities(text)]
    for value in quantities(body):
        if value in unspent:
            unspent.remove(value)
        else:
            defects.append(
                Defect(
                    "hand_typed_count",
                    body,
                    f"{'a number' if value is None else value} is not in the words this "
                    "paragraph cites, and a letter has nothing to compute it from",
                )
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
    """T45's untraced lines plus every unbacked denial its backed lines carry."""
    from integral.generate import claim_is_backed, read_manifest, traceability, withdrawn_turn_ids

    traced = traceability(store, master, offer_id, version)
    withdrawn = withdrawn_turn_ids(store)
    defects: list[Defect] = []
    for claim in read_manifest(store, offer_id, version).claims:
        if claim_is_backed(master, claim, withdrawn):
            entry = section_entries(master, claim.section)[claim.entry_index]
            defects.extend(entry_denials(store, entry))
    return {
        "claims_total": traced["claims_total"],
        "claims_untraced": traced["claims_untraced"],
        "defects": defects,
        "untraced_claim_defects": len(traced["claims_untraced"]) + len(defects),
    }


# ---------------------------------------------------------------------------
# the gate: the corpus, then one probe per hole and per honest counter-case

_DENIAL = "I have not used observability tools in production."
RUNS3 = "I run 3 services."
RUNS4 = "I run 4 services."
_COUNT = "About 1,600 commits across seven repositories, six published."


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
        counted = record("candidate_statement", RUNS3, "application_draft")

        def stored(body: str, backing: str | None) -> int:
            turns = () if backing is None else (ConversationTurn(evidence_id=backing),)
            return len(entry_denials(store, SourcedText(text=body, provenance=turns)))

        skill = Skill(name="Never Kafka")

        def letter(author: str, body: str, *cites: str) -> int:
            return _letter_defects(author, body, store, cites)

        cases: list[tuple[str, int, int]] = [
            ("stored denial with no backing row", 1, stored(_DENIAL, None)),
            ("stored denial the candidate made", 0, stored(_DENIAL, denies)),
            ("stored denial the candidate contradicted", 1, stored(_DENIAL, used)),
            ("stored assertion", 0, stored("Used Honeycomb at Flanks.", None)),
            ("stored skill named as a denial", 1, len(entry_denials(store, skill))),
            ("assistant denial", 1, letter("assistant", _DENIAL)),
            ("edited denial the candidate cited", 0, letter("edited", _DENIAL, draft)),
            ("edited denial the candidate did not", 1, letter("edited", _DENIAL, counted)),
            ("assistant hand-typed count", 3, letter("assistant", _COUNT)),
            ("edited count the candidate wrote", 0, letter("edited", RUNS3, counted)),
            ("edited count the candidate did not", 1, letter("edited", RUNS4, counted)),
            ("assistant year", 0, letter("assistant", "Since 2019 at Flanks.")),
            ("candidate's own count", 0, letter("candidate", RUNS3, counted)),
        ]  # fmt: skip
    return [{"case": label, "expected": want, "found": got} for label, want, got in cases]


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
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        for ad in ads:
            manifest = generate(store, master, offer_id=ad.id, advert=ad.text, asks=_FIXTURE_ASKS)
            checked = check_version(store, master, ad.id, manifest.version)
            defects += checked["untraced_claim_defects"]
            claims += checked["claims_total"]
    probes = probe_cases()
    return {
        "untraced_claim_defects": defects,
        "claims_checked": claims,
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
    """Write T146's evidence. Exit 1 on any untraced claim or misjudged probe, 3 if nothing ran."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["claims_checked"] == 0 or measured["probe_cases"] == 0:
        print("nothing was measured: a clean zero over no claims is not a pass", file=sys.stderr)
        return 3
    if measured["untraced_claim_defects"] or measured["probe_cases_misjudged"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
