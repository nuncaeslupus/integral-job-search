"""T45 — per-advert generation: a CV and a letter built *out of* store entries.

The gate is `cv_generation_traceability == 1.0`, and the design choice that
makes it mean something is structural rather than procedural: **the document is
assembled from store entries, so a claim cannot exist without one.** A generator
that free-writes prose and then tries to trace it afterwards has the failure
mode this task exists to prevent — it can always produce a plausible citation
for a sentence it invented. This one can only emit a line it rendered from an
entry, and `traceability` re-renders every entry from the store and requires the
line back byte-for-byte.

That leaves exactly one way for the metric to drop, and it is the real one: a
line appears in a finished document that no manifest row backs. Whether it got
there from a model, a hand edit, or a later feature, the measurement reads the
file on disk rather than the object that wrote it, so it sees the line.

**Scaffolding is a closed vocabulary.** Headings, blank lines, and the handful
of connective sentences in `_SCAFFOLD` carry no candidate facts, so they are not
claims. Everything else in a `.md` file under the version directory is a claim
and must be in the manifest. This is what stops "not a claim" from becoming a
place to hide one: the exemption list is fixed here, in code, and a new sentence
is a claim until somebody adds it to `_SCAFFOLD` in a diff a reviewer sees.

**Mirroring is bounded by the store.** `asks` is what the advert wants, supplied
by the caller that read the advert. An ask is echoed only when a store entry
already holds it; the rest are `gaps` in the manifest — a report *to the
candidate*, never a line in the document. Borrowing a phrase over ground the
candidate does not hold is a lie with good vocabulary, and the cheapest place to
make that impossible is here, where the phrase would have to be written.

**Nothing is overwritten.** A regeneration writes `v<N+1>`. An earlier version
may already be with an employer, and a candidate has to be able to answer a
question about their own application. Three rounds, then the useful move is to
talk about what is wrong rather than generate a fourth.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integral.cv_store import (
    Certification,
    CVMaster,
    Education,
    Experience,
    LanguageEntry,
    Skill,
    SourcedEntry,
    SourcedText,
    _atomic_write_json,
    _atomic_write_text,
    write_master,
)
from integral.identity import ProfileStore, create_profile

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T45.json"

SCHEMA_VERSION: Literal[1] = 1

# Three regeneration rounds per offer, then stop. Spec step 11's stop rule: the
# useful move past this is a conversation about what is wrong with the draft,
# not a fourth draft of the same wrongness.
GENERATION_CAP = 3

_VERSION_DIR = re.compile(r"^v(\d+)$")

# The only lines in a generated document that are not claims. Closed on purpose
# — see the module docstring. Every one of these is true of any candidate and
# names no fact about this one.
_SCAFFOLD: frozenset[str] = frozenset(
    {
        "Dear hiring team,",
        "Here is what I would bring to this role, and where it comes from:",
        "I would be glad to talk it through.",
        "Kind regards,",
    }
)

# Sections that go on a CV regardless of the advert. You do not omit your own
# job history to suit a posting; what selection decides is which *skills* to
# lead with, which is where the omissions below are recorded.
_ALWAYS: tuple[str, ...] = ("headline", "experience", "education", "languages")
_SELECTED: tuple[str, ...] = ("skills", "certifications")
# Every section a claim can be rendered from. `headline` is in it deliberately:
# it is candidate-written prose about the candidate, which is a claim whatever
# it is typeset as.
_CLAIMABLE: tuple[str, ...] = (*_ALWAYS, *_SELECTED)

_HEADINGS: dict[str, str] = {
    "headline": "Summary",
    "experience": "Experience",
    "education": "Education",
    "skills": "Skills",
    "certifications": "Certifications",
    "languages": "Languages",
}


class GenerationError(Exception):
    """A generation was refused — the cap, or a version that already exists."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Claim(Strict):
    """One line of a generated document, and the store entry it was rendered from.

    `section` + `entry_index` locate the entry; `text` is what the entry renders
    to. The measurement re-renders and compares, so a manifest row cannot be
    made to fit a line that was written some other way.
    """

    document: str = Field(min_length=1)
    text: str = Field(min_length=1)
    section: str = Field(min_length=1)
    entry_index: int = Field(ge=0)


