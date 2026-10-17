"""The sendable set: what `send/` holds beyond the approved Markdown (T338).

`approval.stage_send` used to copy the payload's Markdown and stop, and every real
delivery was finished by hand: PDFs named for sending, one combined upload for a
portal that takes a single file, and the letter as plain text for a text box. This
module derives that set from the two approved documents and nothing else, so each
derived file is a function of text the candidate already approved.

* `<First>-<Last>-CV.pdf` and `<First>-<Last>-Cover-Letter.pdf` — named from
  `identity.json`'s display name, never `cv.pdf`;
* `<First>-<Last>-Application.pdf` — one PDF, **letter first**, then the CV;
* `Cover-Letter.txt` — the letter's text, for a portal with a text box.

The text file is deterministic, so `approval.verify_send` regenerates it from the
approved `letter.md` and compares bytes. A PDF is not (the engine stamps a creation
time), so it is held to the digest recorded at staging, and `verify_send` also
requires the exact set of names derived here.

The PDF engine is a parameter (`Renderer`), because the engine is an optional extra
that needs Pango and evidence must not depend on whether one is installed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence

from integral.application_render import render_document
from integral.document_render import render_pdf_pages

# html pages in, one PDF out; the pages are joined in the order given.
Renderer = Callable[[Sequence[str]], bytes]

CV_MD = "cv.md"
LETTER_MD = "letter.md"
LETTER_TXT = "Cover-Letter.txt"

_HEADING = re.compile(r"^#{1,3}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+(.*)$")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")


class SendSetError(ValueError):
    """The sendable set cannot be derived (no usable name)."""


def name_stem(display_name: str) -> str:
    """`First-Last` from a display name: accents folded, first and last word kept."""
    words: list[str] = []
    for word in display_name.split():
        folded = unicodedata.normalize("NFKD", word)
        kept = "".join(c for c in folded if c.isascii() and c.isalnum())
        if kept:
            words.append(kept)
    if not words:
        raise SendSetError(f"identity.json's display name {display_name!r} yields no file name")
    return words[0] if len(words) == 1 else f"{words[0]}-{words[-1]}"


def derived_names(display_name: str, documents: Sequence[str]) -> tuple[str, ...]:
    """The files `send/` holds beyond `documents`, by name, sorted."""
    stem = name_stem(display_name)
    names: list[str] = []
    if CV_MD in documents:
        names.append(f"{stem}-CV.pdf")
    if LETTER_MD in documents:
        names += [f"{stem}-Cover-Letter.pdf", LETTER_TXT]
    if CV_MD in documents and LETTER_MD in documents:
        names.append(f"{stem}-Application.pdf")
    return tuple(sorted(names))


def letter_text(markdown: str) -> str:
    """The letter as plain text: markers gone, wording and paragraph breaks untouched."""
    lines: list[str] = []
    for line in markdown.splitlines():
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        if heading:
            text = heading.group(1)
        elif bullet:
            text = f"- {bullet.group(1)}"
        else:
            text = line.rstrip()
        lines.append(_BOLD.sub(r"\1", text))
    return "\n".join(lines).strip("\n") + "\n"


def derive(
    display_name: str,
    lang: str,
    texts: Mapping[str, str],
    render: Renderer | None = None,
) -> dict[str, bytes]:
    """Every derived file's bytes, from the approved Markdown in `texts` (name -> text)."""
    render = render or render_pdf_pages
    stem = name_stem(display_name)
    made: dict[str, bytes] = {}
    letter = cv = ""
    if LETTER_MD in texts:
        letter = render_document(texts[LETTER_MD], title=display_name, kind="letter", lang=lang)
        made[f"{stem}-Cover-Letter.pdf"] = render([letter])
        made[LETTER_TXT] = letter_text(texts[LETTER_MD]).encode("utf-8")
    if CV_MD in texts:
        cv = render_document(texts[CV_MD], title=display_name, kind="cv", lang=lang)
        made[f"{stem}-CV.pdf"] = render([cv])
    if LETTER_MD in texts and CV_MD in texts:
        made[f"{stem}-Application.pdf"] = render([letter, cv])
    return made


def fixture_renderer(pages: Sequence[str]) -> bytes:
    """A stand-in engine for fixtures and gates: a `%PDF` header, then each page's html.

    Deterministic and dependency-free, and it keeps the pages in the order given, so a
    check can read which document came first in a combined file.
    """
    return b"%PDF-fixture\n" + b"\n%%PAGE\n".join(page.encode("utf-8") for page in pages)
