"""The CV store: import, build-from-nothing, and the on-disk contract (S4).

`status/spec-v2-brief.md` §2.6 names three things the pre-v2 spec conflated
under "the CV": an **input** (a supplied PDF/DOCX, or nothing at all), a
**store** (`cv/master.json` — "everything a CV contains plus everything it
omits", never sent anywhere as-is), and an **output** (a CV generated per
advert). `claude-arsenal/queue/lo-cb1c.md`'s scope change narrows this task to
the middle one: this module owns `cv/master.json` and the two ways it gets
filled — parsing a document, or a conversation with someone who has none — and
nothing about the third. Per-advert generation is T45; personal details
(name, address, phone, date of birth) are collected at step 11 by T46, not
here (`status/spec-v2-steps.md` step 1's own words: "Do not ask here...").

## The gate, and the concrete failure it prevents

`intake_field_provenance` (`status/spec-v2-steps.md` step 1's gate) is the
fraction of fields in `master.json` that name where they came from — a
document span, or the turn in which it was said. **A field with no provenance
is a claim nobody can check**, and step 2 (Constraints) promotes claims to
facts by *asking about them* — "Barcelona from a CV header is what the
document says, not where they live" — which it cannot do for a claim whose
origin is unknown. So every value this module writes is wrapped in a
`SourcedEntry`/`SourcedText` carrying a non-empty `provenance` tuple, and
`measure_provenance` re-derives the fraction from what is actually on disk
rather than trusting that every writer honoured the rule — the same
"re-measure the guarantee, do not just trust it" posture `jobsearch.
elicit_extract.story_dimension_linkage` takes toward `store_answer`, and
`jobsearch.profile_capture.measure_coverage` takes toward its own drivers.
Concretely: `SourcedEntry.provenance` has **no** `min_length` constraint, on
purpose — a field with an empty provenance tuple loads without error (a
schema violation here would make the deliberate-break demonstration a load
failure rather than a *measurement*, and "loaders raise, measurement
functions report" is the house rule this module follows: `load_master` raises
only on structural corruption — bad JSON, an unknown key, a wrong type — never
on a field that happens to lack sourcing, because that is exactly the
property `intake_field_provenance` exists to catch and report a number for.

## The dependency decision

The project depends on `pydantic` and `pyyaml` only, and every gate in this
repository runs in CI with no network and no optional extras
(`pyproject.toml`'s own precedent, the `collect` extra's comment: "Reading and
validating the committed corpus is stdlib-only, so the T4b gate runs without
them"). Two document formats, two different answers:

**DOCX is a zip of XML.** Verified, not assumed: `_extract_docx_text` opens
the file with stdlib `zipfile`, reads `word/document.xml`, and pulls text out
of `<w:t>` runs with stdlib `xml.etree.ElementTree` — no third-party package
involved, and `tests/test_cv_store.py` proves it end to end against a `.docx`
this module also builds with nothing but `zipfile` (`probe_intake`'s fixture,
`_build_minimal_docx`). So DOCX import needs no extra, and the gate exercises
it directly, unconditionally, everywhere.

**PDF text extraction is not tractable stdlib-only.** No PDF parser ships in
the standard library, and hand-rolling a content-stream parser to avoid one
dependency would be worse than the dependency: slower, less correct, and a
maintenance burden this task has no business taking on. So, following
`pyproject.toml`'s own `collect`-extra precedent to the letter — same shape,
same reasoning, same place in the file — this module adds:

```
cv = ["pypdf>=4.0"]
```

`_extract_pdf_text` imports `pypdf` **inside the function**, never at module
load, so `import jobsearch.cv_store` never requires it. When the extra is
absent (this repository's CI, and every gate run in this task's own
verification), `import_document` reports `ImportResult(status="unavailable",
...)` for a `.pdf` — a clear, structured outcome a caller can show a candidate
("we can't read PDFs without an extra step here — try DOCX, or let's just
talk through it"), never a crash, never a silently empty store. The `S4` gate
is measured over the DOCX-import path and the build-from-nothing path, neither
of which needs `pypdf`, so `intake_field_provenance == 1.0` is reached — and
verified — with **no optional extras installed**, exactly as T4b's corpus
gate runs without `collect`.

## `cv/source/*` holds extracted text, not the original file bytes

The scope change is explicit that "`cv/source/*` is stored unmodified... "
provenance spans are offsets into it, so any normalisation destroys the thing
the gate measures" — the same discipline `jobsearch.corpus` already applies to
the ad corpus, which stores each ad's **extracted text** byte-for-byte, never
the page it was scraped from. This module makes the identical choice for the
identical reason: a `.docx`/`.pdf` is a binary container, and a byte offset
into its compressed, structured bytes cites nothing a human — or a highlight
UI — could ever point at. `cv/source/<doc-id>.txt` is therefore the text
`_extract_docx_text`/`_extract_pdf_text` produced, written exactly as
produced (no stripping, no re-wrapping, no normalisation), and
`DocumentSpan.start`/`.end` are character offsets into *that* file. There is
exactly one on-disk representation of an imported document's content, and
spans are offsets into exactly that — which is what keeps a rebuild-style
re-check honest: `measure_provenance` reads the same file a span was cut
from, not a copy that might have drifted from it. The original upload itself
is the candidate's own file, on their own machine; this module never asks for
a second, permanent copy of it.

## Personal details are out of scope, and no field says otherwise

Per `status/spec-v2-steps.md` step 1: "Do not ask here for a legal name, an
address, a telephone number, an identity number, a date of birth or a
photograph... they are collected by step 11, for the document that actually
needs them." `CVMaster` carries no field for any of them. The payload asks
this module to "leave the door open... without collecting them" — the honest
answer is that no schema change accomplishes that better than simply not
adding a field: every field on a pydantic model with `extra="forbid"` is
additive-compatible by construction (a new `Optional` field with a `None`
default parses every existing `master.json` unchanged), so there is nothing to
design now that a later task could not add without migrating anything. Adding
a speculative, permanently-`None` field today would be exactly the kind of
schema a task cannot fully own — T46 does, later.

**`residence`, unlike the excluded five, belongs here.** Step 1's own protocol
is explicit that establishing where the candidate lives is part of *this*
step ("decides currency, work authorisation, which borders are commutable"),
while being equally explicit that it is a **claim**, not yet a fact: `location`
in `constraints.json` (`jobsearch.candidate`, T24) is where a *confirmed*
residence lives, resolved by T41's engine at step 2. So `CVMaster.residence_claim`
exists and is provenanced exactly like everything else here; nothing in this
module writes to `constraints.json`, and nothing here promotes a claim to a
fact — that promotion is step 2's, `jobsearch.candidate`/`jobsearch.
constraints_step`'s, work.

## Design for templates without building them (§2.7)

The brief's instruction is "design so the store can feed templates rather
than encode one layout" — met by *not* building one. `CVMaster` is a flat set
of typed sections (`experience`, `education`, `skills`, `certifications`,
`languages`, `episodes`, plus `raw_blocks` for content nothing has classified
yet) with no page, ordering, or rendering concept anywhere in the schema. A
template (T45/T46, not built here) selects and arranges sections; nothing here
commits to how.

## Build-from-nothing reaches the same contract, not a degraded one

`add_conversation_entry`/`set_conversation_scalar` write the *same* section
models (`Experience`, `Education`, ...) that a classified document import
would, differing only in which `Provenance` variant they attach —
`ConversationTurn` instead of `DocumentSpan`. `CVMaster` itself has no
`origin` field: nothing about the store's shape depends on how it was built,
which is what makes `test_a_candidate_with_no_cv_can_still_reach_a_first_version`
a meaningful equality, not a coincidence. `status/spec-v2-steps.md` step 1's
own outputs line — "`profile/evidence.jsonl` rows for everything said" — is
honoured directly: every conversation-sourced entry appends a real row through
`jobsearch.profile.EvidenceLog` (T6, unmodified — this module composes it
exactly the way `jobsearch.profile_capture`, T28, already does), and
`ConversationTurn.evidence_id` names that row. `_resolves` checks the row
really exists in the log, not merely that an id-shaped string was supplied.

Document-sourced entries do **not** also write an evidence row: the text
already has a first-class, checkable home (`cv/source/<doc-id>.txt` plus a
span), and duplicating it into `evidence.jsonl` would copy a document's
content into a second store for no reader that needs it there — `jobsearch.
profile.Source` already reserves `"cv_document"` for a future module that
does want that (linking imported CV content into `stories.jsonl`/`traits.json`
the way an interview answer already does); this task's brief says `profile.py`
needs no change, and building that linkage is exactly the kind of extraction
work (T8/T27's territory) the scope change carves out — named here as a
limitation, not smuggled in.

## What "never sent verbatim" can mean at this layer

§2.6 says the store is "never sent anywhere as-is". This module generates no
outbound document (that is T45/T46 — Intake produces no document at all, per
`status/spec-v2-steps.md` step 1: "No document is produced here — no PDF, no
DOCX"), so there is no send path here to test directly — asserting one would
be exactly the "trivially true" mistake the payload warns against. What
**is** real, and enforceable, at this layer: this module's own gate evidence
file (`status/evidence/S4.json`) is a routinely-shared artefact — committed to
git, printed to CI logs, and (this task is living proof) pasted into
conversation with an assistant that has no business reading a candidate's
CV content. `test_the_store_is_never_sent_verbatim` builds a store carrying a
distinctive marker string standing in for something a candidate actually said
— a failure, a number, a lesson — and asserts that string never reaches the
measured evidence payload: `measure_provenance`/`probe_intake` report only
field *paths* (`"experience[1]"`) and boolean/count violations, never a
field's `text`. That is the strongest guarantee this module can make on its
own; full "never sent to a model or an employer" enforcement belongs where
documents are actually generated, and is named here rather than faked.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal
from xml.etree import ElementTree
from xml.sax.saxutils import escape as _xml_escape

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jobsearch.candidate import LANGUAGE_PATTERN, Level
from jobsearch.identity import IdentityError, ProfileStore, create_profile
from jobsearch.profile import EVIDENCE_ID, EvidenceLog

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S4.json"

_DOCX_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DOC_ID = re.compile(r"^doc-(\d{6,})$")
_DOC_ID_WIDTH = 6

# Below this many fields exercised, a clean score is "1.0 over nothing" — the
# same floor T6/T28/D-6 each set for their own probes.
MINIMUM_FIELDS_MEASURED = 5
MINIMUM_CHECKS = 14


class CVStoreError(Exception):
    """`cv/master.json` (or a document import) breaks this module's contract."""


