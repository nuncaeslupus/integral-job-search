"""T254 — `after_text`: a node is read only when its *immediately preceding element
sibling's* text is exactly the label.

Every case is derived from the field's own comment (`FieldSelector.after_text`) and
`Take`'s rule that text without the described shape yields nothing, never a
neighbour. One table, run through the real `_extract` on a constructed page.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from integral.connectors import (
    FieldSelector,
    _extract,
    compile_selector,
    parse_html,
)

_L = "Descripción del trabajo"

_CASES = [
    ("label_directly_before", f"<span>{_L}</span><div>BODY</div>", "BODY"),
    ("label_absent", "<span>Otra cosa</span><div>BODY</div>", None),
    ("label_is_a_substring", f"<span>{_L} y requisitos</span><div>BODY</div>", None),
    ("label_only_inside_the_body", f"<div>{_L}</div>", None),
    ("non_div_between", f"<span>{_L}</span><hr><div>BODY</div>", None),
    ("heading_between", f"<span>{_L}</span><h2>Requisitos</h2><div>REQS</div>", None),
    ("earlier_not_adjacent", f"<span>{_L}</span><p>x</p><p>y</p><div>BODY</div>", None),
    ("label_after_the_div", f"<div>BODY</div><span>{_L}</span>", None),
    ("label_is_last_child", f"<div>x</div><span>{_L}</span>", None),
    (
        "label_in_a_cousin",
        f"<section><span>{_L}</span></section><section><div>BODY</div></section>",
        None,
    ),
    ("label_before_an_ancestor", f"<span>{_L}</span><section><div>BODY</div></section>", None),
    (
        "label_twice_first_wins",
        f"<span>{_L}</span><div>ONE</div><span>{_L}</span><div>TWO</div>",
        "ONE",
    ),
    (
        "whitespace_is_collapsed",
        "<span> Descripción\n  del   trabajo </span><div>BODY</div>",
        "BODY",
    ),
    (
        "label_split_over_inline_tags",
        "<span>Descripción <b>del</b> trabajo</span><div>BODY</div>",
        "BODY",
    ),
    (
        "wrapper_containing_the_label_is_not_the_body",
        f"<div><span>{_L}</span><div>BODY</div></div>",
        "BODY",
    ),
    ("case_differs", "<span>DESCRIPCIÓN DEL TRABAJO</span><div>BODY</div>", None),
]


@pytest.mark.parametrize(("html", "expected"), [c[1:] for c in _CASES], ids=[c[0] for c in _CASES])
def test_after_text_reads_only_the_node_right_after_the_label(
    html: str, expected: str | None
) -> None:
    selector = FieldSelector(css="div", after_text=_L)
    root = parse_html(f"<html><body>{html}</body></html>")
    assert _extract(root, selector, compile_selector("div")) == expected


@pytest.mark.parametrize("label", ["   ", " Descripción del trabajo ", "a  b", "a\tb", ""])
def test_an_after_text_that_can_never_match_is_refused_at_load(label: str) -> None:
    with pytest.raises(ValidationError):
        FieldSelector(css="div", after_text=label)
