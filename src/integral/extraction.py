"""Staged extraction of dimension values from an advert (T15).

Specification v2, step 8: **"the model is the last resort rather than the
first."** Reading every advert with a model is what makes this loop expensive
enough to stop being run, and most of what an advert states is stated plainly.
So extraction runs in three stages, each cheaper than the next:

1. **normalise** — the advert becomes the same shape whatever connector found
   it (`normalise`);
2. **rules** — the dimension model's own `Cue` patterns take what they can
   outright, with negation inverting rather than dropping (`rules_stage`);
3. **the model** — asked only about the dimensions the first two could not
   settle (`model_request`, `accept_model_scores`).

Stage 2 is T14's lexical prefilter, folded in here (#81). It was never a
separate pipeline, only a separate task file, and its gate —
`prefilter_recall >= 0.98` against corpus positives — was measured against
labels T5 never supplied. Its recall obligation survives the fold unchanged and
is what `retained_positives` measures: **the rules stage may narrow what the
model is asked, never decide that a dimension is absent.**

## What this module does not do

It does not call a model. Like `elicit_extract` (T8), the model here is the
session running the step skill: this module says exactly which dimensions are
unsettled and what the advert says, and validates what comes back. That keeps
every judgement the model makes reviewable as data, and keeps this module
deterministic enough to test.

It also never sees the candidate. `extractions/<offer_id>.json` is
candidate-independent by construction — there is no parameter here through
which a profile could arrive — which is what lets an extraction be cached or
shared. Relating an offer to *this* candidate is T42's local annotation pass.

## The gate, and why it currently reports nothing

`extraction_macro_f1 >= 0.75`, and D-2 (`lo-77a6`) binds how it may be
computed:

* only over `Label` rows a person decided, in the **evaluation** split — never
  over `corpus/labelled/suggestions.json`, never over `extraction.gold`;
* `n` reported beside every score, per dimension and in aggregate;
* **refused entirely below the per-dimension floor.**

The corpus has 14 evaluation-split labels over 4 ads, no dimension above 4. So
every dimension is below the floor and the honest output is
`extraction_macro_f1: null` with `extraction_status: "unmeasured"` and the
dimensions named. Unmeasured is a *third* outcome — not a pass, not a fail —
and reporting it as either is the failure D-2 exists to prevent. Do not
"fix" it by relabelling cue-derived gold as human; the empty result is the
finding.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from integral.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    Dimension,
    Language,
    ad_side,
    load_dimensions,
)
from integral.harness import DEFAULT_STORE_PATH, Label, LabelledAd, load_store
from integral.offers import Offer

# §4.1's site: `cue_findings` is where an advert's evidence items become one
# dimension score. The register writes that mean as weighted by extraction
# confidence; a cue hit carries no per-item confidence, so here the weights are
# equal and the formula degenerates to the arithmetic mean. Same formula, one
# input the rules stage cannot supply — stage 3's model scores are where a real
# confidence would enter, and the ref is declared so that divergence is visible
# from the register rather than only from this comment.
METHODS_REF = "METHODS.md#41-dimension-score--weighted-mean"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T15.json"
DEFAULT_NEGATION_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T16.json"

# Below this many evaluation-split labels, a per-dimension F1 is not a
# measurement of the extractor — it is a measurement of which two adverts
# happened to get labelled. At n=10 a single disagreement moves F1 by roughly
# 0.1, already a third of the distance between the 0.75 threshold and chance;
# below that the number swings further than the thing it is meant to detect.
# Declared here rather than passed in, so a run cannot lower the floor until it
# passes (D-2).
MIN_EVALUATION_LABELS_PER_DIMENSION = 10

# T56's round-1 subset, decided cold on 2026-08-25 and recorded here so that the
# declaration lives beside the thing it describes rather than only in prose.
#
# It is a **target, not a cap.** `measure` scores every dimension that reaches the
# label floor, and it must keep doing so: as the corpus grows, more dimensions
# clear the floor and the macro *should* widen with them. Freezing the mean to
# five ids would make the gate permanently narrower than the model.
#
# What D-2 forbids is choosing the subset to flatter the number — narrowing it,
# or picking again once a score is known. Widening by labelling honestly is the
# opposite of that. So the rule is enforced the way this repo enforces its other
# rules: `declared_subset` and `scorable_dimensions` are both recorded, and any
# dimension in the second and not the first is named in the evidence. A widening
# is then visible and auditable instead of silent — which is what "closed" was
# reaching for and could not deliver on its own.
DECLARED_SUBSET: tuple[str, ...] = (
    "compensation_transparency",
    "contract_stability",
    "remote_arrangement",
    "schedule_flexibility",
    "seniority_expectation",
)

# Words that flip a `negatable` cue. Deliberately small and per-language:
# enough for "no on-call" / "sense guàrdies" / "sin guardias". Scope, not
# vocabulary, is what made this wrong in practice — see `_CLAUSE_BOUNDARY`.
_NEGATORS: dict[Language, tuple[str, ...]] = {
    "en": ("no", "not", "never", "without", "free from"),
    "es": ("no", "sin", "nunca"),
    "ca": ("no", "sense", "mai"),
}

# How far back from a cue match a negator still governs it. Characters, not
# tokens, because the cue patterns are regexes over raw text and there is no
# tokeniser here. This is now only a backstop: `_CLAUSE_BOUNDARY` is what
# actually ends a negator's scope, and it ends it sooner in every real case.
_NEGATION_WINDOW = 40

# Where a negator's scope ends. A negator governs its own clause and nothing
# past it — the window alone did not know that, and two adverts in the corpus
# paid for it: `manfred-8392` read "sin ambigüedades. **El inglés fluido" as a
# negated English requirement, and `remotive-2091075` let a `not` in one bullet
# invert the next bullet across a blank line. A comma is deliberately *not* a
# boundary: "Durante tus primeros 6 meses, no harás guardias" is one clause for
# this purpose and negating it is right.
_CLAUSE_BOUNDARY = re.compile(r"[.!?;\n]")

# How many cue matches it takes for the rules stage to settle a **bipolar**
# dimension. On a bipolar scale the same word sits on both sides — "autonomía"
# appears in "trabajarás con autonomía" and in "ejecutar las tareas asignadas
# con autonomía", which a person read as -0.6 — so one keyword is not evidence
# of a direction, it is evidence of the topic. Unipolar dimensions are exempt:
# there the scale runs from absent to present and a single match *is* presence.
#
# Found by measurement, not by argument: `prefilter_suppression` caught the
# team_autonomy case above settling +1 against a human -1.
_CONFIRMING_MATCHES_FOR_BIPOLAR = 2

Provenance = Literal["rules", "model"]
ExtractionStatus = Literal["measured", "unmeasured"]


class ExtractionError(Exception):
    """A caller mistake — never a normal outcome of reading an advert."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSpan(Strict):
    """A half-open range of the advert, and the text it covers.

    `quote` is stored beside the offsets rather than derived from them so an
    extraction stays readable on its own, and so `accept_model_scores` has
    something to check the offsets *against*. A span whose quote does not match
    what its offsets cover is a fabrication, and this is where it is caught.
    """

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _range_is_ordered(self) -> EvidenceSpan:
        if self.end <= self.start:
            raise ValueError(f"span end {self.end} must be after start {self.start}")
        if self.end - self.start != len(self.quote):
            raise ValueError("span length does not match the length of its quote")
        return self


