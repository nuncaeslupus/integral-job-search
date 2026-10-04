"""T241: every page the package writes shares one style and goes through one shell.

The population is derived from the source of ``src/integral`` with ``ast`` (never
imported: nothing in that package may load code), not listed here. Two things
count as writing a page:

* a string literal that *opens a document* (``<!doctype html`` or ``<html``), and
* a function that writes a file (``write_text``/``write_bytes``/``write``/``open``)
  and names a ``.html`` path.

Only ``report_style.page`` may open a document. Anything else the scan finds must
be a recorded ``NOT_A_REPORT`` entry, and each entry must still match something,
so the list can only shrink: a new bypass fails here, and a stale entry fails here.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest

from integral import report_style
from integral.application_render import render_document
from integral.report_style import (
    CSP,
    TOKENS,
    card,
    chip,
    external_references,
    facts,
    page,
    tiles,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "integral"
SHELL = "report_style"

_OPENER = re.compile(r"<!doctype html|<html[\s>]", re.I)
_WRITE_CALLS = {"write_text", "write_bytes", "write", "open"}

Finding = tuple[str, str, str]  # (module, scope, kind)
Findings = Counter[Finding]

OPENS = "opens a document"
WRITES = "writes an .html file"
_HTML_NAME = re.compile(r"\.html?\b", re.I)
_HTML_FILENAME = re.compile(r"\S*\.html?", re.I)  # a name, not prose that mentions one


def _scopes(tree: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    """Every node with the innermost function or class that holds it.

    Top level is ``<module>``; a class body is ``<class Name>``, so an exemption for
    the module does not cover a template tucked into a class.
    """

    def walk(node: ast.AST, scope: str) -> Iterator[tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield from walk(child, child.name)
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"<class {child.name}>")
            else:
                yield scope, child
                yield from walk(child, scope)

    yield from walk(tree, "<module>")


def page_writes(source: str, module: str) -> Findings:
    """What in ``source`` opens a document or writes a file at an ``.html`` name.

    A string constant is read as markup or a name, never a docstring (a bare string
    statement). A ``.html`` name counts for the function that holds it **and** for
    every writing function in the module when it sits at module scope as a bare
    filename or suffix (prose that merely mentions one does not count), so a path
    constant defined once and written from a function is still seen. Writes are
    ``write_text``/``write_bytes``/``write``/``open`` calls; others
    (``os.fdopen``, ``writelines``, ``print(file=)``) are not recognised.
    """
    tree = ast.parse(source)
    docstrings = {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }
    found: Findings = Counter()
    writes: set[str] = set()
    names_html: set[str] = set()
    module_names = False  # a bare filename or suffix held outside any function
    for scope, node in _scopes(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if _OPENER.search(node.value):
                found[(module, scope, OPENS)] += 1
            if _HTML_NAME.search(node.value):
                names_html.add(scope)
            if scope.startswith("<") and _HTML_FILENAME.fullmatch(node.value):
                module_names = True
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            if name in _WRITE_CALLS:
                writes.add(scope)
    for scope in writes:
        if scope in names_html or module_names:
            found[(module, scope, WRITES)] += 1
    return found


def package_population(src: Path = SRC) -> Findings:
    found: Findings = Counter()
    for path in sorted(src.rglob("*.py")):
        name = ".".join(path.relative_to(src).with_suffix("").parts)
        found += page_writes(path.read_text(encoding="utf-8"), name)
    return found


#: Markup the package holds that no person ever reads as a report: stand-ins for a
#: board's response and the copies of one, built for a probe or a fixture. Keyed by
#: module, scope and kind, with how many matches it covers, so an exemption cannot
#: absorb a second opener or a different kind of finding.
NOT_A_REPORT: dict[Finding, tuple[int, str]] = {
    ("connector_exchange", "_stale_source", OPENS): (1, "an empty list page for a fixture"),
    ("connector_exchange", "_stale_source", WRITES): (1, "writes that page into a fixture"),
    ("connector_health", "<module>", OPENS): (12, "simulated board responses (WAF, 429, a list)"),
    ("exclusion_live_round", "measure_live_round", OPENS): (1, "a served board page, offline"),
    ("liveness", "<module>", OPENS): (1, "a sample board page the liveness probe parses"),
    ("markup_text", "<module>", OPENS): (1, "hostile markup fed to the text extractor"),
    ("search_terms", "answer", OPENS): (1, "a stubbed board response"),
    ("sourcing", "flood_board", OPENS): (1, "generated board pages for the reach measurement"),
    ("sourcing", "measure_browser_route", WRITES): (1, "board captures in a temporary directory"),
}


def _unrecorded(findings: Findings) -> Findings:
    """Findings the shell or a recorded exemption does not account for, exactly."""
    left: Findings = Counter()
    for key, count in findings.items():
        if key[0] == SHELL:
            continue
        allowed = NOT_A_REPORT.get(key, (0, ""))[0]
        if count > allowed:
            left[key] = count - allowed
    return left


# --- the population is read from the source, and the check can tell ---------------


def test_the_scan_sees_the_shell_and_every_exempt_module() -> None:
    """The scan's modules are exactly the shell and the exempt ones: no floor to be short by."""
    found = package_population()
    assert found[(SHELL, "page", OPENS)] == 1
    assert {m for m, _, _ in found} == {m for m, _, _ in NOT_A_REPORT} | {SHELL}
    assert len(list(SRC.rglob("*.py"))) > 100


