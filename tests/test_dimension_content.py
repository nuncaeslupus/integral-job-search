"""T3 — what the committed dimension model must contain, not just its shape.

`tests/test_dimension_model.py` (T2) tests the schema: any file satisfying it
loads. These tests are about the model v0 itself — its size, its trilingual
reach, and whether its cues and gold examples touch the real corpus. A model
that satisfies the schema while matching nothing in 100 real ads would pass
every T2 test and be useless.
"""

from __future__ import annotations

import re

import pytest

from jobsearch.corpus import LANGUAGES, load_ads
from jobsearch.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    SCHEMA_LANGUAGES,
    Dimension,
    extractor_coverage,
    load_dimensions,
    unmatched_gold,
    verify_gold,
)

# The plan's v0 range: small enough to be designed before seeing every ad,
# large enough to cover the candidate-zero brief. `ontology_hit_rate` (T17) is
# what makes a wrong choice visible later; this only holds the size.
MIN_DIMENSIONS, MAX_DIMENSIONS = 20, 25


@pytest.fixture(scope="module")
def dimensions() -> list[Dimension]:
    return load_dimensions(DEFAULT_DIMENSIONS_DIR)


def test_every_dimension_has_cues_in_all_three_languages(dimensions: list[Dimension]) -> None:
    """Each dimension carries ≥1 cue per language.

    The corpus is 60% Spanish, 25% English, 15% Catalan. A dimension with cues
    in one language only would be extracted from a quarter of the market and
    silently score zero on the rest — which reads identically to "the ad does
    not mention it".
    """
    missing = {
        dimension.id: [
            language
            for language in SCHEMA_LANGUAGES
            if not dimension.extraction.cues.get(language)
        ]
        for dimension in dimensions
    }
    missing = {dim_id: langs for dim_id, langs in missing.items() if langs}

    assert not missing, f"dimensions missing cues per language: {missing}"


def test_model_v0_is_within_the_planned_size(dimensions: list[Dimension]) -> None:
    """20 to 25 dimensions, per the plan."""
    assert MIN_DIMENSIONS <= len(dimensions) <= MAX_DIMENSIONS, (
        f"model v0 has {len(dimensions)} dimensions, outside {MIN_DIMENSIONS}-{MAX_DIMENSIONS}"
    )


def test_every_dimension_asks_a_behavioural_question_in_three_languages(
    dimensions: list[Dimension],
) -> None:
    """Elicitation is behavioural (METHODS §2.1) and reaches every candidate.

    The question texts are required in all three languages by the schema; what
    is checked here is that each dimension actually asks something, and asks it
    with enough substance to be answered with an episode rather than a rating.
    """
    for dimension in dimensions:
        assert dimension.elicitation.questions, f"{dimension.id} asks nothing"
        for question in dimension.elicitation.questions:
            for language in LANGUAGES:
                text = question.text.get(language)
                assert len(text) > 40, f"{dimension.id}.{question.id}[{language}] is too short"


def test_every_dimension_has_a_gold_example_drawn_from_the_corpus(
    dimensions: list[Dimension],
) -> None:
    """`dimension_extractor_coverage` counts gold, and gold must be real.

    Every span is asserted verbatim against the ad it names, so a gold set can
    never drift into paraphrase — the failure the corpus README refuses for the
    ads themselves.
    """
    without_gold = [d.id for d in dimensions if not d.extraction.gold]

    assert not without_gold, f"dimensions with no gold example: {without_gold}"
    assert verify_gold(dimensions) == []


def test_extractor_coverage_meets_the_gate(dimensions: list[Dimension]) -> None:
    """`dimension_extractor_coverage >= 0.90` — the T3 acceptance gate."""
    assert extractor_coverage(dimensions) >= 0.90


def test_every_dimension_has_a_cue_that_fires_on_a_real_ad(dimensions: list[Dimension]) -> None:
    """At least one cue per dimension matches at least one of the 100 ads.

    Cues are written from imagined phrasing as easily as from observed phrasing,
    and a dimension whose whole cue set matches nothing in the corpus is a
    guess. This is the check that keeps the model anchored to the market it was
    built from rather than to how job ads are assumed to read.
    """
    ads = load_ads()
    assert ads, "corpus is empty — the anchor this test relies on is missing"

    dead = []
    for dimension in dimensions:
        fired = any(
            re.search(cue.pattern, ad["text"], re.I)
            for language, cues in dimension.extraction.cues.items()
            for cue in cues
            for ad in ads
            if ad["language"] == language
        )
        if not fired:
            dead.append(dimension.id)

    assert not dead, f"dimensions whose cues match no ad in the corpus: {dead}"


def test_every_gold_example_is_matched_by_one_of_its_own_cues(
    dimensions: list[Dimension],
) -> None:
    """A gold example no cue reaches counts towards coverage while disproving it.

    Added after review found the reverse case: cues tightened to stop firing on
    the wrong thing, with their gold left pointing at wording the new cue no
    longer describes. Coverage stayed at 1.0 throughout, which is exactly the
    silence this test removes.
    """
    assert unmatched_gold(dimensions) == []


def test_hard_dimensions_are_filters_not_preferences(dimensions: list[Dimension]) -> None:
    """`kind: hard` vetoes, so it must be a magnitude rather than a direction.

    A bipolar hard filter has no defensible cut-off — the ranker would have to
    guess which side of zero vetoes — so the model keeps hard dimensions
    unipolar and expresses direction through the candidate's threshold instead.
    """
    misdeclared = [d.id for d in dimensions if d.kind == "hard" and d.polarity != "unipolar"]

    assert not misdeclared, f"hard dimensions declared bipolar: {misdeclared}"
