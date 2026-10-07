"""T142: a CV and a letter are JSON; the HTML is an artefact nobody edits.

Step 11 used to write Markdown and leave a PDF engine's defaults to make of it
what they would. This module is the render half: one template, a closed block
vocabulary, and a handful of parameters that are real decisions. It renders; it
does not write. Content, and the manifest tracing every claim to its store
entry (T45), are untouched.

**A document** is ``{"title": str, "blocks": [{"type": ..., ...}, ...]}``. The
vocabulary is :data:`BLOCKS` and none of it is candidate-specific: for a CV
``header``, ``summary``, ``section``, ``job``, ``project``, ``bullets``,
``grid``, ``board``; for a letter ``letter``, ``to``, ``text``, ``sign``. A
block of any other type, a field a block does not declare, or a missing
required field is a :class:`RenderError` (never a silent omission), and a
document mixes CV blocks with letter blocks only by being refused.

**One rule about text, learned by breaking it.** Every text field carries inline
HTML and passes through exactly as written; only ``href`` values are escaped
(and must be ``http(s)``/``mailto``/``tel``). Escaping some fields and not
others once shipped ``EDUCATION &AMP; CERTIFICATIONS``: the page's capitals
come from CSS ``text-transform``, which acts on the rendered glyphs, so no
Python ``.upper()`` ever touches markup.

**A project carries two links, and they are not the same claim.** ``href`` is
the repository; ``live`` is a running deployment and renders a ``LIVE`` badge.
A project with only source must not look like one with both.

**The parameters, and nothing else** (:class:`RenderParams`, so a parameter
added later is a field and the tests that vary "every parameter" derive their
list from ``dataclasses.fields``):

* ``page_size``: derived from the recipient's country, not asked
  (:func:`page_size_for`): Letter for :data:`LETTER_COUNTRIES`, A4 everywhere
  else, including an unknown country.
* ``accent``: one hex colour. The default is the employer's own, read from its
  site by :mod:`integral.brand_palette` (:meth:`RenderParams.for_recipient`).
* ``margins_mm``: line length is what a reader feels first, so a margin that
  puts a line outside :data:`LINE_CHARS` is refused rather than printed.
* ``body_size_pt``: **one number sets the whole type scale.** Every other font
  size in the stylesheet is an ``em`` fraction of it. Nine absolute sizes once
  drifted apart the first time the body grew, and the small grid cells ended
  up smaller than the body text.
* ``language``: the document's own, ``<html lang>``, independent of the
  reader's interface language (T141).

**The accent is applied everywhere the template names one**, or nowhere:
heading rules, section titles, link underlines, the ``LIVE`` badge, and
anything drawn. WeasyPrint renders inline SVG standalone and the document's
CSS never reaches inside it, so an SVG whose fills come from a stylesheet
renders in its fallback colour and nothing warns you. The fills here are
attributes, which is why the accent is an argument to the generator and not
only a CSS custom property.

**The PDF** (:func:`render_pdf`, which needs the optional ``pdf`` extra) keeps a
text layer that :mod:`integral.ats` accepts, and a CV is held to
:data:`CV_PAGE_BUDGET` pages by a *rendered* page count, so a later content
edit fails loudly instead of silently becoming three. Page count is a cliff,
not a slope: a flex grid does not fragment, the last section either fits or
moves whole, so freeing 20 mm can change nothing and freeing 36 mm removes a
page. Any contract that tunes size against page count has to know this, or it
reads a null result as "no effect". The gate (``measure``) is HTML/CSS only,
because evidence that depended on whether a PDF engine happens to be installed
would drift between machines; the PDF contracts live in the tests.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from integral import brand_palette, report_style

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T142.json"

#: The recipient countries whose paper is Letter. Everywhere else is A4.
LETTER_COUNTRIES = frozenset({"US", "CA", "MX", "PH", "CL"})

#: Characters per line a reader tolerates, measured at half an em per glyph.
LINE_CHARS = (45, 100)
_GLYPH_EM = 0.5

BODY_PT = (8.0, 14.0)
MARGIN_MM = (10.0, 40.0)

#: The page budget a CV is held to by a rendered page count.
CV_PAGE_BUDGET = 2

#: A contract run that evaluated fewer contracts than this evaluated nothing.
#: It is a denominator for a clean zero, not a count of anything the code owns.
#: arsenal-floor-margin: MINIMUM_CONTRACTS_EVALUATED value=30
MINIMUM_CONTRACTS_EVALUATED = 30

_PAGE_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4)}
PAGE_SIZES = tuple(_PAGE_MM)
_MM_PT = 72 / 25.4

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_LANG = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")
_SAFE_HREF = re.compile(r"(?:https?://|mailto:|tel:)[^\s\"'<>]+", re.I)


class RenderError(ValueError):
    """The document or a parameter cannot be rendered, and says why."""


# --------------------------------------------------------------------------
# Parameters


def page_size_for(country: str | None) -> str:
    """``Letter`` for a Letter country (ISO 3166 alpha-2), else ``A4``."""
    code = (country or "").strip().upper()
    return "Letter" if code in LETTER_COUNTRIES else "A4"


def normalise_accent(value: str) -> str:
    """``#rgb`` or ``#rrggbb`` as lowercase ``#rrggbb``; anything else is refused."""
    text = value.strip() if isinstance(value, str) else ""
    if not _HEX.fullmatch(text):
        raise RenderError(f"accent {value!r} is not a hex colour (#rgb or #rrggbb)")
    text = text.lower()
    if len(text) == 4:
        text = "#" + "".join(c * 2 for c in text[1:])
    return text


