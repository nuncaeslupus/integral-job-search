"""Pre-marked spans, and the instruments that keep them from poisoning the gold.

The suggestions exist to remove work from the labeller. The risk they carry is
that the corpus becomes a transcript of whatever proposed them — and if that is
`Dimension.extraction.cues`, `extraction_macro_f1` (T15) ends up measuring the
extractor against its own output and passes regardless of merit. That is D-2.

Two instruments are tested here. `validate_suggestions` refuses the arrangement
outright where it is provable (a cue-derived set covering an evaluation ad; a
control ad that was given suggestions after all). `cue_agreement` measures the
part that cannot be refused, because a set that merely *happens* to agree with
the cues looks identical to one derived from them until you count.
"""

from __future__ import annotations

import pytest

from jobsearch.dimensions import load_dimensions
from jobsearch.harness import LabelledAd, load_store
from jobsearch.suggestions import (
    SuggestionSet,
    blind_control,
    cue_agreement,
    validate_suggestions,
)

DIMENSIONS = load_dimensions()
TEXT = "Ofrecemos guardias rotativas cada mes y dos horas cada viernes para estudiar."


def ad(ad_id: str = "a-1", split: str = "evaluation", text: str = TEXT) -> LabelledAd:
    return LabelledAd(
        id=ad_id,
        language="es",
        text=text,
        source_url="https://example.invalid/1",
        split=split,  # type: ignore[arg-type]
        labels=[],
    )


def suggestion_set(method: str = "llm_read", **overrides: object) -> SuggestionSet:
    payload: dict[str, object] = {
        "method": method,
        "generated_at": "2026-08-19",
        "by_ad": {
            "a-1": [
                {"dimension": "on_call_load", "value": 0.8, "quote": "guardias rotativas"}
            ]
        },
        **overrides,
    }
    return SuggestionSet.model_validate(payload)


# --- the control set ---------------------------------------------------------


def test_blind_control_carries_every_language() -> None:
    """A control set holding no Catalan ad says nothing about labelling Catalan
    cold, which is exactly the slice most likely to be rubber-stamped."""
    store = load_store()
    chosen = set(blind_control(store))
    languages = {ad.language for ad in store if ad.id in chosen}

    assert languages == {ad.language for ad in store}


def test_blind_control_is_stable_across_regeneration() -> None:
    """An ad labelled blind that later receives a suggestion has already given up
    the only thing it was for, so the set must not move when it is recomputed."""
    store = load_store()
    assert blind_control(store) == blind_control(store)
    assert blind_control(list(reversed(store))) == blind_control(store)


def test_a_control_ad_carrying_suggestions_is_refused() -> None:
    problems = validate_suggestions(
        suggestion_set(blind_control=["a-1"]), [ad()], DIMENSIONS
    )
    assert any("no longer a baseline" in problem for problem in problems)


# --- what a suggestion has to satisfy ----------------------------------------


def test_a_quote_absent_from_the_ad_is_refused() -> None:
    absent = {"a-1": [{"dimension": "on_call_load", "value": 0.8, "quote": "nada de esto"}]}
    problems = validate_suggestions(suggestion_set(by_ad=absent), [ad()], DIMENSIONS)
    assert any("does not appear" in problem for problem in problems)


def test_an_ambiguous_quote_is_refused() -> None:
    """The page turns a quote into offsets by searching for it; two hits means
    the span silently lands on whichever came first."""
    twice = {"a-1": [{"dimension": "on_call_load", "value": 0.8, "quote": "guardias"}]}
    problems = validate_suggestions(
        suggestion_set(by_ad=twice),
        [ad(text="guardias por la tarde y guardias de noche")],
        DIMENSIONS,
    )
    assert any("appears 2 times" in problem for problem in problems)


def test_a_value_off_the_rungs_is_refused() -> None:
    off = {"a-1": [{"dimension": "on_call_load", "value": 0.65, "quote": "guardias rotativas"}]}
    problems = validate_suggestions(suggestion_set(by_ad=off), [ad()], DIMENSIONS)
    assert any("is not a rung" in problem for problem in problems)


def test_an_unknown_dimension_is_refused() -> None:
    unknown = {"a-1": [{"dimension": "vibes", "value": 0.8, "quote": "guardias rotativas"}]}
    problems = validate_suggestions(suggestion_set(by_ad=unknown), [ad()], DIMENSIONS)
    assert any("unknown dimension" in problem for problem in problems)


# --- D-2: cue-derived suggestions and the evaluation split -------------------


def test_cue_derived_suggestions_are_refused_on_an_evaluation_ad() -> None:
    """The half `extraction_macro_f1` is measured on. Confirming a cue here makes
    the gate score the extractor against its own output."""
    problems = validate_suggestions(
        suggestion_set(method="cue"), [ad(split="evaluation")], DIMENSIONS
    )
    assert any("D-2" in problem for problem in problems)


def test_cue_derived_suggestions_are_allowed_on_an_elicitation_ad() -> None:
    """The elicitation half feeds reaction elicitation (T9), not the extraction
    gate, so there is nothing there for a cue to contaminate."""
    problems = validate_suggestions(
        suggestion_set(method="cue"), [ad(split="elicitation")], DIMENSIONS
    )
    assert problems == []


def test_cue_agreement_is_total_when_every_quote_is_a_cue_hit() -> None:
    """What a cue-derived set looks like from the outside, whatever it calls
    itself — the number that makes `method` checkable rather than trusted."""
    measured = cue_agreement(suggestion_set(), [ad()], DIMENSIONS)

    assert measured["suggestion_count"] == 1
    assert measured["suggestion_cue_agreement"] == 1.0
    assert measured["cue_unreachable"] == 0


def test_cue_agreement_counts_a_span_the_extractor_could_not_reach() -> None:
    """The interesting half: suggestions carrying information the cues do not
    already hold are the ones that make the gold worth measuring against.

    "two hours every Friday to study" is learning support by the dimension's own
    definition — time the employer puts behind learning — and no `learning_support`
    cue reaches it: they all key on the words *presupuesto/plan de formación*,
    *formación continua*, or paid certifications. Precisely the phrasing a
    regex-derived gold set would never contain, and so precisely what makes the
    gold worth measuring the extractor against."""
    beyond = {
        "a-1": [
            {
                "dimension": "learning_support",
                "value": 0.8,
                "quote": "dos horas cada viernes para estudiar",
            }
        ]
    }
    measured = cue_agreement(suggestion_set(by_ad=beyond), [ad()], DIMENSIONS)

    assert measured["cue_unreachable"] == 1
    assert measured["suggestion_cue_agreement"] == 0.0
    assert measured["cue_unreachable_examples"] == ["a-1:learning_support"]


@pytest.mark.parametrize("method", ["llm_read", "cue"])
def test_the_method_is_recorded_verbatim(method: str) -> None:
    """Nameable either way. A cue set is a legitimate thing to build for
    debugging the extractor; what it is not is a source of gold, and that is
    enforced by where it may be used, not by refusing to name it."""
    assert suggestion_set(method=method).method == method