def test_only_the_shell_opens_a_document_or_writes_a_page() -> None:
    assert _unrecorded(package_population()) == Counter()


def test_every_exemption_matches_exactly_what_it_records() -> None:
    found = package_population()
    assert {k: v for k, (v, _) in NOT_A_REPORT.items()} == {k: found[k] for k in NOT_A_REPORT}


def test_the_shell_has_exactly_one_document_opener() -> None:
    found = page_writes((SRC / f"{SHELL}.py").read_text(encoding="utf-8"), SHELL)
    assert found == Counter({(SHELL, "page", OPENS): 1})


BYPASSES = [
    ("literal opener", "def render(x):\n    return '<!doctype html><html>' + x\n", OPENS),
    ("html path", "def save(d, t):\n    (d / 'board.html').write_text(t)\n", WRITES),
    ("htm path, upper case", "def save(d, t):\n    (d / 'BOARD.HTM').write_text(t)\n", WRITES),
    (
        "module-scope name, fragment body",
        "NAME = 'board.html'\ndef save(d, rows):\n    (d / NAME).write_text('<h1>x</h1>' + rows)\n",
        WRITES,
    ),
    (
        "module-scope suffix",
        "SUFFIX = '.html'\ndef save(d, n, t):\n    open(str(d / n) + SUFFIX, 'w').write(t)\n",
        WRITES,
    ),
    ("class-body template", "class R:\n    TEMPLATE = '<!doctype html><p>x'\n", OPENS),
    (
        "written through the shell, still a page write",
        "from integral.report_style import page\n"
        "def save(d, x):\n    (d / 'board.html').write_text(page('t', x))\n",
        WRITES,
    ),
]


@pytest.mark.parametrize("name,source,kind", BYPASSES, ids=[b[0] for b in BYPASSES])
def test_a_writer_that_bypasses_the_shell_is_found(name: str, source: str, kind: str) -> None:
    left = _unrecorded(page_writes(source, "newreport"))
    assert {k[2] for k in left} == {kind}, name


def test_the_scan_reads_subpackages(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "board.py").write_text("T = '<!doctype html>'\n", encoding="utf-8")
    assert package_population(tmp_path) == Counter({("reports.board", "<module>", OPENS): 1})


def test_prose_that_mentions_html_is_not_a_page_write() -> None:
    prose = (
        '"""Reads fixture/list.html."""\n'
        "NOTE = 'see connectors/x/fixture/detail.html: a unitText'\n"
        "def save(d, t):\n    (d / 'out.json').write_text(t)\n"
    )
    assert page_writes(prose, "m") == Counter()


def test_an_exemption_does_not_cover_a_second_opener_a_new_kind_or_a_class() -> None:
    key = ("sourcing", "flood_board", OPENS)
    two = Counter({key: NOT_A_REPORT[key][0] + 1})
    assert _unrecorded(two) == Counter({key: 1})
    assert _unrecorded(Counter({("sourcing", "flood_board", WRITES): 1})) != Counter()
    assert (
        _unrecorded(page_writes("class R:\n    T = '<!doctype html>'\n", "liveness")) != Counter()
    )


def test_the_letter_and_cv_writer_calls_the_shell() -> None:
    tree = ast.parse((SRC / "application_render.py").read_text(encoding="utf-8"))
    (render,) = [
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "render_document"
    ]
    called = {
        n.func.id
        for n in ast.walk(render)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "page" in called


# --- the stylesheet ---------------------------------------------------------------


def _block(css: str, head: str) -> str:
    """The body of the first top-level ``head { ... }`` rule, by brace counting."""
    start = css.index(head + " {") + len(head) + 2
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[start : i - 1]


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z]+):\s*([^;]+);", block))