class Omission(Strict):
    """An entry the store holds that this document leaves out.

    Recorded because an omission is as much a decision as an inclusion, and the
    candidate is owed the chance to say it was the wrong one.
    """

    section: str = Field(min_length=1)
    entry_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class Manifest(Strict):
    """`cv/generated/<offer_id>/v<N>/manifest.json`."""

    schema_version: Literal[1] = SCHEMA_VERSION
    offer_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    claims: tuple[Claim, ...] = ()
    omissions: tuple[Omission, ...] = ()
    # What the advert asked for that no store entry holds. Named here so the
    # candidate can decide — apply anyway and address it in the letter, or leave
    # this one — and never written into the document itself.
    gaps: tuple[str, ...] = ()


def render_entry(section: str, entry: SourcedEntry) -> str:
    """The one line an entry becomes. The single source of a claim's wording.

    Both generation and measurement call this, which is what lets the check be
    an equality rather than a judgement about whether a sentence "matches" an
    entry.
    """
    if isinstance(entry, Experience):
        span = " to ".join(part for part in (entry.start, entry.end) if part)
        head = f"{entry.title}, {entry.organisation}"
        if span:
            head = f"{head} ({span})"
        return f"{head} — {entry.description}" if entry.description else head
    if isinstance(entry, Education):
        done = f" ({entry.completed})" if entry.completed else ""
        return f"{entry.qualification}, {entry.institution}{done}"
    if isinstance(entry, Skill):
        return f"{entry.name} ({entry.level})" if entry.level else entry.name
    if isinstance(entry, Certification):
        issued = f", {entry.issuer}" if entry.issuer else ""
        when = f" ({entry.obtained})" if entry.obtained else ""
        return f"{entry.name}{issued}{when}"
    if isinstance(entry, LanguageEntry):
        return f"{entry.language} ({entry.level})"
    if isinstance(entry, SourcedText):
        return entry.text
    raise GenerationError(f"no rendering is defined for a {type(entry).__name__} entry")


def _entries(master: CVMaster, section: str) -> tuple[SourcedEntry, ...]:
    """A section's entries, with the scalar fields presented as sections of one.

    `headline` is a `SourcedText | None` rather than a tuple, but it is a claim
    like any other and must be addressable by `(section, index)` so a manifest
    row can name it.
    """
    value = getattr(master, section)
    if isinstance(value, tuple):
        return value
    return () if value is None else (value,)


def _mentions(haystack: str, needle: str) -> bool:
    """Is `needle` present in `haystack` as a whole term?

    Whole-term, never a bare substring: `"Java" in "JavaScript"` is true and
    means the opposite of what it would be used for here — it would let a store
    holding JavaScript answer an advert asking for Java, so the gap goes
    unnamed and the candidate is never told. That is the failure this module
    exists to prevent, arriving through the back door of a cheap test.

    Still an exact term match rather than a similarity score. Nothing here is
    entitled to decide that "Kubernetes" is close enough to "Docker".
    """
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, re.IGNORECASE) is not None


def _holds(master: CVMaster, ask: str) -> bool:
    """Does any entry in the store hold what `ask` names?"""
    return any(
        _mentions(render_entry(section, entry), ask)
        for section in _CLAIMABLE
        for entry in _entries(master, section)
    )


def _select(
    master: CVMaster, advert: str, asks: tuple[str, ...]
) -> tuple[list[tuple[str, int]], list[Omission]]:
    """Which entries this advert earns, and what that leaves out."""
    chosen: list[tuple[str, int]] = []
    omitted: list[Omission] = []

    for section in _ALWAYS:
        chosen.extend((section, index) for index, _ in enumerate(_entries(master, section)))

    for section in _SELECTED:
        for index, entry in enumerate(_entries(master, section)):
            rendered = render_entry(section, entry)
            # `_mentions` here too, not a substring test: selection and gap
            # naming have to agree about what "the store holds this" means, or
            # an ask can be answered by an entry that is simultaneously
            # reported as a gap — or, worse, not reported at all.
            if _mentions(advert, rendered) or any(_mentions(rendered, ask) for ask in asks):
                chosen.append((section, index))
            else:
                omitted.append(
                    Omission(
                        section=section,
                        entry_index=index,
                        text=rendered,
                        reason="the advert does not ask for it",
                    )
                )
    return chosen, omitted


def _cv_lines(master: CVMaster, chosen: list[tuple[str, int]]) -> tuple[list[str], list[Claim]]:
    lines: list[str] = []
    claims: list[Claim] = []
    for section in _CLAIMABLE:
        picked = [index for name, index in chosen if name == section]
        if not picked:
            continue
        lines.append(f"## {_HEADINGS[section]}")
        for index in picked:
            text = render_entry(section, _entries(master, section)[index])
            lines.append(text)
            claims.append(Claim(document="cv.md", text=text, section=section, entry_index=index))
        lines.append("")
    return lines, claims


