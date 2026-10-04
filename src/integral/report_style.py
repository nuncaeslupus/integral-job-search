"""T241: the one visual style every HTML page this package writes shares.

A candidate gets reports and dashboards (an applications board, a ranked list)
and the letter and CV. Left to each author they drift: one page ships its own
palette, another a web font, a third a ``<script src>``. This module is the one
place that owns the look, so a second page cannot differ from the first.

* **Tokens.** ``surface``, ``ink``, ``muted``, ``line``, ``accent``,
  ``positive`` and ``negative`` are CSS custom properties named once in
  ``:root`` and redefined once under ``prefers-color-scheme: dark``. Nothing
  below the token block spells a colour.
* **Components.** Summary ``tiles``, a ``card``, a status ``chip`` and a
  three-column ``facts`` grid that collapses to one column on a phone. Each
  helper escapes what it is given, so a page built from them carries only
  markup this module wrote.
* **The shell.** ``page(title, body, ...)`` is the only function that opens a
  document. A report is a body wrapped by it.
* **Self-contained.** No external font, script or stylesheet: a candidate's
  report is personal data and must render offline, from a file. The shell's
  Content-Security-Policy forbids the network, and ``page`` also refuses the
  common ways a body asks for it (``external_references`` lists what it
  catches and what it leaves to the policy), so most violations are an error at
  the point of writing, not a missing font on someone's machine.

A printed document (the letter, the CV) is one palette on paper and is not
re-themed by the reader's system setting: it passes ``adaptive=False`` and gets
the light tokens only, with its own rules after them in ``extra_css``.

Nothing in this package may open a document except ``page``; the test in
``tests/test_report_style.py`` derives that from the source with ``ast``.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from html.parser import HTMLParser

#: The colour roles a page may use, in the order the stylesheet declares them.
TOKENS = ("surface", "ink", "muted", "line", "accent", "positive", "negative")

_LIGHT = {
    "surface": "#ffffff",
    "ink": "#17202a",
    "muted": "#5d6b7a",
    "line": "#d9dee4",
    "accent": "#0b5394",
    "positive": "#1e7b4a",
    "negative": "#b3261e",
}
_DARK = {
    "surface": "#12171d",
    "ink": "#e8edf2",
    "muted": "#9aa7b4",
    "line": "#2b3540",
    "accent": "#7ab4ec",
    "positive": "#5fcb8c",
    "negative": "#f2877f",
}


def _declarations(values: dict[str, str], indent: str) -> str:
    return "".join(f"{indent}--{name}: {values[name]};\n" for name in TOKENS)


LIGHT_TOKENS = f":root {{\n  color-scheme: light;\n{_declarations(_LIGHT, '  ')}}}\n"

DARK_TOKENS = (
    "@media (prefers-color-scheme: dark) {\n"
    f"  :root {{\n    color-scheme: dark;\n{_declarations(_DARK, '    ')}  }}\n"
    "}\n"
)

#: Width at or below which the fact grid is one column.
PHONE_WIDTH = "40rem"

COMPONENTS = f"""\
body {{ margin: 0; background: var(--surface); color: var(--ink);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 60rem; margin: 0 auto; padding: 1.5rem 1rem; }}
h1, h2, h3 {{ line-height: 1.25; }}
a {{ color: var(--accent); }}
.muted {{ color: var(--muted); }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: 0.75rem; margin: 0 0 1rem; }}
.tile {{ border: 1px solid var(--line); border-radius: 0.5rem; padding: 0.75rem 1rem; }}
.tile .value {{ display: block; font-size: 1.75rem; font-weight: 600; color: var(--accent); }}
.tile .label {{ color: var(--muted); font-size: 0.875rem; }}
.card {{ border: 1px solid var(--line); border-radius: 0.5rem; padding: 1rem;
  margin: 0 0 1rem; background: var(--surface); }}
.card > h2, .card > h3 {{ margin-top: 0; }}
.chip {{ display: inline-block; border: 1px solid currentColor; border-radius: 999px;
  padding: 0 0.6rem; font-size: 0.8125rem; color: var(--muted); }}
.chip.positive {{ color: var(--positive); }}
.chip.negative {{ color: var(--negative); }}
.chip.accent {{ color: var(--accent); }}
.facts {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.75rem 1rem;
  margin: 0; }}
