"""Render the step-11 letter and CV from Markdown to one printable HTML file.

Markdown is the source and the HTML is generated; hand-editing the HTML is how
the two drift. The subset is headings, bold, paragraphs and bullets, so there
is no Markdown dependency, and no construct can produce a link or an image, so
nothing in the candidate's or the offer's text can reach the network.

**Escaping order is the one non-obvious bug.** ``html.escape`` runs on the raw
text first and the ``**bold**`` substitution second. Reversed, the apostrophes
in Catalan contractions are escaped *inside* the tags' payload a second time
and ship as ``&amp;#x27;``. Escaping first is also what makes every field safe:
the only markup in the output is markup this module wrote.

The photo is an optional input (bytes and a MIME type) and is embedded as a
``data:`` URI; this module extracts nothing.
"""

from __future__ import annotations

import base64
import html
import re

from integral.brand_palette import BrandPalette
from integral.brand_palette import css as palette_css
from integral.report_style import page

PHOTO_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
KINDS = ("letter", "cv")

_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
# A closing ``#`` sequence only counts after a space (CommonMark): ``## C#`` keeps its ``#``.
_HEADING = re.compile(r"^(#{1,3})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+(.*)$")
_LANG = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")

CSS = """\
:root { color-scheme: light; }
body { font: 11pt/1.5 Georgia, 'Times New Roman', serif; color: #111; background: #fff;
  max-width: 170mm; margin: 0 auto; padding: 12mm 8mm; }
h1, h2, h3 { font-family: Helvetica, Arial, sans-serif; line-height: 1.2; break-after: avoid; }
h1 { font-size: 20pt; margin: 0 0 4mm; }
h2 { font-size: 13pt; margin: 7mm 0 2mm; border-bottom: 0.3mm solid #999; }
h3 { font-size: 11pt; margin: 4mm 0 1mm; }
p, li { orphans: 3; widows: 3; }
p { margin: 0 0 3mm; }
ul { margin: 0 0 3mm; padding-left: 5mm; }
li { break-inside: avoid; }
header.photo { display: flex; align-items: center; gap: 6mm; margin-bottom: 4mm; }
header.photo img { width: 32mm; height: 40mm; object-fit: cover; border-radius: 1mm; }
@media print {
  @page { size: A4; margin: 22mm 24mm; }
  body { max-width: none; margin: 0; padding: 0; }
}
"""


def inline(text: str) -> str:
    """Escape *first*, then turn ``**bold**`` into ``<strong>``.

    Text nodes need only ``& < >`` escaped, so apostrophes stay literal.
    """
    return _BOLD.sub(r"<strong>\1</strong>", html.escape(text, quote=False))


def markdown_to_body(markdown: str) -> str:
    """Headings (#-###), bullets, bold and paragraphs, as an HTML fragment."""
    out: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + "<br>\n".join(inline(p) for p in paragraph) + "</p>")
            paragraph.clear()

    def flush_bullets() -> None:
        if bullets:
            out.append("<ul>\n" + "\n".join(f"<li>{inline(b)}</li>" for b in bullets) + "\n</ul>")
            bullets.clear()

    for raw in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        if not line.strip():
            flush_paragraph()
            flush_bullets()
        elif heading:
            flush_paragraph()
            flush_bullets()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif bullet:
            flush_paragraph()
            bullets.append(bullet.group(1))
        else:
            flush_bullets()
            paragraph.append(line.strip())
    flush_paragraph()
    flush_bullets()
    return "\n".join(out)


def _photo_header(photo: bytes, mime: str, alt: str) -> str:
    if mime not in PHOTO_MIME_TYPES:
        raise ValueError(f"photo MIME type {mime!r} is not one of {sorted(PHOTO_MIME_TYPES)}")
    uri = f"data:{mime};base64,{base64.b64encode(photo).decode('ascii')}"
    return (
        f'<header class="photo"><img src="{uri}" alt="{html.escape(alt, quote=True)}"></header>\n'
    )


def render_document(
    markdown: str,
    *,
    title: str,
    kind: str = "letter",
    photo: bytes | None = None,
    photo_mime: str = "image/jpeg",
    lang: str = "en",
    palette: BrandPalette | None = None,
) -> str:
    """One self-contained HTML document. ``photo`` is for the CV only; elsewhere it is refused.

    ``palette`` (T182) adds plain colour declarations after the base CSS; none is an at-rule.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    if not _LANG.fullmatch(lang):
        raise ValueError(f"lang {lang!r} is not a language tag")
    if photo is not None and (kind != "cv" or not photo):
        raise ValueError("photo must be non-empty bytes and is only valid for kind='cv'")
    extra_css = palette_css(palette) if palette else ""
    header = _photo_header(photo, photo_mime, title) if photo is not None and kind == "cv" else ""
    return page(
        title,
        f"{header}{markdown_to_body(markdown)}",
        lang=lang,
        body_class=kind,
        extra_css=CSS + extra_css,
        adaptive=False,
    )
