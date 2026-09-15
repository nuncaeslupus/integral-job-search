"""T178 — a cue matches whole words, and every reader of a cue matches that way."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from integral.dimensions import Cue

SRC = Path(__file__).resolve().parents[1] / "src" / "integral"


@pytest.mark.parametrize(
    ("pattern", "text", "quote"),
    [
        # Inside a word, at either end: refused.
        ("go", "the Django framework", None),
        ("go", "Remote, Chicago", None),
        ("rust", "a high-trust team", None),
        ("ret[ée]n", "curvas de retención", None),
        ("ret[ée]n", "marcas de entretenimiento", None),
        ("our mission is", "Your mission is to ship", None),
        # At a word's edge: matched, whatever case the text is in.
        ("go", "in GO today", "GO"),
        ("ret[ée]n", "guardias y retén", "retén"),
        # The guard is in the regex, so the engine backtracks to the alternative
        # that ends on a word edge instead of rejecting the first one tried.
        ("(cliente|clientes)", "contacto con clientes y proveedores", "clientes"),
        # A stem says it is one.
        (r"escalab\w*", "mejorar su escalabilidad", "escalabilidad"),
        # Digits are not letters: scraped text glues numbers to words.
        (r"100\s*remoto", "Modalidad100 remoto", "100 remoto"),
        (r"\$\s?\d{2,3},?\d{3}", "US$120,000 a year", "$120,000"),
        # A proper noun scopes case-insensitivity off.
        ("(?-i:Go)", "teams go from alert to answer", None),
        ("(?-i:Go)", "written in Go", "Go"),
    ],
)
def test_a_cue_matches_whole_words_only(pattern: str, text: str, quote: str | None) -> None:
    found = Cue(pattern=pattern, value=0.5).search(text)
    assert (found and found.group(0)) == quote
    assert [m.group(0) for m in Cue(pattern=pattern, value=0.5).finditer(text)] == (
        [quote] if quote else []
    )


def test_no_module_matches_a_pattern_attribute_through_re_directly() -> None:
    """The guard lives in `Cue.finditer`/`Cue.search`; a reader that calls `re`
    on `cue.pattern` gets the old substring match back, silently. Ten readers did,
    before T178 — the rules stage, the gold check, the cue audit, the prefilter,
    the harness, suggestions and elicitation each matched a cue its own way.
    """
    bypasses = [
        f"{path.name}:{node.lineno}"
        for path in sorted(SRC.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "re"
        and node.args
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "pattern"
    ]
    assert bypasses == []