class ExtractorUnavailable(Exception):
    """A document format needs an optional extractor this environment lacks."""


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this schema — see `jobsearch.candidate.Strict`."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# provenance — a claim names a document span, or the turn it was said in


class DocumentSpan(Strict):
    """Character offsets into `cv/source/<source_file>.txt` — see the module docstring."""

    kind: Literal["document_span"] = "document_span"
    source_file: str = Field(pattern=DOC_ID.pattern)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ConversationTurn(Strict):
    """One row of `profile/evidence.jsonl` — the turn this claim was said in."""

    kind: Literal["conversation_turn"] = "conversation_turn"
    evidence_id: str = Field(pattern=EVIDENCE_ID.pattern)


Provenance = Annotated[DocumentSpan | ConversationTurn, Field(discriminator="kind")]


class SourcedEntry(Strict):
    """A base every section entry shares: where it came from, if anywhere.

    `provenance` has no `min_length` — see the module docstring's gate
    section for why an empty tuple must be a *loadable, measured* state
    rather than a validation error.
    """

    provenance: tuple[Provenance, ...] = ()


class SourcedText(SourcedEntry):
    """One scalar claim (`headline`, `residence_claim`) plus its provenance."""

    text: str = Field(min_length=1)


class RawBlock(SourcedEntry):
    """One paragraph of an imported document, verbatim, not yet classified.

    `import_document` writes only these — see the module docstring's
    "reaches the same contract" section for why classifying a block into
    `Experience`/`Education`/... is left to whichever conversation reads it
    back (the `step-01-intake` skill, or a future task), not guessed at here.
    """

    text: str = Field(min_length=1)


