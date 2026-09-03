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

from integral.corpus import LANGUAGES, load_ads
from integral.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    SCHEMA_LANGUAGES,
    Dimension,
    ad_side,
    candidate_traits,
    evaluation_gold,
    extractor_coverage,
    gold_provenance,
    load_dimensions,
    trait_dimensions_ready,
    unmatched_gold,
    verify_gold,
)

# The plan's v0 range was 20 to 25: small enough to be designed before seeing every
# ad, large enough to cover the candidate-zero brief. `ontology_hit_rate` (T17) is
# what makes a wrong choice visible later; this only holds the size.
#
# **T57 is that later.** The corpus broadened past remote programming to six job
# families (T25), and the read pass measured the v0 model at `ontology_hit_rate`
# 0.6143 — 648 of 1,680 stated concepts with nowhere in the model to go, and the
# gap sitting in exactly what v0 never saw: a required vocational title, a driving
# licence, a Catalan C1, part-time hours, bodily work. Re-reading the v0 model as
# generously as its own definitions allow reaches 0.6875, so the 20 to 25 band and the
# 0.85 gate could not both hold. Twelve dimensions were added and the band moved to
# match. A range still exists, because a model free to coin a dimension per unmapped
# concept would drive the rate to 1.0 while measuring nothing.
MIN_DIMENSIONS, MAX_DIMENSIONS = 20, 40


@pytest.fixture(scope="module")
def dimensions() -> list[Dimension]:
    return load_dimensions(DEFAULT_DIMENSIONS_DIR)


def test_every_dimension_has_cues_in_all_three_languages(dimensions: list[Dimension]) -> None:
    """Each dimension carries ≥1 cue per language.

    The corpus is 60% Spanish, 25% English, 15% Catalan. A dimension with cues
    in one language only would be extracted from a quarter of the market and
    silently score zero on the rest — which reads identically to "the ad does
    not mention it".

    Ad-side only: a `candidate_trait` is refused cues at load (T26b), so asking
    it for three languages of them would be asking it to be a contradiction.
    """
    missing = {
        dimension.id: [
            language for language in SCHEMA_LANGUAGES if not dimension.extraction.cues.get(language)
        ]
        for dimension in ad_side(dimensions)
    }
    missing = {dim_id: langs for dim_id, langs in missing.items() if langs}

    assert not missing, f"dimensions missing cues per language: {missing}"


