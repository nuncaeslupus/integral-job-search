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
time), so it cannot be compared byte for byte. Its independent reference is its text
layer: `pdf_defects` reads the text out of the PDF and requires the visible text of the
document(s) re-rendered from the approved Markdown, in order (letter, then CV, for the
combined file). A PDF swapped together with its `send.json` digest, or a CV and a letter
saved under each other's name, is refused. `verify_send` also requires the exact set of
names derived here.

The PDF engine is a parameter (`Renderer`), because the engine is an optional extra
that needs Pango and evidence must not depend on whether one is installed.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from html.parser import HTMLParser

from integral.application_render import render_document
from integral.document_render import render_pdf_pages

# html pages in, one PDF out; the pages are joined in the order given.
Renderer = Callable[[Sequence[str]], bytes]
# a PDF in, its text layer out (see `read_pdf_text`).
TextReader = Callable[[bytes], str]

FALLBACK_STEM = "Candidate"

CV_MD = "cv.md"
LETTER_MD = "letter.md"
LETTER_TXT = "Cover-Letter.txt"

_HEADING = re.compile(r"^#{1,3}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+(.*)$")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")


_FIXTURE_HEADER = b"%PDF-fixture\n"
_FIXTURE_SEPARATOR = b"\n%%PAGE\n"


class SendSetError(ValueError):
    """The sendable set cannot be derived."""


def name_stem(display_name: str) -> str:
    """`First-Last` from a display name: accents folded, first and last word kept.

    Only ASCII letters and digits survive (a name is a file name); a name with none
    falls back to `FALLBACK_STEM` rather than refusing.
    """
    words: list[str] = []
    for word in display_name.split():
        folded = unicodedata.normalize("NFKD", word)
        kept = "".join(c for c in folded if c.isascii() and c.isalnum())
        if kept:
            words.append(kept)
    if not words:
        # A name with no Latin letters or digits (Cyrillic, CJK, Greek) must not stop
        # the whole folder staging: the files take a neutral stem instead.
        return FALLBACK_STEM
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
    return _FIXTURE_HEADER + _FIXTURE_SEPARATOR.join(page.encode("utf-8") for page in pages)


class _VisibleText(HTMLParser):
    """The text a reader sees in a page's html: no head, no style, no script."""

    _HIDDEN = frozenset({"head", "style", "script", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._HIDDEN:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HIDDEN and self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._depth:
            self.parts.append(data)


def text_stream(text: str) -> str:
    """Letters and digits only, folded: robust to wrapping, bullets and ligatures."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c for c in folded if c.isalnum())


def page_stream(page_html: str) -> str:
    """`text_stream` of what a rendered page shows."""
    parser = _VisibleText()
    parser.feed(page_html)
    parser.close()
    return text_stream(" ".join(parser.parts))


def read_pdf_text(pdf: bytes) -> str:
    """A PDF's text layer. `fixture_renderer` output is html pages, read as pages show.

    Anything else goes through `pypdf` (the `cv` extra); without it the text cannot be
    read, which `pdf_defects` reports as a defect rather than waving the file through.
    """
    if pdf.startswith(_FIXTURE_HEADER):
        return " ".join(
            page_stream(chunk.decode("utf-8", "replace"))
            for chunk in pdf.removeprefix(_FIXTURE_HEADER).split(_FIXTURE_SEPARATOR)
        )
    try:
        import io

        import pypdf  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        raise SendSetError(
            "reading a PDF's text needs the optional 'cv' extra (pypdf): `uv sync --extra cv`"
        ) from exc
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf))
        return " ".join(text_stream(page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pypdf raises many types on a malformed file
        raise SendSetError(f"the PDF's text cannot be read: {exc}") from exc


def pdf_references(
    display_name: str, lang: str, texts: Mapping[str, str]
) -> dict[str, tuple[str, ...]]:
    """Each derived PDF's name -> the ordered text streams its text layer must hold.

    Built from the approved Markdown only, never from a staged file: this is the
    independent reference. The combined file is the letter, then the CV.
    """
    stem = name_stem(display_name)
    letter = cv = ""
    refs: dict[str, tuple[str, ...]] = {}
    if LETTER_MD in texts:
        letter = page_stream(
            render_document(texts[LETTER_MD], title=display_name, kind="letter", lang=lang)
        )
        refs[f"{stem}-Cover-Letter.pdf"] = (letter,)
    if CV_MD in texts:
        cv = page_stream(render_document(texts[CV_MD], title=display_name, kind="cv", lang=lang))
        refs[f"{stem}-CV.pdf"] = (cv,)
    if LETTER_MD in texts and CV_MD in texts:
        refs[f"{stem}-Application.pdf"] = (letter, cv)
    return refs


def pdf_defects(
    name: str, pdf: bytes, expected: Sequence[str], reader: TextReader | None = None
) -> list[str]:
    """What is wrong with a staged PDF's content, against the approved documents."""
    try:
        stream = (reader or read_pdf_text)(pdf)
    except SendSetError as exc:
        return [f"{name} in send/ cannot be checked: {exc}"]
    stream = stream.replace(" ", "")
    at = 0
    for number, wanted in enumerate(expected):
        found = stream.find(wanted, at) if wanted else -1
        if found < 0:
            what = "the approved text" if len(expected) == 1 else f"approved document {number + 1}"
            return [f"{name} in send/ does not hold {what} in the required order"]
        at = found + len(wanted)
    return []