class DimensionScore(Strict):
    """One dimension's value on one advert, with the advert's own words for it.

    `spans` is `min_length=1` for the same reason T8 refuses an episode with no
    dimension: a score with no evidence is unqueryable and unreviewable. The
    named test `test_score_without_evidence_span_is_rejected` pins it here
    rather than at the call sites, so no caller can produce one.
    """

    dimension: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    spans: list[EvidenceSpan] = Field(min_length=1)
    negated: bool = False
    provenance: Provenance


class NormalisedAd(Strict):
    """Stage 1 — one advert in the shape the later stages read.

    Carries the offer's own id and language rather than re-deriving them: an
    extraction that disagreed with its offer about which advert it describes
    would be worse than no extraction.
    """

    offer_id: str = Field(min_length=1)
    language: Language
    text: str = Field(min_length=1)
    title: str = ""
    company: str = ""

    def slice(self, start: int, end: int) -> str:
        return self.text[start:end]


class ModelRequest(Strict):
    """Stage 3's input: what the model is asked, and nothing else.

    There is no profile field, and there is no place to put one. The advert and
    the dimension ids are the whole of it — step 8's "never send the
    candidate's profile with the advert", made structural rather than
    remembered.
    """

    offer_id: str = Field(min_length=1)
    language: Language
    text: str = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)


class OfferExtraction(Strict):
    """`extractions/<offer_id>.json` — candidate-independent, by construction."""

    offer_id: str = Field(min_length=1)
    language: Language
    scores: list[DimensionScore] = Field(default_factory=list)
    # Dimensions neither stage settled. Named rather than omitted: "the advert
    # does not say" is a finding a ranking is entitled to show, and an absent
    # key cannot be told apart from a dimension nobody looked at.
    unsettled: list[str] = Field(default_factory=list)
    # Concepts the advert states that no dimension covers. T17's
    # `ontology_hit_rate` reads these; an ontology that never learns what it is
    # missing cannot be told it is stale.
    unmapped_concepts: list[str] = Field(default_factory=list)


def normalise(offer: Offer, *, default_language: Language = "es") -> NormalisedAd:
    """Stage 1 — the same shape whatever connector produced the offer.

    Unicode is NFC-normalised because the cue patterns are written against
    composed characters: an advert carrying a decomposed "à" would silently
    match no Catalan cue at all, and a stage that quietly matches nothing looks
    exactly like a stage that found nothing.

    `default_language` fills in only when the offer states none. Guessing is
    confined to this one place so the fallback is visible in a diff.
    """
    text = unicodedata.normalize("NFC", offer.text)
    if not text.strip():  # pragma: no cover - Offer forbids blank text
        raise ExtractionError(f"{offer.id}: advert text is blank after normalisation")
    return NormalisedAd(
        offer_id=offer.id,
        language=offer.language or default_language,
        text=text,
        title=offer.title or "",
        company=offer.company or "",
    )


