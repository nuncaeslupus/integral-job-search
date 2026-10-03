"""T181: the application renders to one printable, escaped HTML file."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from integral.application_render import render_document

HOSTILE = '<script>alert(1)</script> & "q" <img src=x onerror=y>'


class Doc(HTMLParser):
    """Parse the output rather than grep it: tests see what a browser sees."""

    def __init__(self, source: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []
        self.css = ""
        self._in_style = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        self.tags.append((tag, dict(attrs)))
        self._in_style = tag == "style"

    def handle_endtag(self, tag):  # type: ignore[no-untyped-def]
        self._in_style = False

    def handle_data(self, data):  # type: ignore[no-untyped-def]
        if self._in_style:
            self.css += data
        else:
            self.text.append(data)

    def names(self) -> list[str]:
        return [t for t, _ in self.tags]


def test_escape_precedes_bold_substitution() -> None:
    out = render_document("Això és **l'equip d'Anna** gran.", title="t")
    assert "<strong>l'equip d'Anna</strong>" in out
    assert "&amp;#x27;" not in out
    assert "l'equip d'Anna" in "".join(Doc(out).text)


def test_output_is_a_single_file() -> None:
    for kind in ("letter", "cv"):
        out = render_document(
            f"# H\n\n- {HOSTILE}\n\n{HOSTILE}",
            title=HOSTILE,
            kind=kind,
            photo=b"\x89PNG-bytes" if kind == "cv" else None,
            photo_mime="image/png",
        )
        doc = Doc(out)
        for tag, attrs in doc.tags:
            assert tag not in {"link", "script", "iframe", "object", "embed"}
            for name in ("href", "src", "srcset", "poster", "data", "action"):
                value = attrs.get(name)
                if value is not None:
                    assert (tag, name) == ("img", "src")
                    assert value.startswith("data:image/png;base64,")
            assert not [a for a in attrs if a.startswith("on")]
        assert "@import" not in doc.css
        assert not re.search(r"url\(\s*['\"]?(?!data:)", doc.css)


Rule = tuple[str, tuple[str, ...], dict[str, str]]  # (context, selectors, declarations)


def _decls(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in block.split(";"):
        if ":" in part:
            name, _, value = part.partition(":")
            out[name.strip().lower()] = " ".join(value.split())
    return out


def _parse_css(css: str) -> list[Rule]:
    """Flat list of rules; context is 'top', 'media:<query>' for one nesting level."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[Rule] = []

    def walk(text: str, context: str) -> None:
        i = 0
        while True:
            head_end = text.find("{", i)
            if head_end < 0:
                return
            head = " ".join(text[i:head_end].split())
            depth, k = 1, head_end + 1
            while depth and k < len(text):
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[head_end + 1 : k - 1]
            if head.startswith("@media"):
                walk(body, "media:" + head[len("@media") :].strip())
            else:
                selectors = tuple(x.strip() for x in head.split(","))
                rules.append((context, selectors, _decls(body)))
            i = k

    walk(css, "top")
    return rules


def _print_rule_violations(css: str) -> list[str]:
    """Why this stylesheet does not carry the print rules the spec requires."""
    rules = _parse_css(css)
    live = ("top", "media:print")  # contexts that apply when printing
    want: list[tuple[str, str, str]] = [
        ("@page", "size", "A4"),
        ("@page", "margin", "22mm 24mm"),
        ("p", "orphans", "3"),
        ("p", "widows", "3"),
        ("li", "orphans", "3"),
        ("li", "widows", "3"),
        ("h1", "break-after", "avoid"),
        ("h2", "break-after", "avoid"),
        ("h3", "break-after", "avoid"),
    ]
    found: list[str] = []
    for selector, prop, value in want:
        values = [
            (ctx, decls[prop])
            for ctx, sels, decls in rules
            if selector in sels and prop in decls and ctx in live
        ]
        if not values:
            found.append(f"{selector} {prop}: no declaration that applies in print")
        elif values[-1][1] != value:
            found.append(f"{selector} {prop}: final value {values[-1][1]!r}, want {value!r}")
        found += [f"{selector} {prop}: {v!r} is not {value!r}" for _, v in values if v != value]
    return sorted(set(found))


def test_print_rules_are_present() -> None:
    css = Doc(render_document("# H", title="t")).css
    assert _print_rule_violations(css) == []