@dataclass(frozen=True)
class RenderParams:
    page_size: str = "A4"
    accent: str = brand_palette.NEUTRAL_ACCENT
    margins_mm: float = 22.0
    body_size_pt: float = 10.5
    language: str = "en"

    @classmethod
    def for_recipient(
        cls,
        country: str | None,
        employer_colours: Mapping[str, int] | None = None,
        **chosen: Any,
    ) -> RenderParams:
        """Page size from the country, accent from the employer's measured palette.

        ``employer_colours`` is ``{"#ff671d": 31, ...}``, element counts read off
        the employer's site (the connector layer's job, not this module's). With
        nothing usable the accent is the neutral one: a guessed brand colour is
        worse than none. Anything in ``chosen`` overrides, so ``accent`` and
        ``page_size`` stay the author's to set.
        """
        palette = brand_palette.extract_palette(employer_colours)
        base = cls(page_size=page_size_for(country), accent=brand_palette.to_hex(palette.accent))
        return replace(base, **chosen)

    def checked(self) -> RenderParams:
        """These parameters, normalised, or a :class:`RenderError` naming the first fault."""
        if not isinstance(self.page_size, str) or self.page_size not in _PAGE_MM:
            raise RenderError(f"page_size {self.page_size!r} is not one of {PAGE_SIZES}")
        for name in ("margins_mm", "body_size_pt"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise RenderError(f"{name} {value!r} is not a number")
        if not (MARGIN_MM[0] <= self.margins_mm <= MARGIN_MM[1]):
            raise RenderError(f"margins_mm {self.margins_mm!r} is outside {MARGIN_MM}")
        if not (BODY_PT[0] <= self.body_size_pt <= BODY_PT[1]):
            raise RenderError(f"body_size_pt {self.body_size_pt!r} is outside {BODY_PT}")
        if not isinstance(self.language, str) or not _LANG.fullmatch(self.language):
            raise RenderError(f"language {self.language!r} is not a language tag")
        checked = replace(self, accent=normalise_accent(self.accent))
        chars = line_chars(checked)
        if not (LINE_CHARS[0] <= chars <= LINE_CHARS[1]):
            raise RenderError(
                f"margins {self.margins_mm} mm at {self.body_size_pt} pt on "
                f"{self.page_size} give about {chars:.0f} characters a line; "
                f"readable is {LINE_CHARS[0]} to {LINE_CHARS[1]}"
            )
        return checked


def line_chars(params: RenderParams) -> float:
    """Estimated characters per line: the text width over half an em a glyph."""
    width = _PAGE_MM[params.page_size][0] - 2 * params.margins_mm
    return width * _MM_PT / (_GLYPH_EM * params.body_size_pt)


# --------------------------------------------------------------------------
# The block vocabulary


@dataclass(frozen=True)
class Block:
    required: frozenset[str]
    optional: frozenset[str]
    kind: str  # "cv" or "letter"


def _block(kind: str, required: str, optional: str = "") -> Block:
    return Block(frozenset(required.split()), frozenset(optional.split()), kind)


BLOCKS: dict[str, Block] = {
    "header": _block("cv", "name", "title contact"),
    "summary": _block("cv", "text"),
    "section": _block("cv", "title"),
    "job": _block("cv", "role org", "dates place bullets"),
    "project": _block("cv", "name text", "href live tags"),
    "bullets": _block("cv", "items"),
    "grid": _block("cv", "cells"),
    "board": _block("cv", "rows"),
    "letter": _block("letter", "", "date place"),
    "to": _block("letter", "lines"),
    "text": _block("letter", "text"),
    "sign": _block("letter", "name", "closing"),
}

_LIST_FIELDS = frozenset({"contact", "bullets", "tags", "items", "lines"})
_ROW_FIELDS = {"cells": ("title", "text"), "rows": ("label", "text")}


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise RenderError(f"{where} must be text, not {type(value).__name__}")
    return value


def _texts(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RenderError(f"{where} must be a list of text")
    return list(value)


def _href(value: Any, where: str) -> str:
    text = _text(value, where).strip()
    if not _SAFE_HREF.fullmatch(text):
        raise RenderError(f"{where} {value!r} is not an http(s), mailto or tel link")
    return html.escape(text, quote=True)


def _svg_dot(accent: str) -> str:
    return (
        '<svg class="dot" viewBox="0 0 8 8" aria-hidden="true">'
        f'<circle cx="4" cy="4" r="4" fill="{accent}"/></svg>'
    )


def _svg_bar(accent: str) -> str:
    return (
        '<svg class="mark" viewBox="0 0 24 4" aria-hidden="true">'
        f'<rect width="24" height="4" fill="{accent}"/></svg>'
    )


def _items(values: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{v}</li>" for v in values) + "</ul>"


def _render_block(block: Mapping[str, Any], accent: str) -> str:
    kind = block["type"]
    g = block.get
    if kind == "header":
        contact = " · ".join(_texts(g("contact", []), "header.contact"))
        sub = f'<p class="role">{g("title")}</p>' if g("title") else ""
        line = f'<p class="contact">{contact}</p>' if contact else ""
        return f"<header>{_svg_bar(accent)}<h1>{g('name')}</h1>{sub}{line}</header>"
    if kind == "summary":
        return f'<p class="summary">{g("text")}</p>'
    if kind == "section":
        return f"<h2>{g('title')}</h2>"
    if kind == "job":
        meta = " · ".join(x for x in (g("dates"), g("place")) if x)
        body = _items(_texts(g("bullets", []), "job.bullets")) if g("bullets") else ""
        meta_html = f'<span class="meta">{meta}</span>' if meta else ""
        head = f'<p class="job-head"><strong>{g("role")}</strong>, {g("org")}{meta_html}</p>'
        return f'<div class="job">{head}{body}</div>'
    if kind == "project":
        links = ""
        if g("href"):
            links += f'<a href="{_href(g("href"), "project.href")}">source</a>'
        if g("live"):
            live = _href(g("live"), "project.live")
            links += f'<a class="live" href="{live}">{_svg_dot(accent)}LIVE</a>'
        tag_html = ""
        if g("tags"):
            tag_html = f'<span class="tags">{" · ".join(_texts(g("tags"), "project.tags"))}</span>'
        head = f'<p class="project-head"><strong>{g("name")}</strong>{links}{tag_html}</p>'
        return f'<div class="project">{head}<p>{g("text")}</p></div>'
    if kind == "bullets":
        return _items(_texts(g("items"), "bullets.items"))
    if kind in ("grid", "board"):
        field = "cells" if kind == "grid" else "rows"
        rows = g(field)
        if not isinstance(rows, list) or not all(isinstance(r, Mapping) for r in rows):
            raise RenderError(f"{kind}.{field} must be a list of objects")
        allowed = set(_ROW_FIELDS[field])
        out = []
        for row in rows:
            extra = set(row) - allowed
            if extra or "text" not in row:
                raise RenderError(f"{kind}.{field} rows take {sorted(allowed)}, got {sorted(row)}")
            label = _text(row.get(_ROW_FIELDS[field][0], ""), f"{kind} label")
            label_html = f"<b>{label}</b> " if label else ""
            out.append(f'<div class="cell">{label_html}{_text(row["text"], kind)}</div>')
        return f'<div class="{kind}">{"".join(out)}</div>'
    if kind == "letter":
        line = " · ".join(x for x in (g("place"), g("date")) if x)
        return f'<p class="dateline">{line}</p>' if line else ""
    if kind == "to":
        return '<p class="to">' + "<br>".join(_texts(g("lines"), "to.lines")) + "</p>"
    if kind == "text":
        return f"<p>{g('text')}</p>"
    if kind == "sign":
        closing = f"<p>{g('closing')}</p>" if g("closing") else ""
        return f'<div class="sign">{closing}<p><strong>{g("name")}</strong></p></div>'
    raise RenderError(f"no renderer for {kind!r}")  # unreachable: validated against BLOCKS


def validate(document: Mapping[str, Any]) -> str:
    """The document's kind (``cv`` or ``letter``), or a :class:`RenderError`."""
    if not isinstance(document, Mapping) or set(document) - {"title", "blocks"}:
        raise RenderError("a document is {'title': text, 'blocks': [...]} and nothing else")
    _text(document.get("title"), "title")
    blocks = document.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise RenderError("a document needs at least one block")
    kinds: set[str] = set()
    for n, block in enumerate(blocks):
        kind = block.get("type") if isinstance(block, Mapping) else None
        if not isinstance(kind, str) or kind not in BLOCKS:
            raise RenderError(f"block {n} is not one of {sorted(BLOCKS)}")
        spec = BLOCKS[block["type"]]
        keys = set(block) - {"type"}
        if missing := spec.required - keys:
            raise RenderError(f"block {n} ({block['type']}) lacks {sorted(missing)}")
        if extra := keys - spec.required - spec.optional:
            raise RenderError(f"block {n} ({block['type']}) has unknown {sorted(extra)}")
        for key in keys:
            if key in _LIST_FIELDS:
                _texts(block[key], f"block {n} {key}")
            elif key not in _ROW_FIELDS:
                _text(block[key], f"block {n} {key}")
        kinds.add(spec.kind)
    if len(kinds) != 1:
        raise RenderError("a document is a CV or a letter, not both")
    return kinds.pop()


# --------------------------------------------------------------------------
# The stylesheet


def _size(factor: float) -> str:
    return f"{factor:g}em"


def stylesheet(params: RenderParams) -> str:
    """The document's CSS. The *only* absolute font size is the root's.

    Colours are tokens: ``--accent`` decorates (rules, underlines) and
    ``--accent-text`` is the same hue darkened only as far as legibility on
    paper needs, so an accent that already reaches AA is applied unchanged.
    """
    paper = brand_palette.parse_colour(report_style._LIGHT["surface"]) or (255, 255, 255)
    accent_rgb = brand_palette.parse_colour(params.accent) or (0, 0, 0)
    accent_text = brand_palette.to_hex(brand_palette.text_variant(accent_rgb, paper))
    width, height = _PAGE_MM[params.page_size]
    return f"""\
:root {{ --accent: {params.accent}; --accent-text: {accent_text}; }}
@page {{ size: {width:g}mm {height:g}mm; margin: {params.margins_mm:g}mm; }}
html {{ font-size: {params.body_size_pt:g}pt; }}
body {{ margin: 0; color: var(--ink); background: var(--surface);
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; line-height: 1.4; }}
h1 {{ font-size: {_size(2)}; margin: 0.2em 0 0; line-height: 1.1; }}
h2 {{ font-size: {_size(1)}; margin: 1.3em 0 0.5em; padding-bottom: 0.2em;
  text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent-text);
  border-bottom: 0.15em solid var(--accent); break-after: avoid; }}
p {{ margin: 0 0 0.6em; }}
.mark {{ width: 3em; height: 0.5em; display: block; }}
.dot {{ width: 0.6em; height: 0.6em; margin-right: 0.3em; }}
.role {{ font-size: {_size(1.2)}; color: var(--muted); margin: 0.2em 0 0; }}
.contact {{ font-size: {_size(0.9)}; color: var(--muted); margin: 0.4em 0 0; }}
header {{ padding-bottom: 0.6em; border-bottom: 0.15em solid var(--accent); }}
.meta {{ float: right; font-size: {_size(0.9)}; color: var(--muted); }}
ul {{ margin: 0 0 0.6em; padding-left: 1.2em; }}
li {{ margin-bottom: 0.2em; }}
a {{ color: inherit; text-decoration: underline; text-decoration-color: var(--accent); }}
.live {{ margin-left: 0.6em; font-size: {_size(0.8)}; font-weight: bold;
  letter-spacing: 0.05em; color: var(--accent-text); text-decoration-color: var(--accent); }}
.project, .job {{ break-inside: avoid; }}
.project-head a {{ margin-left: 0.6em; font-size: {_size(0.9)}; }}
.tags {{ float: right; font-size: {_size(0.85)}; color: var(--muted); }}
.grid, .board {{ display: flex; flex-wrap: wrap; gap: 0.4em 1em; }}
.grid .cell {{ flex: 1 1 30%; font-size: {_size(0.9)}; }}
.board .cell {{ flex: 1 1 100%; font-size: {_size(0.95)}; }}
.dateline {{ text-align: right; color: var(--muted); }}
.to {{ margin-bottom: 1.4em; }}
.sign {{ margin-top: 1.4em; border-top: 0.1em solid var(--accent); padding-top: 0.6em; }}
"""


def render(
    document: Mapping[str, Any],
    params: RenderParams | None = None,
    *,
    title: str | None = None,
) -> str:
    """The HTML for ``document``: a finished, self-contained page for the PDF engine.

    Built by :func:`integral.report_style.page` (``adaptive=False``: paper is
    one palette) so the document cannot open itself some other way.
    """
    used = (params or RenderParams()).checked()
    validate(document)
    body = "\n".join(_render_block(b, used.accent) for b in document["blocks"])
    try:
        return report_style.page(
            title if title is not None else document["title"],
            body,
            lang=used.language,
            adaptive=False,
            extra_css=stylesheet(used),
        )
    except ValueError as exc:
        raise RenderError(str(exc)) from exc


def _refuse_every_url(url: str, *_args: Any, **_kwargs: Any) -> Any:
    """A WeasyPrint ``url_fetcher`` that fetches nothing.

    The page is self-contained, so the engine has nothing legitimate to load. Its
    default fetcher reads ``file:`` and the network: ``<a rel="attachment">`` embeds
    the target in the PDF and ``<svg><image href>`` is fetched, and the engine
    ignores the page's CSP. Text fields pass through as HTML, so an advert's string
    could otherwise put a local file into a PDF sent to an employer.
    """
    raise ValueError(f"the renderer fetches nothing: {url!r}")


def _refusing_fetcher() -> Any:
    """The refusing fetcher in the shape the installed WeasyPrint expects.

    Recent engines read ``_fail_on_errors`` off the fetcher, so it must be a
    ``URLFetcher``; older engines call a plain function.
    """
    try:
        from weasyprint.urls import URLFetcher  # type: ignore[import-not-found,unused-ignore]
    except ImportError:
        return _refuse_every_url

    class _Refusing(URLFetcher):  # type: ignore[misc,unused-ignore]
        def fetch(self, url: str, headers: Any = None) -> Any:
            return _refuse_every_url(url)

    return _Refusing()


def render_pdf(page_html: str, *, max_pages: int | None = None) -> tuple[bytes, int]:
    """``(pdf bytes, page count)``; needs the optional ``pdf`` extra (WeasyPrint).

    ``max_pages`` makes a budget loud: a document that renders longer raises
    :class:`RenderError` rather than quietly becoming a page longer.
    """
    try:
        import weasyprint  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except (ImportError, OSError) as exc:
        raise RenderError(
            "PDF output needs the optional 'pdf' extra (WeasyPrint): `uv sync --extra pdf`"
        ) from exc
    rendered = weasyprint.HTML(string=page_html, url_fetcher=_refusing_fetcher()).render()
    pages = len(rendered.pages)
    if max_pages is not None and pages > max_pages:
        raise RenderError(f"the document renders to {pages} pages; the budget is {max_pages}")
    return bytes(rendered.write_pdf()), int(pages)


# --------------------------------------------------------------------------
# What the gate reads from a rendered page: derived from the page, never from
# the generator that wrote it.

_STYLE = re.compile(r"<style>(.*?)</style>", re.S)
_ROOT_BLOCK = re.compile(r":root\s*\{[^{}]*\}")
_FONT_SIZE = re.compile(r"font-size\s*:\s*([^;}]+)")
_COLOUR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|(?<![-\w])(?:red|blue|green|orange|purple|"
    r"yellow|pink|black|white|gray|grey|teal|navy|maroon|olive|lime|aqua|cyan|magenta)\b"
)
_SVG = re.compile(r"<svg\b.*?</svg>", re.S)
_PAINT = re.compile(r'\b(fill|stroke)="([^"]*)"')


def style_of(page_html: str) -> str:
    return "\n".join(_STYLE.findall(page_html))


def font_sizes(page_html: str) -> list[str]:
    """Every ``font-size`` value the page's CSS declares, in order."""
    return [v.strip() for v in _FONT_SIZE.findall(style_of(page_html))]


def colour_literals_outside_tokens(page_html: str) -> list[str]:
    """Colour literals in the CSS beyond the ``:root`` token blocks.

    The template may name a colour only by token, so that one value governs
    every use. A literal here is a colour the accent cannot reach.
    """
    return _COLOUR_LITERAL.findall(_ROOT_BLOCK.sub("", style_of(page_html)))


def effective_token(page_html: str, name: str) -> str | None:
    """The last ``:root`` declaration of ``--name``: the one the cascade lands on."""
    value = None
    for block in _ROOT_BLOCK.findall(style_of(page_html)):
        for found in re.findall(rf"--{re.escape(name)}\s*:\s*([^;}}]+)", block):
            value = found.strip()
    return value


def svg_paints(page_html: str) -> list[tuple[str, str]]:
    """``(attribute, value)`` for every fill and stroke on every inline SVG."""
    return [m for svg in _SVG.findall(page_html) for m in _PAINT.findall(svg)]


def drawn_elements(page_html: str) -> int:
    """How many SVG shapes the page draws (so a paint check has a population)."""
    return len(re.findall(r"<(?:rect|circle|path|line|polygon|ellipse)\b", page_html))


#: Where the template names the accent: place -> (selector, property, token).
#: The task's own list (heading rules, section titles, link underlines) plus the
#: badge and the signature rule. Each is read from **that selector's own rule**:
#: a looser "some rule mentions both" let the badge's underline vouch for the
#: link underline, and a mutant that un-accented every other link survived.
#: SVG is read separately, from the attributes.
ACCENT_PLACES = {
    "heading rule": ("h2", "border-bottom", "var(--accent)"),
    "header rule": ("header", "border-bottom", "var(--accent)"),
    "section title": ("h2", "color", "var(--accent-text)"),
    "link underline": ("a", "text-decoration-color", "var(--accent)"),
    "live badge": (".live", "color", "var(--accent-text)"),
    "live underline": (".live", "text-decoration-color", "var(--accent)"),
    "signature rule": (".sign", "border-top", "var(--accent)"),
}


def rule_declarations(css: str) -> dict[str, dict[str, str]]:
    """``{selector: {property: value}}`` for the page's flat rules, later rules winning."""
    out: dict[str, dict[str, str]] = {}
    for rule in re.findall(r"[^{}]+\{[^{}]*\}", css):
        selector, _, body = rule.partition("{")
        declarations = out.setdefault(" ".join(selector.split()), {})
        for part in body.rstrip("}").split(";"):
            name, colon, value = part.partition(":")
            if colon:
                declarations[name.strip()] = value.strip()
    return out


def accent_places_reached(page_html: str) -> dict[str, bool]:
    """Whether each named place carries its accent token in the page's own CSS."""
    rules = rule_declarations(style_of(page_html))
    return {
        name: token in rules.get(selector, {}).get(prop, "")
        for name, (selector, prop, token) in ACCENT_PLACES.items()
    }


def contract_text_accent(accent: str) -> list[str]:
    """``--accent-text`` reaches AA on paper while the decoration stays the accent."""
    page = render(sample_cv(), replace(RenderParams(), accent=accent))
    text = effective_token(page, "accent-text") or ""
    rgb = brand_palette.parse_colour(text)
    paper = brand_palette.parse_colour(report_style._LIGHT["surface"])
    defects = []
    if (
        rgb is None
        or paper is None
        or brand_palette.contrast_ratio(rgb, paper) < brand_palette.AA_TEXT
    ):
        defects.append(f"{accent}: the text colour {text!r} is below AA on paper")
    if effective_token(page, "accent") != accent or {v for _, v in svg_paints(page)} != {accent}:
        defects.append(f"{accent}: the decoration is not the accent itself")
    return defects


# --------------------------------------------------------------------------
# Fixtures and the gate


def sample_cv() -> dict[str, Any]:
    return {
        "title": "Ana Perez - CV",
        "blocks": [
            {
                "type": "header",
                "name": "Ana Perez",
                "title": "Data engineer",
                "contact": ["ana@example.org", "Girona", '<a href="https://example.org">site</a>'],
            },
            {"type": "summary", "text": "Builds data platforms &amp; the teams that run them."},
            {"type": "section", "title": "Experience"},
            {
                "type": "job",
                "role": "Engineer",
                "org": "Acme",
                "dates": "2020 - 2024",
                "place": "Remote",
                "bullets": ["Moved the nightly load to streaming", "Cut <em>p95</em> latency"],
            },
            {"type": "section", "title": "Projects"},
            {
                "type": "project",
                "name": "pipeline-kit",
                "text": "A small orchestration library.",
                "href": "https://example.org/repo?a=1&b=2",
                "live": "https://example.org/demo",
                "tags": ["python", "sql"],
            },
            {
                "type": "project",
                "name": "notes",
                "text": "Source only.",
                "href": "https://x.test/n",
            },
            {"type": "section", "title": "Education &amp; certifications"},
            {"type": "bullets", "items": ["BSc, UdG", "Cloud practitioner"]},
            {"type": "grid", "cells": [{"title": "Python", "text": "daily"}, {"text": "SQL"}]},
            {"type": "board", "rows": [{"label": "Languages", "text": "Catalan, Spanish"}]},
        ],
    }


def sample_letter() -> dict[str, Any]:
    return {
        "title": "Letter",
        "blocks": [
            {"type": "letter", "place": "Girona", "date": "7 September 2026"},
            {"type": "to", "lines": ["Hiring team", "Acme"]},
            {"type": "text", "text": "I am writing about the <em>data</em> role."},
            {"type": "sign", "closing": "Regards,", "name": "Ana Perez"},
        ],
    }


def contract_parameters(page_html: str, params: RenderParams) -> list[str]:
    """Defects in one rendered page against the parameters it was rendered with."""
    defects = []
    sizes = font_sizes(page_html)
    absolute = [s for s in sizes if not s.endswith(("em", "%"))]
    if absolute != [f"{params.body_size_pt:g}pt"]:
        defects.append(f"font sizes other than the one root size are absolute: {absolute}")
    if effective_token(page_html, "accent") != params.accent:
        defects.append(f"the accent token is {effective_token(page_html, 'accent')!r}")
    if not re.search(rf'<html\s+lang="{re.escape(params.language)}"', page_html):
        defects.append("the document language is not on the root element")
    width, height = _PAGE_MM[params.page_size]
    if f"size: {width:g}mm {height:g}mm" not in page_html:
        defects.append(f"the page is not {params.page_size}")
    if f"margin: {params.margins_mm:g}mm" not in page_html:
        defects.append("the margin is not the margin asked for")
    return defects


def contract_accent(page_html: str, params: RenderParams) -> list[str]:
    defects = [
        f"{n} does not carry the accent"
        for n, ok in accent_places_reached(page_html).items()
        if not ok
    ]
    if literal := colour_literals_outside_tokens(page_html):
        defects.append(f"colour literals outside the tokens: {literal}")
    paints = svg_paints(page_html)
    if not paints or not drawn_elements(page_html):
        defects.append("no drawn element carries a paint, so the SVG rule was not exercised")
    for attribute, value in paints:
        if value != params.accent:
            defects.append(f"svg {attribute}={value!r} is not the accent {params.accent!r}")
    return defects


#: Accents that already reach AA on paper, so ``--accent-text`` is the accent
#: itself and a swap of one for another is a swap of the whole page's colour.
READABLE_ACCENTS = ("#123abc", "#8a2be2", "#b00020", "#00695c")


def swap_accent(first: str, second: str, params: RenderParams) -> list[str]:
    """Two renders differing only in accent must differ only by that colour."""
    a = render(sample_cv(), replace(params, accent=first))
    b = render(sample_cv(), replace(params, accent=second))
    if a == b or first not in a:
        return ["the accent never reached the page"]
    return (
        []
        if a.replace(first, second) == b
        else ["a part of the page is not governed by the accent"]
    )


def contract_project_links() -> list[str]:
    defects = []
    for with_href, with_live in ((True, True), (True, False), (False, True)):
        project: dict[str, Any] = {"type": "project", "name": "p", "text": "t"}
        if with_href:
            project["href"] = "https://r.test/p"
        if with_live:
            project["live"] = "https://l.test/p"
        page = render({"title": "x", "blocks": [project]})
        body = page[page.index("<body") :]
        if body.count("LIVE") != int(with_live):
            defects.append(
                f"href={with_href} live={with_live}: LIVE shown {body.count('LIVE')} times"
            )
        if ("https://r.test/p" in body) != with_href or ("https://l.test/p" in body) != with_live:
            defects.append(f"href={with_href} live={with_live}: the links do not match the claim")
    return defects


def contract_text_passthrough() -> list[str]:
    defects = []
    page = render(sample_cv())
    for needle in ("Education &amp; certifications", "<em>p95</em>", "&amp;"):
        if needle not in page:
            defects.append(f"{needle!r} did not pass through as written")
    if re.search(r"&amp;amp;|&AMP;|&#38;", page):
        defects.append("a text field was escaped or capitalised")
    if "https://example.org/repo?a=1&amp;b=2" not in page:
        defects.append("an href was not escaped")
    return defects


def contract_refusals() -> list[str]:
    defects = []
    cases: dict[str, Any] = {
        "unknown block": {"title": "t", "blocks": [{"type": "script", "text": "x"}]},
        "unknown field": {"title": "t", "blocks": [{"type": "summary", "text": "x", "font": "y"}]},
        "missing field": {"title": "t", "blocks": [{"type": "job", "role": "r"}]},
        "mixed kinds": {
            "title": "t",
            "blocks": [{"type": "summary", "text": "x"}, {"type": "text", "text": "y"}],
        },
        "javascript link": {
            "title": "t",
            "blocks": [
                {"type": "project", "name": "n", "text": "t", "href": "javascript:alert(1)"}
            ],
        },
        "no blocks": {"title": "t", "blocks": []},
    }
    for name, doc in cases.items():
        try:
            render(doc)
        except RenderError:
            continue
        defects.append(f"{name} was rendered")
    return defects


def variations() -> dict[str, tuple[Any, Any]]:
    """One alternative value per parameter. Keyed by field name and checked
    against ``fields(RenderParams)``, so a parameter added without a variation
    here fails the gate instead of going unvaried."""
    return {
        "page_size": ("A4", "Letter"),
        "accent": ("#ff671d", "#1d67ff"),
        "margins_mm": (22.0, 26.0),
        "body_size_pt": (10.5, 11.5),
        "language": ("en", "ca"),
    }


def contract_every_parameter_matters() -> list[str]:
    defects = []
    varied = variations()
    names = [f.name for f in fields(RenderParams)]
    if sorted(varied) != sorted(names):
        return [f"parameters {names} and variations {sorted(varied)} differ"]
    for name, (one, other) in varied.items():
        a = render(sample_cv(), replace(RenderParams(), **{name: one}))
        b = render(sample_cv(), replace(RenderParams(), **{name: other}))
        if a == b:
            defects.append(f"changing {name} changed nothing")
        for value, page in ((one, a), (other, b)):
            defects += [
                f"{name}={value}: {d}"
                for d in contract_parameters(page, replace(RenderParams(), **{name: value}))
            ]
    return defects


def contract_scale() -> list[str]:
    """Body size moves one number: nothing else in the stylesheet may differ."""
    small = render(sample_cv(), RenderParams(body_size_pt=10.0))
    large = render(sample_cv(), RenderParams(body_size_pt=11.0))
    if small.replace("10pt", "11pt") != large:
        return ["a type size other than the root's moved with the body size"]
    return []


def contract_page_size() -> list[str]:
    defects = []
    cases = [("US", "Letter"), ("us", "Letter"), (" CL ", "Letter"), ("MX", "Letter")]
    cases += [("PH", "Letter"), ("CA", "Letter"), ("ES", "A4"), ("GB", "A4"), ("BR", "A4")]
    for code, expected in cases:
        if page_size_for(code) != expected:
            defects.append(f"{code!r} gave {page_size_for(code)}")
    if page_size_for(None) != "A4" or page_size_for("") != "A4":
        defects.append("an unknown country is not A4")
    if RenderParams.for_recipient("MX").page_size != "Letter":
        defects.append("for_recipient did not derive the page size")
    return defects


def contract_default_accent() -> list[str]:
    grafana = {"#ff671d": 31, "#ffffff": 80, "#111217": 40}
    got = RenderParams.for_recipient("SE", grafana).accent
    defects = [] if got == "#ff671d" else [f"the employer's accent was {got!r}"]
    if RenderParams.for_recipient("SE", {}).accent != brand_palette.NEUTRAL_ACCENT:
        defects.append("nothing measured did not give the neutral accent")
    return defects


def contract_line_length() -> list[str]:
    defects = []
    for size in PAGE_SIZES:
        if not (LINE_CHARS[0] <= line_chars(RenderParams(page_size=size)) <= LINE_CHARS[1]):
            defects.append(f"the default measure on {size} is outside {LINE_CHARS}")
    for bad in (
        RenderParams(margins_mm=MARGIN_MM[0], body_size_pt=BODY_PT[0]),  # lines too long
        RenderParams(margins_mm=MARGIN_MM[0] - 1),
        RenderParams(body_size_pt=BODY_PT[1] + 1),
        RenderParams(accent="red"),
        RenderParams(language="not a tag"),
        RenderParams(page_size="A3"),
    ):
        try:
            bad.checked()
        except RenderError:
            continue
        defects.append(f"{bad} was accepted")
    return defects


def contract_vocabulary() -> list[str]:
    seen = {b["type"] for b in sample_cv()["blocks"]} | {
        b["type"] for b in sample_letter()["blocks"]
    }
    defects = [] if seen == set(BLOCKS) else [f"fixtures miss {sorted(set(BLOCKS) - seen)}"]
    for fixture, kind in ((sample_cv(), "cv"), (sample_letter(), "letter")):
        if validate(fixture) != kind:
            defects.append(f"a {kind} fixture was not recognised")
    return defects


def measure() -> dict[str, Any]:
    """T142's gate reading: contract failures over rendered pages (HTML/CSS only)."""
    defects: list[str] = []
    contracts = 0

    def record(label: str, found: list[str]) -> None:
        nonlocal contracts
        contracts += 1
        defects.extend(f"{label}: {d}" for d in found)

    accents = ("#ff671d", "#1d67ff", "#123abc", "#8a2be2")
    for size in PAGE_SIZES:
        base = RenderParams(page_size=size)
        for kind, doc in (("cv", sample_cv()), ("letter", sample_letter())):
            record(f"{size}/{kind} parameters", contract_parameters(render(doc, base), base))
        for accent in accents:
            params = replace(base, accent=accent)
            record(f"{size}/{accent} accent", contract_accent(render(sample_cv(), params), params))
            record(f"{size}/{accent} letter accent", contract_accent_letter(params))
        for first, second in pairwise(READABLE_ACCENTS):
            record(f"{size} swap {first}->{second}", swap_accent(first, second, base))
    record("vocabulary", contract_vocabulary())
    record("project links", contract_project_links())
    record("text passes through", contract_text_passthrough())
    record("refusals", contract_refusals())
    record("every parameter", contract_every_parameter_matters())
    record("one type scale", contract_scale())
    record("page size", contract_page_size())
    record("default accent", contract_default_accent())
    for accent in ("#ff671d", "#ffd400", "#999999"):
        record(f"text accent {accent}", contract_text_accent(accent))
    record("line length", contract_line_length())
    if contracts < MINIMUM_CONTRACTS_EVALUATED:
        return _unmeasured(
            f"only {contracts} contract(s) evaluated (floor {MINIMUM_CONTRACTS_EVALUATED})"
        )
    return {
        "document_render_defects": len(defects),
        "contracts_evaluated_at_least": MINIMUM_CONTRACTS_EVALUATED,
        "parameters": [f.name for f in fields(RenderParams)],
        "blocks": sorted(BLOCKS),
        "page_sizes": list(PAGE_SIZES),
        "gate_status": "measured",
        "defects": defects,
    }


def contract_accent_letter(params: RenderParams) -> list[str]:
    """A letter has no drawn mark, so only the stylesheet's places are read."""
    page = render(sample_letter(), params)
    return [d for d in contract_accent(page, params) if not d.startswith(("no drawn", "svg "))]


def _unmeasured(reason: str) -> dict[str, Any]:
    return {"document_render_defects": -1, "gate_status": "unmeasured", "reasons": [reason]}


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: Sequence[str] | None = None) -> int:
    """`python -m integral.document_render` -> T142's evidence; `render` makes a page."""
    parser = argparse.ArgumentParser(prog="integral.document_render")
    sub = parser.add_subparsers(dest="command")
    one = sub.add_parser("render", help="render a document JSON to HTML (and a PDF with --pdf)")
    one.add_argument("document", type=Path)
    one.add_argument("--country", help="the recipient's country; sets the page size")
    one.add_argument("--accent", help="hex colour; default is the neutral accent")
    one.add_argument("--margins-mm", type=float)
    one.add_argument("--body-size-pt", type=float)
    one.add_argument("--language", default="en")
    one.add_argument("--output", type=Path, required=True)
    one.add_argument("--pdf", type=Path, help="also write a PDF here (needs the 'pdf' extra)")
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.command == "render":
        chosen: dict[str, Any] = {"language": args.language}
        for key in ("accent", "margins_mm", "body_size_pt"):
            if getattr(args, key) is not None:
                chosen[key] = getattr(args, key)
        try:
            document = json.loads(args.document.read_text(encoding="utf-8"))
            page = render(
                document,
                RenderParams.for_recipient(args.country, None, **chosen),
            )
            args.output.write_text(page, encoding="utf-8")
            if args.pdf is not None:
                budget = CV_PAGE_BUDGET if validate(document) == "cv" else None
                args.pdf.write_bytes(render_pdf(page, max_pages=budget)[0])
        except (RenderError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"wrote {args.output}")
        return 0
    measured = write_evidence()
    print(json.dumps({k: v for k, v in measured.items() if k != "defects"}, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        for reason in measured["reasons"]:
            print(reason, file=sys.stderr)
        return 3
    for defect in measured["defects"]:
        print(defect, file=sys.stderr)
    return 1 if measured["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