def _normalise_labelled(ad: LabelledAd) -> NormalisedAd:
    """Stage 1 over a corpus ad rather than an offer.

    Kept separate from `normalise` rather than routing a `LabelledAd` through
    `Offer`: an offer id is content-addressed (`sha256:…`) and a corpus ad id is
    a portal reference, so the round-trip would need a fabricated id — a lie in
    the one field that says which advert this is. The two carry the same text
    and language, which is all the cue stage reads.
    """
    return NormalisedAd(
        offer_id=ad.id,
        language=ad.language,
        text=unicodedata.normalize("NFC", ad.text),
        title=ad.title,
        company=ad.company,
    )


def _negation_scope(text: str, start: int) -> str:
    """The text a negator would have to sit in to govern the match at `start`.

    The window back from the cue, cut at the last clause boundary inside it. A
    negator on the far side of that boundary belongs to a different statement.
    """
    window = text[max(0, start - _NEGATION_WINDOW) : start]
    boundaries = [m.end() for m in _CLAUSE_BOUNDARY.finditer(window)]
    return window[boundaries[-1] :] if boundaries else window


def _has_negator(text: str, language: Language) -> bool:
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _NEGATORS[language])


def _is_negated(text: str, start: int, language: Language) -> bool:
    """Does a negator govern the match beginning at `start`?"""
    return _has_negator(_negation_scope(text, start), language)


def cue_findings(ad: NormalisedAd, dimension: Dimension) -> DimensionScore | None:
    """Every cue of `dimension` that matches `ad`, resolved into one score.

    Returns `None` rather than a zero-valued score when nothing matches. The
    difference is the whole of the prefilter's recall obligation: "no cue
    matched" means *the model must be asked*, and a zero would mean "the advert
    says this dimension is absent" — a claim no regex is entitled to make.
    """
    cues = dimension.extraction.cues.get(ad.language, [])
    spans: list[EvidenceSpan] = []
    values: list[float] = []
    negations: list[bool] = []

    for cue in cues:
        for match in re.finditer(cue.pattern, ad.text, re.IGNORECASE):
            if match.end() <= match.start():  # pragma: no cover - zero-width cue
                continue
            value = cue.value
            # Two routes to the same conclusion, and both must reach it. A
            # `negatable` cue is negated by a negator *before* it, which is what
            # `_is_negated` can see; a `denies` cue carries its negator inside its
            # own pattern, where nothing looking backwards ever will.
            negated = cue.denies or (
                cue.negatable and _is_negated(ad.text, match.start(), ad.language)
            )
            if negated:
                value = -value
            spans.append(
                EvidenceSpan(
                    start=match.start(),
                    end=match.end(),
                    quote=ad.slice(match.start(), match.end()),
                )
            )
            values.append(value)
            negations.append(negated)

    if not spans:
        return None

    # A cue whose match lies wholly inside another cue's match is the less
    # specific reading of the same words, and must not be averaged in beside it.
    # "Modelo presencial con 1 día de teletrabajo" matches both the hybrid cue
    # and the bare `presencial` inside it; averaging 0.5 with 0.0 records 0.25,
    # which is not a rung this dimension has. Dropping the contained match is
    # what a guard on the narrower pattern was reaching for, except that a guard
    # can only look one way — a lookahead misses `teletrabajo … presencial` — and
    # this is symmetric by construction.
    kept = [
        i
        for i, span in enumerate(spans)
        if not any(
            j != i
            and other.start <= span.start
            and span.end <= other.end
            and (other.end - other.start) > (span.end - span.start)
            for j, other in enumerate(spans)
        )
    ]
    spans = [spans[i] for i in kept]
    values = [values[i] for i in kept]
    # Recomputed from what survived, never carried over. A dropped match must
    # not leave its negation behind: the score would report `negated=True` with
    # no negated span under it, and — since a negated match settles a bipolar
    # dimension on its own (T59) — one leftover flag would bypass the two-match
    # requirement entirely.
    negations = [negations[i] for i in kept]
    negated_any = any(negations)

    # A bipolar dimension needs corroboration, and needs the matches to agree.
    # Disagreeing cues on a bipolar scale are the clearest possible signal that
    # the advert is saying something the cue list cannot read — exactly the case
    # the model exists for — so this returns None and the dimension stays on
    # stage 3's agenda rather than being settled by whichever cue averaged out.
    #
    # Corroboration is asked of **positives only**, and the asymmetry is the
    # point. One `sprint` does not establish a process culture: the word appears
    # in passing, in a tool list, in a sentence about something else. `sin
    # sprints tradicionales` is not ambiguous in any of those ways — a denial is
    # a claim the advert went out of its way to make. Requiring a second match
    # before believing it is how `manfred-8392/process_formality` reached the
    # model as "unsettled" while the advert said plainly what it meant (T59).
    #
    # Measured over the committed corpus when this landed: three (ad, dimension)
    # pairs out of 2,080 become settled this way, all three the same true denial,
    # and `prefilter_suppressed_positives` stays 0. That is a narrow base of
    # evidence and worth re-reading if the corpus grows.
    if dimension.polarity == "bipolar":
        signs = {_sign(value, False) for value in values}
        if len(signs) > 1:
            return None
        if len(spans) < _CONFIRMING_MATCHES_FOR_BIPOLAR and not negated_any:
            return None

    return DimensionScore(
        dimension=dimension.id,
        value=max(-1.0, min(1.0, sum(values) / len(values))),
        spans=spans,
        negated=negated_any,
        provenance="rules",
    )


