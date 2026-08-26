"""T80 — the ATS text-layer contract, asserted over the document text.

The generated CV is the one artefact in this system that reaches a stranger,
and nothing checked that a machine could read it. An applicant-tracking
system parses the **text layer**: contact details carried only by an icon
glyph or a hyperlink are invisible to it.

**Renderer-independent, deliberately.** No PDF renderer exists yet (T45
produces Markdown; a PDF renderer is deferred until a live session needs
one). `text_layer` reads a `.md` file as plain text and shells out to
`pdftotext -layout -enc UTF-8` only for a `.pdf` — the same assertions below
run unchanged over either, so writing the contract now costs nothing extra
the day a renderer lands. `-enc UTF-8` matters here more than upstream: Xpdf
builds default to Latin-1, and this candidate's documents carry Catalan and
Spanish accents.

**Scope is the generated CV, not the letter.** `cv.md` (or its `cv.pdf`
sibling, once one exists) is what an ATS ingests; a cover letter is read by a
person. `_cv_documents` looks for `cv.md` specifically.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). T83
records the attribution; it does not belong here.

## What a document is checked for

* **A required field is present as literal text.** Today that is a contact
  email — `REQUIRED_TEXT_LAYER_FIELDS` is a closed tuple so a new requirement
  is a diff a reviewer sees, not a silent addition. Presence is a pattern
  match over the whole text, not a lookup against a specific candidate value:
  the check is renderer-independent, and the value that should appear is
  whatever the document was built with.
* **The text layer is not corrupted.** No `�` (a glyph the extractor
  could not decode) and no `(cid:NNN)` (a glyph the extractor could not map
  to a character at all) — both are what a subset-embedded font's text layer
  looks like to a parser that cannot read the font's private encoding, and
  both mean the words around the marker are unreadable even though something
  rendered on screen.

## A zero count must prove the mechanism ran

`documents_missing_a_required_text_layer_field == 0` is also what an empty
input set produces. `gate_status` names the difference: `"unmeasured"`
whenever `documents_missing_a_required_text_layer_field_evaluated` is `0`,
`"measured"` otherwise — the same third outcome D-2 gives
`extraction_macro_f1`, read by `gate_evidence.py`'s `status-key` before it
reads the metric.

## T81 — keyword coverage against the posting, in four statuses

The second gate this module owns. Every keyword a posting names is classified
into exactly one of `covered` / `synonym-only` / `missing (have it)` /
`missing (gap)` against one generated application (`cv.md` and `letter.md`
together — T81 asks what the application says, not what an ATS parses, so it
is not scoped to the CV alone the way T80 is).

* `covered` — the keyword itself is present, literally, somewhere in the
  application.
* `synonym-only` — the keyword itself is not there, but a spelling
  `_SYNONYMS` records as the same thing is (`PostgreSQL` for a posting that
  says `Postgres`). Closed on purpose, like `REQUIRED_TEXT_LAYER_FIELDS`
  above: two spellings of the same technology are not evidence of anything,
  and only a mapping a reviewer can see should ever decide that.
* `missing (have it)` — `_holds` finds the keyword (or a synonym of it)
  somewhere in the store, but neither made it into the application. This is
  the manifest's own `omissions` surfacing here: a `_SELECTED`-section entry
  the store holds and generation left out. A document bug, never the
  candidate's to answer for.
* `missing (gap)` — the store holds nothing that matches, under any spelling
  this module knows. A fact about the candidate, and never something to
  quietly write in.

`classify_keyword` checks literal presence, then synonym presence, then the
store, in that order: `_holds` alone cannot tell "the document phrased this
differently" from "the document left this out", which is the whole
distinction the synonym check exists to make, so the store is consulted last.

Maps onto T45's generation nearly for free: `_holds` and `_mentions` are T45's
own. Every entry in an `_ALWAYS` section (experience, education, headline,
languages) is rendered unconditionally, whatever the advert says, so it can
never be the store holding something the document leaves out — a keyword
`missing (have it)` can only ever come from a `_SELECTED`-section entry
(skills, certifications), the one kind of entry T45's own selection can omit.

**A zero count must prove the mechanism ran, here too.**
`posting_keywords_left_unclassified == 0` is what zero posting keywords
produces as well as a correctly classified nonzero set — `classify_keyword`
is total over the four statuses by construction, so the count that actually
carries information is `posting_keywords_left_unclassified_evaluated`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from integral.cv_store import CVMaster, SourcedText, write_master
from integral.generate import _FIXTURE_ASKS, DEFAULT_FIXTURE_MASTER, _holds, _mentions, generate
from integral.identity import ProfileStore, create_profile

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T80.json"

# Closed on purpose — see the module docstring. A new required field is a diff
# a reviewer sees, not a value quietly added to a set somewhere.
REQUIRED_TEXT_LAYER_FIELDS: tuple[str, ...] = ("contact_email",)

# Whole-token, not a bare substring, so a fixture that mentions "@example" in
# passing is not itself proof of anything — the pattern has to look like an
# address.
_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "contact_email": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+\.[A-Za-z]{2,}(?![\w.+-])"),
}

# What a broken text layer looks like to a parser, not to a human looking at
# the rendered page: a replacement character where a glyph could not be
# decoded, or a raw character-id fallback where it could not even be mapped.
_CORRUPTION_RE = re.compile(r"�|\(cid:\d+\)")

# The email this module's own fixture generation embeds into the fixture
# candidate's headline — a claimable field, so it is rendered onto the CV by
# the same path any candidate's own contact line would be.
_FIXTURE_EMAIL = "gate.fixture@example.invalid"


class ATSError(Exception):
    """The text layer of a document could not be read."""


def text_layer(path: Path) -> str:
    """The text an ATS would see for `path` — renderer-independent.

    A `.pdf` is read through `pdftotext -layout -enc UTF-8`, the tool an ATS
    itself is modelled on here; anything else (today, always `.md`) is read
    directly, because Markdown *is* its own text layer.
    """
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8")
    try:
        completed = subprocess.run(  # fixed argv, no shell
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ATSError(f"pdftotext is not available to read {path}") from exc
    if completed.returncode != 0:
        raise ATSError(f"pdftotext failed on {path}: {completed.stderr.strip()}")
    return completed.stdout


def check_document(path: Path) -> dict[str, Any]:
    """One document's violations of the text-layer contract, `path` read fresh."""
    text = text_layer(path)
    missing_fields = tuple(
        field for field in REQUIRED_TEXT_LAYER_FIELDS if not _FIELD_PATTERNS[field].search(text)
    )
    corruption_markers = tuple(sorted(set(_CORRUPTION_RE.findall(text))))

    violations = [f"missing required field: {field}" for field in missing_fields]
    violations += [f"corrupted text layer: {marker!r}" for marker in corruption_markers]

    return {
        "path": str(path),
        "missing_fields": list(missing_fields),
        "corruption_markers": list(corruption_markers),
        "violations": violations,
    }


