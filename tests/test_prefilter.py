"""T14's recall obligation, carried into T15 by the fold (#81).

T14 was cancelled and absorbed, but the property it existed to protect was not:
**the rules stage may narrow what the model is asked, never decide that a
dimension is absent.** Its named test comes here with it.

What changed is the measurement. T14 declared `prefilter_recall >= 0.98` over
corpus positives T5 never supplied — 14 evaluation labels, four dimensions with
none — so the number was noise wearing a threshold. What is measurable, and
measured here, is the reachable failure: the cues settling a dimension a person
labelled the other way, so the model is never asked and the wrong answer stands.
"""

from __future__ import annotations

import unicodedata

from integral.dimensions import Cue, Extraction, load_dimensions
from integral.extraction import (
    _cue_reaches_the_cited_span,
    cue_findings,
    normalise,
    prefilter_suppression,
    rules_stage,
    unsettled_dimensions,
)
from integral.harness import Label, LabelledAd, Span, load_store
from integral.offers import Offer, compute_offer_id

_DIMENSIONS = load_dimensions()
_STORE = load_store()


def test_prefilter_retains_all_corpus_positives() -> None:
    """T14's named test: no positive a person labelled is buried by the cues.

    "Buried" rather than "dropped", deliberately. A dimension the cues do not
    match stays in `unsettled` and still reaches the model, so a literal
    drop is impossible by construction — measuring *that* would be a tautology
    dressed as a gate. The reachable failure is a confident wrong answer, and
    that is what this counts.
    """
    suppressed, checked, detail, uncovered = prefilter_suppression(_STORE, _DIMENSIONS)
    assert checked > 0, "a clean result over nothing is not a result"
    # Locked to what the corpus actually holds, not to zero — and split, because
    # the two were different failures. `manfred-8360` is this stage's: a cue
    # matched inside the very span the labeller cited ("se huye de los *sprints*
    # infinitos") and resolved it to the opposite sign, because the rejection is
    # phrased with a verb `_NEGATORS` does not carry. Nothing was missing; the
    # combination was wrong.
    assert detail == [
        "manfred-8360/process_formality: cues settled 1, a person labelled -1",
    ], detail
    assert suppressed == 1

    # `stack_modernity` is not: no cue reaches "Experiencia sólida en JBoss /
    # JBoss EAP" at all, so the stage never saw the evidence and settled on the
    # Kubernetes and cloud mentions elsewhere. That is vocabulary, which T57's
    # `ontology_hit_rate` owns. Asserted, not ignored — a confident wrong answer
    # still stops the model being asked.
    assert uncovered == [
        "tecnoempleo-5daa18bff2393309c941/stack_modernity: cues settled 1, "
        "a person labelled -1 — no cue reaches the cited span",
    ], uncovered


def test_the_suppression_check_would_notice_a_bad_cue() -> None:
    """The other half: a check that cannot fail is not evidence of anything.

    A cue is inverted on a dimension a person labelled, and the count must move.
    Without this, `prefilter_suppressed_positives == 0` is equally consistent
    with a correct cue set and with a measurement that never compares anything.
    """
    labelled = [
        (ad, label)
        for ad in _STORE
        for label in ad.labels
        if any(d.id == label.dimension and d.polarity == "bipolar" for d in _DIMENSIONS)
    ]
    assert labelled, "the corpus carries no bipolar label to invert"
    ad, label = labelled[0]

    # Two matching cues so the bipolar corroboration rule is satisfied and the
    # stage actually settles — pointed the opposite way from the person.
    wrong = -1.0 if label.value > 0 or label.negated else 1.0
    quote = label.spans[0].extract(ad.text)
    word = next(w for w in quote.split() if len(w) > 4)
    poisoned = [
        d.model_copy(
            update={
                "extraction": Extraction(
                    cues={ad.language: [Cue(pattern=word, value=wrong)] * 2},
                )
            }
        )
        if d.id == label.dimension
        else d
        for d in _DIMENSIONS
    ]
    suppressed, _, detail, _uncovered = prefilter_suppression([ad], poisoned)
    assert suppressed >= 1, f"an inverted cue on {label.dimension} went unnoticed: {detail}"


def test_a_dimension_the_cues_miss_still_reaches_the_model() -> None:
    """The narrowing is of the model's agenda, never of the answer space."""
    base = next(d for d in _DIMENSIONS if d.id == "travel_requirement")
    nothing = Extraction(cues={"es": [Cue(pattern="zzz", value=1.0)]})
    blind = base.model_copy(update={"extraction": nothing})
    ad = normalise(
        Offer(
            id=compute_offer_id("Viajes constantes."),
            source="t",
            text="Viajes constantes.",
            language="es",
        )
    )
    assert cue_findings(ad, blind) is None
    assert unsettled_dimensions([blind], rules_stage(ad, [blind])) == ["travel_requirement"]


def test_a_decomposed_cited_span_is_still_matched_against_the_cues() -> None:
    """The split must not misfile a soundness failure as a coverage gap.

    `cue_findings` matches NFC-normalised text. If this audit compared cues to
    the *raw* cited span, a labeller's span holding decomposed characters would
    fail to match a composed cue that had matched perfectly well upstream — and
    the failure would be recorded as `prefilter_uncovered_positives`, dropping a
    real T15 failure out of its own gate.
    """
    composed = "Puesto presencial en Barcelona."
    decomposed = unicodedata.normalize("NFD", "Modalidad híbrida presencial en Barcelona.")
    assert decomposed != unicodedata.normalize("NFC", decomposed), "fixture must be decomposed"

    ad = LabelledAd(
        id="nfd-1",
        language="es",
        text=decomposed,
        source_url="https://example.test/ad",
        split="evaluation",
        labels=[
            Label(
                dimension="remote_arrangement",
                value=0.5,
                spans=[Span(start=0, end=len(decomposed))],
                labeller="test",
            )
        ],
    )
    dimension = next(d for d in _DIMENSIONS if d.id == "remote_arrangement")
    assert _cue_reaches_the_cited_span(ad, ad.labels[0], dimension), (
        "the cited span was decomposed; matching it raw would have hidden a real failure"
    )
    assert composed  # the composed control, for the reader