def rules_stage(ad: NormalisedAd, dimensions: list[Dimension]) -> list[DimensionScore]:
    """Stage 2 — what the dimension model's own cues can take outright.

    Only ad-side dimensions are considered: a `candidate_trait` carries no cues
    by construction (`Dimension._a_trait_cannot_be_read_from_an_ad`), so asking
    an advert about one would produce a permanently unsettled dimension that
    the model then gets asked about on every single offer.
    """
    scored = [cue_findings(ad, dimension) for dimension in ad_side(dimensions)]
    return [score for score in scored if score is not None]


def unsettled_dimensions(dimensions: list[Dimension], scores: list[DimensionScore]) -> list[str]:
    """The ad-side dimensions stage 2 did not settle — stage 3's whole agenda."""
    settled = {score.dimension for score in scores}
    return sorted(d.id for d in ad_side(dimensions) if d.id not in settled)


def model_request(ad: NormalisedAd, unsettled: list[str]) -> ModelRequest:
    """Stage 3's input. Empty `dimensions` means the model need not be called."""
    return ModelRequest(
        offer_id=ad.offer_id,
        language=ad.language,
        text=ad.text,
        dimensions=sorted(unsettled),
    )


def accept_model_scores(
    ad: NormalisedAd,
    proposed: list[DimensionScore],
    asked: list[str],
) -> list[DimensionScore]:
    """Validate what the model returned before it becomes an extraction.

    Three refusals, each a thing a model does and a schema cannot catch:

    * **a span that is not in the advert.** `EvidenceSpan` checks that the quote
      matches its own length; only here can it be checked against the advert it
      claims to come from. An invented quote would put fabricated text in front
      of the candidate as the employer's own words, which is the one thing
      step 8's evidence spans exist to prevent.
    * **a dimension nobody asked about.** Stage 3 is asked a specific list; an
      answer outside it is either a hallucinated dimension id or the model
      re-deciding what stage 2 already settled from the advert's own words.
    * **the same dimension twice**, which would make the extraction's meaning
      depend on which copy a reader happened to take.
    """
    allowed = set(asked)
    seen: set[str] = set()
    accepted: list[DimensionScore] = []
    for score in proposed:
        if score.dimension not in allowed:
            raise ExtractionError(
                f"{ad.offer_id}: model returned {score.dimension!r}, which it was not asked about"
            )
        if score.dimension in seen:
            raise ExtractionError(f"{ad.offer_id}: model scored {score.dimension!r} twice")
        seen.add(score.dimension)
        for span in score.spans:
            if ad.slice(span.start, span.end) != span.quote:
                raise ExtractionError(
                    f"{ad.offer_id}: {score.dimension} cites {span.quote!r}, "
                    "which is not what the advert says at those offsets"
                )
        accepted.append(score.model_copy(update={"provenance": "model"}))
    return accepted


def extract(
    offer: Offer,
    dimensions: list[Dimension],
    *,
    model_scores: list[DimensionScore] | None = None,
    unmapped_concepts: list[str] | None = None,
    default_language: Language = "es",
) -> OfferExtraction:
    """All three stages over one offer.

    `model_scores` is what the session returned for `model_request(...)`. Left
    `None`, the extraction is the rules stage alone and every dimension the
    cues did not settle stays in `unsettled` — which is the correct output for
    a run that has not called a model, and is emphatically not the same as
    those dimensions being absent from the advert.
    """
    ad = normalise(offer, default_language=default_language)
    scores = rules_stage(ad, dimensions)
    asked = unsettled_dimensions(dimensions, scores)
    if model_scores:
        scores = scores + accept_model_scores(ad, model_scores, asked)
    return OfferExtraction(
        offer_id=ad.offer_id,
        language=ad.language,
        scores=sorted(scores, key=lambda s: s.dimension),
        unsettled=unsettled_dimensions(dimensions, scores),
        unmapped_concepts=sorted(unmapped_concepts or []),
    )


def _sign(value: float, negated: bool) -> int:
    """The three-class form of a value, matching `harness._sign`.

    Extraction and the labelled store must agree about what "against" means or
    the two are not comparable at all.
    """
    if negated or value < 0:
        return -1
    return 1 if value > 0 else 0


