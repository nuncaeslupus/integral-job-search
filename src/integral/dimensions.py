"""The dimension model — schema, loader, validator (T2).

`dimensions/*.yaml` is the spine of the system: the questions asked, the cues
extracted from an ad, the ranking and the explanations are all projections of
it (`status/specification.md` §5.1). Everything here exists to make that
contract mechanical rather than a convention:

* the Pydantic models refuse a dimension that does not satisfy §5.1, including
  unknown fields — a typo'd key is a silently ignored setting otherwise;
* `load_dimensions` raises, because a caller cannot proceed on a broken model;
* `collect_violations` reports, because a gate that crashes records no number;
* `methods_anchors` resolves every `methods_ref` against `docs/METHODS.md`,
  which is what makes `undocumented_methods == 0` (T22) checkable at all.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from integral.corpus import LANGUAGES, load_ads

# src-layout repo root, as in `integral.corpus`: valid for the editable install
# this project is always used through.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIMENSIONS_DIR = _REPO_ROOT / "dimensions"
DEFAULT_METHODS_PATH = _REPO_ROOT / "docs" / "METHODS.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T2.json"
DEFAULT_COVERAGE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T3.json"
DEFAULT_SIDE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T23.json"

# `LANGUAGES` is imported, not restated: a dimension carries all of them on every
# human-readable string (a label in one language only produces a question no
# Catalan-speaking candidate can answer), and a second copy of the tuple drifts
# from the corpus it is supposed to mirror. The `Literal` below is the one place
# the languages are spelled out again — Pydantic needs them statically — and
# `test_schema_languages_match_the_corpus_languages` holds the two in step.
Language = Literal["en", "es", "ca"]
# The same three, as a tuple a type checker accepts as cue-dict keys.
SCHEMA_LANGUAGES: tuple[Language, ...] = get_args(Language)

# Which half of the comparison a dimension lives on (`status/plan.md`, scope
# extension 2026-08-16 §2). Everything in v0 is `matched` and stays so by
# default — the field is additive.
#
#   matched          the ad describes it, the candidate has a preference about
#                    it, and ranking compares the two. Needs cues.
#   candidate_fact   a fact about the person — languages, location, salary
#                    floor — filtered against an ad-side *requirement* named by
#                    `compares_against`, not weighed against a preference.
#   candidate_trait  creativity, ambition, learning orientation. No ad wording
#                    evidences these, so they are elicited and never extracted.
Side = Literal["matched", "candidate_fact", "candidate_trait"]

# Where a gold example's value came from — the distinction D-2 exists to make
# unmixable (`arsenal/tasks/lo-77a6.md`).
#
#   cue     the span was found by searching the corpus for text this dimension's
#           own cues already match, then reading the surrounding excerpt. Real
#           ad wording, and a fair demonstration that a cue fires on genuine
#           market language — but not independent of the extractor. Scoring
#           extraction against it asks a regex to re-find the string it was
#           written from, which passes near 1.0 and measures nothing.
#   human   a person read the ad and decided the value. The only kind that can
#           evidence generalisation, and the only kind `extraction_macro_f1`
#           may be computed over.
#
# There is deliberately no default. A default is a provenance decided by
# absence, and getting it wrong in the `human` direction is exactly the silent
# failure this field exists to prevent — so the schema makes every author say
# which they have.
GoldProvenance = Literal["cue", "human"]

# Which section of the labelling picker a dimension appears under. Purely a
# presentation axis — nothing scores on it — but it is declared here rather than
# in the page because a picker that lists 22 flat options is the thing that made
# hand-labelling slow: the labeller could not find a dimension without already
# knowing its name. `dealbreakers` is exactly the `kind: hard` set today; that
# is a coincidence of v0 content, not a rule, so the two stay independent.
Group = Literal["dealbreakers", "terms", "the_work", "people", "growth"]
GROUPS: tuple[Group, ...] = get_args(Group)

# `METHODS.md#<github-style-slug>` — a relative link into the methods register,
# resolved by `methods_anchors`. Any other shape is a link nothing can check.
METHODS_REF = re.compile(r"^METHODS\.md#[a-z0-9][a-z0-9-]*$")
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")

DimensionId = Annotated[str, Field(pattern=SNAKE_CASE.pattern, min_length=2, max_length=64)]


class DimensionError(Exception):
    """A dimension file does not satisfy the §5.1 contract."""


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this schema.

    Connectors "may not invent fields" (§5.2); the spine is held to the same
    rule, because an ignored key reads as a setting that took effect.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalisedText(Strict):
    """A string in each corpus language. All three are required."""

    en: str = Field(min_length=1)
    es: str = Field(min_length=1)
    ca: str = Field(min_length=1)

    def get(self, language: str) -> str:
        if language not in LANGUAGES:
            raise KeyError(f"unknown language {language!r}; known: {', '.join(LANGUAGES)}")
        return str(getattr(self, language))


class Level(Strict):
    """One named rung on a dimension's scale — the unit a human actually labels in.

    The scale is `-1..1` because the ranker needs a number, but nobody can
    answer "is this ad 0.6 or 0.7 on mentoring". A dimension therefore declares
    the two-to-five *named* positions its scale really has, each with the value
    it stands for and a `tell` naming what that rung looks like in ad wording.
    The labeller clicks a name; the float is a storage detail they never see.

    This is also what gives `extraction_macro_f1` (T15) a class set. Macro-F1 is
    defined over classes, and a continuous score has none — so the levels are
    the classes, and an extracted float is snapped to the nearest rung
    (`Dimension.snap`) before it is compared with a human label. Without this
    the metric had to invent a binning rule at measurement time, where it would
    be unreviewable and could be chosen to flatter the result.
    """

    value: float = Field(ge=-1.0, le=1.0)
    label: LocalisedText
    tell: str = Field(min_length=1)


def synthetic_levels() -> list[Level]:
    """The minimal two-rung scale the synthetic test-fixture dimensions carry.

    Five modules build a throwaway `Dimension` to exercise a driver that only
    reads its id, side and questions. None of them is about the scale, but
    `levels` is required — a dimension whose rungs are optional is a dimension a
    real author can forget to give any, which is the drift the field exists to
    stop. One helper keeps that requirement from being answered five slightly
    different ways.
    """
    return [
        Level(
            value=0.0,
            label=LocalisedText(en="Absent", es="Ausente", ca="Absent"),
            tell="the ad says nothing about it",
        ),
        Level(
            value=1.0,
            label=LocalisedText(en="Present", es="Presente", ca="Present"),
            tell="the ad says so plainly",
        ),
    ]


class Question(Strict):
    """A behavioural elicitation question (METHODS §2.1), not a self-rating."""

    id: DimensionId
    text: LocalisedText


class ReactionProbe(Strict):
    """Selector for the ad excerpt a reaction is elicited on (METHODS §2.4)."""

    excerpt_kind: str = Field(min_length=1)


class Elicitation(Strict):
    questions: list[Question] = Field(min_length=1)
    reaction_probes: list[ReactionProbe] = Field(default_factory=list)

    @field_validator("questions")
    @classmethod
    def _question_ids_are_unique(cls, questions: list[Question]) -> list[Question]:
        seen = [q.id for q in questions]
        duplicates = sorted({qid for qid in seen if seen.count(qid) > 1})
        if duplicates:
            raise ValueError(f"duplicate question id(s): {', '.join(duplicates)}")
        return questions


class Cue(Strict):
    """A regex over ad text and the dimension value a match contributes.

    `negatable` records that a negated match inverts the sign rather than
    dropping the cue — "no on-call" is evidence *against*, not absence of
    evidence (spec risk register; T16).
    """

    pattern: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    negatable: bool = False

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"cue pattern does not compile: {exc}") from exc
        return pattern


class GoldExample(Strict):
    """A real ad excerpt and the value this dimension should take on it.

    Anchored to the committed corpus by `ad_id`, with `span` required to appear
    **verbatim** in that ad's text. An invented excerpt would let every later
    extraction gate measure the model against fiction — the same failure the
    corpus README refuses for the ads themselves.

    `derived_from` is what keeps two incompatible kinds of gold from being
    averaged into one number (D-2); see `GoldProvenance`.
    """

    ad_id: str = Field(min_length=1)
    language: Language
    span: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    derived_from: GoldProvenance


class Extraction(Strict):
    """Cues per language, and gold examples drawn from the corpus.

    T2 does not require all three languages to be present — that is T3's
    `dimension_extractor_coverage` gate over the finished model. What the schema
    enforces is that any language key present is one of the corpus languages, so
    a typo'd `eng:` block cannot sit there matching nothing.
    """

    cues: dict[Language, list[Cue]] = Field(default_factory=dict)
    gold: list[GoldExample] = Field(default_factory=list)


class Dimension(Strict):
    """One dimension of the model — `dimensions/<id>.yaml`."""

    id: DimensionId
    kind: Literal["soft", "hard"]
    polarity: Literal["bipolar", "unipolar"]
    side: Side = "matched"
    compares_against: str = ""
    group: Group
    label: LocalisedText
    definition: str = Field(min_length=1)
    levels: list[Level] = Field(min_length=2, max_length=5)
    elicitation: Elicitation
    extraction: Extraction = Field(default_factory=Extraction)
    methods_ref: str = Field(pattern=METHODS_REF.pattern)

    @model_validator(mode="after")
    def _a_trait_cannot_be_read_from_an_ad(self) -> Dimension:
        """A `candidate_trait` carrying cues is a contradiction, not a warning.

        A cue on `ambition` asserts that an ad's wording evidences the
        *candidate's* ambition. It evidences the employer's prose. Permitted, it
        would let the extractor score a personality trait from marketing copy —
        which is the failure METHODS §2.6 warns about, applied to the person
        rather than the job.
        """
        if self.side == "candidate_trait" and (
            any(self.extraction.cues.values()) or self.extraction.gold
        ):
            raise ValueError(
                f"{self.id}: a candidate_trait must not carry ad cues or gold — "
                "a trait is elicited, never extracted from an ad"
            )
        return self

    @model_validator(mode="after")
    def _cue_values_fit_the_polarity(self) -> Dimension:
        """Polarity bounds the values cues may carry: unipolar 0..1, bipolar -1..1.

        A negative cue on a unipolar dimension is not a rounding problem — the
        ranker reads a unipolar score as a magnitude, so the sign would be lost
        rather than honoured.
        """
        if self.polarity != "unipolar":
            return self
        offenders = [
            f"{language}:{cue.pattern}={cue.value}"
            for language, cues in self.extraction.cues.items()
            for cue in cues
            if cue.value < 0
        ]
        offenders += [
            f"gold:{gold.ad_id}={gold.value}" for gold in self.extraction.gold if gold.value < 0
        ]
        if offenders:
            raise ValueError(
                f"unipolar dimension carries negative cue value(s): {', '.join(offenders)}"
            )
        return self

    @model_validator(mode="after")
    def _levels_are_ordered_distinct_and_fit_the_polarity(self) -> Dimension:
        """Rungs ascend, never repeat, and respect the polarity's floor.

        Two rungs at the same value are two names for one class, so a labeller
        picking between them records nothing distinguishable and macro-F1 counts
        them as one. Unordered rungs break the nearest-rung snap, which assumes
        it can compare against a sorted scale.
        """
        values = [level.value for level in self.levels]
        if values != sorted(values):
            raise ValueError(f"{self.id}: levels must ascend by value, got {values}")
        duplicates = sorted({v for v in values if values.count(v) > 1})
        if duplicates:
            raise ValueError(f"{self.id}: duplicate level value(s): {duplicates}")
        if self.polarity == "unipolar" and values[0] < 0:
            raise ValueError(
                f"{self.id}: unipolar dimension carries negative level value(s): "
                f"{[v for v in values if v < 0]}"
            )
        return self

    @model_validator(mode="after")
    def _gold_lands_on_a_level(self) -> Dimension:
        """Every gold value is a declared rung; cue values need only be in range.

        The asymmetry is the point. Gold is a *human* judgement about a real ad
        — the same kind of judgement the corpus labels record — so it has to be
        expressible in the vocabulary a human labels in, or the two cannot be
        compared. A cue is the extractor's continuous estimate, which is snapped
        to the nearest rung at scoring time (`snap`) and so is free to sit
        between them; all it must not do is point off the end of the scale,
        where snapping would silently clamp it into a rung it never meant.
        """
        rungs = {level.value for level in self.levels}
        low, high = self.levels[0].value, self.levels[-1].value
        stray_gold = sorted({g.value for g in self.extraction.gold if g.value not in rungs})
        if stray_gold:
            raise ValueError(
                f"{self.id}: gold value(s) {stray_gold} are not declared levels "
                f"({sorted(rungs)}) — a gold example must be expressible as a rung"
            )
        out_of_range = sorted(
            {
                cue.value
                for cues in self.extraction.cues.values()
                for cue in cues
                if not low <= cue.value <= high
            }
        )
        if out_of_range:
            raise ValueError(
                f"{self.id}: cue value(s) {out_of_range} fall outside the level scale "
                f"[{low}, {high}]"
            )
        return self

    def snap(self, value: float) -> Level:
        """The declared rung nearest `value` — the class an extracted score counts as.

        Ties go to the rung nearer zero: a score exactly between "not stated"
        and a signal is weaker evidence for the signal than for its absence, and
        an arbitrary tie-break would make macro-F1 depend on float noise.
        """
        return min(self.levels, key=lambda level: (abs(level.value - value), abs(level.value)))

    def level_for(self, value: float) -> Level | None:
        """The rung declared at exactly `value`, or `None` — no snapping.

        What the importer uses: a label arriving from the labelling page names a
        rung, and a value that is not one is a page out of step with the model,
        not a number to round into the nearest acceptable shape.
        """
        return next((level for level in self.levels if level.value == value), None)

    @property
    def anchor(self) -> str:
        """The `docs/METHODS.md` anchor this dimension's method is documented at."""
        return self.methods_ref.split("#", 1)[1]


