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

from jobsearch.dimensions import Cue, Extraction, load_dimensions
from jobsearch.extraction import (
    cue_findings,
    normalise,
    prefilter_suppression,
    rules_stage,
    unsettled_dimensions,
)
from jobsearch.harness import load_store
from jobsearch.offers import Offer, compute_offer_id

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
    suppressed, checked, detail = prefilter_suppression(_STORE, _DIMENSIONS)
    assert checked > 0, "a clean result over nothing is not a result"
    assert suppressed == 0, detail


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
    suppressed, _, detail = prefilter_suppression([ad], poisoned)
    assert suppressed >= 1, f"an inverted cue on {label.dimension} went unnoticed: {detail}"


def test_a_dimension_the_cues_miss_still_reaches_the_model() -> None:
    """The narrowing is of the model's agenda, never of the answer space."""
    base = next(d for d in _DIMENSIONS if d.id == "travel_requirement")
    nothing = Extraction(cues={"es": [Cue(pattern="zzz", value=1.0)]})
    blind = base.model_copy(update={"extraction": nothing})
    ad = normalise(Offer(id=compute_offer_id("Viajes constantes."), source="t",
                         text="Viajes constantes.", language="es"))
    assert cue_findings(ad, blind) is None
    assert unsettled_dimensions([blind], rules_stage(ad, [blind])) == ["travel_requirement"]