class Experience(SourcedEntry):
    title: str = Field(min_length=1)
    organisation: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None
    description: str = ""


class Education(SourcedEntry):
    qualification: str = Field(min_length=1)
    institution: str = Field(min_length=1)
    completed: str | None = None


class Skill(SourcedEntry):
    name: str = Field(min_length=1)
    level: Literal["basic", "working", "strong", "expert"] | None = None


class Certification(SourcedEntry):
    name: str = Field(min_length=1)
    issuer: str | None = None
    obtained: str | None = None


class LanguageEntry(SourcedEntry):
    """Reuses T24's own vocabulary (`jobsearch.candidate.Level`) rather than
    inventing a second one — the same "one profile cannot reach another kind
    of drift" avoidance `jobsearch.profile`'s module docstring calls out for
    directory reuse, applied here to a shared enum instead."""

    language: str = Field(pattern=LANGUAGE_PATTERN)
    level: Level


class Episode(SourcedEntry):
    """Everything a CV omits (§2.6): a failure, a lesson, a number, context."""

    kind: Literal["achievement", "failure", "lesson", "context", "number"]
    text: str = Field(min_length=1)


class CVMaster(Strict):
    """`cv/master.json` — the on-disk contract this task pins.

    No `origin` field: see the module docstring's "reaches the same contract"
    section for why the shape is identical regardless of how it was built.
    """

    schema_version: int = 1
    residence_claim: SourcedText | None = None
    headline: SourcedText | None = None
    raw_blocks: tuple[RawBlock, ...] = ()
    experience: tuple[Experience, ...] = ()
    education: tuple[Education, ...] = ()
    skills: tuple[Skill, ...] = ()
    certifications: tuple[Certification, ...] = ()
    languages: tuple[LanguageEntry, ...] = ()
    episodes: tuple[Episode, ...] = ()