def _class_of(sign: int, dimension: Dimension) -> int:
    """The comparable class of a sign, given what the dimension's scale means.

    On a **unipolar** scale there is no negative: it runs from absent to
    present, so "no travel" and "travel not mentioned as required" are the same
    class. The store and the cue set encode that differently — a person wrote
    "Sin viajes ni guardias" as `value=0.0, negated=True`, which
    `harness._sign` reads as -1, while the cue matching the same phrase carries
    `value=0.0`, which reads as 0. Comparing those raw made two encodings of one
    agreement look like a disagreement.

    Bipolar scales keep all three classes, where -1 and 0 genuinely differ.
    """
    if dimension.polarity == "unipolar":
        return 1 if sign > 0 else 0
    return sign


def evaluation_labels(store: list[LabelledAd]) -> list[tuple[LabelledAd, Label]]:
    """Every label a person placed on an **evaluation**-split ad.

    D-2's denominator, and the only one this gate may use. `Label.source` is
    already `human | confirmed | edited` by its own type, so the filter that
    matters is the split: elicitation-split labels shaped the model and scoring
    against them measures the model against its own training.
    """
    return [(ad, label) for ad in store if ad.split == "evaluation" for label in ad.labels]


def _per_dimension_counts(pairs: list[tuple[LabelledAd, Label]]) -> dict[str, int]:
    return dict(Counter(label.dimension for _, label in pairs))


def prefilter_suppression(
    store: list[LabelledAd],
    dimensions: list[Dimension],
) -> tuple[int, int, list[str], list[str]]:
    """T14's recall obligation, folded in: how often did the rules stage bury a positive?

    The stage cannot drop a dimension outright — anything its cues do not settle
    stays in `unsettled` and reaches the model — so "did it drop a true
    positive?" is structurally always no, and measuring *that* would be a
    tautology dressed as a gate. The reachable failure is the other one: the
    cues settle a dimension a person labelled positive, and settle it with the
    wrong sign, so the model is never asked and the wrong answer stands.

    **Two different failures were being counted as one, and only the first is
    this stage's.** Split on a question with a checkable answer: *did any cue
    match inside the span the person cited as their evidence?*

    * **Yes** — the stage read the very words the labeller pointed at and
      resolved them to the opposite sign. Nothing was missing; the combination
      was wrong. That is a soundness bug in this stage, and it is what
      `prefilter_suppressed_positives` counts.
    * **No** — no pattern in the cue set reaches that text at all, so the stage
      never saw the evidence and settled on whatever else the advert happened to
      contain. That is a vocabulary gap, which is T57's `ontology_hit_rate` and
      not this gate's, and it is counted separately as
      `prefilter_uncovered_positives`.

    Both are recorded, because the second is not harmless — a confident wrong
    answer stops the model being asked either way. It is simply not evidence
    that *this* stage reasons badly, and a gate that cannot tell the two apart
    sends whoever reads it to fix the wrong thing. Widening the corpus adds
    adverts the cue set has never seen; without the split, `== 0` becomes a
    threshold on how much vocabulary the model happens to have, asserted against
    a task that does not own it.

    Counted over both splits. This is a property of the cue set, not a score
    against held-out data, so the elicitation-split labels are legitimate here
    in a way they are not for `extraction_macro_f1`.
    """
    suppressed: list[str] = []
    uncovered: list[str] = []
    checked = 0
    by_id = {d.id: d for d in dimensions}
    for ad in store:
        for label in ad.labels:
            dimension = by_id.get(label.dimension)
            if dimension is None:
                continue  # unknown_dimensions() is harness's finding, not this gate's
            truth = _class_of(_sign(label.value, label.negated), dimension)
            if truth == 0:
                continue
            checked += 1
            found = cue_findings(_normalise_labelled(ad), dimension)
            if found is None:
                continue  # not settled — the model still gets asked, which is the contract
            predicted = _class_of(_sign(found.value, found.negated), dimension)
            if predicted == _class_of(truth, dimension):
                continue
            where = (
                f"{ad.id}/{label.dimension}: cues settled {predicted}, "
                f"a person labelled {_class_of(truth, dimension)}"
            )
            if _cue_reaches_the_cited_span(ad, label, dimension):
                suppressed.append(where)
            else:
                uncovered.append(f"{where} — no cue reaches the cited span")
    return len(suppressed), checked, sorted(suppressed), sorted(uncovered)


def _cue_reaches_the_cited_span(ad: LabelledAd, label: Label, dimension: Dimension) -> bool:
    """Did any cue match inside the text the labeller pointed at?

    The span is the labeller's own answer to "what in this advert made you say
    that", so a cue matching inside it is the strongest available evidence that
    the stage was looking at the right words.

    **Sliced with the stored offsets, then NFC-normalised — in that order, and
    both steps matter.** The offsets index the store's raw text, so slicing must
    happen first or they point at the wrong characters. But `cue_findings`
    matches against `_normalise_labelled`'s NFC output, so comparing a cue to the
    *raw* segment asks a different question than the stage was asked: a cited span
    holding decomposed characters would fail to match a composed cue that had
    matched perfectly well upstream. The audit would then file a real soundness
    failure under `prefilter_uncovered_positives` and quietly drop it out of the
    gate — the corpus is full of decomposed text and non-BMP characters, and this
    is the same hazard `test_decomposed_characters_are_composed_before_cues_run`
    exists for, one layer up.
    """
    for span in label.spans:
        segment = unicodedata.normalize("NFC", ad.text[span.start : span.end])
        for cue in dimension.extraction.cues.get(ad.language, []):
            if re.search(cue.pattern, segment, re.IGNORECASE):
                return True
    return False


