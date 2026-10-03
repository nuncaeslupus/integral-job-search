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
            photo=b"\x89PNG-bytes",
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


def test_print_rules_are_present() -> None:
    css = Doc(render_document("# H", title="t")).css
    page = re.search(r"@page\s*\{([^}]*)\}", css)
    assert page
    assert re.search(r"size:\s*A4\b", page.group(1))
    assert re.search(r"margin:\s*22mm 24mm", page.group(1))
    assert re.search(r"@media print\s*\{[^@]*@page", css)
    assert re.search(r"p,\s*li\s*\{[^}]*orphans:\s*3;[^}]*widows:\s*3", css)
    assert re.search(r"h1,\s*h2,\s*h3\s*\{[^}]*break-after:\s*avoid", css)


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
    assert (
        "img" not in Doc(render_document("# N", title="Name", kind="letter", photo=b"abc")).names()
    )
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