def _cv_documents(store: ProfileStore, offer_id: str, version: int) -> Path:
    """The document an ATS receives for one generated application.

    A `cv.pdf` sibling — once a renderer exists to write one — is what
    actually reaches an employer's system and is preferred over the `.md`
    it was built from; nothing in this task writes one, so today this is
    always `cv.md`.
    """
    where = store.path("cv", "generated", offer_id, f"v{version}")
    pdf = where / "cv.pdf"
    return pdf if pdf.exists() else where / "cv.md"


def audit_documents(paths: list[Path]) -> dict[str, Any]:
    """The gate, over an explicit list of documents.

    Takes paths rather than discovering them, because the two callers need
    different sets: `measure` generates one document per advert in the real
    corpus, and a test wants exactly the one or two it just built.
    """
    checks = [check_document(path) for path in paths]
    violating = [check for check in checks if check["violations"]]
    # The gate's key names ONE of the two contract breaches, so it must count
    # only that one. `violations` is the union of missing fields and corruption
    # markers, so counting it here reported a document whose fields are all
    # present but whose text layer is mojibake as "missing a required field" —
    # a true failure under a false name. Corruption still fails the gate, via
    # the CLI exit code in the task's own ```bash``` block, which is why the
    # total below exists.
    missing_required_field = [check for check in checks if check["missing_fields"]]
    evaluated = len(checks)

    return {
        "documents_missing_a_required_text_layer_field": len(missing_required_field),
        "documents_missing_a_required_text_layer_field_evaluated": evaluated,
        "documents_with_text_layer_violations": len(violating),
        # Same count, the addendum's own name for it — see the module
        # docstring's "a zero count must prove the mechanism ran" section.
        "documents_checked": evaluated,
        "gate_status": "unmeasured" if evaluated == 0 else "measured",
        "violations": sorted(
            f"{check['path']}: {reason}" for check in violating for reason in check["violations"]
        ),
    }


# ---------------------------------------------------------------------------
# the gate — measured over the real corpus, against a stated fixture candidate