def negation_recall(
    store: list[LabelledAd],
    dimensions: list[Dimension],
) -> tuple[int, list[str]]:
    """T59's score: of the negated evaluation labels, which does the extractor also read as negated?

    Recall over the **rules stage**, because that is the only stage a gate can
    run — stage 3 asks a model and an evidence file cannot make that call. So a
    negated label whose dimension no cue settles is a **miss**, not an exclusion.
    Excluding it would measure the scope rule against exactly the adverts the
    cue set already reaches and report ~1.0 whatever the cues cover; the miss
    reasons below say which of the two failures each one is.

    Unlike `prefilter_suppression`, a label naming an unknown dimension is
    counted rather than skipped. There, skipping shrinks a count that is not a
    scored denominator; here it would shrink the denominator of a score, so a
    typo would raise recall.
    """
    by_id = {d.id: d for d in dimensions}
    hits = 0
    misses: list[str] = []
    for ad, label in evaluation_labels(store):
        if not label.negated:
            continue
        dimension = by_id.get(label.dimension)
        if dimension is None:
            misses.append(f"{ad.id}/{label.dimension}: no such dimension")
            continue
        found = cue_findings(_normalise_labelled(ad), dimension)
        if found is None:
            misses.append(f"{ad.id}/{label.dimension}: no cue settled the dimension")
        elif not found.negated:
            misses.append(f"{ad.id}/{label.dimension}: settled, but not as negated")
        else:
            hits += 1
    return hits, sorted(misses)