def methods_anchors(path: Path = DEFAULT_METHODS_PATH) -> set[str]:
    """GitHub-style anchor slugs for every ATX heading in a Markdown file.

    GitHub's rule, which is what a `METHODS.md#…` link resolves against in the
    rendered doc: lowercase, drop everything that is not a word character,
    space or hyphen, then spaces to hyphens. `### 4.1 Dimension score — weighted
    mean` becomes `41-dimension-score--weighted-mean` (the em dash vanishes and
    leaves its two spaces behind as two hyphens, which is why this is computed
    rather than guessed).
    """
    anchors: set[str] = set()
    for line in _read(path, "methods register").splitlines():
        match = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if not match:
            continue
        slug = match.group(2).lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        anchors.add(slug.replace(" ", "-"))
    return anchors


def _read(path: Path, what: str) -> str:
    """Read a UTF-8 file, turning every failure into a `DimensionError`.

    An unreadable or mis-encoded file is a violation like any other, and
    `collect_violations` promises a count rather than a traceback — so the OS
    and decoding errors are converted here, at the one place that touches disk,
    instead of escaping past every caller that catches `DimensionError`.
    """
    if not path.exists():
        raise DimensionError(f"{what} not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DimensionError(f"{path.name}: not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise DimensionError(f"{path.name}: cannot be read: {exc}") from exc


def _dimension_files(directory: Path) -> list[Path]:
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise DimensionError(f"dimension directory cannot be read: {exc}") from exc
    return sorted(
        (p for p in entries if p.suffix in {".yaml", ".yml"}),
        key=lambda p: (p.stem, p.suffix),
    )


def _parse(path: Path) -> Dimension:
    """Read one file into a `Dimension`, or raise `DimensionError` naming it."""
    try:
        raw = yaml.safe_load(_read(path, "dimension"))
    except yaml.YAMLError as exc:
        raise DimensionError(f"{path.name}: not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise DimensionError(f"{path.name}: expected a mapping, got {type(raw).__name__}")
    try:
        dimension = Dimension.model_validate(raw)
    except ValidationError as exc:
        raise DimensionError(f"{path.name}: {_format(exc)}") from exc
    if dimension.id != path.stem:
        raise DimensionError(
            f"{path.name}: id {dimension.id!r} does not match its filename "
            f"(expected {dimension.id}{path.suffix})"
        )
    return dimension


def _format(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        detail = error["msg"]
        # `extra_forbidden` reports the offending key in `loc` only, so the key
        # has to survive into the message for the error to be actionable.
        parts.append(f"{location}: {detail}")
    return "; ".join(parts)


def load_dimensions(
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path | None = DEFAULT_METHODS_PATH,
) -> list[Dimension]:
    """Load every dimension in `directory`, sorted by id.

    Raises `DimensionError` on the first problem: a caller that wants a count of
    problems instead wants `collect_violations`.

    Anchor resolution is part of loading, not an opt-in extra — §5.1 requires
    every `methods_ref` to resolve, so a default that skipped the check would let
    the ordinary load path accept exactly the models the spec forbids. Pass
    `methods_path=None` only to load a model deliberately detached from a methods
    register (a fixture that ships no `METHODS.md`).
    """
    if not directory.is_dir():
        raise DimensionError(f"dimension directory not found: {directory}")

    dimensions: dict[str, Dimension] = {}
    for path in _dimension_files(directory):
        dimension = _parse(path)
        if dimension.id in dimensions:
            raise DimensionError(f"{path.name}: duplicate dimension id {dimension.id!r}")
        dimensions[dimension.id] = dimension

    if methods_path is not None:
        anchors = methods_anchors(methods_path)
        for dimension in dimensions.values():
            if dimension.anchor not in anchors:
                raise DimensionError(
                    f"{dimension.id}: methods_ref {dimension.methods_ref!r} resolves to no "
                    f"heading in {methods_path.name}"
                )

    return [dimensions[key] for key in sorted(dimensions)]


def collect_violations(
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> list[str]:
    """Every §5.1 violation in the model, as human-readable strings.

    Unlike `load_dimensions` this does not stop at the first problem and does
    not raise — `dimension_schema_violations` is a count, and a gate that dies
    on the first bad file measures nothing.
    """
    if not directory.is_dir():
        return [f"dimension directory not found: {directory}"]

    violations: list[str] = []
    by_id: dict[str, Path] = {}
    parsed: list[Dimension] = []

    try:
        files = _dimension_files(directory)
    except DimensionError as exc:
        return [str(exc)]

    for path in files:
        try:
            dimension = _parse(path)
        except DimensionError as exc:
            violations.append(str(exc))
            continue
        if dimension.id in by_id:
            violations.append(
                f"{path.name}: duplicate dimension id {dimension.id!r} "
                f"(already defined in {by_id[dimension.id].name})"
            )
            continue
        by_id[dimension.id] = path
        parsed.append(dimension)

    try:
        anchors = methods_anchors(methods_path)
    except DimensionError as exc:
        return [*violations, str(exc)]

    violations.extend(
        f"{by_id[dimension.id].name}: methods_ref {dimension.methods_ref!r} resolves to no "
        f"heading in {methods_path.name}"
        for dimension in parsed
        if dimension.anchor not in anchors
    )
    # Gold examples are part of the contract too: an excerpt that is not really
    # in the ad it cites is a violation of the model, not a corpus problem.
    violations.extend(verify_gold(parsed))
    return violations


def verify_gold(
    dimensions: list[Dimension],
    ads: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Check every gold example against the committed corpus.

    A gold span that is not verbatim in the ad it names is worse than no gold at
    all: it silently turns every downstream extraction measurement into a test
    against invented text. `ads=None` loads the committed corpus.
    """
    if ads is None:
        try:
            ads = load_ads()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return [f"corpus could not be read to verify gold examples: {exc}"]

    total_gold = sum(len(d.extraction.gold) for d in dimensions)
    if not ads:
        if not total_gold:
            return []
        return [f"corpus is empty — {total_gold} gold example(s) cannot be verified"]

    by_id = {str(ad["id"]): ad for ad in ads}
    violations: list[str] = []
    for dimension in dimensions:
        for gold in dimension.extraction.gold:
            ad = by_id.get(gold.ad_id)
            if ad is None:
                violations.append(f"{dimension.id}: gold ad {gold.ad_id!r} is not in the corpus")
                continue
            if ad["language"] != gold.language:
                violations.append(
                    f"{dimension.id}: gold {gold.ad_id} is declared {gold.language!r} but the ad "
                    f"is {ad['language']!r}"
                )
            if gold.span not in str(ad["text"]):
                violations.append(
                    f"{dimension.id}: gold span for {gold.ad_id} does not appear verbatim in the ad"
                )
    return violations


def unmatched_gold(dimensions: list[Dimension]) -> list[str]:
    """**Cue-derived** gold examples that none of their own dimension's cues match.

    A cue-derived gold example the extractor cannot reach is not a
    demonstration of anything: it counts towards
    `dimension_extractor_coverage` while proving the opposite of what that
    metric claims. This catches the two ways that happens — a cue tightened
    without revisiting its gold, and a gold span chosen from wording no cue
    describes.

    Human gold is exempt, and the exemption is the whole point (D-2). This rule
    demands that a gold span be reachable by the very cues it is meant to test,
    which is a fair thing to ask of an example *selected* by those cues and an
    incoherent thing to ask of a person's reading. A human label matters most
    exactly when the cues miss it — that is what generalisation means — and
    applying this check to it would reject the evidence with the highest value
    and re-create the circularity D-2 exists to break. Worse, `_main` treats a
    violation here as a hard failure, so before the split the first human label
    the cues did not anticipate would have turned the T3 gate red and read as a
    bad label rather than as an extractor gap.
    """
    return [
        f"{dimension.id}: cue-derived gold {gold.ad_id} is matched by no {gold.language} cue"
        for dimension in dimensions
        for gold in dimension.extraction.gold
        if gold.derived_from == "cue"
        and not any(
            re.search(cue.pattern, gold.span, re.IGNORECASE)
            for cue in dimension.extraction.cues.get(gold.language, [])
        )
    ]


def evaluation_gold(dimensions: list[Dimension]) -> dict[str, list[GoldExample]]:
    """Per dimension, the gold an extraction score may legitimately be computed over.

    This is the single function T15 (`lo-25b1`) calls, so "score only against
    human labels" is code rather than a rule someone has to remember. Reading
    `dimension.extraction.gold` directly is the mistake; there is no filter
    argument here because an optional one is a filter that gets left off.

    Empty lists are kept, not dropped: a dimension with no independent gold is
    a dimension that **cannot be scored**, and a caller that receives nothing
    for it must report it unmeasured rather than average over what is left.
    Today every list is empty — the entire committed gold set is cue-derived —
    and that is the honest state of the measurement, not a bug in this
    function.
    """
    return {
        dimension.id: [g for g in dimension.extraction.gold if g.derived_from == "human"]
        for dimension in dimensions
    }


def gold_provenance(dimensions: list[Dimension]) -> dict[str, Any]:
    """How much gold there is of each kind, and which dimensions cannot be scored.

    `dimensions_without_evaluation_gold` is fix step 3 of D-2: a dimension
    whose only gold is cue-derived must surface rather than pass silently, so
    the T17 `ontology_hit_rate` review has something to read.
    """
    per_dimension = evaluation_gold(dimensions)
    counts = {"cue": 0, "human": 0}
    for dimension in dimensions:
        for gold in dimension.extraction.gold:
            counts[gold.derived_from] += 1
    return {
        "gold_by_provenance": counts,
        "evaluation_gold_count": counts["human"],
        # D-2's gate, and the one number here that can actually go wrong. The
        # name is the plan's (`status/plan.md`, Divergences), and "the
        # evaluation split" now means what `evaluation_gold` returns: the plan
        # was written when T5 would have hand-labelled a held-out slice of the
        # corpus, and the owner retired that campaign on 2026-08-19. The
        # invariant is unchanged — no cue-derived example may reach whatever is
        # scored — so the metric keeps its declared name rather than the code
        # growing a second one for the same thing.
        #
        # The counts above are descriptive; this asserts the separation holds
        # by running the real `evaluation_gold` and counting anything in its
        # output that is not a human label. It goes non-zero the moment someone
        # relaxes that filter — which is the failure D-2 exists to prevent, and
        # is otherwise invisible until an `extraction_macro_f1` of ~1.0 is
        # reported and believed.
        "cue_derived_gold_in_evaluation_split": sum(
            1 for golds in per_dimension.values() for g in golds if g.derived_from != "human"
        ),
        # Ad-side only: a candidate-trait dimension is never read from an advert,
        # so it is not "missing" evaluation gold — see `extractor_coverage`.
        "dimensions_without_evaluation_gold": sorted(
            d.id for d in ad_side(dimensions) if not per_dimension[d.id]
        ),
    }


def silent_language_slices(
    dimensions: list[Dimension],
    ads: list[dict[str, Any]],
) -> list[str]:
    """`<dimension>:<language>` pairs whose cues match no ad in the corpus.

    Not a failure — Catalan ads in this corpus carry no wellbeing benefits and
    no company-stage language, and inventing cue hits would be worse than the
    gap. It is reported so the gap stays visible instead of being mistaken for
    coverage the model does not have.
    """
    return [
        f"{dimension.id}:{language}"
        for dimension in dimensions
        for language in SCHEMA_LANGUAGES
        if dimension.extraction.cues.get(language)
        and not any(
            re.search(cue.pattern, str(ad["text"]), re.IGNORECASE)
            for cue in dimension.extraction.cues[language]
            for ad in ads
            if ad["language"] == language
        )
    ]


def ad_side(dimensions: list[Dimension]) -> list[Dimension]:
    """The dimensions that something in an ad could evidence.

    `matched` dimensions and the ad-side requirements a `candidate_fact` is
    filtered against. Traits are excluded because no ad wording evidences them.
    """
    return [d for d in dimensions if d.side == "matched"]


def side_violations(dimensions: list[Dimension]) -> list[str]:
    """Dimensions whose declared side and actual content disagree.

    `side` must not become a way to opt out of writing cues, so each side is
    held to what it claims:

    * `matched` with no cues is the original defect `dimension_extractor_coverage`
      exists to catch, and stays a violation;
    * `candidate_fact` naming no `compares_against` — or naming one that does
      not resolve — is a value collected and never used, which is
      indistinguishable, from every metric's point of view, from a filter that
      matched everything;
    * `candidate_trait` carrying cues is refused at load, so it cannot reach here.
    """
    by_id = {d.id: d for d in dimensions}
    violations: list[str] = []
    for dimension in dimensions:
        if dimension.side == "matched" and not any(dimension.extraction.cues.values()):
            violations.append(f"{dimension.id}: a matched dimension with no cues")
        if dimension.side == "candidate_fact":
            if any(dimension.extraction.cues.values()) or dimension.extraction.gold:
                # A fact's ad-side evidence belongs to the requirement it is
                # compared against, not to the fact. Cues here would score the
                # same ad wording twice, once on each side of the comparison.
                owner = dimension.compares_against or "the requirement it compares against"
                violations.append(
                    f"{dimension.id}: a candidate_fact carries its own cues or gold — "
                    f"ad-side evidence belongs to {owner}"
                )
            if not dimension.compares_against:
                violations.append(
                    f"{dimension.id}: a candidate_fact names no compares_against, so nothing "
                    "filters on it"
                )
            elif dimension.compares_against not in by_id:
                violations.append(
                    f"{dimension.id}: compares_against {dimension.compares_against!r} "
                    "resolves to no dimension"
                )
            elif by_id[dimension.compares_against].side != "matched":
                # Comparing a fact against another candidate-side dimension
                # compares the candidate with themselves: no ad is consulted, so
                # the filter can never reject an offer.
                target = by_id[dimension.compares_against]
                violations.append(
                    f"{dimension.id}: compares_against {target.id!r} is {target.side}, not an "
                    "ad-side requirement"
                )
        if dimension.side != "candidate_fact" and dimension.compares_against:
            violations.append(
                f"{dimension.id}: compares_against is only meaningful on a candidate_fact, "
                f"not on a {dimension.side} dimension"
            )
        if dimension.compares_against == dimension.id:
            violations.append(f"{dimension.id}: compares_against points at itself")
    return violations


def extractor_coverage(dimensions: list[Dimension]) -> float:
    """`dimension_extractor_coverage` — the T3 gate metric.

    The fraction of **ad-side** dimensions carrying both ≥1 extractor rule and
    ≥1 gold example, per the spec's success criteria. Either half alone is
    uncheckable: cues with no gold cannot be shown to fire on real text, and
    gold with no cues has nothing to fire.

    Candidate-side dimensions are excluded rather than counted as uncovered.
    The metric asks "can this be extracted from an ad", and asking it of
    ambition scores the model down for holding the thing the interview exists to
    elicit — pressure on a future author to delete traits to keep a gate green.
    A model with no ad-side dimensions at all returns 0.0, not 1.0: nothing to
    report is not the same as full coverage.
    """
    extractable = ad_side(dimensions)
    if not extractable:
        return 0.0
    covered = sum(1 for d in extractable if any(d.extraction.cues.values()) and d.extraction.gold)
    return covered / len(extractable)


def write_coverage_evidence(
    evidence: Path = DEFAULT_COVERAGE_EVIDENCE_PATH,
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> dict[str, Any]:
    """Measure T3's gate from the committed model and record it."""
    dimensions = load_dimensions(directory, methods_path)
    uncovered = sorted(
        d.id for d in dimensions if not any(d.extraction.cues.values()) or not d.extraction.gold
    )
    try:
        ads = load_ads()
    except (OSError, ValueError, json.JSONDecodeError):
        ads = []
    measured: dict[str, Any] = {
        "dimension_extractor_coverage": round(extractor_coverage(dimensions), 4),
        "dimension_count": len(dimensions),
        "gold_example_count": sum(len(d.extraction.gold) for d in dimensions),
        "languages_with_cues": {
            language: sum(1 for d in dimensions if d.extraction.cues.get(language))
            for language in SCHEMA_LANGUAGES
        },
        "dimensions_without_cues_or_gold": uncovered,
        "gold_violations": verify_gold(dimensions, ads),
        "gold_unmatched_by_own_cues": unmatched_gold(dimensions),
        # D-2. Recorded beside coverage on purpose: `dimension_extractor_coverage`
        # counts a dimension as covered on the strength of gold that cannot
        # evidence generalisation, so the two numbers have to be read together
        # or the first one flatters the model.
        **gold_provenance(dimensions),
        # Reported, not failed: see `silent_language_slices`.
        "language_slices_with_no_corpus_hit": silent_language_slices(dimensions, ads),
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_side_evidence(
    evidence: Path = DEFAULT_SIDE_EVIDENCE_PATH,
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> dict[str, Any]:
    """Measure T23's gate: every dimension's side agrees with its content."""
    dimensions = load_dimensions(directory, methods_path)
    violations = side_violations(dimensions)
    extractable = ad_side(dimensions)
    measured: dict[str, Any] = {
        "side_coverage_violations": len(violations),
        "violations": violations,
        "dimension_count": len(dimensions),
        "by_side": {side: sum(1 for d in dimensions if d.side == side) for side in get_args(Side)},
        # Reported next to the coverage number so a model that is all traits and
        # no cues cannot show full coverage over an empty ad-side set.
        "ad_side_count": len(extractable),
        "dimension_extractor_coverage": round(extractor_coverage(dimensions), 4),
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> dict[str, Any]:
    """Measure T2's gate from the committed model and record it."""
    violations = collect_violations(directory, methods_path)
    try:
        dimension_count = len(_dimension_files(directory)) if directory.is_dir() else 0
    except DimensionError:
        # Already reported by `collect_violations`; the count is zero because
        # nothing could be listed, and the writer refuses a zero count anyway.
        dimension_count = 0
    measured: dict[str, Any] = {
        "dimension_schema_violations": len(violations),
        "dimension_count": dimension_count,
        "violations": violations,
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write this module's gate evidence.

        python -m integral.dimensions                     → T2, T3 and T23
        python -m integral.dimensions <path>              → T2, schema violations
        python -m integral.dimensions --coverage [path]   → T3, extractor coverage
        python -m integral.dimensions --sides [path]      → T23, side agreement

    The bare run writes **all three**, because that is the form `make evidence`
    uses: it derives its module list by grepping for `^def _main` and runs each
    one once, with no way to know a module owns more than one measurement. Under
    the old behaviour a bare run wrote T2 alone, so T3 and T23 sat in the tree
    unregenerated and undrift-checked — and the 23rd dimension landed with both
    of them still saying 22, which is exactly the stale-evidence failure that
    target exists to catch. Naming a path or a flag still writes just that one,
    so every gate block in the queue keeps its precise invocation.
    """
    coverage = "--coverage" in argv[1:]
    sides = "--sides" in argv[1:]
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]

    if not coverage and not sides and not positional:
        return max(
            _main([argv[0], str(DEFAULT_EVIDENCE_PATH)]),
            _main([argv[0], "--coverage"]),
            _main([argv[0], "--sides"]),
        )

    if sides:
        target = Path(positional[0]) if positional else DEFAULT_SIDE_EVIDENCE_PATH
        try:
            measured = write_side_evidence(target)
        except DimensionError as exc:
            print(f"cannot measure sides: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(measured, ensure_ascii=False))
        if measured["dimension_count"] == 0:
            print(f"no dimensions in {DEFAULT_DIMENSIONS_DIR} — nothing measured", file=sys.stderr)
            return 3
        for violation in measured["violations"]:
            print(violation, file=sys.stderr)
        return 1 if measured["violations"] else 0

    if coverage:
        target = Path(positional[0]) if positional else DEFAULT_COVERAGE_EVIDENCE_PATH
        try:
            measured = write_coverage_evidence(target)
        except DimensionError as exc:
            # Coverage is measured over a *loadable* model; a broken one is T2's
            # gate to report, and reporting a coverage number over it would be a
            # measurement of something that does not exist.
            print(f"cannot measure coverage: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(measured, ensure_ascii=False))
        if measured["dimension_count"] == 0:
            print(f"no dimensions in {DEFAULT_DIMENSIONS_DIR} — nothing measured", file=sys.stderr)
            return 3
        problems = [*measured["gold_violations"], *measured["gold_unmatched_by_own_cues"]]
        for violation in problems:
            print(violation, file=sys.stderr)
        return 1 if problems else 0

    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["dimension_count"] == 0:
        # An empty directory yields zero violations, which is a pass over
        # nothing. Refuse it: the gate has to fail when nothing was measured.
        print(f"no dimension files in {DEFAULT_DIMENSIONS_DIR} — nothing measured", file=sys.stderr)
        return 3
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    return 1 if measured["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
