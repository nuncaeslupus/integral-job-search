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

from jobsearch.corpus import LANGUAGES, load_ads

# src-layout repo root, as in `jobsearch.corpus`: valid for the editable install
# this project is always used through.
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIMENSIONS_DIR = _REPO_ROOT / "dimensions"
DEFAULT_METHODS_PATH = _REPO_ROOT / "docs" / "METHODS.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T2.json"
DEFAULT_COVERAGE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T3.json"

# `LANGUAGES` is imported, not restated: a dimension carries all of them on every
# human-readable string (a label in one language only produces a question no
# Catalan-speaking candidate can answer), and a second copy of the tuple drifts
# from the corpus it is supposed to mirror. The `Literal` below is the one place
# the languages are spelled out again — Pydantic needs them statically — and
# `test_schema_languages_match_the_corpus_languages` holds the two in step.
Language = Literal["en", "es", "ca"]
# The same three, as a tuple a type checker accepts as cue-dict keys.
SCHEMA_LANGUAGES: tuple[Language, ...] = get_args(Language)

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
    """

    ad_id: str = Field(min_length=1)
    language: Language
    span: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)


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
    label: LocalisedText
    definition: str = Field(min_length=1)
    elicitation: Elicitation
    extraction: Extraction = Field(default_factory=Extraction)
    methods_ref: str = Field(pattern=METHODS_REF.pattern)

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
    """Gold examples that none of their own dimension's cues match.

    A gold example the extractor cannot reach is not a demonstration of
    anything: it counts towards `dimension_extractor_coverage` while proving
    the opposite of what that metric claims. This catches the two ways that
    happens — a cue tightened without revisiting its gold, and a gold span
    chosen from wording no cue describes.
    """
    return [
        f"{dimension.id}: gold {gold.ad_id} is matched by no {gold.language} cue"
        for dimension in dimensions
        for gold in dimension.extraction.gold
        if not any(
            re.search(cue.pattern, gold.span, re.IGNORECASE)
            for cue in dimension.extraction.cues.get(gold.language, [])
        )
    ]


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


def extractor_coverage(dimensions: list[Dimension]) -> float:
    """`dimension_extractor_coverage` — the T3 gate metric.

    The fraction of dimensions carrying **both** ≥1 extractor rule and ≥1 gold
    example, per the spec's success criteria. Either half alone is uncheckable:
    cues with no gold cannot be shown to fire on real text, and gold with no
    cues has nothing to fire.
    """
    if not dimensions:
        return 0.0
    covered = sum(
        1
        for d in dimensions
        if any(d.extraction.cues.values()) and d.extraction.gold
    )
    return covered / len(dimensions)


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
        # Reported, not failed: see `silent_language_slices`.
        "language_slices_with_no_corpus_hit": silent_language_slices(dimensions, ads),
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
    """Write one of the two gate evidence files.

        python -m jobsearch.dimensions [path]              → T2, schema violations
        python -m jobsearch.dimensions --coverage [path]    → T3, extractor coverage
    """
    coverage = "--coverage" in argv[1:]
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]

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