.facts div {{ min-width: 0; }}
.facts dt {{ color: var(--muted); font-size: 0.875rem; }}
.facts dd {{ margin: 0; overflow-wrap: anywhere; }}
@media (max-width: {PHONE_WIDTH}) {{
  .facts {{ grid-template-columns: 1fr; }}
}}
"""

#: The adaptive stylesheet: light and dark tokens, then the components.
STYLESHEET = LIGHT_TOKENS + DARK_TOKENS + COMPONENTS

#: Nothing may load: not a font, a script, a stylesheet nor a frame. Images are
#: allowed only as ``data:`` URIs (the CV photo).
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"

_LANG = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")
_CLASS = re.compile(r"[A-Za-z0-9_ -]*")
_TONES = ("neutral", "positive", "negative", "accent")

_LOADING_ATTRIBUTES = ("src", "srcset", "poster", "data", "action", "formaction")
_CSS_FETCH = re.compile(r"@import|url\(\s*['\"]?(?!data:)", re.I)
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|(.))", re.S)


def _decode_css(text: str) -> str:
    """Resolve CSS escapes (``\\75 rl(``, ``@\\69mport``) the way a browser does before it reads."""

    def one(m: re.Match[str]) -> str:
        if m.group(1):
            code = int(m.group(1), 16)
            return chr(code) if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else "\ufffd"
        return m.group(2)

    return _CSS_ESCAPE.sub(one, text)


class _References(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []
        self._style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._style = tag == "style"
        if tag in ("link", "base"):
            self.found.append(f"<{tag}>")
        if tag == "meta" and dict(attrs).get("http-equiv", "").strip().lower() == "refresh":
            self.found.append("<meta http-equiv=refresh>")
        for name, value in attrs:
            value = (value or "").strip()
            if name in _LOADING_ATTRIBUTES and value and not value.lower().startswith("data:"):
                self.found.append(f"<{tag} {name}={value[:40]!r}>")
            if name == "style" and _CSS_FETCH.search(_decode_css(value)):
                self.found.append(f"<{tag} style> fetches")

    def handle_endtag(self, tag: str) -> None:
        self._style = False

    def handle_data(self, data: str) -> None:
        if self._style and _CSS_FETCH.search(_decode_css(data)):
            self.found.append("<style> fetches")


def external_references(document: str) -> list[str]:
    """What in ``document`` would make a browser reach for anything but the file.

    Catches ``<link>`` and ``<base>`` in any form, ``<meta http-equiv=refresh>``,
    any ``src``/``srcset``/``poster``/``data``/``action``/``formaction`` that is
    not a ``data:`` URI, and any ``@import`` or ``url()`` in ``<style>`` or a
    ``style`` attribute, after CSS escapes are decoded. A plain ``<a href>`` is
    navigation the reader chooses and loads nothing, so it is not listed.

    It does **not** catch SVG ``href``/``xlink:href`` outside ``<a>``, ``ping``,
    ``background``, ``srcdoc``, ``image-set()`` or entities inside a foreign
    ``<style>``. The Content-Security-Policy is the layer that stops those, which
    is why its exact directive set is pinned by the tests.
    """
    parser = _References()
    parser.feed(document)
    parser.close()
    return parser.found


def tile(label: str, value: object) -> str:
    return (
        f'<div class="tile"><span class="value">{html.escape(str(value))}</span>'
        f'<span class="label">{html.escape(label)}</span></div>'
    )


def tiles(items: Iterable[tuple[str, object]]) -> str:
    """Summary tiles from ``(label, value)`` pairs."""
    return '<div class="tiles">' + "".join(tile(label, value) for label, value in items) + "</div>"


def card(title: str, body: str) -> str:
    """A card; ``body`` is markup the caller built from these helpers."""
    return f'<section class="card"><h2>{html.escape(title)}</h2>\n{body}\n</section>'


def chip(text: str, tone: str = "neutral") -> str:
    if tone not in _TONES:
        raise ValueError(f"tone must be one of {_TONES}, not {tone!r}")
    cls = "chip" if tone == "neutral" else f"chip {tone}"
    return f'<span class="{cls}">{html.escape(text)}</span>'


def facts(pairs: Sequence[tuple[str, str]]) -> str:
    """The fact grid: three columns on a desktop, one on a phone."""
    cells = "".join(
        f"<div><dt>{html.escape(term)}</dt><dd>{html.escape(value)}</dd></div>"
        for term, value in pairs
    )
    return f'<dl class="facts">{cells}</dl>'


def page(
    title: str,
    body: str,
    *,
    lang: str = "en",
    body_class: str = "",
    extra_css: str = "",
    adaptive: bool = True,
) -> str:
    """The one page shell: wrap ``body`` in a self-contained document.

    ``adaptive`` selects the screen stylesheet (light and dark, components);
    ``adaptive=False`` is for a printed document and carries the light tokens
    only. ``extra_css`` is appended after either. Raises ``ValueError`` for a
    malformed ``lang`` or ``body_class``, or if the finished document would load
    anything from outside the file.
    """
    if not _LANG.fullmatch(lang):
        raise ValueError(f"lang {lang!r} is not a language tag")
    if not _CLASS.fullmatch(body_class):
        raise ValueError(f"body_class {body_class!r} is not a class list")
    base = STYLESHEET if adaptive else LIGHT_TOKENS
    cls = f' class="{body_class}"' if body_class else ""
    document = (
        "<!doctype html>\n"
        f'<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>\n{base}{extra_css}</style>\n</head>\n"
        f"<body{cls}>\n{body}\n</body>\n</html>\n"
    )
    found = external_references(document)
    if found:
        raise ValueError(f"a page must be self-contained; it references {found}")
    return document
