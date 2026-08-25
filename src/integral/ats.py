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
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from integral.cv_store import CVMaster, SourcedText, write_master
from integral.generate import DEFAULT_FIXTURE_MASTER, generate
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


def _main(argv: list[str]) -> int:
    """Write T80's gate evidence. Exit 1 on any text-layer contract violation."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