def test_tokens_are_named_once_for_light_and_once_for_dark() -> None:
    css = report_style.STYLESHEET
    light = _tokens(_block(css, ":root"))
    dark = _tokens(_block(_block(css, "@media (prefers-color-scheme: dark)"), ":root"))
    assert (
        tuple(light)
        == tuple(dark)
        == TOKENS
        == ("surface", "ink", "muted", "line", "accent", "positive", "negative")
    )
    assert all(light[name] != dark[name] for name in TOKENS)
    assert css.count("prefers-color-scheme") == 1


def test_no_colour_is_spelled_outside_the_token_blocks() -> None:
    css = report_style.COMPONENTS
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    used = set(re.findall(r"var\(--([a-z]+)\)", css))
    assert used == set(TOKENS)  # every role is used, so none is dead


def test_the_fact_grid_is_three_columns_and_collapses_on_a_phone() -> None:
    css = report_style.STYLESHEET
    assert re.search(r"\.facts \{[^}]*repeat\(3, 1fr\)", css)
    phone = _block(css, f"@media (max-width: {report_style.PHONE_WIDTH})")
    assert re.search(r"\.facts \{[^}]*grid-template-columns: 1fr;", phone)


def test_the_components_render_escaped_markup() -> None:
    hostile = '<script>x</script> & "q"'
    for markup in (
        tiles([(hostile, hostile)]),
        card(hostile, "<p>ok</p>"),
        chip(hostile, "positive"),
        facts([(hostile, hostile)]),
    ):
        assert "<script>" not in markup
        assert "&lt;script&gt;" in markup
    assert 'class="chip negative"' in chip("x", "negative")
    assert 'class="chip"' in chip("x")
    with pytest.raises(ValueError):
        chip("x", "loud")
    assert tiles([("a", 1), ("b", 2)]).count('class="tile"') == 2
    assert facts([("a", "1")] * 4).count("<dt>") == 4


# --- the shell --------------------------------------------------------------------


def test_the_shell_is_a_complete_document_with_the_policy_first() -> None:
    doc = page("Board", "<main>x</main>")
    assert doc.startswith("<!doctype html>\n")
    assert doc.index(CSP) < doc.index("<title>") < doc.index("<style>") < doc.index("<body")
    assert "prefers-color-scheme: dark" in doc
    assert 'name="viewport"' in doc


def test_a_printed_document_gets_light_tokens_only() -> None:
    doc = render_document("# H", title="t")
    assert "prefers-color-scheme" not in doc
    assert "--surface" in doc
    assert "@page" in doc


def test_the_shell_escapes_the_title_and_validates_lang_and_class() -> None:
    assert "<script>" not in page("</title><script>x</script>", "")
    with pytest.raises(ValueError):
        page("t", "", lang='en"><script>')
    with pytest.raises(ValueError):
        page("t", "", body_class='x"><script>')


# --- self-contained ---------------------------------------------------------------

EXTERNAL = [
    ("stylesheet link", '<link rel="stylesheet" href="https://fonts.example/a.css">'),
    ("preload font link", '<link rel="preload" href="a.woff2" as="font">'),
    ("script src", '<script src="https://cdn.example/x.js"></script>'),
    ("relative script src", '<script src="x.js"></script>'),
    ("remote image", '<img src="https://x.example/a.png">'),
    ("iframe", '<iframe src="https://x.example/"></iframe>'),
    ("srcset", '<img srcset="a.png 2x" src="data:image/png;base64,AA==">'),
    ("css import", "<style>@import url(https://x.example/a.css);</style>"),
    ("css url", "<style>body{background:url(https://x.example/a.png)}</style>"),
    ("inline style url", '<div style="background:url(a.png)"></div>'),
    ("base", '<base href="https://x.example/">'),
    ("object data", '<object data="https://x.example/a.swf"></object>'),
    ("video poster", '<video poster="https://x.example/a.png"></video>'),
    ("form action", '<form action="https://x.example/post"></form>'),
    ("button formaction", '<form><button formaction="https://x.example/p">x</button></form>'),
    ("upper-case URL()", "<style>a{background:URL(https://x.example/a.png)}</style>"),
    ("upper-case @IMPORT", "<style>@IMPORT url(https://x.example/a.css);</style>"),
    (
        "css-escaped url(",
        r"<style>@font-face{font-family:f;src:\75rl(https://fonts.example/f.woff2)}</style>",
    ),
    ("css-escaped @import", r'<style>@\69mport "https://x.example/a.css";</style>'),
    (
        "css-escaped url( in style=",
        r'<div style="background:\75 rl(https://x.example/a.png)"></div>',
    ),
    ("meta refresh", '<meta http-equiv="Refresh" content="0;url=https://x.example/">'),
]