def test_model_v0_is_within_the_planned_size(dimensions: list[Dimension]) -> None:
    """20 to 25 dimensions, per the plan.

    Counted over the ad-side model, which is what the plan's range describes.
    Candidate-side dimensions are elicited rather than designed against the
    corpus, so counting them here would make coining a trait read as the model
    outgrowing its plan.
    """
    sized = ad_side(dimensions)
    assert MIN_DIMENSIONS <= len(sized) <= MAX_DIMENSIONS, (
        f"model v0 has {len(sized)} ad-side dimensions, outside {MIN_DIMENSIONS}-{MAX_DIMENSIONS}"
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
    without_gold = [d.id for d in ad_side(dimensions) if not d.extraction.gold]

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
    for dimension in ad_side(dimensions):
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


# --- D-2: gold provenance ---------------------------------------------------
#
# The divergence these guard is not that a number is wrong, but that a number
# would be *right about the wrong thing*: `extraction_macro_f1` computed over
# cue-derived gold asks a regex to re-find the string it was written from, and
# passes near 1.0 while measuring nothing. The schema field is the mechanism;
# these are what stop it being quietly bypassed.


def test_every_gold_example_declares_where_it_came_from(dimensions: list[Dimension]) -> None:
    """No gold without provenance, and no third kind of provenance.

    Enforced by the schema rather than here — this asserts the schema is
    actually in force over the *committed* model, which is what would break if
    `derived_from` ever grew a default.
    """
    for dimension in dimensions:
        for gold in dimension.extraction.gold:
            assert gold.derived_from in {"cue", "human"}, (
                f"{dimension.id}: gold {gold.ad_id} has provenance {gold.derived_from!r}"
            )


def test_the_committed_gold_set_is_entirely_cue_derived(dimensions: list[Dimension]) -> None:
    """The v0 gold was selected by searching for text its own cues match.

    This is the finding D-2 records, asserted rather than described. It is
    expected to fail the day a genuine human label is committed — and that
    failure is the signal to update D-2's scope, not to relabel the new gold.
    """
    measured = gold_provenance(dimensions)
    assert measured["gold_by_provenance"]["human"] == 0
    assert measured["gold_by_provenance"]["cue"] == sum(len(d.extraction.gold) for d in dimensions)


def test_no_evaluation_example_is_derived_from_a_cue(dimensions: list[Dimension]) -> None:
    """The gate metric: `evaluation_gold` never hands back cue-derived gold.

    The one assertion here that can fail against a plausible future edit —
    someone widening the filter to "use whatever gold we have" because every
    dimension currently returns an empty list and that looks like a bug.
    """
    assert gold_provenance(dimensions)["cue_derived_gold_in_evaluation_split"] == 0
    for golds in evaluation_gold(dimensions).values():
        assert all(g.derived_from == "human" for g in golds)


def test_evaluation_gold_keeps_unscoreable_dimensions_rather_than_dropping_them(
    dimensions: list[Dimension],
) -> None:
    """Every dimension gets a key, even when its list is empty.

    A caller that iterates the mapping must see the dimensions it *cannot*
    score, so it can report them unmeasured. Dropping them would make a
    macro-average over the survivors look complete — the third outcome D-2
    insists on ("unmeasured is not a pass and not a fail") collapsing back into
    two.
    """
    per_dimension = evaluation_gold(dimensions)
    assert set(per_dimension) == {d.id for d in dimensions}


def test_a_human_gold_span_no_cue_matches_is_not_a_violation() -> None:
    """`unmatched_gold` exempts human labels, and must.

    Before D-2 this rule applied to all gold, and `_main` treats a violation as
    a hard failure — so the first human label whose wording the cues did not
    anticipate would have turned the T3 gate red. That is precisely the label
    with the most evidential value: it is where the extractor does not
    generalise, which is the thing being measured.
    """
    payload = {
        "ad_id": "manfred-8419",
        "language": "en",
        "span": "wording that no cue in this dimension describes",
        "value": 1.0,
    }
    # Ad-side: a trait carries no gold to copy, and sorts first alphabetically.
    dimension = ad_side(load_dimensions(DEFAULT_DIMENSIONS_DIR))[0]
    cue_gold = dimension.extraction.gold[0].model_copy(update={**payload, "derived_from": "cue"})
    human_gold = dimension.extraction.gold[0].model_copy(
        update={**payload, "derived_from": "human"}
    )

    as_cue = dimension.model_copy(
        update={"extraction": dimension.extraction.model_copy(update={"gold": [cue_gold]})}
    )
    as_human = dimension.model_copy(
        update={"extraction": dimension.extraction.model_copy(update={"gold": [human_gold]})}
    )

    assert unmatched_gold([as_cue]), "an unreachable cue-derived gold must still be reported"
    assert unmatched_gold([as_human]) == [], "a human label is not required to be cue-reachable"


# T26b — the candidate-trait dimensions. Traits are elicited in the interview and
# never read from an ad, so the whole-model checks above (cues, gold, a cue that
# fires on a real ad) are scoped to `ad_side` and these three stand in their place.

SELF_RATING = re.compile(
    r"\b(rate|scale of|out of ten|how (creative|ambitious) are you"
    r"|pun[tú]a|del 1 al|escala de|c[oó]mo de (creativo|ambicioso)"
    r"|puntua|de l'1 al|escala d)",
    re.IGNORECASE,
)


def test_trait_dimensions_carry_no_cues(dimensions: list[Dimension]) -> None:
    """A cue on a trait asserts an ad's wording evidences the *candidate*.

    It evidences the employer's prose. The loader refuses it outright, so this
    asserts the committed model never tries — and that traits bring no gold
    either, since gold is an ad span and a trait has no ad to draw one from.
    """
    for trait in candidate_traits(dimensions):
        assert not any(trait.extraction.cues.values()), f"{trait.id} carries ad cues"
        assert not trait.extraction.gold, f"{trait.id} carries ad gold"


def test_every_trait_dimension_declares_its_rungs(dimensions: list[Dimension]) -> None:
    """A coined dimension without `levels` has no class set for anything to score."""
    traits = candidate_traits(dimensions)

    assert traits, "the model declares no candidate_trait dimensions"
    for trait in traits:
        assert len(trait.levels) >= 2, f"{trait.id} declares fewer than two rungs"
        for level in trait.levels:
            assert level.tell.strip(), f"{trait.id} has a rung with no tell"
    assert trait_dimensions_ready(dimensions) == sorted(t.id for t in traits)


def test_a_trait_question_is_behavioural_not_a_self_rating(dimensions: list[Dimension]) -> None:
    """METHODS §2.1: "tell me about a time…", never "rate your ambition out of ten".

    A self-rating measures what someone believes about themselves, which is the
    one thing the story bank exists to avoid asking for.
    """
    for trait in candidate_traits(dimensions):
        for question in trait.elicitation.questions:
            for language in LANGUAGES:
                text = question.text.get(language)
                assert not SELF_RATING.search(text), (
                    f"{trait.id}.{question.id}[{language}] asks for a self-rating: {text!r}"
                )


def test_the_readme_names_every_group_the_model_declares() -> None:
    """`dimensions/README.md` said five groups; T57 made it seven.

    The paragraph listed `dealbreakers`, `terms`, `the_work`, `people`, `growth`
    and was correct until `requirements` and `skills` were added to keep every
    picker group under the eight-row no-scroll cap. Nothing read it, so it went
    stale in the same commit that made it stale — prose about the model that no
    test reads is documentation only until the model moves.

    Reported by review on the PR that introduced the two groups (#320); this is
    the fixture, so it is caught by the suite rather than by the next reader.
    """
    from pathlib import Path

    from integral.dimensions import load_dimensions

    readme = (Path(__file__).resolve().parents[1] / "dimensions" / "README.md").read_text(
        encoding="utf-8"
    )
    paragraph = readme.split("## Groups")[1].split("It is purely presentational")[0]
    # The list is what follows "without already knowing its name:" — slicing there
    # rather than over the whole paragraph keeps the field name `group`, which the
    # sentence necessarily mentions, out of the set of group values.
    named = set(re.findall(r"`([a-z_]+)`", paragraph.split("its name:")[1]))
    declared = {dimension.group for dimension in load_dimensions()}

    assert declared == named, f"README names {sorted(named)}, the model declares {sorted(declared)}"
    # And the count the prose states, which a set comparison cannot see: the
    # sentence said "five" while listing five stale names, so both halves were
    # wrong together and either alone would have passed.
    words = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
    spelled = words.get(len(declared), str(len(declared)))
    assert spelled in paragraph.lower(), f"the prose does not say there are {spelled} groups"


_FULL_TIME_CASES: tuple[tuple[str, bool, str], ...] = (
    ("Employment type: Full-time\nRemote in Europe", True, "the labelled field these boards use"),
    ("Headquarters:\nZug\n\nFull-time\n\nRemote in Europe", True, "the field on its own line"),
    ("This is a full-time position based in Barcelona.", True, "stated of the offered role"),
    (
        "Those who prefer consistent contract work over a full-time role, who want more.",
        False,
        "a comparison — it states what the post is not",
    ),
    ("Unlike a full-time job, this engagement is per-deliverable.", False, "a contrast"),
    ("https://weworkremotely.com/remote-jobs/yooli-full-time-engineer", False, "a URL slug"),
)


@pytest.mark.parametrize(("text", "should_fire", "why"), _FULL_TIME_CASES)
def test_the_full_time_cue_reads_the_offered_contract_not_a_comparison(
    text: str, should_fire: bool, why: str
) -> None:
    """`contracted_hours` 0.9, run the way extraction runs it — over a document.

    Two defects hid behind the gold row for this cue, and neither was visible to
    the gold check. `_gold` runs a pattern against the **isolated span**
    (`extraction.py:654`), so a `^…$` branch matched there — the span is the whole
    string — while `extraction.py:331` compiles with `re.IGNORECASE` alone and
    binds those anchors to the whole advert, where the branch could never fire.
    And the `full[- ]time\\s+(role|position|…)` branch matched exactly one advert
    in the corpus: the comparison *"…prefer consistent contract work over a
    full-time role…"* that the review reported. The phrasing reads the same in an
    offer and in a contrast, so it bought nothing and cost only the false
    positive.

    These cases therefore search whole documents, with the flags extraction uses.
    A cue checked only where its own gold points cannot be caught being dead.
    """
    from integral.dimensions import load_dimensions

    dimension = next(d for d in load_dimensions() if d.id == "contracted_hours")
    cue = next(c for c in dimension.extraction.cues["en"] if c.value == 0.9)

    assert bool(re.search(cue.pattern, text, re.IGNORECASE)) is should_fire, why
