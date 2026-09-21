"""`tools/excerpt_fixture.py` locates the container it was pointed at.

The tool truncates one span of a recorded fixture and leaves every other byte
alone, so its failure mode is silent by construction: a span it cannot find is
simply not excerpted, and the run reports `0` where it would have reported
`1`. Nothing outside the tool reads that number, so a fixture still carrying a
whole advert ships looking exactly like one that does not.

That is not hypothetical. The locator matched `<div class="X">` — the closing
quote immediately after the selector's own class — which finds nothing on a
board serving `class="sc-f4dbceab-10 fRvput"`, and `es.talent.com` is such a
board. The fix was to split the class list and test membership; this file is
what makes reverting it red.

**The population is derived, never listed.** Every `<div class="…">` opener in
every committed fixture is read, and the ones carrying the connector's own
declared class *beside other classes* are the cases — so a package added later
is covered without anyone remembering, and if the library ever stopped holding
such a container the non-vacuity check below fails rather than passing over
nothing.

`meta.yaml`'s `bodies: excerpted` is deliberately **not** the population: it is
the broader claim that a fixture carries no whole advert, and packages satisfy
it whose text selector this tool cannot address at all (`[itemprop=…]`,
`#joa-duties`, `p.…`, or no text field on either page). Excerpting those was
not this tool's doing and reverting this tool's locator cannot break them.
"""

from __future__ import annotations

import importlib.util
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from integral.connectors import load_connector

_ROOT = Path(__file__).resolve().parents[1]
_CONNECTORS = _ROOT / "connectors"


class _DivClasses(HTMLParser):
    """Every `<div>`'s class list, read by a parser rather than by a regex.

    This deliberately does **not** re-spell the tool's own locator. The first
    version of this file did, byte for byte, which made the target list and the
    non-vacuity guard below blind in exactly the direction the code under test
    is blind: a `<div>` spelled in any way that regex misses would be missing
    from both sides at once, and the check would report green over a fixture
    the tool silently leaves whole. `html.parser` is the stdlib reading the
    same bytes by other means, which is the only thing that makes the
    comparison evidence.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.classes: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        for name, value in attrs:
            if name == "class" and value:
                self.classes.append(value.split())


def _div_class_lists(raw: str) -> list[list[str]]:
    parser = _DivClasses()
    parser.feed(raw)
    return parser.classes


def _load_excerpt_fixture() -> Any:
    """Import `tools/excerpt_fixture.py` by path — `tools/` is not on the path."""
    path = _ROOT / "tools" / "excerpt_fixture.py"
    spec = importlib.util.spec_from_file_location("excerpt_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_TOOL = _load_excerpt_fixture()


def _addressable_targets() -> list[tuple[Path, str, int]]:
    """Every (fixture, class, widest class-list length) this tool can address.

    Built the way `excerpt_package` builds its own plan — the connector's
    `text` field on the list and on the advert page, first class of the
    selector — and then kept only where the committed bytes hold a `<div>`
    carrying that class. The third member is how many classes that `<div>`
    names, which is what separates the case the old locator saw from the case
    it did not.
    """
    found = []
    for package in sorted(p for p in _CONNECTORS.iterdir() if (p / "connector.yaml").exists()):
        connector = load_connector(package)
        plan = [("list.html", connector.list.fields.get("text"))]
        if connector.detail is not None:
            plan.append(("detail.html", connector.detail.fields.get("text")))
        for filename, field in plan:
            path = package / "fixture" / filename
            if field is None or not path.exists():
                continue
            classes = _TOOL._CLASS.findall(field.css)
            if not classes:
                continue
            raw = path.read_text(encoding="utf-8")
            widths = [len(names) for names in _div_class_lists(raw) if classes[0] in names]
            if widths:
                found.append((path, classes[0], max(widths)))
    return found


_TARGETS = _addressable_targets()


def test_the_library_holds_a_container_naming_more_than_one_class() -> None:
    """Non-vacuity: the case the old locator could not see still exists here.

    Without this, a library that drifted to single-class containers would
    leave the check below iterating over nothing and reporting green.
    """
    assert [t for t in _TARGETS if t[2] > 1], "no committed fixture is multi-class at its target"


@pytest.mark.parametrize(
    "path,css_class,width",
    _TARGETS,
    ids=lambda v: v.name if isinstance(v, Path) else str(v),
)
def test_the_tool_finds_the_container_the_connector_names(
    path: Path, css_class: str, width: int
) -> None:
    """Both widths, one assertion: one class is the control, several is the fix."""
    with path.open(encoding="utf-8", newline="") as handle:
        raw = handle.read()
    assert _TOOL._spans(raw, css_class), (
        f"{path.relative_to(_CONNECTORS)}: {css_class!r} is on a <div> naming "
        f"{width} class(es) and the tool found no span — it would have left the "
        "advert whole and said so only in a count nobody reads"
    )


def _membership_variants(token: str) -> tuple[list[str], list[str]]:
    """Class lists that must match `token`, and class lists that must not.

    Derived from the token rather than listed, because an enumeration of
    near-misses has no last element. A class attribute matches when the token
    is one of its whitespace-separated *members*, so the positives are the
    token at every position of a list, and the negatives are every way of
    writing a string that merely **contains** it — the welds and the
    truncations that a substring, prefix or suffix match would accept.
    """
    others = ("fRvput", "x")
    positives = [
        " ".join([*members[:i], token, *members[i:]])
        for members in (list(others[:n]) for n in range(len(others) + 1))
        for i in range(len(members) + 1)
    ]
    negatives = [token + others[0], others[0] + token, token[:-1], token + "-1", token + "x"]
    return positives, negatives


def _openers(classes: str) -> list[str]:
    """Every way a `<div>` can carry that class attribute, as an opening tag.

    The second generated axis, and it is here because the first version of this
    file did not have it: `class` is not always the first attribute, and a
    locator anchored on `<div class=` misses the rest **silently**. Varying the
    position generatively is what stops that from being one more case answered
    once — a third spelling added below is varied against every class list at
    no further cost.
    """
    return [
        f'<div class="{classes}">',
        f'<div id="before" class="{classes}">',
        f'<div class="{classes}" id="after">',
        f'<div\n  class="{classes}">',
    ]


@pytest.mark.parametrize(
    "path,css_class,width",
    _TARGETS,
    ids=lambda v: v.name if isinstance(v, Path) else str(v),
)
def test_only_the_container_naming_the_class_is_excerpted(
    path: Path, css_class: str, width: int
) -> None:
    """The other direction: found is not the property, found *and only that* is.

    The test above asserts the tool reaches the container, which a locator
    that returned every `<div>` on the page also satisfies — and that locator
    excerpts adverts the connector never named. Membership in the class list
    is the property, so both halves are asserted at once against a document
    built from the token itself.
    """
    positives, negatives = _membership_variants(css_class)
    assert not set(positives) & set(negatives), f"{css_class!r}: a variant is in both halves"
    openers = [
        (opener, classes in positives, f"body{index}")
        for index, classes in enumerate([*positives, *negatives])
        for opener in _openers(classes)
    ]
    document = "".join(f"{opener}{body}-{n}</div>" for n, (opener, _, body) in enumerate(openers))
    found = {inner for _, _, inner in _TOOL._spans(document, css_class)}
    assert found == {
        f"{body}-{n}" for n, (_, is_positive, body) in enumerate(openers) if is_positive
    }, (
        f"{path.relative_to(_CONNECTORS)}: {css_class!r} matched the wrong set of "
        "containers — a span that does not name this class was excerpted, or one "
        "that names it among others was not"
    )