SECTION_MODELS: dict[str, type[SourcedEntry]] = {
    "experience": Experience,
    "education": Education,
    "skills": Skill,
    "certifications": Certification,
    "languages": LanguageEntry,
    "episodes": Episode,
}
SCALAR_FIELDS: tuple[str, ...] = ("headline", "residence_claim")
_ALL_LIST_SECTIONS: tuple[str, ...] = (*SECTION_MODELS, "raw_blocks")


# ---------------------------------------------------------------------------
# load / write — loaders raise, measurement functions report


def load_master(store: ProfileStore) -> CVMaster:
    """The store as it stands, or an empty one if intake has not started.

    A missing file is a normal, expected state (nobody has begun intake yet)
    and is not an error; a file that exists but does not parse as `CVMaster`
    is structural corruption and raises — the "loaders raise" half of the
    module docstring's rule. A field merely lacking provenance is *not*
    corruption (see `SourcedEntry`) and loads without complaint; only
    `measure_provenance` has an opinion about that.
    """
    if not store.exists("cv", "master.json"):
        return CVMaster()
    try:
        return CVMaster.model_validate(store.read_json("cv", "master.json"))
    except (ValidationError, IdentityError) as exc:
        raise CVStoreError(f"{store.handle}/cv/master.json is not a valid CV store: {exc}") from exc


def write_master(store: ProfileStore, master: CVMaster) -> Path:
    return store.write_json(master.model_dump(mode="json"), "cv", "master.json")


# ---------------------------------------------------------------------------
# document import


def next_doc_id(store: ProfileStore) -> str:
    """`doc-000001`, `doc-000002`, ... — mirrors `EvidenceLog.next_id`'s own
    "derive from what's highest on disk" reasoning, for the same reason: a
    hand-repaired or partially-synced `cv/source/` must not mint an id that
    collides with one already there."""
    highest = 0
    source_dir = store.path("cv", "source")
    if source_dir.is_dir():
        for entry in source_dir.iterdir():
            match = DOC_ID.match(entry.stem)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"doc-{highest + 1:0{_DOC_ID_WIDTH}d}"


