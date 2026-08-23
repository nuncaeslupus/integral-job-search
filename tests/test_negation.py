"""T16 — negation scope: a negator governs its own clause, and nothing past it.

Written against the committed dimension model and corpus, like `test_extract.py`,
because the failures this suite exists for were found in real adverts and not in
a fixture: a `sin` at the end of one sentence was inverting a cue in the next.
"""

from __future__ import annotations

import pytest

from integral.dimensions import DEFAULT_DIMENSIONS_DIR as DIMS_DIR
from integral.dimensions import Dimension, Language, load_dimensions
from integral.extraction import (
    NormalisedAd,
    _is_negated,
    cue_findings,
    negation_audit,
)
from integral.harness import DEFAULT_STORE_PATH as STORE
from integral.harness import load_store


def _ad(text: str, language: Language = "es") -> NormalisedAd:
    return NormalisedAd(offer_id="t16", language=language, text=text, title="t", company="c")


@pytest.fixture(scope="module")
def dimensions() -> dict[str, Dimension]:
    return {d.id: d for d in load_dimensions(DIMS_DIR)}


def test_negated_cue_inverts_not_drops_score(dimensions: dict[str, Dimension]) -> None:
    """The task's own test: "no on-call" scores negative, it does not go missing."""
    found = cue_findings(
        _ad("Horario de oficina sin turnos ni guardias."), dimensions["on_call_load"]
    )
    assert found is not None, "a negated cue must still produce a score"
    assert found.negated is True
    assert found.value < 0


def test_negator_does_not_reach_past_a_full_stop(dimensions: dict[str, Dimension]) -> None:
    """`manfred-8392`: "sin ambigüedades. **El inglés fluido" is not a negation."""
    found = cue_findings(
        _ad(
            "Comunicas de forma directa y sin ambigüedades. **El inglés fluido** es imprescindible."
        ),
        dimensions["english_demand"],
    )
    assert found is not None
    assert found.negated is False


def test_negator_does_not_reach_past_a_line_break() -> None:
    """`remotive-2091075`: a `not` in one bullet does not negate the next one.

    Asserted on the predicate rather than on a score, because the dimension this
    was found on is bipolar and would return `None` for the unrelated reason
    that one match cannot settle a bipolar scale.
    """
    text = "- Hunting new business, not just worked warm leads\n\n- Able to work autonomously"
    assert _is_negated(text, text.index("autonomously"), "en") is False


def test_negator_still_reaches_across_a_comma(dimensions: dict[str, Dimension]) -> None:
    """`manfred-8389`: a comma is not a clause boundary — "no harás guardias" negates."""
    found = cue_findings(
        _ad("Durante tus primeros 6 meses, no harás guardias."), dimensions["on_call_load"]
    )
    assert found is not None
    assert found.negated is True


def test_no_negation_leaks_across_a_boundary_in_the_corpus(
    dimensions: dict[str, Dimension],
) -> None:
    """The corpus-wide property T16 owns, asserted where the evidence file records it."""
    audit = negation_audit(load_store(STORE), list(dimensions.values()))
    assert audit["negation_scope_leaks"] == 0, audit["negation_firings"]


def test_recall_is_refused_while_the_corpus_cannot_carry_it(
    dimensions: dict[str, Dimension],
) -> None:
    """T59's placeholder, asserting the refusal rather than describing it.

    Null and `unmeasured`, never 0.0 and never absent — D-2's third outcome. When
    the corpus grows past the floor, `negation_audit` raises instead of quietly
    keeping this shape, and this test is what fails to say so.
    """
    audit = negation_audit(load_store(STORE), list(dimensions.values()))
    assert audit["extraction_negation_recall"] is None
    assert audit["negation_status"] == "unmeasured"
    assert audit["negated_label_count"] < audit["negation_label_floor"]
