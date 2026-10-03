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


Rule = tuple[str, tuple[str, ...], list[tuple[str, str]]]  # (context, selectors, declarations)

# The only values a governed property may ever take, in any rule, under any selector.
ALLOWED = {
    "size": "a4",
    "margin": "22mm 24mm",
    "orphans": "3",
    "widows": "3",
    "break-after": "avoid",
    "break-inside": "avoid",
}
REQUIRED = [
    ("@page", "size"),
    ("@page", "margin"),
    ("p", "orphans"),
    ("p", "widows"),
    ("li", "orphans"),
    ("li", "widows"),
    ("h1", "break-after"),
    ("h2", "break-after"),
    ("h3", "break-after"),
]


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _all_decls(block: str) -> list[tuple[str, str]]:
    out = []
    for part in block.split(";"):
        if ":" in part:
            name, _, value = part.partition(":")
            out.append((_norm(name), _norm(value)))
    return out


def _parse_css(css: str) -> tuple[list[Rule], list[str]]:
    """Rules as (context, selectors, declarations) plus refused constructs.

    Closed rule: the only at-rules are a bare ``@media print`` at top level and a
    bare ``@page`` at top level or inside it. Anything else is refused outright
    rather than interpreted, so no spelling of a condition can hide an override.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[Rule] = []
    refused = [
        f"at-rule refused: statement {m.group(1)!r}"
        for m in re.finditer(r"(?:^|[;}{])\s*(@[^{};]*);", css)
    ]

    def walk(text: str, context: str) -> None:
        i = 0
        while True:
            head_end = text.find("{", i)
            if head_end < 0:
                return
            head = _norm(text[i:head_end].replace("}", " "))
            depth, k = 1, head_end + 1
            while depth and k < len(text):
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[head_end + 1 : k - 1]
            i = k
            if head == "@media print" and context == "top":
                walk(body, "print")
            elif head.startswith("@") and head != "@page":
                refused.append(f"at-rule refused: {head!r} in {context}")
            elif "{" in body:  # CSS nesting would hide an override from this parser
                refused.append(f"nested rule refused: {head!r}")
            elif head == "@page":
                rules.append((context, ("@page",), _all_decls(body)))
            else:
                sels = tuple(x.strip() for x in head.split(","))
                rules.append((context, sels, _all_decls(body)))

    walk(css, "top")
    return rules, refused


def _is_governed(selector: str, prop: str) -> bool:
    if selector == "@page":
        return prop == "size" or prop.startswith("margin")
    return prop in ("orphans", "widows") or prop.startswith(("break-", "page-break-"))


def _print_rule_violations(css: str) -> list[str]:
    """Why this stylesheet does not carry the print rules the spec requires."""
    rules, found = _parse_css(css)
    present: set[tuple[str, str]] = set()
    for _, selectors, decls in rules:
        for prop, value in decls:
            for selector in selectors:
                if not _is_governed(selector, prop):
                    continue
                if ALLOWED.get(prop) != value:
                    found.append(f"governed {selector} {prop}: {value!r} is not allowed")
                else:
                    present.add((selector, prop))
    found += [f"missing: {s} {p}" for s, p in REQUIRED if (s, p) not in present]
    return sorted(set(found))


def test_print_rules_are_present() -> None:
    css = Doc(render_document("# H", title="t")).css
    assert _print_rule_violations(css) == []


BASE = Doc(render_document("# H", title="t")).css

# Each is appended to a stylesheet that is otherwise clean, so a red result is
# about the appended text and nothing else. (name, appended css, reason fragment)
REFUSED = [
    (
        "N1 print and condition",
        "@media print and (orientation: portrait) {p,li{orphans:1}}",
        "at-rule",
    ),
    ("N2 only print", "@media only print {h1,h2,h3{break-after:auto}}", "at-rule"),
    ("N3 print, screen", "@media print, screen {@page{size:letter}}", "at-rule"),
    ("N4 supports", "@supports (display:grid) {p,li{orphans:1}}", "at-rule"),
    ("N5 descendant selector", "body p, body li {orphans:1;widows:1}", "governed"),
    ("N6 upper-case selector", "P, LI {orphans:1;widows:1}", "governed"),
    ("N7 universal !important", "* {orphans:1 !important;widows:1 !important}", "governed"),
    ("N8 page pseudo", "@page :first {margin:0}", "at-rule"),
    ("N9 margin longhand", "@page {margin-top:0}", "governed"),
    ("N10 page-break-after", "h1,h2,h3{page-break-after:auto}", "governed"),
    ("N11 landscape", "@page {size: A4 landscape}", "governed"),
    ("N12 important before correct", "p { orphans: 1 !important }", "governed"),
    ("N13 nested media", "@media print {@media print {p{orphans:1}}}", "at-rule"),
    ("N14 screen block", "@media screen {h1{break-after:auto}}", "at-rule"),
    ("N15 widows 30", "p {widows: 30}", "governed"),
    ("N16 avoid-column", "h2 {break-after: avoid-column}", "governed"),
    ("N18 css nesting", "body { p { orphans: 1 } }", "nested"),
    ("N19 css nesting &", "p { & { orphans: 1 } }", "nested"),
    ("N20 nesting in page", "@page { @top-left { margin: 0 } }", "nested"),
    ("N17 import", "@import url(https://x.test/a.css);", "at-rule"),
]


@pytest.mark.parametrize("name,extra,reason", REFUSED, ids=[r[0] for r in REFUSED])
def test_overriding_print_rules_are_refused(name: str, extra: str, reason: str) -> None:
    assert _print_rule_violations(BASE) == []
    found = _print_rule_violations(BASE + "\n" + extra)
    assert any(reason in f for f in found), (name, found)


def test_an_offender_before_the_correct_rule_is_still_refused() -> None:
    """Every value counts, not the last: N12 placed first, the correct rule after."""
    found = _print_rule_violations("p { orphans: 1 !important }\n" + BASE)
    assert any("governed p orphans" in f for f in found)


def test_removing_a_required_declaration_is_refused() -> None:
    needle = "p, li { orphans: 3; widows: 3; }"
    assert needle in BASE
    assert any("missing" in f for f in _print_rule_violations(BASE.replace(needle, "")))
    assert any("missing" in f for f in _print_rule_violations(""))


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