@pytest.mark.parametrize("name,markup", EXTERNAL, ids=[n for n, _ in EXTERNAL])
def test_a_body_that_reaches_for_the_network_is_refused(name: str, markup: str) -> None:
    assert external_references(markup), name
    with pytest.raises(ValueError, match="self-contained"):
        page("t", markup)


def test_data_uris_and_plain_links_are_not_external() -> None:
    ok = '<img src="data:image/png;base64,AA=="><a href="https://x.example/job/1">job</a>'
    assert external_references(ok) == []
    assert "job/1" in page("t", ok)
    assert external_references("<style>a{background:url(data:image/png;base64,AA==)}</style>") == []


def test_the_shell_stylesheets_load_nothing() -> None:
    assert external_references(page("t", tiles([("a", 1)]) + facts([("a", "b")]))) == []
    assert "font-face" not in report_style.STYLESHEET
    assert "default-src 'none'" in CSP
    assert "script-src" not in CSP and "connect-src" not in CSP


# --- the policy is pinned by its effect, not by a substring -----------------------

CSP_DIRECTIVES = {
    "default-src": ["'none'"],
    "img-src": ["data:"],
    "style-src": ["'unsafe-inline'"],
}


class _Head(HTMLParser):
    """The elements of a document in order, with whether each is inside ``<head>``."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self.seen: list[tuple[str, dict[str, str | None], bool]] = []
        self._in_head = False
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._in_head = self._in_head or tag == "head"
        self.seen.append((tag, dict(attrs), self._in_head))

    def handle_endtag(self, tag: str) -> None:
        self._in_head = self._in_head and tag != "head"


def _policy(document: str) -> dict[str, list[str]]:
    """The directives of the one ``http-equiv`` CSP meta that is in force, in ``<head>``."""
    elements = _Head(document).seen
    policies = [
        (i, attrs["content"] or "")
        for i, (tag, attrs, in_head) in enumerate(elements)
        if tag == "meta"
        and (attrs.get("http-equiv") or "").lower() == "content-security-policy"
        and in_head
    ]
    assert len(policies) == 1, "exactly one Content-Security-Policy meta, inside <head>"
    index, content = policies[0]
    first_content = next(
        i for i, (tag, _, _) in enumerate(elements) if tag in ("title", "style", "link", "script")
    )
    assert index < first_content, "the policy precedes every title, style and script"
    out: dict[str, list[str]] = {}
    for directive in filter(None, (d.strip() for d in content.split(";"))):
        name, *values = directive.split()
        assert name not in out, f"{name} declared twice"
        out[name] = values
    return out


def test_the_shell_emits_exactly_this_policy_before_anything_loads() -> None:
    assert _policy(page("t", "x")) == CSP_DIRECTIVES
    assert _policy(page("t", "x", adaptive=False)) == CSP_DIRECTIVES
    assert _policy(render_document("# H", title="t")) == CSP_DIRECTIVES


def test_the_policy_constant_is_that_directive_set() -> None:
    assert {n: v.split() for n, v in (d.strip().split(" ", 1) for d in CSP.split(";"))} == (
        CSP_DIRECTIVES
    )


@pytest.mark.parametrize(
    "broken",
    [
        "default-src 'none'; img-src * data:; font-src *; style-src * 'unsafe-inline'",
        "default-src *; img-src data:; style-src 'unsafe-inline'",
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src *",
        "default-src 'none'; img-src data:",
    ],
)
def test_a_wider_policy_is_not_this_policy(broken: str) -> None:
    doc = page("t", "x").replace(CSP, broken)
    assert doc != page("t", "x")
    assert _policy(doc) != CSP_DIRECTIVES


def test_a_meta_that_is_not_a_policy_is_not_one() -> None:
    renamed = page("t", "x").replace('http-equiv="Content-Security-Policy"', 'name="csp-note"')
    with pytest.raises(AssertionError, match="exactly one"):
        _policy(renamed)
    late = (
        page("t", "x")
        .replace('<meta http-equiv="Content-Security-Policy" content="' + CSP + '">\n', "")
        .replace("</style>", '</style><meta http-equiv="Content-Security-Policy" content="x">')
    )
    with pytest.raises(AssertionError, match="precedes"):
        _policy(late)