def _extract_docx_text(path: Path) -> str:
    """Every paragraph's text, joined by newlines — stdlib only.

    A `.docx` is a zip of XML parts; `word/document.xml` holds the body, one
    `<w:p>` per paragraph, text split across `<w:t>` runs wherever Word
    happened to break formatting. Concatenating every run inside a paragraph
    reassembles the paragraph's text exactly; nothing here interprets styles,
    tables, or headers/footers — a limitation named rather than hidden.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise CVStoreError(f"{path} is not a readable .docx file: {exc}") from exc
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise CVStoreError(f"{path}'s word/document.xml is not well-formed XML: {exc}") from exc
    paragraphs = [
        "".join(run.text or "" for run in paragraph.iter(f"{{{_DOCX_W_NS}}}t"))
        for paragraph in root.iter(f"{{{_DOCX_W_NS}}}p")
    ]
    return "\n".join(paragraphs)


def _extract_pdf_text(path: Path) -> str:
    """Real PDF text extraction, gated behind the optional `cv` extra.

    Imported here, inside the function, never at module load — see the
    module docstring's dependency-decision section for why that is what
    keeps `import jobsearch.cv_store` extras-free.
    """
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ExtractorUnavailable(
            "PDF import needs the optional 'cv' extra (pypdf) — install it with "
            "`uv sync --extra cv`. This environment (like every gate this project "
            "runs) does not have it, by design; use a .docx or build the CV by "
            "conversation instead."
        ) from exc
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # pragma: no cover - pypdf's own error surface, never exercised in CI
        raise CVStoreError(f"{path} could not be read as a PDF: {exc}") from exc


def _nonblank_spans(text: str) -> list[tuple[int, int, str]]:
    """`(start, end, content)` for every non-blank line of `text`, as
    character offsets into `text` itself — what `DocumentSpan` cites."""
    spans: list[tuple[int, int, str]] = []
    position = 0
    for line in text.split("\n"):
        end = position + len(line)
        if line.strip():
            spans.append((position, end, line))
        position = end + 1  # the "\n" this split consumed
    return spans


@dataclass(frozen=True)
class ImportResult:
    """What happened importing one document — never an exception for an
    ordinary outcome (missing extractor, unsupported format, empty
    extraction); see the module docstring."""

    status: Literal["imported", "unavailable", "unsupported", "empty", "corrupt"]
    doc_id: str | None
    blocks_added: int
    detail: str


SUPPORTED_SUFFIXES = (".docx", ".pdf")


def import_document(store: ProfileStore, path: Path) -> ImportResult:
    """Extract `path`'s text, store it under `cv/source/`, and append one
    `RawBlock` per non-blank paragraph to `cv/master.json`.

    Never raises for an ordinary candidate-facing outcome — a missing
    extractor, an unsupported extension, a document with no readable text —
    each comes back as a structured `ImportResult` instead. A caller mistake
    (`path` does not exist) is the one thing this still lets surface as a
    `FileNotFoundError` from `Path.read_bytes`/`zipfile`, because that is not
    a thing to show a candidate — it is this module being called wrongly.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return ImportResult(
            status="unsupported",
            doc_id=None,
            blocks_added=0,
            detail=f"{suffix or '(no extension)'} is not a supported CV format — "
            f"supply one of {', '.join(SUPPORTED_SUFFIXES)}",
        )
    try:
        text = _extract_docx_text(path) if suffix == ".docx" else _extract_pdf_text(path)
    except ExtractorUnavailable as exc:
        return ImportResult(status="unavailable", doc_id=None, blocks_added=0, detail=str(exc))
    except CVStoreError as exc:
        return ImportResult(status="corrupt", doc_id=None, blocks_added=0, detail=str(exc))

    spans = _nonblank_spans(text)
    if not spans:
        return ImportResult(
            status="empty",
            doc_id=None,
            blocks_added=0,
            detail="the document extracted no readable text",
        )

    doc_id = next_doc_id(store)
    store.write_text(text, "cv", "source", f"{doc_id}.txt")

    blocks = tuple(
        RawBlock(text=content, provenance=(DocumentSpan(source_file=doc_id, start=start, end=end),))
        for start, end, content in spans
    )
    master = load_master(store)
    master = master.model_copy(update={"raw_blocks": (*master.raw_blocks, *blocks)})
    write_master(store, master)
    return ImportResult(
        status="imported",
        doc_id=doc_id,
        blocks_added=len(blocks),
        detail=f"{len(blocks)} paragraph(s) imported from {path.name} as {doc_id}",
    )


# ---------------------------------------------------------------------------
# adding sourced entries — one code path per (section kind, provenance kind)


def _with_list_entry(master: CVMaster, section: str, entry: SourcedEntry) -> CVMaster:
    if section not in SECTION_MODELS:
        raise CVStoreError(
            f"{section!r} is not a CVMaster section — one of {sorted(SECTION_MODELS)}"
        )
    current: tuple[SourcedEntry, ...] = getattr(master, section)
    return master.model_copy(update={section: (*current, entry)})


def add_document_entry(
    master: CVMaster,
    section: str,
    fields: dict[str, Any],
    *,
    doc_id: str,
    start: int,
    end: int,
) -> CVMaster:
    """Classify one span of an already-imported document into a typed section
    entry — the step that turns a `RawBlock` (or the text around it) into an
    `Experience`/`Education`/... row, with the same span cited either way."""
    model = SECTION_MODELS.get(section)
    if model is None:
        raise CVStoreError(
            f"{section!r} is not a CVMaster section — one of {sorted(SECTION_MODELS)}"
        )
    span = DocumentSpan(source_file=doc_id, start=start, end=end)
    entry = model(**fields, provenance=(span,))
    return _with_list_entry(master, section, entry)


def add_conversation_entry(
    store: ProfileStore,
    master: CVMaster,
    section: str,
    fields: dict[str, Any],
    *,
    said: str,
    recorded_at: str,
) -> CVMaster:
    """Append one turn to `profile/evidence.jsonl` (T6, unmodified) and add a
    typed section entry citing it — the build-from-nothing half of this
    module, and step 1's own "profile/evidence.jsonl rows for everything
    said" (`status/spec-v2-steps.md`)."""
    model = SECTION_MODELS.get(section)
    if model is None:
        raise CVStoreError(
            f"{section!r} is not a CVMaster section — one of {sorted(SECTION_MODELS)}"
        )
    stripped = said.strip()
    if not stripped:
        raise CVStoreError(
            "add_conversation_entry needs non-blank `said` text to provenance the entry"
        )
    row = EvidenceLog(store).append(
        recorded_at=recorded_at,
        step="intake",
        kind="statement",
        text=stripped,
        source="conversation",
    )
    entry = model(**fields, provenance=(ConversationTurn(evidence_id=row.id),))
    return _with_list_entry(master, section, entry)


