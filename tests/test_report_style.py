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
from collections.abc import Iterator
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

Finding = tuple[str, str, str]  # (module, function, kind)


def _scopes(tree: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    """Every node with the innermost function that holds it (``<module>`` at top level)."""

    def walk(node: ast.AST, fn: str) -> Iterator[tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield from walk(child, child.name)
            else:
                yield fn, child
                yield from walk(child, fn)

    yield from walk(tree, "<module>")


def page_writes(source: str, module: str) -> set[Finding]:
    """What in ``source`` opens a document or writes an ``.html`` file."""
    found: set[Finding] = set()
    writes: set[str] = set()
    names_html: set[str] = set()
    for fn, node in _scopes(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _OPENER.search(node.value):
                found.add((module, fn, "opens a document"))
            if ".html" in node.value:
                names_html.add(fn)
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            if name in _WRITE_CALLS:
                writes.add(fn)
    found |= {(module, fn, "writes an .html file") for fn in writes & names_html}
    return found


def package_population() -> set[Finding]:
    found: set[Finding] = set()
    for path in sorted(SRC.glob("*.py")):
        found |= page_writes(path.read_text(encoding="utf-8"), path.stem)
    return found


#: Markup the package holds that no person ever reads as a report: stand-ins for a
#: board's response and the copies of one, built for a probe or a fixture.
NOT_A_REPORT: dict[tuple[str, str], str] = {
    (
        "connector_exchange",
        "_stale_source",
    ): "an empty list page scaffolded into a connector fixture",
    ("connector_health", "<module>"): "simulated board responses (WAF, rate limit, a real list)",
    ("exclusion_live_round", "measure_live_round"): "a served board page for the offline round",
    ("liveness", "<module>"): "a sample board page the liveness probe parses",
    ("markup_text", "<module>"): "hostile markup fed to the text extractor",
    ("search_terms", "answer"): "a stubbed board response",
    ("sourcing", "flood_board"): "generated board pages for the reach measurement",
    ("sourcing", "measure_browser_route"): "board captures copied into a temporary directory",
}


def _unrecorded(findings: set[Finding]) -> set[Finding]:
    return {f for f in findings if f[0] != SHELL and (f[0], f[1]) not in NOT_A_REPORT}


# --- the population is read from the source, and the check can tell ---------------


def test_the_scan_sees_the_shell_and_the_known_stand_ins() -> None:
    """A denominator: a scan that read nothing would pass the checks below vacuously."""
    found = package_population()
    assert (SHELL, "page", "opens a document") in found
    assert len({module for module, _, _ in found}) >= 7
    assert len(list(SRC.glob("*.py"))) > 100


def test_only_the_shell_opens_a_document_or_writes_a_page() -> None:
    assert _unrecorded(package_population()) == set()


def test_every_exemption_still_matches_something() -> None:
    present = {(module, fn) for module, fn, _ in package_population()}
    assert set(NOT_A_REPORT) - present == set()


def test_the_shell_has_exactly_one_document_opener() -> None:
    openers = [
        f
        for f in page_writes((SRC / f"{SHELL}.py").read_text(encoding="utf-8"), SHELL)
        if f[2] == "opens a document"
    ]
    assert openers == [(SHELL, "page", "opens a document")]


def test_a_writer_that_bypasses_the_shell_is_found() -> None:
    literal = "def render(x):\n    return '<!doctype html><html><body>' + x\n"
    assert _unrecorded(page_writes(literal, "newreport")) == {
        ("newreport", "render", "opens a document")
    }
    by_path = "def save(d, text):\n    (d / 'board.html').write_text(text)\n"
    assert _unrecorded(page_writes(by_path, "newreport")) == {
        ("newreport", "save", "writes an .html file")
    }
    through_shell = (
        "from integral.report_style import page\n"
        "def render(x):\n    return page('t', x)\n"
        "def save(d, x):\n    (d / 'board.html').write_text(render(x))\n"
    )
    # the .html write is still a write of a page: it must be recorded, not assumed fine
    assert _unrecorded(page_writes(through_shell, "newreport")) == {
        ("newreport", "save", "writes an .html file")
    }


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
