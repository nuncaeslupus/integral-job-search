"""T141 — an annotatable reader for any HTML document this tool generates.

The candidate edits a letter or a CV by *fragment*: one note box beside each
paragraph, list item, heading and header line, instead of retyping the
paragraph into chat. Notes autosave in the browser, **export** to a Markdown
file (fragment id, a quote of the source, the note) and the same file
**imports** back, so a returned export re-seeds the reader. Built by hand for a
live application on 2026-09-07 and used for thirteen revisions; this is that
tool, made part of the package.

**Two languages, independent.** The document is in the employer's language
(`document_language`); everything the reader itself shows is in the
candidate's (`reader_language`), from `strings/reader.json`, which `strings`
checks for completeness and staleness exactly as it does the results page.

**Why the measurement is behavioural.** `reader_fragment_defects` counts
contract failures over readers this module *generated*, never patterns in its
source. Four defects were met by hand, each looked almost right, and each has a
contract below:

1. A `<div>` taken as a fragment boundary swallowed a whole letter — eleven
   paragraphs in one note box. Contract: every fragment balances its own tags,
   holds exactly one fragment element, and the reader as a whole balances.
2. A 25-character floor dropped short headings (`Projects`) and an 18-character
   project header. Contract: every heading and header line of the input is its
   own fragment whatever its length — and no text of the input goes missing.
3. A double-unescaped `\\n` put a literal newline inside a JavaScript string,
   a syntax error, so the browser discarded the whole `<script>`: nothing
   autosaved and Export was inert while typing, which is HTML, still worked.
   Contract: the generator parses the script it emits (`node --check`) and
   refuses to return a reader whose JavaScript does not compile — and the
   script is then *run* against a stand-in for the page, where the Export
   button must produce a file, a keystroke must reach storage, and the file
   must import back.
4. A note box below a short fragment instead of beside it. Contract: the
   layout declared in the emitted stylesheet is evaluated at every width a
   document is read at, and the box must stay in the second column of the
   fragment's own row.

**What the layout contract is not.** There is no browser in this gate, so it
evaluates the *declared* cascade (simple class selectors, last rule wins,
`min-width` / `max-width` media queries) of the stylesheet the reader emits. It
catches a media query that stacks the box under the fragment; it cannot catch a
renderer that disobeys a grid. That limit is the module's, stated here so it is
not read as more.

**What the i18n contract is not.** Quality of a translation is not countable
and is not claimed (see `strings`). What is counted: every catalogue string
reaches the reader in the reader's language, no source-language text leaks into
a translated reader, and with every string replaced by a sentinel the export a
reader writes contains no word that is neither a sentinel nor the candidate's
own text — so the code path that writes it has no string literal of its own.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from integral import corpus, strings
from integral.report_style import CSP, page

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOGUE = _REPO_ROOT / "strings" / "reader.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T141.json"

#: A run that evaluated fewer contracts than this evaluated nothing. Each
#: subject in `SUBJECTS` is read in each of the three reader languages and
#: every reader meets seven contracts, so a clean run evaluates 70 today; the
#: floor sits well under that so adding a fixture never trips it, and
#: emptying the fixture list or dropping a contract family does. It is a
#: denominator for a clean zero, not a count of anything the code owns.
#: arsenal-floor-margin: MINIMUM_CONTRACTS_EVALUATED value=40
MINIMUM_CONTRACTS_EVALUATED = 40

#: Widths, in CSS pixels, at which a document is actually read: a small phone,
#: a large phone, a tablet, a laptop, a desktop, a wide screen.
READING_WIDTHS = (360, 480, 768, 1024, 1280, 1920)

EXPORT_MARK = "reader-notes"
EXPORT_VERSION = 1

# --------------------------------------------------------------------------
# The fragment model


class ReaderError(Exception):
    """A reader could not be made, or what was made does not hold."""


_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_FRAGMENT_TAGS = frozenset({"p", "li"}) | _HEADINGS
_HEADER_CLASSES = frozenset({"header-line", "hdr"})
_VOID = frozenset({"br", "hr", "img", "wbr", "input", "meta", "link", "col", "area", "base"})
_INLINE = frozenset(
    {
        "a", "abbr", "b", "br", "cite", "code", "em", "i", "mark", "q", "s", "small",
        "span", "strong", "sub", "sup", "time", "u", "wbr",
    }
)  # fmt: skip
_SKIP = frozenset(
    {"script", "style", "template", "head", "title", "noscript", "iframe", "object", "embed", "svg"}
)
_CLOSES_P = frozenset(
    {
        "p",
        "ul",
        "ol",
        "div",
        "table",
        "section",
        "header",
        "footer",
        "blockquote",
        "pre",
        "hr",
        "li",
    }
    | _HEADINGS
)
_KEPT_ATTRIBUTES = frozenset({"class", "lang", "dir", "title", "href", "src", "alt"})
_SAFE_HREF = re.compile(r"(https?:|mailto:|tel:|#)", re.I)
_SAFE_SRC = re.compile(r"data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]*\Z")
_LANG = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*")


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    @property
    def classes(self) -> frozenset[str]:
        return frozenset(self.attrs.get("class", "").split())


class _TreeBuilder(HTMLParser):
    """HTML to a tree, tolerating the omitted end tags HTML allows.

    Only `</li>` and `</p>` are ever implied, and only by the next sibling that
    forces it: a tolerant parse is what lets a fragment be *serialised from the
    tree* and so balance by construction, rather than be sliced out of the
    source text between offsets, which is how a boundary comes to swallow a
    letter.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root")
        self.stack: list[_Node] = [self.root]

    def _open(self, tag: str) -> bool:
        return any(node.tag == tag for node in self.stack[1:])

    def _pop_to(self, tag: str) -> None:
        while len(self.stack) > 1:
            node = self.stack.pop()
            if node.tag == tag:
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _CLOSES_P and self.stack[-1].tag == "p":
            self.stack.pop()
        if tag == "li":
            for node in reversed(self.stack[1:]):
                if node.tag in ("ul", "ol"):
                    break
                if node.tag == "li":
                    self._pop_to("li")
                    break
        node = _Node(tag, {name: value or "" for name, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID and self._open(tag):
            self._pop_to(tag)

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _parse(markup: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root


def _find(node: _Node, tag: str) -> _Node | None:
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag == tag:
                return child
            found = _find(child, tag)
            if found is not None:
                return found
    return None


def _is_candidate(node: _Node) -> bool:
    return node.tag in _FRAGMENT_TAGS or bool(node.classes & _HEADER_CLASSES)


def _children(node: _Node) -> Iterator[_Node]:
    return (c for c in node.children if isinstance(c, _Node) and c.tag not in _SKIP)


def _contains_candidate(node: _Node) -> bool:
    return any(_is_candidate(c) or _contains_candidate(c) for c in _children(node))


def _raw_text(item: _Node | str) -> str:
    if isinstance(item, str):
        return item
    if item.tag in _SKIP:
        return ""
    if item.tag in ("br", "wbr"):
        return " "
    return "".join(_raw_text(c) for c in item.children)


def normalise(text: str) -> str:
    """Whitespace collapsed to single spaces: the quote a fragment is known by."""
    return " ".join(text.split())


def _text(item: _Node | str) -> str:
    return normalise(_raw_text(item))


def _attributes(node: _Node) -> str:
    kept = []
    for name, value in node.attrs.items():
        if name not in _KEPT_ATTRIBUTES:
            continue  # ids would collide with the reader's own; on* and style are code
        if name == "href" and not _SAFE_HREF.match(value.strip()):
            continue
        if name == "src" and not _SAFE_SRC.match(value.strip()):
            continue
        kept.append(f' {name}="{html.escape(value, quote=True)}"')
    return "".join(kept)


def _serialise(item: _Node | str) -> str:
    """Escape on the way out: the only markup in a reader is markup written here.

    The reader needs `script-src 'unsafe-inline'` for its own script, which is
    also what would let a `<script>` or an `onclick=` in the *document* run. So
    the document never carries one through: scripts and styles are dropped,
    attributes are an allowlist, and every text node is escaped again.
    """
    if isinstance(item, str):
        return html.escape(item, quote=False)
    if item.tag in _SKIP:
        return ""
    if item.tag in _VOID:
        return f"<{item.tag}{_attributes(item)}>"
    inner = "".join(_serialise(c) for c in item.children)
    return f"<{item.tag}{_attributes(item)}>{inner}</{item.tag}>"


@dataclass(frozen=True)
class Fragment:
    """One annotatable unit: a note box is attached to each of these."""

    id: str
    kind: str  # heading | header | item | paragraph
    html: str
    text: str


@dataclass(frozen=True)
class Passthrough:
    """Markup with no text to annotate (a photo, a rule), kept so layout holds."""

    html: str


Part = Fragment | Passthrough


class _Walker:
    def __init__(self) -> None:
        self.parts: list[Part] = []

    def _fragment(self, kind: str, markup: str, text: str, list_tag: str, number: int) -> None:
        if kind == "item":
            start = f' start="{number}"' if list_tag == "ol" else ""
            markup = f"<{list_tag}{start}>{markup}</{list_tag}>"
        self.parts.append(
            Fragment(f"f{sum(isinstance(p, Fragment) for p in self.parts) + 1}", kind, markup, text)
        )

    def _leaf(self, node: _Node, in_header: bool, list_tag: str, number: int) -> None:
        text = _text(node)
        if not text:
            # An empty candidate (`<p></p>`) has nothing to annotate; keep only
            # what it still carries, such as an image, as plain markup.
            markup = _serialise(node)
            if any(isinstance(c, _Node) and c.tag not in _SKIP for c in node.children):
                self.parts.append(Passthrough(markup))
            return
        if node.tag in _HEADINGS:
            kind = "heading"
        elif node.tag == "li":
            kind = "item"
        elif in_header or node.classes & _HEADER_CLASSES:
            kind = "header"
        else:
            kind = "paragraph"
        self._fragment(kind, _serialise(node), text, list_tag, number)

    def children(
        self,
        parent: _Node,
        *,
        in_header: bool = False,
        list_tag: str = "ul",
        wrapper: _Node | None = None,
    ) -> None:
        run: list[_Node | str] = []
        counter = [0]

        def flush() -> None:
            if not run:
                return
            text = _text(_Node("#run", children=list(run)))
            if text:
                tag = wrapper.tag if wrapper is not None else "p"
                attrs = _attributes(wrapper) if wrapper is not None else ""
                markup = f"<{tag}{attrs}>{''.join(_serialise(r) for r in run)}</{tag}>"
                kind = (
                    "item"
                    if tag == "li"
                    else "heading"
                    if tag in _HEADINGS
                    else ("header" if in_header else "paragraph")
                )
                counter[0] += 1 if tag == "li" else 0
                self._fragment(kind, markup, text, list_tag, counter[0])
            elif any(isinstance(r, _Node) and r.tag not in _SKIP for r in run):
                self.parts.append(Passthrough("".join(_serialise(r) for r in run)))
            run.clear()

        for child in parent.children:
            if isinstance(child, str):
                run.append(child)
            elif child.tag in _SKIP:
                continue
            elif _is_candidate(child):
                flush()
                if child.tag == "li":
                    counter[0] += 1
                if _contains_candidate(child):
                    self.children(child, in_header=in_header, list_tag=list_tag, wrapper=child)
                else:
                    self._leaf(child, in_header, list_tag, counter[0])
            elif child.tag in _INLINE and not _contains_candidate(child):
                run.append(child)
            else:
                flush()
                if child.tag in ("ul", "ol"):
                    self.children(child, in_header=in_header, list_tag=child.tag)
                elif _contains_candidate(child):
                    self.children(child, in_header=in_header or child.tag == "header")
                elif in_header and child.tag != "header" and _text(child):
                    self._fragment("header", _serialise(child), _text(child), list_tag, 0)
                elif _text(child):
                    self.children(child, in_header=in_header or child.tag == "header")
                else:
                    markup = _serialise(child)
                    if markup:
                        self.parts.append(Passthrough(markup))
        flush()


def fragment(document: str) -> list[Part]:
    """The body of `document` as fragments and text-free passthrough markup.

    `document` is a whole HTML document or a body fragment. A `<div>`, a
    `<section>` or a `<ul>` is never a fragment: it is walked into, and the
    paragraphs, items, headings and header lines inside it are. Text sitting
    loose in a container, or beside a nested list inside an item, becomes a
    fragment of its own rather than going unannotated.
    """
    root = _parse(document)
    body = _find(root, "body") or root
    walker = _Walker()
    walker.children(body, in_header=body.tag == "header")
    return walker.parts


# --------------------------------------------------------------------------
# The reader's own script. Everything the candidate sees arrives through `T`.

#: A raw string on purpose: every backslash below is for JavaScript, and a
#: second round of unescaping is exactly how defect 3 shipped.
_SCRIPT = r"""
(function () {
  "use strict";
  var T = __STRINGS__;
  var DOC = __DOC__;
  var SEED = __SEED__;
  var MARK = "__MARK__";
  var KEY = "reader:" + DOC.id;

  function fmt(text, vars) {
    return text.replace(/\{(\w+)\}/g, function (whole, name) {
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole;
    });
  }
  function say(key, vars) {
    var status = document.getElementById("reader-status");
    if (status) { status.textContent = fmt(T[key], vars || {}); }
  }
  function openStore() {
    try {
      var storage = window.localStorage;
      var probe = KEY + ":probe";
      storage.setItem(probe, "1");
      storage.removeItem(probe);
      return storage;
    } catch (error) { return null; }
  }
  function has(object, key) { return Object.prototype.hasOwnProperty.call(object, key); }
  function bare(source) {
    var made = Object.create(null);
    if (source && typeof source === "object") {
      Object.keys(source).forEach(function (key) { made[key] = source[key]; });
    }
    return made;
  }
  function loadMap(storage, key) {
    if (!storage) { return bare(null); }
    try {
      var raw = storage.getItem(key);
      return bare(raw ? JSON.parse(raw) : null);
    } catch (error) { return bare(null); }
  }
  function saveMap(storage, key, map) {
    if (!storage) { return false; }
    try { storage.setItem(key, JSON.stringify(map)); return true; }
    catch (error) { return false; }
  }
  function encodeData(data) {
    return JSON.stringify(data)
      .replace(/-/g, "\\u002d").replace(/</g, "\\u003c").replace(/>/g, "\\u003e");
  }
  function buildExport(notes) {
    var lines = ["# " + fmt(T.reader_export_heading, { title: DOC.title }), ""];
    var carried = {};
    DOC.order.forEach(function (id) {
      var note = notes[id];
      if (!note || !note.trim()) { return; }
      carried[id] = { quote: DOC.quotes[id], note: note };
      lines.push("## " + id, "", "> " + DOC.quotes[id], "", note, "");
    });
    lines.push("<!-- " + MARK + " " + encodeData({ v: __VERSION__, notes: carried }) + " -->", "");
    return { text: lines.join("\n"), count: Object.keys(carried).length };
  }
  function parseExport(text) {
    var found = null;
    var pattern = new RegExp("<!--\\s*" + MARK + "\\s+(\\{[\\s\\S]*?\\})\\s*-->", "g");
    var match;
    while ((match = pattern.exec(text)) !== null) { found = match[1]; }
    if (found === null) { return null; }
    try {
      var data = JSON.parse(found);
      if (!data || data.v !== __VERSION__ || !data.notes || typeof data.notes !== "object") {
        return null;
      }
      return data.notes;
    } catch (error) { return null; }
  }

  var storage = openStore();
  var ORIGIN_KEY = KEY + ":origin";
  var notes = loadMap(storage, KEY);
  var origins = loadMap(storage, ORIGIN_KEY);
  var boxes = Array.prototype.slice.call(document.querySelectorAll("textarea[data-frag]"));
  var byId = Object.create(null);

  function mark(id, moved) {
    var hint = document.getElementById("m-" + id);
    if (hint) { hint.hidden = !moved; }
  }
  function setNote(id, text, quote) {
    var box = byId[id];
    if (!box) { return false; }
    box.value = text;
    notes[id] = text;
    // The quote a note was written against is kept beside it, so the flag
    // survives a reload instead of living only until the page closes.
    if (typeof quote === "string" && quote !== DOC.quotes[id]) { origins[id] = quote; }
    else { delete origins[id]; }
    mark(id, has(origins, id));
    return true;
  }
  function autosave(id, text) {
    if (text.trim()) { notes[id] = text; }
    else { delete notes[id]; delete origins[id]; mark(id, false); }
    var saved = saveMap(storage, KEY, notes) && saveMap(storage, ORIGIN_KEY, origins);
    if (saved) { say("reader_saved"); }
    else { say("reader_storage_unavailable"); }
  }

  boxes.forEach(function (box) {
    var id = box.dataset.frag;
    byId[id] = box;
    var local = has(notes, id);
    var seeded = !local && has(SEED, id) ? SEED[id] : null;
    var start = local ? notes[id] : (seeded ? seeded.note : "");
    if (start) { setNote(id, start, local ? origins[id] : seeded.quote); }
    box.addEventListener("input", function () { autosave(id, box.value); });
  });
  if (!storage) { say("reader_storage_unavailable"); }

  var exportButton = document.getElementById("reader-export");
  if (exportButton) {
    exportButton.addEventListener("click", function () {
      var current = {};
      boxes.forEach(function (box) { current[box.dataset.frag] = box.value; });
      var built = buildExport(current);
      if (built.count === 0) { say("reader_no_notes"); return; }
      var blob = new Blob([built.text], { type: "text/markdown;charset=utf-8" });
      var link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = DOC.file;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      say("reader_exported", { n: built.count });
    });
  }
  var importInput = document.getElementById("reader-import");
  if (importInput) {
    importInput.addEventListener("change", function () {
      var file = importInput.files && importInput.files[0];
      if (!file) { return; }
      file.text().then(function (text) {
        var data = parseExport(text);
        if (data === null) { say("reader_import_failed"); return; }
        var count = 0;
        var dropped = 0;
        Object.keys(data).forEach(function (id) {
          var item = data[id];
          if (item && typeof item.note === "string" && setNote(id, item.note, item.quote)) {
            count += 1;
            autosave(id, item.note);
          } else { dropped += 1; }
        });
        if (dropped) { say("reader_imported_dropped", { n: count, d: dropped }); }
        else { say("reader_imported", { n: count }); }
        importInput.value = "";
      }, function () { say("reader_import_failed"); });
    });
  }
})();
"""

#: Every key the script reads through `T`, derived by reading it back rather
#: than listed: a key added to the script and not to the catalogue is a
#: reader that shows `undefined`, which is what the i18n contract looks for.
_SCRIPT_KEY = re.compile(r"\b(?:say\(\s*|T\.)\"?(reader_[a-z_]+)")

_STYLE = """\
.reader-bar { position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap;
  align-items: center; gap: 0.5rem 1rem; padding: 0.5rem 0; background: var(--surface); }
.reader-bar .intro { flex: 1 1 18rem; margin: 0; color: var(--muted); }
.reader-bar button, .reader-bar .btn { font: inherit; padding: 0.3rem 0.8rem; cursor: pointer;
  border: 1px solid var(--line); border-radius: 0.3rem; background: var(--surface);
  color: var(--ink); }
#reader-status { color: var(--muted); min-height: 1.4em; }
.reader-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(8rem, 15rem);
  column-gap: 1rem; align-items: start; padding: 0.15rem 0; }
.reader-row > .doc { grid-column: 1; grid-row: 1; min-width: 0; }
.reader-row > .note { grid-column: 2; grid-row: 1; min-width: 0; }
.reader-row .doc > p, .reader-row .doc > h1, .reader-row .doc > h2, .reader-row .doc > h3,
.reader-row .doc > ul, .reader-row .doc > ol { margin-top: 0; margin-bottom: 0.3rem; }
.note label { display: block; font-size: 0.75rem; color: var(--muted); }
.note textarea { box-sizing: border-box; width: 100%; min-height: 2.6rem; font: inherit;
  font-size: 0.85rem; resize: vertical; border: 1px solid var(--line); border-radius: 0.3rem;
  background: var(--surface); color: var(--ink); }
.note textarea:not(:placeholder-shown) { border-color: var(--accent); }
.note .moved { display: block; font-size: 0.75rem; color: var(--negative); }
.passthrough img { max-width: 8rem; height: auto; }
@media print { .reader-bar, .note { display: none; } .reader-row { display: block; } }
"""


# --------------------------------------------------------------------------
# Strings: the reader's own, in the candidate's language


def load_catalogue(path: Path = DEFAULT_CATALOGUE) -> dict[str, Any]:
    try:
        return strings.load(path)
    except strings.StringsError as exc:
        raise ReaderError(str(exc)) from exc


def reader_strings(catalogue: Mapping[str, Any], language: str) -> dict[str, str]:
    """Every catalogue key in `language` — a stale or missing entry falls back
    to the source text and `strings.fallbacks` is what says so."""
    if language not in catalogue["languages"]:
        raise ReaderError(
            f"reader language {language!r} is not one of {list(catalogue['languages'])}"
        )
    return {key: strings.text(catalogue, key, language) for key in strings.keys(catalogue)}


def script_keys(script: str = _SCRIPT) -> frozenset[str]:
    """The catalogue keys the script reads."""
    return frozenset(_SCRIPT_KEY.findall(script))


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48] or "document"


def _json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")


# --------------------------------------------------------------------------
# The export file, read from Python (the in-browser reader writes it)

_EXPORT = re.compile(rf"<!--\s*{EXPORT_MARK}\s+(\{{.*?\}})\s*-->", re.S)


def encode_export_data(notes: Mapping[str, Mapping[str, str]]) -> str:
    """The trailing comment of an export, byte for byte as the in-browser reader writes it.

    `-`, `<` and `>` are written as JSON escapes so that no note can contain
    the two characters that would end the comment early.
    """
    body = json.dumps(
        {"v": EXPORT_VERSION, "notes": {k: dict(v) for k, v in notes.items()}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    body = body.replace("-", "\\u002d").replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<!-- {EXPORT_MARK} {body} -->"


def parse_export(text: str) -> dict[str, dict[str, str]] | None:
    """The notes carried by an export file, or `None` if it is not one.

    The *last* matching comment wins: the reader appends its data after every
    note, so a note that happens to quote the marker cannot hijack an import.
    Shape is validated, never repaired — a note that is not a string, or a
    version this module does not know, is `None`.
    """
    found = _EXPORT.findall(text)
    if not found:
        return None
    try:
        data = json.loads(found[-1])
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("v") != EXPORT_VERSION:
        return None
    notes = data.get("notes")
    if not isinstance(notes, dict):
        return None
    result: dict[str, dict[str, str]] = {}
    for key, item in notes.items():
        if not (
            isinstance(key, str)
            and isinstance(item, dict)
            and isinstance(item.get("quote"), str)
            and isinstance(item.get("note"), str)
        ):
            return None
        result[key] = {"quote": item["quote"], "note": item["note"]}
    return result


# --------------------------------------------------------------------------
# Building a reader


def node_path() -> str | None:
    return shutil.which("node")


def check_script(script: str) -> str | None:
    """`None` if Node parses `script`, else its complaint. Raises if Node is absent."""
    node = node_path()
    if node is None:
        raise ReaderError("node is not installed, so the reader's script cannot be checked")
    with tempfile.TemporaryDirectory() as scratch:
        target = Path(scratch) / "reader.cjs"
        target.write_text(script, encoding="utf-8")
        done = subprocess.run(
            [node, "--check", str(target)], capture_output=True, text=True, timeout=60, check=False
        )
    return None if done.returncode == 0 else done.stderr.strip() or "node --check failed"


def reader_csp() -> str:
    """The page policy plus the one allowance the reader's own script needs."""
    return f"{CSP}; script-src 'unsafe-inline'"


_PLACEHOLDER = re.compile(r"__(?:STRINGS|DOC|SEED|MARK|VERSION)__")


def render_script(
    table: Mapping[str, str],
    quotes: Mapping[str, str],
    order: Sequence[str],
    doc: Mapping[str, Any],
    seed: Mapping[str, Mapping[str, str]],
) -> str:
    meta = {**doc, "quotes": dict(quotes), "order": list(order)}
    values = {
        "__STRINGS__": _json_for_script(dict(table)),
        "__DOC__": _json_for_script(meta),
        "__SEED__": _json_for_script({k: dict(v) for k, v in seed.items()}),
        "__MARK__": EXPORT_MARK,
        "__VERSION__": str(EXPORT_VERSION),
    }
    # One pass over the *template*, never over its own output. Chained
    # `str.replace` re-reads what earlier passes inserted, so a placeholder
    # typed into the document, the title or a note was substituted again —
    # at best a misquote, at worst a string literal broken open and the
    # candidate's text run as code.
    return _PLACEHOLDER.sub(lambda match: values[match.group(0)], _SCRIPT)


def build_reader(
    document: str,
    *,
    title: str,
    reader_language: str,
    document_language: str = "en",
    catalogue: Mapping[str, Any] | None = None,
    notes: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """The annotatable reader for `document`, or a `ReaderError`.

    `notes` is what `parse_export` returned for a returned export; it seeds the
    boxes whose own autosave is empty. Nothing is returned unless the script
    it carries compiles.
    """
    if not _LANG.fullmatch(document_language):
        raise ReaderError(f"document language {document_language!r} is not a language tag")
    cat = catalogue if catalogue is not None else load_catalogue()
    table = reader_strings(cat, reader_language)
    parts = fragment(document)
    frags = [p for p in parts if isinstance(p, Fragment)]
    if not frags:
        raise ReaderError("the document has no text to annotate")
    quotes = {f.id: f.text for f in frags}
    digest = hashlib.sha256("\n".join(quotes[f.id] for f in frags).encode("utf-8")).hexdigest()
    doc = {"id": digest[:16], "title": title, "file": f"{_slug(title)}-notes.md"}
    script = render_script(table, quotes, [f.id for f in frags], doc, notes or {})
    problem = check_script(script)
    if problem is not None:
        raise ReaderError(f"the reader's script does not compile: {problem}")

    esc = html.escape
    rows = []
    for part in parts:
        if isinstance(part, Passthrough):
            rows.append(f'<div class="passthrough">{part.html}</div>')
            continue
        rows.append(
            f'<div class="reader-row" data-kind="{part.kind}">'
            f'<div class="doc">{part.html}</div>'
            f'<div class="note" lang="{reader_language}">'
            f'<label for="n-{part.id}">{esc(table["reader_note_label"])}</label>'
            f'<textarea id="n-{part.id}" data-frag="{part.id}" rows="2" '
            f'placeholder="{esc(table["reader_note_placeholder"], quote=True)}"></textarea>'
            f'<span class="moved" id="m-{part.id}" hidden>'
            f"{esc(table['reader_text_changed'])}</span>"
            "</div></div>"
        )
    bar = (
        f'<div class="reader-bar" lang="{reader_language}">'
        f'<p class="intro">{esc(table["reader_intro"])}</p>'
        f'<button type="button" id="reader-export">{esc(table["reader_export"])}</button>'
        f'<label class="btn" for="reader-import">{esc(table["reader_import"])}</label>'
        '<input type="file" id="reader-import" accept=".md,text/markdown,text/plain" hidden>'
        '<span id="reader-status" role="status" aria-live="polite"></span></div>'
    )
    shell = page(
        title,
        bar + "\n" + "\n".join(rows),
        lang=document_language,
        body_class="reader",
        extra_css=_STYLE,
    )
    shell = shell.replace(CSP, reader_csp(), 1)
    return shell.replace("</body>", f"<script>{script}</script>\n</body>", 1)


# --------------------------------------------------------------------------
# The contracts. Each returns a list of defects; empty is the goal.


class _Balance(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.problems: list[str] = []
        self.candidates = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _FRAGMENT_TAGS:
            self.candidates += 1
        if tag not in _VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _FRAGMENT_TAGS:
            self.candidates += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"</{tag}> closes {self.stack[-1:] or 'nothing'}")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()


def balance_problems(markup: str) -> tuple[list[str], int]:
    """Unbalanced or unclosed tags in `markup`, and how many fragment elements it has."""
    parser = _Balance()
    parser.feed(markup)
    parser.close()
    unclosed = [f"<{tag}> never closed" for tag in parser.stack]
    return parser.problems + unclosed, parser.candidates


def _contract_balance(document: str, parts: Sequence[Part], reader: str) -> list[str]:
    defects = []
    for part in parts:
        if not isinstance(part, Fragment):
            continue
        problems, candidates = balance_problems(part.html)
        if problems:
            defects.append(f"fragment {part.id} does not balance its tags: {problems}")
        # A list item is wrapped in its own list, so the one fragment element is
        # the `<li>`; a header line may be a `<div>` and counts none.
        expected = 1 if part.kind != "header" or part.html.startswith(("<p", "<h")) else 0
        if candidates != expected:
            defects.append(
                f"fragment {part.id} holds {candidates} fragment elements, not {expected}"
                " — a boundary swallowed its neighbours"
            )
    problems, _ = balance_problems(reader)
    if problems:
        defects.append(f"the reader does not balance its tags: {problems[:5]}")
    return defects


class _Truth(HTMLParser):
    """The input read a second, independent way: the text of every heading and
    header line, and all visible text — without `fragment`'s tree."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth_skip = 0
        self.heading: list[str] | None = None
        self.header_classes: list[tuple[str, list[str]]] = []
        self.headings: list[str] = []
        self.header_lines: list[str] = []
        self.text: list[str] = []
        self._open: list[tuple[str, bool]] = []
        self._line: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.depth_skip += 1
        classes = set(dict((n, v or "") for n, v in attrs).get("class", "").split())
        is_line = bool(classes & _HEADER_CLASSES)
        if tag not in _VOID:
            self._open.append((tag, is_line))
        if is_line:
            self._line.append([])
        if tag in _HEADINGS:
            self.heading = []
        if tag in ("br", "wbr"):
            self.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.depth_skip = max(0, self.depth_skip - 1)
        if not self._open:
            return
        name, is_line = self._open.pop()
        if is_line and self._line:
            self.header_lines.append(normalise("".join(self._line.pop())))
        if name in _HEADINGS and self.heading is not None:
            self.headings.append(normalise("".join(self.heading)))
            self.heading = None

    def handle_data(self, data: str) -> None:
        if self.depth_skip:
            return
        self.text.append(data)
        if self.heading is not None:
            self.heading.append(data)
        for line in self._line:
            line.append(data)


def _contract_headings(document: str, parts: Sequence[Part]) -> list[str]:
    truth = _Truth()
    truth.feed(document)
    truth.close()
    texts = [p.text for p in parts if isinstance(p, Fragment)]
    defects = []
    for kind, wanted in (("heading", truth.headings), ("header line", truth.header_lines)):
        for text in wanted:
            if text and text not in texts:
                defects.append(f"{kind} {text!r} is not a fragment of its own")
    seen = normalise("".join(truth.text))
    if "<body" in document.lower():
        body = document[document.lower().index("<body") :]
        probe = _Truth()
        probe.feed(body)
        probe.close()
        seen = normalise("".join(probe.text))
    carried = normalise(" ".join(texts))
    if re.sub(r"\s+", "", seen) != re.sub(r"\s+", "", carried):
        defects.append("the fragments do not carry every word of the document, or add some")
    return defects


def widths_layout(css: str, widths: Sequence[int] = READING_WIDTHS) -> list[str]:
    """Defects in the layout *declared* by `css`, at each width.

    The effective declarations of `.reader-row`, `.reader-row > .doc` and
    `.reader-row > .note` are resolved by source order under the media queries
    that apply at that width. The box must be in the second column of a grid
    with at least two tracks, in the same row as its fragment.
    """
    defects = []
    for width in widths:
        effective: dict[str, dict[str, str]] = {}
        for media, selector, body in _rules(css):
            if not _applies(media, width):
                continue
            target = {
                ".reader-row": "row",
                ".reader-row > .doc": "doc",
                ".reader-row > .note": "note",
                ".note": "note",
                ".doc": "doc",
            }.get(selector.strip())
            if target is None:
                continue
            for declaration in body.split(";"):
                name, _, value = declaration.partition(":")
                if value.strip():
                    effective.setdefault(target, {})[name.strip()] = " ".join(value.split())
        row, doc, note = (effective.get(k, {}) for k in ("row", "doc", "note"))
        if row.get("display") != "grid":
            defects.append(f"{width}px: the row is {row.get('display')!r}, not a grid")
        if _tracks(row.get("grid-template-columns", "")) < 2:
            defects.append(f"{width}px: the row has fewer than two columns")
        if note.get("display") == "none":
            defects.append(f"{width}px: the note box is hidden")
        if note.get("grid-column") != "2" or doc.get("grid-column") != "1":
            defects.append(f"{width}px: the note box is not in the second column")
        if note.get("grid-row") != doc.get("grid-row") or not note.get("grid-row"):
            defects.append(f"{width}px: the note box is not in its fragment's row")
        if row.get("align-items") not in ("start", "flex-start"):
            defects.append(f"{width}px: the note box does not start at its fragment's top")
    return defects


_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _rules(css: str) -> Iterator[tuple[str, str, str]]:
    """(media prelude, selector, declarations) in source order; flat media only."""
    index = 0
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    while index < len(css):
        at = css.find("@media", index)
        plain_end = at if at != -1 else len(css)
        for match in _RULE.finditer(css[index:plain_end]):
            for selector in match.group(1).split(","):
                yield "", selector, match.group(2)
        if at == -1:
            return
        open_brace = css.index("{", at)
        depth, cursor = 1, open_brace + 1
        while depth and cursor < len(css):
            depth += {"{": 1, "}": -1}.get(css[cursor], 0)
            cursor += 1
        prelude = css[at + len("@media") : open_brace].strip()
        for match in _RULE.finditer(css[open_brace + 1 : cursor - 1]):
            for selector in match.group(1).split(","):
                yield prelude, selector, match.group(2)
        index = cursor


def _applies(media: str, width: int) -> bool:
    if not media:
        return True
    if re.search(r"\bprint\b", media) and not re.search(r"\bscreen\b", media):
        return False
    for kind, value in re.findall(r"\((min|max)-width:\s*([\d.]+)px\)", media):
        if kind == "min" and width < float(value):
            return False
        if kind == "max" and width > float(value):
            return False
    return not re.search(r"\((?!(?:min|max)-width)", media)


def _tracks(template: str) -> int:
    tokens, depth, current = 0, 0, ""
    for char in template:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == " " and depth == 0:
            tokens += 1 if current else 0
            current = ""
        else:
            current += char
    return tokens + (1 if current else 0)


def _style_of(reader: str) -> str:
    return "\n".join(re.findall(r"<style>(.*?)</style>", reader, flags=re.S))


def _script_of(reader: str) -> str:
    found = re.findall(r"<script>(.*?)</script>", reader, flags=re.S)
    return found[-1] if found else ""


# A stand-in for the page, just big enough to run the reader's script: the
# elements the reader declares, a localStorage, Blob/URL for the download, and
# a file whose `.text()` resolves. It is the same shape every contract drives.
_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const html = input.html, script = input.script;
function element(props) {
  return Object.assign({
    listeners: {}, dataset: {}, hidden: false, value: "", textContent: "",
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
  }, props);
}
const byId = {}, boxes = [];
for (const m of html.matchAll(/\bid="([^"]+)"[^>]*?( hidden)?>/g)) {
  byId[m[1]] = element({ id: m[1], hidden: Boolean(m[2]) });
}
for (const m of html.matchAll(/data-frag="([^"]+)"/g)) {
  const b = element({ id: "n-" + m[1] });
  b.dataset.frag = m[1];
  boxes.push(b);
}
const downloads = [];
const store = Object.assign({}, input.storage || {});
const blocked = () => { throw new Error("blocked"); };
const storage = input.noStorage
  ? { setItem: blocked, getItem: blocked, removeItem: blocked }
  : {
    setItem(k, v) { store[k] = String(v); },
    getItem(k) { return k in store ? store[k] : null; },
    removeItem(k) { delete store[k]; },
  };
const document = {
  querySelectorAll: () => boxes,
  getElementById: (id) => byId[id] || null,
  createElement: () => element({
    click() { downloads.push({ name: this.download, blob: this.href }); },
  }),
  body: { appendChild() {}, removeChild() {} },
};
const blobs = {};
class Blob { constructor(parts) { this.text = parts.join(""); } }
const URLStub = {
  createObjectURL(b) { const u = "blob:" + Object.keys(blobs).length; blobs[u] = b; return u; },
};
const sandbox = { document, window: { localStorage: storage }, Blob, URL: URLStub, console };
vm.createContext(sandbox);
vm.runInContext(script, sandbox, { filename: "reader.js" });
const out = {};
function fire(el, type) { for (const fn of el.listeners[type] || []) fn(); }
async function run() {
  for (const step of input.steps) {
    if (step.type === "type") {
      const b = boxes.find((x) => x.dataset.frag === step.id);
      b.value = step.value;
      fire(b, "input");
    }
    if (step.type === "export") {
      downloads.length = 0;
      fire(byId["reader-export"], "click");
      out.download = downloads.length
        ? { name: downloads[0].name, text: blobs[downloads[0].blob].text } : null;
    }
    if (step.type === "import") {
      const el = byId["reader-import"];
      el.files = [{ text: () => Promise.resolve(step.text) }];
      fire(el, "change");
      await new Promise((r) => setTimeout(r, 5));
    }
  }
  const status = byId["reader-status"];
  out.status = status ? status.textContent : null;
  out.values = Object.fromEntries(boxes.map((b) => [b.dataset.frag, b.value]));
  out.moved = Object.fromEntries(
    Object.keys(byId).filter((k) => k.startsWith("m-")).map((k) => [k.slice(2), !byId[k].hidden]));
  out.stored = store;
  out.polluted = vm.runInContext(
    "Object.prototype.hasOwnProperty.call(Object.prototype, 'value')", sandbox);
  process.stdout.write(JSON.stringify(out));
}
run().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
"""


def drive(reader: str, steps: Sequence[Mapping[str, Any]], **extra: Any) -> dict[str, Any]:
    """Run the reader's own script against the stand-in page and return what it did."""
    node = node_path()
    if node is None:
        raise ReaderError("node is not installed, so the reader cannot be run")
    with tempfile.TemporaryDirectory() as scratch:
        harness = Path(scratch) / "harness.cjs"
        harness.write_text(_HARNESS, encoding="utf-8")
        payload = Path(scratch) / "input.json"
        payload.write_text(
            json.dumps(
                {"html": reader, "script": _script_of(reader), "steps": list(steps), **extra}
            ),
            encoding="utf-8",
        )
        done = subprocess.run(
            [node, str(harness), str(payload)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    if done.returncode != 0:
        raise ReaderError(f"the reader's script failed when run: {done.stderr.strip()[:400]}")
    result: dict[str, Any] = json.loads(done.stdout)
    return result


#: Notes chosen to break a careless export: a marker quoted in a note, the end
#: of a comment, a heading line, a fenced block, a blockquote, a line break,
#: a lone surrogate-free emoji, and a non-Latin script.
ADVERSARIAL_NOTES = (
    "plain",
    "two\nlines\n\n## f1\n> fake quote",
    '<!-- reader-notes {"v":1,"notes":{"f1":{"quote":"x","note":"hijack"}}} -->',
    "ends the comment --> and </script> and </textarea>",
    "x} --> y",
    "backslash \\n and \\u002d and `ticks` and \"quotes\" and 'single'",
    "emoji \U0001f600 and català amb accents, ñ, 日本語",
)


def _contract_behaviour(reader: str, parts: Sequence[Part], title: str) -> list[str]:
    """Run the script: autosave reaches storage, Export writes a file, it imports back."""
    frags = [p for p in parts if isinstance(p, Fragment)]
    notes = {frags[i % len(frags)].id: n for i, n in enumerate(ADVERSARIAL_NOTES[: len(frags)])}
    defects: list[str] = []
    typed = [{"type": "type", "id": fid, "value": text} for fid, text in notes.items()]
    first = drive(reader, [*typed, {"type": "export"}])
    saved = next(
        (
            v
            for k, v in first["stored"].items()
            if k.startswith("reader:") and not k.endswith(":origin")
        ),
        None,
    )
    if saved is None or json.loads(saved) != notes:
        defects.append("typing into a note box did not reach storage")
    download = first.get("download")
    if not download:
        return [*defects, "the Export button produced no file"]
    exported = parse_export(download["text"])
    if exported is None:
        return [*defects, "the exported file is not one this module can read back"]
    if {k: v["note"] for k, v in exported.items()} != notes:
        defects.append("the exported notes differ from the typed ones")
    for fid, item in exported.items():
        if item["quote"] != next(f.text for f in frags if f.id == fid):
            defects.append(f"the export's quote of {fid} is not the fragment's text")
    if not download["name"].endswith("-notes.md"):
        defects.append(f"the export is named {download['name']!r}")
    # Import in a *fresh* reader (a new browser, empty storage): the file seeds it.
    second = drive(reader, [{"type": "import", "text": download["text"]}])
    if (
        second["values"].get("f1") is None
        or {k: v for k, v in second["values"].items() if v} != notes
    ):
        defects.append("importing the exported file did not restore every note")
    if any(second["moved"].values()):
        defects.append("an import of an unchanged document flagged text as changed")
    # ... and a note whose quote no longer matches is flagged, not silently attached.
    trailer = encode_export_data(exported)
    if trailer not in download["text"]:
        defects.append("the in-browser export and encode_export_data disagree byte for byte")
    changed = {k: dict(v) for k, v in exported.items()}
    changed[frags[0].id if frags[0].id in changed else next(iter(changed))]["quote"] = "older"
    stale = download["text"].replace(trailer, encode_export_data(changed))
    third = drive(reader, [{"type": "import", "text": stale}])
    flagged = [k for k, v in third["moved"].items() if v]
    if len(flagged) != 1:
        defects.append(
            f"a note whose quoted text changed was flagged on {flagged}, not on one fragment"
        )
    # Not an export: refused with a message, nothing set.
    fourth = drive(reader, [{"type": "import", "text": "# just a file"}])
    if any(fourth["values"].values()):
        defects.append("importing a file that is not an export set a note")
    # Seeded at generation from a returned export (the Python half of import).
    seeded = build_reader(
        "".join(p.html for p in parts),
        title=title,
        reader_language=_reader_language_of(reader),
        document_language=_document_language_of(reader),
        notes=exported,
    )
    fifth = drive(seeded, [])
    if {k: v for k, v in fifth["values"].items() if v} != notes:
        defects.append("a reader built from a returned export is not seeded with its notes")
    # A browser that cannot store: the box still takes a note and the page still says so.
    sixth = drive(reader, [{"type": "type", "id": frags[0].id, "value": "kept"}], noStorage=True)
    if sixth["values"][frags[0].id] != "kept" or not sixth["status"]:
        defects.append("a browser without storage broke the note box or stayed silent")
    return defects


#: A note keyed by something that is not a fragment id, written to close a
#: string literal and run as code if the script's data were ever re-read.
HOSTILE_SEED = {"+PWNED()/*": {"quote": "*/+0/*", "note": "*/+"}}


def _contract_script_data(
    document: str, parts: Sequence[Part], title: str, language: str
) -> list[str]:
    """The data the script carries is the document's own, never something else.

    The reader is rebuilt with a seed that tries to break out of its string
    literal, and the data block is read back out of the emitted script and
    compared with the fragments, whatever placeholders the document or title
    spell.
    """
    reader = build_reader(
        document, title=title, reader_language=language, document_language="de", notes=HOSTILE_SEED
    )
    try:
        drive(reader, [])
    except ReaderError as exc:
        return [f"a hostile seed broke the script: {exc}"]
    script = _script_of(reader)
    found = re.search(r"var DOC = (\{.*?\});\n", script, flags=re.S)
    try:
        doc = json.loads(found.group(1)) if found else {}
    except ValueError:
        return ["the script's data block is not JSON"]
    frags = [p for p in parts if isinstance(p, Fragment)]
    defects = []
    if doc.get("quotes") != {f.id: f.text for f in frags}:
        defects.append("the script's quotes are not the fragments' text")
    if doc.get("order") != [f.id for f in frags]:
        defects.append("the script's fragment order is not the document's")
    if doc.get("title") != title:
        defects.append("the script's title is not the title")
    return defects


def _reader_language_of(reader: str) -> str:
    match = re.search(r'class="note" lang="([^"]+)"', reader)
    return match.group(1) if match else "en"


def _document_language_of(reader: str) -> str:
    match = re.search(r'<html\slang="([^"]+)"', reader)
    return match.group(1) if match else "en"


def _contract_i18n(
    reader: str, catalogue: Mapping[str, Any], language: str, other: str
) -> list[str]:
    """Every shown string is the candidate's, the document's language untouched."""
    defects = []
    # Expected text comes from `strings` directly, never from `reader_strings`:
    # a contract that asks the generator what it should have produced agrees
    # with every generator, including one that always answers in English.
    keys = strings.keys(catalogue)
    table = {key: strings.text(catalogue, key, language) for key in keys}
    source_language = catalogue["source_language"]
    source = {key: strings.text(catalogue, key, source_language) for key in keys}
    shown = html.unescape(re.sub(r"<script>.*?</script>", "", reader, flags=re.S))
    script = _script_of(reader)
    carried = re.search(r"var T = (\{.*?\});\n", script, flags=re.S)
    try:
        in_script = json.loads(carried.group(1)) if carried else {}
    except ValueError:
        in_script = {}
    for key in keys:
        if in_script.get(key) != table[key]:
            defects.append(f"the script's string {key} is not the {language} text")
    for key in sorted(set(keys) - script_keys()):
        if table[key] not in shown:
            defects.append(f"{key} is not shown in {language}")
    if language != source_language:
        for key in keys:
            if source[key] != table[key] and source[key] in shown:
                defects.append(f"{key} is shown in {source_language}, not {language}")
    for key in sorted(script_keys() - set(keys)):
        defects.append(f"the script reads {key}, which the catalogue lacks")
    if _document_language_of(reader) != other:
        defects.append("the document's own language was replaced by the reader's")
    if _reader_language_of(reader) != language:
        defects.append("the reader's own controls are not marked with the reader's language")
    if f'<div class="reader-bar" lang="{language}">' not in reader:
        defects.append("the toolbar is not marked with the reader's language")
    if shown.count(f'lang="{language}"') < 2:
        defects.append("the note boxes are not marked with the reader's language")
    return defects


def _contract_no_literals(document: str, catalogue: Mapping[str, Any], title: str) -> list[str]:
    """With every string a sentinel, the export holds no words that are not
    sentinels or the candidate's own: nothing the script says is its own."""
    sentinels = {k: f"«{k}»" for k in strings.keys(catalogue)}
    fake = {
        **catalogue,
        "entries": {
            key: {lang: sentinels[key] for lang in catalogue["languages"]} for key in sentinels
        },
    }
    reader = build_reader(
        document, title=title, reader_language=catalogue["source_language"], catalogue=fake
    )
    frags = [p for p in fragment(document) if isinstance(p, Fragment)]
    note = "n0te"
    out = drive(
        reader,
        [{"type": "type", "id": frags[0].id, "value": note}, {"type": "export"}],
    )
    residue = out["download"]["text"] if out.get("download") else ""
    start = residue.index("<!--") if "<!--" in residue else len(residue)
    residue = residue[:start]
    for sentinel in sentinels.values():
        residue = residue.replace(sentinel.replace("{title}", ""), "")
    for text in (frags[0].id, frags[0].text, note, title):
        residue = residue.replace(text, "")
    leftover = re.findall(r"[^\W\d_]{2,}", residue)
    defects = [f"the export contains text of its own: {leftover[:5]}"] if leftover else []
    status = out.get("status") or ""
    status_words = re.findall(r"[^\W\d_]{2,}", re.sub(r"«[a-z_]+»", "", status))
    if status_words:
        defects.append(f"the status line contains text of its own: {status_words[:5]}")
    return defects


# --------------------------------------------------------------------------
# What the gate runs the contracts over

_LONG_PARAGRAPH = (
    "Ich bewerbe mich auf die ausgeschriebene Stelle, weil sie Erfahrung mit Datenplattformen und "
    "mit der Zusammenarbeit zwischen Fachbereichen verbindet, die ich in den letzten Jahren "
    "aufgebaut habe."
)


def _letter() -> str:
    """Eleven paragraphs inside one `<div class="letter">` — defect 1's shape."""
    paragraphs = "\n".join(f"<p>{_LONG_PARAGRAPH} Absatz {n}.</p>" for n in range(1, 12))
    return f'<div class="letter"><h1>Anschreiben</h1>\n{paragraphs}\n</div>'


def _cv() -> str:
    """Short headings, an 18-character project header, header lines — defect 2's shape."""
    return (
        '<header><div class="hdr">Ana Pérez</div>'
        '<div class="hdr">a@b.example · Girona</div></header>'
        "<h2>Projects</h2>"
        '<div class="project"><h3>opos — oposiciones</h3><p class="hdr">opos project</p>'
        "<ul><li>Built the importer</li>"
        "<li>Wrote the <strong>tests</strong> &amp; the docs</li></ul></div>"
        "<h2>Education &amp; certifications</h2>"
        "<ol><li>Grado en Ingeniería</li><li>Máster</li></ol>"
        "<p>Short.</p>"
    )


def _awkward() -> str:
    """Structures a boundary rule can mishandle: a nested list, a paragraph inside an
    item, loose text, omitted end tags, markup that must stay inert, and a photo."""
    return (
        "<head><title>t</title><style>p{color:red}</style></head><body>"
        '<header class="photo"><img src="data:image/png;base64,AAAA" alt="x"></header>'
        "<div>loose text in a div<br>second line</div>"
        "<ul><li>Skills<ul><li>Python</li><li>SQL</li></ul></li>"
        "<li><p>An item holding a paragraph</p><p>and another</p></li></ul>"
        "<p>Unclosed paragraph<p>Second, also unclosed"
        "<p>__SEED__ __DOC__ __MARK__ __VERSION__ __STRINGS__</p>"
        '<p>Hostile &lt;/textarea&gt; <script>alert(1)</script><b onclick="x()">bold</b> '
        '<a href="javascript:alert(1)">link</a></p>'
        "<header><div>Plain header line</div></header>"
        "<h3>x</h3><hr></body>"
    )


@dataclass(frozen=True)
class Subject:
    name: str
    document: str
    title: str


SUBJECTS = (
    Subject("letter", _letter(), "Anschreiben: Datenplattform"),
    Subject("cv", _cv(), "Lebenslauf — Ana Pérez"),
    Subject("awkward", _awkward(), 'Awkward "doc" </title><script> __SEED__'),
)


def _contract_inert(reader: str) -> list[str]:
    body = reader[: reader.rindex("<script>")]
    defects = []
    for needle in ("alert(1)", "onclick", "javascript:", "<style>p{color"):
        if needle in body.replace(_style_of(reader), ""):
            defects.append(f"the document's own {needle!r} reached the reader")
    if body.count("<script") != 0:
        defects.append("a script other than the reader's own is in the page")
    return defects


def measure(catalogue_path: Path = DEFAULT_CATALOGUE) -> dict[str, Any]:
    """T141's gate reading: contract failures over generated readers."""
    if node_path() is None:
        return _unmeasured("node is not installed: the reader's script cannot be parsed or run")
    try:
        catalogue = load_catalogue(catalogue_path)
    except ReaderError as exc:
        return _unmeasured(str(exc))
    defects: list[str] = []
    contracts = 0
    readers = 0

    def record(label: str, found: list[str]) -> None:
        nonlocal contracts
        contracts += 1
        defects.extend(f"{label}: {d}" for d in found)

    record("catalogue missing", strings.missing(catalogue))
    record("catalogue stale", strings.stale(catalogue))
    record(
        "catalogue languages",
        []
        if set(catalogue["languages"]) == set(corpus.LANGUAGES)
        else ["differ from corpus.LANGUAGES"],
    )
    languages = list(catalogue["languages"])
    for subject in SUBJECTS:
        parts = fragment(subject.document)
        for language in languages:
            label = f"{subject.name}/{language}"
            try:
                reader = build_reader(
                    subject.document,
                    title=subject.title,
                    reader_language=language,
                    document_language="de",
                    catalogue=catalogue,
                )
            except ReaderError as exc:
                record(label, [f"no reader was produced: {exc}"])
                continue
            readers += 1
            record(f"{label} balance", _contract_balance(subject.document, parts, reader))
            record(f"{label} headings", _contract_headings(subject.document, parts))
            record(f"{label} inert", _contract_inert(reader))
            record(
                f"{label} data",
                _contract_script_data(subject.document, parts, subject.title, language),
            )
            record(f"{label} i18n", _contract_i18n(reader, catalogue, language, "de"))
            record(f"{label} layout", widths_layout(_style_of(reader)))
            record(f"{label} behaviour", _contract_behaviour(reader, parts, subject.title))
        record(
            f"{subject.name} no literals",
            _contract_no_literals(subject.document, catalogue, subject.title),
        )
    # The refusal itself: a script that does not compile must not become a reader.
    refused = _refuses_broken_script()
    record("a broken script is refused", refused)
    if contracts < MINIMUM_CONTRACTS_EVALUATED:
        return _unmeasured(
            f"only {contracts} contract(s) evaluated (floor {MINIMUM_CONTRACTS_EVALUATED})"
        )
    return {
        "reader_fragment_defects": len(defects),
        "contracts_evaluated_at_least": MINIMUM_CONTRACTS_EVALUATED,
        "readers_generated": readers,
        "reader_languages": languages,
        "documents_evaluated": [s.name for s in SUBJECTS],
        "reading_widths": list(READING_WIDTHS),
        "gate_status": "measured",
        "defects": defects,
    }


def _refuses_broken_script() -> list[str]:
    """`check_script` must say no to the defect-3 shape, and build_reader must follow it."""
    broken = 'var s = "a\nb";'  # a literal newline inside a string: the browser drops the script
    if check_script(broken) is None:
        return ["check_script accepted a script with a newline inside a string"]
    if check_script("var s = 1;") is not None:
        return ["check_script rejected a valid script"]
    original = _SCRIPT
    try:
        globals()["_SCRIPT"] = _SCRIPT.replace('"use strict";', 'var s = "a\nb";', 1)
        try:
            build_reader("<p>x</p>", title="t", reader_language="en")
        except ReaderError:
            return []
        return ["build_reader returned a reader whose script does not compile"]
    finally:
        globals()["_SCRIPT"] = original


def _unmeasured(reason: str) -> dict[str, Any]:
    return {
        "reader_fragment_defects": -1,
        "gate_status": "unmeasured",
        "reasons": [reason],
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.document_reader` → T141's evidence; `build` makes a reader."""
    parser = argparse.ArgumentParser(prog="integral.document_reader")
    sub = parser.add_subparsers(dest="command")
    build = sub.add_parser("build", help="make an annotatable reader from a generated document")
    build.add_argument("document", type=Path)
    build.add_argument("--title", required=True)
    build.add_argument("--reader-language", required=True, help="the candidate's language")
    build.add_argument("--document-language", default="en", help="the document's language")
    build.add_argument("--notes", type=Path, help="a returned export to seed the boxes from")
    build.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv[1:])
    if args.command == "build":
        seeded = None
        if args.notes is not None:
            seeded = parse_export(args.notes.read_text(encoding="utf-8"))
            if seeded is None:
                print(f"{args.notes} is not an export from this reader", file=sys.stderr)
                return 2
        try:
            reader = build_reader(
                args.document.read_text(encoding="utf-8"),
                title=args.title,
                reader_language=args.reader_language,
                document_language=args.document_language,
                notes=seeded,
            )
        except ReaderError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        args.output.write_text(reader, encoding="utf-8")
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