def set_document_scalar(
    master: CVMaster, field: str, *, text: str, doc_id: str, start: int, end: int
) -> CVMaster:
    if field not in SCALAR_FIELDS:
        raise CVStoreError(f"{field!r} is not a CVMaster scalar field — one of {SCALAR_FIELDS}")
    span = DocumentSpan(source_file=doc_id, start=start, end=end)
    value = SourcedText(text=text, provenance=(span,))
    return master.model_copy(update={field: value})


def set_conversation_scalar(
    store: ProfileStore, master: CVMaster, field: str, *, said: str, recorded_at: str
) -> CVMaster:
    if field not in SCALAR_FIELDS:
        raise CVStoreError(f"{field!r} is not a CVMaster scalar field — one of {SCALAR_FIELDS}")
    stripped = said.strip()
    if not stripped:
        raise CVStoreError(
            "set_conversation_scalar needs non-blank `said` text to provenance the field"
        )
    row = EvidenceLog(store).append(
        recorded_at=recorded_at,
        step="intake",
        kind="statement",
        text=stripped,
        source="conversation",
    )
    value = SourcedText(text=stripped, provenance=(ConversationTurn(evidence_id=row.id),))
    return master.model_copy(update={field: value})


# ---------------------------------------------------------------------------
# the gate: intake_field_provenance


def _named_fields(master: CVMaster) -> list[tuple[str, SourcedEntry]]:
    """Every populated field in `master`, named the way a violation reports
    it — a scalar by its field name, a list entry by `section[index]`."""
    named: list[tuple[str, SourcedEntry]] = []
    for field in SCALAR_FIELDS:
        value = getattr(master, field)
        if value is not None:
            named.append((field, value))
    for section in _ALL_LIST_SECTIONS:
        for index, entry in enumerate(getattr(master, section)):
            named.append((f"{section}[{index}]", entry))
    return named


def _resolves(store: ProfileStore, item: DocumentSpan | ConversationTurn) -> str | None:
    """`None` if `item` genuinely resolves against `store`; otherwise why not.

    A `DocumentSpan` resolves only if its source text exists and the span is
    within bounds; a `ConversationTurn` resolves only if its id is a row that
    is really in `profile/evidence.jsonl` — existence is checked against the
    log itself (`EvidenceLog.rows`), never merely against the id's shape.
    """
    if isinstance(item, DocumentSpan):
        parts = ("cv", "source", f"{item.source_file}.txt")
        if not store.exists(*parts):
            return f"document {item.source_file!r} has no stored source text"
        length = len(store.read_text(*parts))
        if not (0 <= item.start < item.end <= length):
            return (
                f"span [{item.start}, {item.end}) is out of bounds for "
                f"{item.source_file!r} ({length} chars)"
            )
        return None
    known_ids = {row.id for row in EvidenceLog(store).rows()}
    if item.evidence_id not in known_ids:
        return f"evidence row {item.evidence_id!r} is not in this profile's evidence.jsonl"
    return None


@dataclass(frozen=True)
class ProvenanceResult:
    coverage: float
    fields_measured: int
    violations: tuple[str, ...]


def measure_provenance(store: ProfileStore, master: CVMaster) -> ProvenanceResult:
    """`intake_field_provenance` over one store: the fraction of its populated
    fields whose provenance is present *and resolves*.

    An empty store (no fields at all) reports `(0.0, 0, ())` — matching every
    other measure in this codebase (`jobsearch.question_bank.
    dimension_coverage`, `jobsearch.elicit_extract.story_dimension_linkage`):
    nothing to measure is not the same as full provenance, and the module
    docstring's gate section is explicit that a clean score over nothing must
    not pass.
    """
    named = _named_fields(master)
    violations: list[str] = []
    for name, entry in named:
        if not entry.provenance:
            violations.append(f"{name}: no provenance recorded")
            continue
        reasons = [
            reason for item in entry.provenance if (reason := _resolves(store, item)) is not None
        ]
        if reasons:
            violations.append(f"{name}: {'; '.join(reasons)}")
    measured = len(named)
    coverage = (measured - len(violations)) / measured if measured else 0.0
    return ProvenanceResult(
        coverage=coverage, fields_measured=measured, violations=tuple(violations)
    )


# ---------------------------------------------------------------------------
# fixtures + the adversarial probe


def _build_minimal_docx(paragraphs: Sequence[str]) -> bytes:
    """A syntactically valid, minimal `.docx`, built with stdlib `zipfile`
    only — proof `_extract_docx_text` needs no third-party package to read
    one, by needing none to write one either."""
    import io

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{_xml_escape(paragraph)}</w:t></w:r></w:p>'
        for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