def measure(
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
    store_path: Path | None = None,
) -> dict[str, Any]:
    """`documents_missing_a_required_text_layer_field` over every advert in the corpus.

    Real advert text, a stated fixture candidate — there is no person in this
    repository and there must not be one. The fixture's headline carries a
    literal contact email so the documents this measurement generates are the
    positive case the gate is meant to certify; `tests/test_ats.py` is what
    proves the check would notice a document that does not.
    """
    from integral.harness import DEFAULT_STORE_PATH, load_store

    committed = CVMaster.model_validate_json(fixture_master.read_text(encoding="utf-8"))
    base_headline = committed.headline.text if committed.headline else "Candidate"
    master = committed.model_copy(
        update={"headline": SourcedText(text=f"{base_headline} — {_FIXTURE_EMAIL}")}
    )
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    documents: list[Path] = []
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        for ad in ads:
            manifest = generate(store, master, offer_id=ad.id, advert=ad.text)
            documents.append(_cv_documents(store, ad.id, manifest.version))
        measured = audit_documents(documents)

    measured["adverts_generated"] = len(ads)
    return measured


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T80.json`."""
    measured = measure(fixture_master)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _text_layer_report(measured: dict[str, Any]) -> int:
    """Print T80's measurement and say whether it fails the gate."""
    for line in measured["violations"]:
        print(f"✗ {line}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(
            "documents_missing_a_required_text_layer_field: UNMEASURED — "
            f"{measured['documents_missing_a_required_text_layer_field_evaluated']} document(s) "
            "evaluated. Not a pass and not a fail (D-2).",
            file=sys.stderr,
        )
        return 0
    # Fail on ANY contract breach, not only the named half: a corrupted text
    # layer is as unreadable to an ATS as an absent field.
    return 1 if measured["documents_with_text_layer_violations"] else 0


# ---------------------------------------------------------------------------
# T81 — keyword coverage against the posting, in four statuses

DEFAULT_KEYWORD_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T81.json"

COVERED = "covered"
SYNONYM_ONLY = "synonym-only"
MISSING_HAVE_IT = "missing (have it)"
MISSING_GAP = "missing (gap)"

KEYWORD_STATUSES: tuple[str, ...] = (COVERED, SYNONYM_ONLY, MISSING_HAVE_IT, MISSING_GAP)

# Closed on purpose — see the module docstring's T81 section. A new pair is a
# diff a reviewer sees, never a runtime decision about what counts as "close
# enough".
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "postgres": ("postgresql",),
    "k8s": ("kubernetes",),
    "js": ("javascript",),
    "node": ("node.js", "nodejs"),
}


def _synonyms_of(keyword: str) -> tuple[str, ...]:
    """The other spellings `_SYNONYMS` records for `keyword`, from either side of the pair."""
    key = keyword.casefold()
    if key in _SYNONYMS:
        return _SYNONYMS[key]
    for canonical, alternates in _SYNONYMS.items():
        if key in alternates:
            return (canonical, *(alt for alt in alternates if alt != key))
    return ()


def classify_keyword(document_text: str, master: CVMaster, keyword: str) -> str:
    """One posting keyword's status against one candidate's application.

    Checked in this order — literal, then synonym, then the store — because
    `_holds` alone cannot distinguish "the document said this differently"
    from "the document left this out"; the synonym check is what makes that
    distinction, so it has to run before the store is consulted.
    """
    synonyms = _synonyms_of(keyword)
    # A longer declared spelling contains the shorter one (`node.js` contains
    # `node`) and `_mentions` treats `.` as a term boundary, so a plain literal
    # check reports `covered` for a document that only ever used the alternate
    # spelling — contradicting the very table that declares them to be two
    # spellings. Mask the longer spellings first so the matcher and `_SYNONYMS`
    # agree: the candidate is told to add the posting's own wording, which is
    # the whole point of separating `covered` from `synonym-only`.
    masked = document_text
    for synonym in sorted(synonyms, key=len, reverse=True):
        if len(synonym) > len(keyword):
            masked = re.sub(re.escape(synonym), " ", masked, flags=re.IGNORECASE)
    if _mentions(masked, keyword):
        return COVERED
    if any(_mentions(document_text, synonym) for synonym in synonyms):
        return SYNONYM_ONLY
    if _holds(master, keyword) or any(_holds(master, synonym) for synonym in synonyms):
        return MISSING_HAVE_IT
    return MISSING_GAP


def _application_text(store: ProfileStore, offer_id: str, version: int) -> str:
    """Everything one generated application says — the CV and the letter, together.

    Unlike `_cv_documents`, not scoped to the CV alone: T81 asks whether the
    application addresses a keyword at all, not whether the one document an
    ATS parses does.
    """
    where = store.path("cv", "generated", offer_id, f"v{version}")
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (where / "cv.md", where / "letter.md")
        if path.exists()
    )


def keyword_coverage(
    document_text: str, master: CVMaster, keywords: tuple[str, ...]
) -> dict[str, Any]:
    """The gate: every posting keyword classified into exactly one of the four statuses."""
    rows = [
        {"keyword": keyword, "status": classify_keyword(document_text, master, keyword)}
        for keyword in keywords
    ]
    evaluated = len(rows)
    # `classify_keyword` is total over `KEYWORD_STATUSES` by construction, so
    # this stays at 0 for a correct implementation — it exists to catch a
    # future status this counter does not yet know about, the same role
    # `documents_missing_a_required_text_layer_field` plays for T80.
    unclassified = [row["keyword"] for row in rows if row["status"] not in KEYWORD_STATUSES]
    by_status = Counter(row["status"] for row in rows)

    return {
        "posting_keywords_left_unclassified": len(unclassified),
        "posting_keywords_left_unclassified_evaluated": evaluated,
        "posting_keywords_checked": evaluated,
        "gate_status": "unmeasured" if evaluated == 0 else "measured",
        "by_status": {status: by_status.get(status, 0) for status in KEYWORD_STATUSES},
        "rows": rows,
        "unclassified_keywords": sorted(unclassified),
    }


# What the measurement treats a posting as asking for. T45's own `measure`
# names this same honesty problem for `asks` — no module in this repository
# extracts a posting's own keywords from its text yet, so the real-corpus
# measurement below states its fixed set rather than pretending it read one
# off the advert. Reusing `_FIXTURE_ASKS` rather than inventing a second list
# keeps the two gates' real-corpus runs asking the same question of the same
# fixture candidate.
_FIXTURE_KEYWORDS: tuple[str, ...] = _FIXTURE_ASKS


def measure_keyword_coverage(
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
    store_path: Path | None = None,
) -> dict[str, Any]:
    """`posting_keywords_left_unclassified` over every advert in the corpus."""
    from integral.harness import DEFAULT_STORE_PATH, load_store

    master = CVMaster.model_validate_json(fixture_master.read_text(encoding="utf-8"))
    ads = load_store(store_path or DEFAULT_STORE_PATH)

    # A row per advert per keyword, not kept: 208 adverts times 4 keywords is
    # a multi-hundred-line evidence file for a number that `by_status`
    # already carries. `unclassified` is the exception — every entry in it is
    # this gate's own violation and has to be named, the same way T80 names
    # each `violations` line rather than only counting them.
    unclassified: list[str] = []
    by_status: Counter[str] = Counter()
    evaluated = 0
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        identity = create_profile(root, "Gate Fixture", handle="fixture", language="en")
        store = ProfileStore(root, identity.handle)
        write_master(store, master)
        for ad in ads:
            manifest = generate(
                store, master, offer_id=ad.id, advert=ad.text, asks=_FIXTURE_KEYWORDS
            )
            document_text = _application_text(store, ad.id, manifest.version)
            measured = keyword_coverage(document_text, master, _FIXTURE_KEYWORDS)
            evaluated += measured["posting_keywords_left_unclassified_evaluated"]
            by_status.update(measured["by_status"])
            unclassified.extend(
                f"{ad.id}: {keyword}" for keyword in measured["unclassified_keywords"]
            )

    return {
        "posting_keywords_left_unclassified": len(unclassified),
        "posting_keywords_left_unclassified_evaluated": evaluated,
        "posting_keywords_checked": evaluated,
        "gate_status": "unmeasured" if evaluated == 0 else "measured",
        "by_status": {status: by_status.get(status, 0) for status in KEYWORD_STATUSES},
        "adverts_generated": len(ads),
        "unclassified_keywords": sorted(unclassified),
    }


def write_keyword_coverage_evidence(
    evidence: Path = DEFAULT_KEYWORD_EVIDENCE_PATH,
    fixture_master: Path = DEFAULT_FIXTURE_MASTER,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T81.json`."""
    measured = measure_keyword_coverage(fixture_master)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _keyword_coverage_report(measured: dict[str, Any]) -> int:
    """Print T81's measurement and say whether it fails the gate."""
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(
            "posting_keywords_left_unclassified: UNMEASURED — "
            f"{measured['posting_keywords_left_unclassified_evaluated']} keyword(s) "
            "evaluated. Not a pass and not a fail (D-2).",
            file=sys.stderr,
        )
        return 0
    if measured["posting_keywords_left_unclassified"]:
        print(
            f"posting_keywords_left_unclassified: {measured['unclassified_keywords']}",
            file=sys.stderr,
        )
    return 1 if measured["posting_keywords_left_unclassified"] else 0


def _main(argv: list[str]) -> int:
    """Write T80's and T81's gate evidence — one module, two gates.

    `make evidence` discovers this module once (`grep -l '^def _main'`) and
    runs `python -m integral.ats` once, so both this module's gates are
    written from the same entry point rather than needing a second `_main`
    nothing would ever call.
    """
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    text_layer_measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    text_layer_exit = _text_layer_report(text_layer_measured)

    keyword_measured = write_keyword_coverage_evidence()
    keyword_exit = _keyword_coverage_report(keyword_measured)

    return 1 if (text_layer_exit or keyword_exit) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