def _letter_lines(master: CVMaster, chosen: list[tuple[str, int]]) -> tuple[list[str], list[Claim]]:
    """Connective text plus the selected entries, and nothing else.

    Every sentence here is in `_SCAFFOLD`. The letter says what the candidate
    has; it does not characterise it, because a characterisation is a claim the
    store cannot back.
    """
    lines = [
        "Dear hiring team,",
        "",
        "Here is what I would bring to this role, and where it comes from:",
        "",
    ]
    claims: list[Claim] = []
    for section, index in chosen:
        text = render_entry(section, _entries(master, section)[index])
        lines.append(text)
        claims.append(Claim(document="letter.md", text=text, section=section, entry_index=index))
    lines.extend(["", "I would be glad to talk it through.", "", "Kind regards,"])
    return lines, claims


def next_version(store: ProfileStore, offer_id: str) -> int:
    """One past the highest `v<N>` already written for this offer."""
    root = store.path("cv", "generated", offer_id)
    if not root.is_dir():
        return 1
    found = [
        int(match.group(1))
        for child in root.iterdir()
        if child.is_dir() and (match := _VERSION_DIR.match(child.name))
    ]
    return max(found, default=0) + 1


def generate(
    store: ProfileStore,
    master: CVMaster,
    *,
    offer_id: str,
    advert: str,
    asks: tuple[str, ...] = (),
) -> Manifest:
    """Write `cv/generated/<offer_id>/v<N>/` — CV, letter, and manifest."""
    version = next_version(store, offer_id)
    if version > GENERATION_CAP:
        raise GenerationError(
            f"{offer_id} already has {GENERATION_CAP} versions — the cap is three "
            "rounds, and past it the useful move is to talk about what is wrong "
            "with the draft rather than generate another one"
        )

    # Reserve `v<N>` before rendering anything. `next_version` reads the
    # directory and two callers can read the same answer; an exclusive mkdir is
    # what makes the allocation a compare-and-swap rather than a hope, so the
    # loser is refused instead of quietly interleaving its files with the
    # winner's. "Never overwrites" has to hold against a second process too.
    where = ("cv", "generated", offer_id, f"v{version}")
    try:
        store.path(*where).mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise GenerationError(
            f"{offer_id} v{version} already exists — another generation took this "
            "version; nothing was written, and a fresh call will take the next one"
        ) from exc

    chosen, omissions = _select(master, advert, asks)
    cv_lines, cv_claims = _cv_lines(master, chosen)
    letter_lines, letter_claims = _letter_lines(master, chosen)
    manifest = Manifest(
        offer_id=offer_id,
        version=version,
        claims=tuple(cv_claims + letter_claims),
        omissions=tuple(omissions),
        gaps=tuple(sorted({ask for ask in asks if not _holds(master, ask)})),
    )

    _atomic_write_text(store, "\n".join(cv_lines).rstrip("\n") + "\n", *where, "cv.md")
    _atomic_write_text(store, "\n".join(letter_lines).rstrip("\n") + "\n", *where, "letter.md")
    _atomic_write_json(store, manifest.model_dump(mode="json"), *where, "manifest.json")
    return manifest


def read_manifest(store: ProfileStore, offer_id: str, version: int) -> Manifest:
    path = store.path("cv", "generated", offer_id, f"v{version}", "manifest.json")
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def _exempt() -> frozenset[str]:
    """The closed set of lines that are not claims.

    `startswith("#")` was the wrong rule and is the reason this is a set: it
    exempted *any* heading, so a headline — candidate-written prose about the
    candidate — was invisible to the measurement, and anything typed after a
    `#` inherited that invisibility. Exemption is now membership in a fixed
    vocabulary, so a new exempt line costs a diff a reviewer sees.
    """
    return frozenset(_SCAFFOLD | {f"## {heading}" for heading in _HEADINGS.values()})


def _claim_lines(text: str) -> list[str]:
    """Every line of a document that asserts something about the candidate."""
    exempt = _exempt()
    return [line for raw in text.splitlines() if (line := raw.strip()) and line not in exempt]