# A distinctive string standing in for something a candidate actually said —
# `test_the_store_is_never_sent_verbatim` proves it never reaches the gate's
# own evidence payload. See the module docstring's last section.
_LEAK_PROBE_MARKER = "Zylofoundry Q9 supply-chain rescue, 2019"


def probe_intake(root: Path) -> dict[str, Any]:
    """Run every scenario the payload and module docstring name, in a fresh
    tree under `root`. Backs `write_evidence`; also driven directly by tests
    the same way `jobsearch.profile_capture.probe_capture` is."""
    import tempfile

    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    now = "2026-08-18T09:00:00Z"

    # --- document import: real, stdlib DOCX, no extras ----------------------
    doc_identity = create_profile(root, "Probe CV Document", handle="probe-cv-document")
    doc_store = ProfileStore(root, doc_identity.handle)
    docx_bytes = _build_minimal_docx(
        [
            "Jordi Puig — Backend Engineer",
            "",
            "Led the migration of a 40-service platform off a monolith, cutting "
            "deploy time from 45 minutes to 6.",
            "Missed a launch date once by two weeks from under-scoping a data "
            "migration; now estimates carry a 30% pad.",
        ]
    )
    with tempfile.TemporaryDirectory(prefix="jobsearch-s4-fixture-") as fixture_dir:
        docx_path = Path(fixture_dir) / "cv.docx"
        docx_path.write_bytes(docx_bytes)
        import_result = import_document(doc_store, docx_path)
        check(import_result.status == "imported", f"DOCX import did not succeed: {import_result}")
        check(
            import_result.blocks_added == 3,
            f"expected 3 non-blank paragraphs imported, got {import_result}",
        )

        pdf_path = Path(fixture_dir) / "cv.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%not a real pdf, only the extractor decides\n")
        pdf_result = import_document(doc_store, pdf_path)
        check(
            pdf_result.status == "unavailable",
            f"PDF import should report 'unavailable' with no extras installed, got {pdf_result}",
        )
        check(
            bool(pdf_result.detail),
            "an 'unavailable' import gave no reported detail to show a candidate",
        )

    doc_master = load_master(doc_store)
    check(len(doc_master.raw_blocks) == 3, "imported blocks were not persisted to master.json")
    check(
        doc_master.raw_blocks == load_master(doc_store).raw_blocks,
        "the failed PDF import silently changed a store a successful DOCX import already wrote",
    )

    source_text = doc_store.read_text("cv", "source", f"{import_result.doc_id}.txt")
    start = source_text.index("Led the migration")
    end = start + len(
        "Led the migration of a 40-service platform off a monolith, cutting "
        "deploy time from 45 minutes to 6."
    )
    doc_master = add_document_entry(
        doc_master,
        "experience",
        {
            "title": "Backend Engineer",
            "organisation": "(unspecified — see raw_blocks[0])",
            "description": source_text[start:end],
        },
        doc_id=import_result.doc_id or "",
        start=start,
        end=end,
    )
    write_master(doc_store, doc_master)
    doc_result = measure_provenance(doc_store, doc_master)
    check(
        doc_result.coverage == 1.0,
        f"document-import store did not reach full provenance: {doc_result}",
    )

    # --- build from nothing: a conversation, no document at all -------------
    nothing_identity = create_profile(root, "Probe CV Nothing", handle="probe-cv-nothing")
    nothing_store = ProfileStore(root, nothing_identity.handle)
    fresh_master = load_master(nothing_store)
    check(fresh_master == CVMaster(), "a fresh profile did not start with an empty store")
    empty_result = measure_provenance(nothing_store, fresh_master)
    check(
        empty_result.coverage == 0.0 and empty_result.fields_measured == 0,
        f"an empty store reported nonzero coverage over nothing measured: {empty_result}",
    )

    nothing_master = set_conversation_scalar(
        nothing_store,
        fresh_master,
        "residence_claim",
        said="I live in Girona, and have done for about six years.",
        recorded_at=now,
    )
    nothing_master = add_conversation_entry(
        nothing_store,
        nothing_master,
        "experience",
        {
            "title": "Warehouse Supervisor",
            "organisation": "Cintra Logistics",
            "start": "2021",
            "end": None,
            "description": "Ran the night shift; put in a new pick-and-pack sequence that "
            "cut short-picks by half.",
        },
        said="Most recently I've supervised the night shift at Cintra Logistics, since 2021 — "
        "still there. I put in a new pick-and-pack sequence that cut our short-picks by half.",
        recorded_at=now,
    )
    nothing_master = add_conversation_entry(
        nothing_store,
        nothing_master,
        "episodes",
        {
            "kind": "lesson",
            "text": f"The {_LEAK_PROBE_MARKER} taught me to confirm upstream before promising.",
        },
        said=f"The {_LEAK_PROBE_MARKER} cost us a client because I promised a date before "
        "checking with our supplier. I confirm upstream before promising a date now.",
        recorded_at=now,
    )
    write_master(nothing_store, nothing_master)
    nothing_result = measure_provenance(nothing_store, nothing_master)
    check(
        nothing_result.coverage == 1.0,
        f"build-from-nothing store did not reach full provenance: {nothing_result}",
    )
    check(
        nothing_result.fields_measured >= 2,
        "the build-from-nothing scenario exercised too few fields to mean anything",
    )
    reloaded_nothing_master = load_master(nothing_store)
    check(
        reloaded_nothing_master == nothing_master,
        "the build-from-nothing store did not round-trip through the same on-disk "
        "contract a parsed document uses — write_master/load_master disagree with themselves",
    )
    check(
        isinstance(nothing_master.experience[0], Experience)
        and isinstance(doc_master.experience[0], Experience),
        "a candidate with no CV reached a different section type than a parsed one",
    )
    evidence_ids = {row.id for row in EvidenceLog(nothing_store).rows()}
    check(
        len(evidence_ids) == 3,
        f"conversation entries did not each write a profile/evidence.jsonl row: {evidence_ids}",
    )

    # --- required verification: strip one field's provenance, watch it fall -
    stripped_first = nothing_master.experience[0].model_copy(update={"provenance": ()})
    broken_master = nothing_master.model_copy(
        update={"experience": (stripped_first, *nothing_master.experience[1:])}
    )
    broken_result = measure_provenance(nothing_store, broken_master)
    check(
        broken_result.coverage < 1.0,
        "stripping one field's provenance did not move intake_field_provenance",
    )
    check(
        any("no provenance recorded" in violation for violation in broken_result.violations),
        f"the stripped field was not named in the violations: {broken_result.violations}",
    )
    check(
        broken_result.fields_measured == nothing_result.fields_measured,
        "the denominator changed when only one field's provenance was stripped",
    )

    combined_measured = doc_result.fields_measured + nothing_result.fields_measured
    combined_violations = doc_result.violations + nothing_result.violations
    combined_coverage = (
        (combined_measured - len(combined_violations)) / combined_measured
        if combined_measured
        else 0.0
    )

    outcome = {
        "intake_field_provenance": combined_coverage,
        "fields_measured": combined_measured,
        "document_import": {
            "coverage": doc_result.coverage,
            "fields_measured": doc_result.fields_measured,
            "violations": list(doc_result.violations),
            "import_result": {
                "status": import_result.status,
                "blocks_added": import_result.blocks_added,
            },
            "pdf_without_extras": {"status": pdf_result.status},
        },
        "build_from_nothing": {
            "coverage": nothing_result.coverage,
            "fields_measured": nothing_result.fields_measured,
            "violations": list(nothing_result.violations),
        },
        "deliberate_break_demonstration": {
            "coverage_before_break": nothing_result.coverage,
            "coverage_after_break": broken_result.coverage,
            "violations_after_break": list(broken_result.violations),
        },
        "checks_run": checks,
        "failures": failures,
    }

    # --- never sent verbatim: the marker never reaches this payload ---------
    leaked = _LEAK_PROBE_MARKER in json.dumps(outcome, ensure_ascii=False)
    check(not leaked, "the store's own content leaked into the gate's evidence payload")

    return outcome


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `intake_field_provenance` in a throwaway tree and record it."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-s4-") as tmp:
        measured = probe_intake(Path(tmp) / "profiles")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.cv_store [--check] [--write-evidence [PATH]]` -> S4's gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/S4.json)",
    )
    args = parser.parse_args(argv[1:])

    if args.check:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="jobsearch-s4-") as tmp:
            measured = probe_intake(Path(tmp) / "profiles")
    else:
        measured = write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))

    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} checks ran (floor {MINIMUM_CHECKS}) — a clean "
            "score without exercising the scenarios is not a measurement",
            file=sys.stderr,
        )
        return 3
    if measured["fields_measured"] < MINIMUM_FIELDS_MEASURED:
        print(
            f"only {measured['fields_measured']} fields were measured (floor "
            f"{MINIMUM_FIELDS_MEASURED}) — full provenance over almost nothing is no measurement",
            file=sys.stderr,
        )
        return 3

    violations = list(measured["failures"])
    if measured["intake_field_provenance"] != 1.0:
        violations.append(
            f"intake_field_provenance = {measured['intake_field_provenance']} (want 1.0)"
        )
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