BASE = Doc(render_document("# H", title="t")).css


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("P1 landscape", "size: A4;", "size: A4 landscape;"),
        ("P2 extra margin", "margin: 22mm 24mm;", "margin: 22mm 24mm 0 0;"),
        ("P3 widows 30", "p, li { orphans: 3; widows: 3; }", "p, li { orphans: 3; widows: 30; }"),
        ("P4 avoid-column", "break-after: avoid;", "break-after: avoid-column;"),
        (
            "P5 commented out",
            "p, li { orphans: 3; widows: 3; }",
            "/* p, li { orphans: 3; widows: 3; } */",
        ),
        (
            "P6 screen only",
            "@media print {\n  @page { size: A4; margin: 22mm 24mm; }",
            "@media screen {\n  @page { size: A4; margin: 22mm 24mm; }",
        ),
        (
            "P7 later override",
            "li { break-inside: avoid; }",
            "li { break-inside: avoid; }\np, li { orphans: 1; widows: 1; }",
        ),
    ],
)
def test_broken_print_rules_are_refused(name: str, old: str, new: str) -> None:
    assert old in BASE, name
    assert _print_rule_violations(BASE.replace(old, new)), name


def test_heading_rule_moved_to_screen_is_refused() -> None:
    css = BASE.replace(
        "h1, h2, h3 { font-family",
        "@media screen { h1, h2, h3 { break-after: avoid; } }\nh1, h2, h3 { font-family",
    )
    css = css.replace(" break-after: avoid; }\nh1 {", " }\nh1 {", 1)
    assert _print_rule_violations(css)


def test_every_field_is_escaped() -> None:
    out = render_document(f"# {HOSTILE}\n\n{HOSTILE}\n\n- **{HOSTILE}**", title=HOSTILE)
    doc = Doc(out)
    assert doc.names().count("script") == 0
    assert doc.names().count("img") == 0
    assert HOSTILE in "".join(doc.text)  # parsed back, the text is the input
    assert doc.names().count("strong") == 1


def test_structure_headings_bullets_paragraphs() -> None:
    doc = Doc(render_document("# A\n## B\n### C\n\nline1\nline2\n\n- x\n- y\n\npara", title="t"))
    names = doc.names()
    assert names.count("h1") == names.count("h2") == names.count("h3") == 1
    assert names.count("li") == 2
    assert names.count("ul") == 1
    assert names.count("p") == 2
    assert names.count("br") == 1


def test_photo_is_a_cv_variant_and_validated() -> None:
    cv = Doc(render_document("# N", title="Name", kind="cv", photo=b"abc", photo_mime="image/jpeg"))
    imgs = [a for t, a in cv.tags if t == "img"]
    assert len(imgs) == 1
    assert imgs[0]["src"] == "data:image/jpeg;base64,YWJj"
    with pytest.raises(ValueError):
        render_document("# N", title="Name", kind="letter", photo=b"abc")
    with pytest.raises(ValueError):
        render_document("# N", title="Name", kind="cv", photo=b"")
    assert "img" not in Doc(render_document("# N", title="Name", kind="cv")).names()
    with pytest.raises(ValueError):
        render_document("x", title="t", kind="cv", photo=b"a", photo_mime='image/png"onload="x')
    with pytest.raises(ValueError):
        render_document("x", title="t", kind="memo")
    with pytest.raises(ValueError):
        render_document("x", title="t", lang='en"><script>')


def test_csp_forbids_everything_but_inline_and_data() -> None:
    doc = Doc(render_document("x", title="t"))
    csp = [
        a["content"]
        for t, a in doc.tags
        if t == "meta" and a.get("http-equiv") == "Content-Security-Policy"
    ]
    assert csp == ["default-src 'none'; img-src data:; style-src 'unsafe-inline'"]


def test_title_cannot_break_out_of_the_head() -> None:
    title = "x</title><script>alert(1)</script><title>"
    doc = Doc(render_document("body", title=title))
    assert "script" not in doc.names()
    assert doc.names().count("title") == 1
    assert title in "".join(doc.text)


def test_csp_meta_precedes_title_and_style() -> None:
    doc = Doc(render_document("body", title="t"))
    order = [(t, a.get("http-equiv")) if t == "meta" else (t, None) for t, a in doc.tags]
    csp = order.index(("meta", "Content-Security-Policy"))
    names = [t for t, _ in order]
    assert names.index("head") < csp < names.index("title")
    assert csp < names.index("style") < names.index("body")


def test_comments_in_the_stylesheet_do_not_hide_real_rules() -> None:
    css = BASE.replace("p, li {", "/* note { size: A5 } */\np, li {", 1)
    assert css != BASE
    assert _print_rule_violations(css) == []


def test_closing_hash_needs_a_space() -> None:
    doc = Doc(render_document("## C#\n\n## Title ##\n\n### F# and C ###", title="t"))
    text = [x for x in doc.text if x.strip()][1:]  # [0] is the <title>
    assert text == ["C#", "Title", "F# and C"]