def traceability(
    store: ProfileStore, master: CVMaster, offer_id: str, version: int
) -> dict[str, Any]:
    """The gate: the fraction of claim lines on disk that a store entry backs.

    Reads the **files**, not the objects that wrote them, and re-renders each
    manifest row's entry from the store. A row survives only if it names a real
    entry and that entry still renders to the line it claims.
    """
    where = store.path("cv", "generated", offer_id, f"v{version}")
    # A Counter, not a set: one manifest row backs **one** line. With a set, a
    # duplicated claim line kept passing — `claims_total` rose while membership
    # still succeeded — so an extra copy of a true sentence was a free line the
    # gate could not see. Each on-disk line consumes one row's worth of backing.
    backed: Counter[tuple[str, str]] = Counter()
    for claim in read_manifest(store, offer_id, version).claims:
        entries = _entries(master, claim.section)
        if claim.entry_index < len(entries) and (
            render_entry(claim.section, entries[claim.entry_index]) == claim.text
        ):
            backed[(claim.document, claim.text)] += 1

    total = 0
    untraced: list[str] = []
    for document in sorted(where.glob("*.md")):
        for line in _claim_lines(document.read_text(encoding="utf-8")):
            total += 1
            key = (document.name, line)
            if backed[key] > 0:
                backed[key] -= 1
            else:
                untraced.append(f"{document.name}: {line}")

    # Backing nothing consumed: a manifest row describing a line the document
    # does not have. `cv_generation_traceability` cannot see this and should not
    # — every line still present still traces, so the fraction is honestly 1.0.
    # It is a different property: the manifest and the document have to agree
    # about what was sent. Step 12 reads these documents to prepare for the
    # interview, and a manifest claiming what the CV does not say would walk a
    # candidate into a question about a sentence nobody sent.
    unused = sorted(f"{document}: {text}" for (document, text), left in backed.items() if left > 0)

    return {
        # 1.0 over zero claims would be a document that says nothing passing the
        # gate that exists to keep documents honest. Null is the same third
        # outcome D-2 gives an unmeasurable score.
        "cv_generation_traceability": None if total == 0 else (total - len(untraced)) / total,
        "claims_total": total,
        "claims_untraced": sorted(untraced),
        "claims_unused": unused,
    }


# ---------------------------------------------------------------------------
# the gate — measured over the real corpus, against a stated fixture candidate

DEFAULT_FIXTURE_MASTER = _REPO_ROOT / "tests" / "fixtures" / "generation" / "master.json"

# What the measurement pretends each advert asks for. Two the fixture holds and
# two it does not, so every run exercises both branches: the mirrored word and
# the named gap. A measurement that only ever took the happy path would report
# 1.0 for a generator that had no gap handling at all.
_FIXTURE_ASKS: tuple[str, ...] = ("PostgreSQL", "Python", "Kubernetes", "Salesforce")


def measure(
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
    store_path: Path | None = None,
) -> dict[str, Any]:
    """`cv_generation_traceability` over every advert in the labelled corpus.

    Real advert text, a stated fixture candidate. The candidate has to be a
    fixture — there is no person in this repository and there must not be — but
    the *adverts* are the committed corpus, so the denominator is real prose
    with real vocabulary rather than a sentence written to pass.
    """
    from integral.harness import DEFAULT_STORE_PATH, load_store

    master = CVMaster.model_validate_json(fixture_master.read_text(encoding="utf-8"))
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    total = 0
    untraced: list[str] = []
    unused: list[str] = []
    gaps_named = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        for ad in ads:
            manifest = generate(store, master, offer_id=ad.id, advert=ad.text, asks=_FIXTURE_ASKS)
            gaps_named += len(manifest.gaps)
            measured = traceability(store, master, ad.id, manifest.version)
            total += measured["claims_total"]
            untraced.extend(f"{ad.id}/{line}" for line in measured["claims_untraced"])
            unused.extend(f"{ad.id}/{line}" for line in measured["claims_unused"])

    return {
        "cv_generation_traceability": None if total == 0 else (total - len(untraced)) / total,
        "claims_total": total,
        "claims_untraced": sorted(untraced),
        "claims_unused": sorted(unused),
        "adverts_generated": len(ads),
        "gaps_named": gaps_named,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T45.json`."""
    measured = measure(fixture_master)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T45's gate evidence. Exit 1 on any claim no store entry backs."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    for line in measured["claims_untraced"]:
        print(f"✗ untraced claim: {line}", file=sys.stderr)
    for line in measured["claims_unused"]:
        print(f"✗ manifest row backs no line in the document: {line}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["claims_unused"]:
        return 1
    # `== 1.0`, not "no untraced lines". A run that generated nothing at all
    # scores `None` with an empty untraced list, and exiting 0 on that would
    # report a gate met by a generator that produced no document.
    if measured["cv_generation_traceability"] != 1.0:
        print(
            f"cv_generation_traceability is {measured['cv_generation_traceability']!r}, not 1.0",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