def negation_audit(
    store: list[LabelledAd],
    dimensions: list[Dimension],
) -> dict[str, Any]:
    """T16's gate, and the count that shows the scope rule is doing something.

    Two numbers, and they are not the same kind of number:

    `negation_scope_leaks` is the **invariant**: no firing may have a clause
    boundary between its negator and its cue. It is 0 by construction of
    `_negation_scope`, so this is a regression gate — it does not show the
    negation is *accurate*, it shows the scope rule has not been widened back
    out. Accuracy is `extraction_negation_recall`, which needs a corpus this one
    does not have yet; T59 owns it and this file records why.

    `negation_window_only` is the **effect**: matches a negator reaches under
    the raw character window but not under the clause rule. Every one of those
    was a wrong negation before T16, so this is the count that would be 0 if the
    change had done nothing.

    `extraction_negation_recall` is the third and is a **score**, so it obeys
    D-2's floor: `negation_recall` computes it on every run, and it is recorded
    only once the evaluation split carries enough negated labels to divide by.
    """
    firings: list[str] = []
    leaks: list[str] = []
    window_only: list[str] = []

    for ad in store:
        normalised = _normalise_labelled(ad)
        text, language = normalised.text, normalised.language
        for dimension in ad_side(dimensions):
            for cue in dimension.extraction.cues.get(language, []):
                if not cue.negatable:
                    continue
                for match in re.finditer(cue.pattern, text, re.IGNORECASE):
                    scope = _negation_scope(text, match.start())
                    window = text[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
                    where = f"{ad.id}/{dimension.id}: {text[match.start() : match.end()]!r}"
                    if _has_negator(scope, language):
                        firings.append(where)
                        if _CLAUSE_BOUNDARY.search(scope):
                            leaks.append(where)
                    elif _has_negator(window, language):
                        window_only.append(where)

    # `evaluation_labels`, not every label in the store: this is the denominator of
    # a **score**, and D-2 binds those to the evaluation split. Counting the
    # elicitation split here would let ten labels that shaped the model unblock a
    # measurement of the model against itself. The firing audit above is the other
    # kind of number — a property of the cue set, not a score against held-out
    # data — so it reads both splits, for the reason `prefilter_suppression` gives.
    negated_labels = [
        f"{ad.id}/{label.dimension}" for ad, label in evaluation_labels(store) if label.negated
    ]
    hits, misses = negation_recall(store, dimensions)
    measurable = len(negated_labels) >= MIN_EVALUATION_LABELS_PER_DIMENSION

    return {
        "negation_scope_leaks": len(leaks),
        "negation_leaks": sorted(leaks),
        "negation_firings_count": len(firings),
        "negation_firings": sorted(firings),
        "negation_window_only_count": len(window_only),
        "negation_window_only": sorted(window_only),
        # T59's score. Null while the corpus is below the floor — not 0.0, the
        # same third outcome D-2 requires of `extraction_macro_f1`. The hits and
        # misses are recorded either way: below the floor they are what a person
        # reads to find out what the round is walking into.
        "extraction_negation_recall": round(hits / len(negated_labels), 4) if measurable else None,
        "negation_status": "measured" if measurable else "unmeasured",
        "negation_recall_hits": hits,
        "negation_recall_misses": misses,
        "negated_label_count": len(negated_labels),
        "negated_labels": sorted(negated_labels),
        "negation_label_floor": MIN_EVALUATION_LABELS_PER_DIMENSION,
    }


def _dimension_f1(
    pairs: list[tuple[LabelledAd, Label]],
    dimension: Dimension,
) -> dict[str, Any]:
    """One dimension's F1 = 2PR/(P+R), scored against the **rules stage**.

    Stage 3 asks a model, and an evidence file cannot make that call — so the
    prediction here is `cue_findings` alone, exactly as in `negation_recall`,
    and a dimension no cue settles predicts class 0. That is a *miss* against a
    positive label rather than an exclusion: excluding it would score the cue
    set against precisely the adverts the cue set already reaches.

    Binary, over "the advert asserts this dimension" — class 0 is the negative
    on both polarities, so a bipolar -1 read as +1 is one false positive and one
    false negative, which is what a sign error deserves.

    `f1` is **None** when the labels assert nothing — every one of them class 0.
    F1 on an empty positive class is undefined, not zero: the 0.0 that a
    precision of 0 conventionally yields is a *convention*, and averaging a
    convention into a mean and calling the mean a measurement is the move D-2
    exists to refuse. `measure` drops those dimensions from the average and
    names them.

    Dropping them must not hide anything, and it does not: `false_positives` is
    still counted for a dropped dimension, and `measure` totals those into
    `false_positives_outside_the_macro`, so a cue set hallucinating a dimension
    onto every advert is a visible number rather than an absent one. What it is
    not is a *score*, because there is nothing to score it against.
    """
    tp = fp = fn = 0
    for ad, label in pairs:
        truth = _class_of(_sign(label.value, label.negated), dimension)
        found = cue_findings(_normalise_labelled(ad), dimension)
        predicted = 0 if found is None else _class_of(_sign(found.value, found.negated), dimension)
        if truth == predicted:
            tp += truth != 0
            continue
        fp += predicted != 0
        fn += truth != 0
    # `asserted`, not `denominator`: a dimension whose labels are all class 0 has
    # no positive class, so no F1 — even when the rules stage fired on it and
    # `fp` is non-zero. Keying on the denominator instead let one false positive
    # manufacture an `f1: 0.0` and drag a dimension into the macro that the macro
    # cannot say anything about.
    asserted = tp + fn
    denominator = 2 * tp + fp + fn
    return {
        "f1": round(2 * tp / denominator, 4) if asserted else None,
        "n": len(pairs),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }


def measure(
    store_path: Path = DEFAULT_STORE_PATH,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """T15's gate, computed under D-2's rules — including its refusal to compute.

    The floor is checked **before** any prediction is made. Producing scores and
    then declining to average them would leave a per-dimension F1 sitting in the
    evidence file for somebody to quote, which is the same mistake one step
    later. If the denominator cannot support the number, the number is not
    computed at all.
    """
    store = load_store(store_path)
    dimensions = load_dimensions(dimensions_dir)
    ad_side_ids = sorted(d.id for d in ad_side(dimensions))

    pairs = evaluation_labels(store)
    counts = _per_dimension_counts(pairs)
    floor = MIN_EVALUATION_LABELS_PER_DIMENSION
    scorable = sorted(d for d in ad_side_ids if counts.get(d, 0) >= floor)
    below_floor = sorted(d for d in ad_side_ids if d not in scorable)

    suppressed_count, positives_checked, suppressed, uncovered = prefilter_suppression(
        store, dimensions
    )

    measured: dict[str, Any] = {
        # Null, not 0.0, and not omitted. Zero would be a failing score; an
        # absent key would be indistinguishable from a run that never happened.
        # Null plus `extraction_status` is the third outcome D-2 requires.
        "extraction_macro_f1": None,
        "extraction_status": "unmeasured",
        "label_floor": MIN_EVALUATION_LABELS_PER_DIMENSION,
        "evaluation_label_count": len(pairs),
        "evaluation_labels_by_dimension": dict(sorted(counts.items())),
        "scorable_dimensions": scorable,
        "dimensions_below_floor": below_floor,
        "prefilter_suppressed_positives": suppressed_count,
        "prefilter_positives_checked": positives_checked,
        "prefilter_suppressions": suppressed,
        # Not this gate's failure, and recorded so that it cannot be mistaken for
        # one: the cue set has no pattern reaching the text the labeller cited, so
        # the stage never saw the evidence it got wrong. T57 owns the vocabulary.
        "prefilter_uncovered_positives": len(uncovered),
        "prefilter_uncovered": uncovered,
    }

    by_id = {d.id: d for d in ad_side(dimensions)}
    per_dimension = {
        d: _dimension_f1([p for p in pairs if p[1].dimension == d], by_id[d]) for d in scorable
    }
    scored = {d: s for d, s in per_dimension.items() if s["f1"] is not None}
    unscored = sorted(set(per_dimension) - set(scored))
    measured["extraction_f1_by_dimension"] = per_dimension
    measured["dimensions_without_positives"] = unscored
    # The false positives of the dimensions the macro cannot cover. Zero here and
    # a short `extraction_scored_dimensions` means "nothing to score"; non-zero
    # means the rules stage is asserting dimensions no labeller did, which the
    # macro would otherwise never mention.
    measured["false_positives_outside_the_macro"] = sum(
        per_dimension[d]["false_positives"] for d in unscored
    )
    # D-2's third requirement: `n` beside the aggregate as well as beside each
    # dimension, counting only the dimensions the mean is over. Emitted on every
    # run, including an unmeasured one — a key that appears only on success makes
    # the two outcomes different *shapes*, and a reader who has to branch on which
    # keys exist cannot tell an unmeasured run from a run that never happened.
    measured["extraction_scored_n"] = sum(s["n"] for s in scored.values())
    measured["extraction_scored_dimensions"] = sorted(scored)
    measured["declared_subset"] = sorted(DECLARED_SUBSET)
    measured["scored_beyond_the_declared_subset"] = sorted(set(scored) - set(DECLARED_SUBSET))
    if scored:
        measured["extraction_macro_f1"] = round(
            sum(s["f1"] for s in scored.values()) / len(scored), 4
        )
        measured["extraction_status"] = "measured"
    return measured


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T15.json`."""
    measured = measure(store_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_negation_evidence(
    evidence: Path = DEFAULT_NEGATION_EVIDENCE_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """Audit and record `status/evidence/T16.json`."""
    audited = negation_audit(load_store(store_path), load_dimensions(dimensions_dir))
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(audited, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return audited


def _negation_main(argv: list[str]) -> int:
    """Write T16's gate evidence. Exit 1 on a scope leak, 0 while recall waits."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    audited = write_negation_evidence(Path(args[0]) if args else DEFAULT_NEGATION_EVIDENCE_PATH)
    if audited["negation_status"] == "measured":
        print(
            f"extraction_negation_recall: {audited['extraction_negation_recall']} over "
            f"{audited['negated_label_count']} negated label(s) "
            f"({audited['negation_recall_hits']} hit, {len(audited['negation_recall_misses'])} "
            "missed). The threshold is the gate block's to assert, not this command's.",
            file=sys.stderr,
        )
        for miss in audited["negation_recall_misses"]:
            print(f"  missed {miss}", file=sys.stderr)
    else:
        print(
            "extraction_negation_recall: UNMEASURED — "
            f"{audited['negated_label_count']} negated label(s), floor "
            f"{audited['negation_label_floor']}. Not a pass and not a fail (D-2); T59 owns it.",
            file=sys.stderr,
        )
    for leak in audited["negation_leaks"]:
        print(f"✗ {leak}", file=sys.stderr)
    print(json.dumps(audited, ensure_ascii=False))
    return 1 if audited["negation_scope_leaks"] else 0


def _main(argv: list[str]) -> int:
    """Write T15's gate evidence.

    **Suppressions are printed, not exited on.** They were an exit code while the
    corpus held four labelled adverts and the count was 0 by having nothing to be
    wrong about; T56's round 2 took it to 2 over 209 positives checked, and neither
    case is a cue bug — both are adverts carrying evidence at both poles of a
    bipolar dimension where the cue set has vocabulary for one. Failing here would
    block every `make evidence` in the repo behind a number whose right value is a
    decision (`lo-25b1`, reopened). The regression signal did not go away, it moved
    somewhere stricter: `test_prefilter` names the exact two, so a *third* fails the
    suite, and `lo-25b1`'s own gate block is what asserts the threshold.

    **Exit 0 while the score is unmeasured**, because
    unmeasured is not a failure: the extractor is not broken, the corpus cannot
    yet say whether it is right. The unmeasured state is loud on stderr instead,
    and `extraction_macro_f1` stays null so nothing downstream can quote a
    number that was never computed.
    """
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    # T16's evidence is written here too, not only under `--negation`. `make
    # evidence` discovers modules by `def _main` and runs each with no
    # arguments, so a file only a flag can regenerate is a file the drift check
    # never regenerates — which is precisely the silent staleness that target
    # exists to catch. The flag stays because T16's own gate wants the audit
    # alone, without T15's exit code riding on it.
    write_negation_evidence()

    if measured["extraction_status"] == "unmeasured":
        print(
            "extraction_macro_f1: UNMEASURED — "
            f"{measured['evaluation_label_count']} evaluation labels, floor "
            f"{measured['label_floor']} per dimension; "
            f"{len(measured['dimensions_below_floor'])} dimension(s) below it. "
            "Not a pass and not a fail (D-2).",
            file=sys.stderr,
        )
    for suppression in measured["prefilter_suppressions"]:
        print(f"✗ {suppression}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    if "--negation" in sys.argv:
        raise SystemExit(_negation_main(sys.argv))
    raise SystemExit(_main(sys.argv))
