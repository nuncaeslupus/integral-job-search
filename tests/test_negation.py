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
    evaluation_labels,
    negation_audit,
)
from integral.harness import DEFAULT_STORE_PATH as STORE
from integral.harness import Label, LabelledAd, Span, load_store


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
    store = load_store(STORE)
    audit = negation_audit(store, list(dimensions.values()))
    assert audit["extraction_negation_recall"] is None
    assert audit["negation_status"] == "unmeasured"
    assert audit["negated_label_count"] < audit["negation_label_floor"]

    # The denominator is the **evaluation** split, because this is a score and D-2
    # binds scores to held-out data. Counting every label in the store would let
    # the labels that shaped the model unblock a measurement of the model against
    # itself, and would trip the placeholder raise on the wrong population.
    expected = [label for _, label in evaluation_labels(store) if label.negated]
    assert audit["negated_label_count"] == len(expected)


def _negated_ad(
    index: int, text: str, quote: str, dimension: str = "on_call_load"
) -> LabelledAd:
    """One evaluation-split ad carrying a single negated label on `dimension`."""
    start = text.index(quote)
    return LabelledAd(
        id=f"t59-{index}",
        language="es",
        text=text,
        source_url="https://example.invalid/t59",
        split="evaluation",
        labels=[
            Label(
                dimension=dimension,
                value=0.0,
                spans=[Span(start=start, end=start + len(quote))],
                negated=True,
                labeller="fixture",
            )
        ],
    )


def test_recall_is_scored_once_the_floor_is_met(dimensions: dict[str, Dimension]) -> None:
    """The floor's tenth label scores the corpus; it does not break the build.

    Nine adverts phrase the denial the cue set reaches, one phrases it a way no
    cue does. Ten labels is the floor exactly, so this fixture is also the
    assertion that the boundary is `>=` and not `>`.
    """
    store = [
        _negated_ad(i, "Puesto estable. Sin guardias ni retenes.", "guardias") for i in range(9)
    ]
    store.append(_negated_ad(9, "Olvídate de las llamadas nocturnas.", "llamadas nocturnas"))

    audit = negation_audit(store, list(dimensions.values()))

    assert audit["negated_label_count"] == 10
    assert audit["negation_status"] == "measured"
    assert audit["extraction_negation_recall"] == 0.9
    assert audit["negation_recall_hits"] == 9
    assert audit["negation_recall_misses"] == ["t59-9/on_call_load: no cue settled the dimension"]


def test_a_settled_but_unnegated_dimension_is_a_miss_not_a_hit(
    dimensions: dict[str, Dimension],
) -> None:
    """The other way recall fails, and the reason that distinguishes it.

    The cue fires and settles `on_call_load`, but the negator sits on the far
    side of a full stop, so the extractor reads a rotation where a person read a
    denial. Silently excluding this — as excluding the unsettled case would —
    is how a recall number reaches 1.0 by construction.
    """
    text = "No trabajarás los fines de semana. Guardias en rotación semanal."
    store = [_negated_ad(i, text, "Guardias") for i in range(10)]

    audit = negation_audit(store, list(dimensions.values()))

    assert audit["extraction_negation_recall"] == 0.0
    assert audit["negation_recall_misses"][0].endswith("settled, but not as negated")


def test_an_unknown_dimension_lowers_recall_rather_than_the_denominator(
    dimensions: dict[str, Dimension],
) -> None:
    """A typo'd dimension must not be able to raise the score by leaving."""
    store = [
        _negated_ad(i, "Puesto estable. Sin guardias ni retenes.", "guardias") for i in range(10)
    ]
    store[0].labels[0] = store[0].labels[0].model_copy(update={"dimension": "on_call_lod"})

    audit = negation_audit(store, list(dimensions.values()))

    assert audit["negated_label_count"] == 10
    assert audit["extraction_negation_recall"] == 0.9
    assert audit["negation_recall_misses"] == ["t59-0/on_call_lod: no such dimension"]


def test_a_denies_hit_is_not_credited_to_the_scope_rule(
    dimensions: dict[str, Dimension],
) -> None:
    """Perfect recall, half of it earned by vocabulary the cue set already had.

    `sin viajes` is a `denies` cue — the negator is inside the pattern, so
    matching it proves nothing about T16's backward-looking scope rule. `no hace
    guardias` reaches the same verdict the other way: the bare `guardias` cue is
    `negatable` and only the scope rule makes it negative. (`sin guardias` would
    *not* do — it is its own `denies` cue and `cue_findings` drops the narrower
    `guardias` match contained inside it, so nothing negatable survives.)
    Counting both mechanisms as one number is what T59's task file forbids, and
    this is what stops it: recall is 1.0 and the split says only half of it
    tested the rule.

    The per-language counts come along because they are the same failure at a
    different grain — a floor that is a bare total lets ten Spanish labels score
    a number reported for ES, EN and CA alike.
    """
    store = [
        _negated_ad(i, "Puesto estable. El equipo no hace guardias.", "guardias")
        for i in range(5)
    ]
    store += [
        _negated_ad(5 + i, "Trabajo estable. Sin viajes.", "Sin viajes", "travel_requirement")
        for i in range(5)
    ]

    audit = negation_audit(store, list(dimensions.values()))

    assert audit["extraction_negation_recall"] == 1.0
    assert audit["negation_recall_hits_by_mechanism"] == {"scope": 5, "denies": 5}
    assert audit["negated_label_count_by_language"] == {"en": 0, "es": 10, "ca": 0}
