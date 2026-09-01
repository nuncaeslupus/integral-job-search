"""Question bank generation from the dimension model (T7).

`status/specification.md` §5.1 puts `elicitation.questions` inside every
dimension file, not beside it — the questions the interview asks are part of
the same spine that drives extraction and ranking, so a hand-maintained
question list would be a second copy of that spine, free to drift the moment
someone edits a dimension and forgets the sibling file. `docs/dimension-catalogue.md`
§2 states the reason this matters beyond tidiness: candidate traits — and, in
this model, every elicited quantity — are "elicited, never extracted"; there is
no ad text a cue could ever fire on to stand in for a missing question. If the
bank is not generated from the model, there is no fallback source for it.

This module is the projection: `build_bank` walks the loaded dimension model
(`integral.dimensions.load_dimensions`) and turns each dimension's
`elicitation.questions` into a flat, ordered, independently addressable
`QuestionBank` — the thing a future interview step (T27) can iterate without
knowing anything about YAML files or which dimension owns which question id.

**Why a question needs a bank-local id at all.** `Elicitation` only guarantees
a question id is unique *within* its own dimension
(`Elicitation._question_ids_are_unique`); nothing in the schema stops two
dimensions from reusing the same short id, and two already do in the committed
model — `company_stage.yaml` and `contract_stability.yaml` both carry `cs_q1`.
Citing "cs_q1" anywhere downstream (a session transcript, an interview
resumption pointer) would be ambiguous the day both dimensions are in play at
once. `BankEntry.bank_id` is `<dimension_id>:<question_id>`, which is unique by
construction whenever the model itself has unique dimension ids
(`load_dimensions` already refuses duplicates), and `QuestionBank` re-checks it
anyway rather than trusting that composition never breaks.

**The gate, `question_dimension_coverage == 1.0`, is about the generated
artefact, not the source model.** `Question.text` (a `LocalisedText`) already
requires non-empty `en`/`es`/`ca` fields at the schema level, so a dimension
that loads at all already carries a fully localised question — but that only
proves the *model* is complete. It says nothing about whether *this module's*
projection of it preserves that completeness: a bug that dropped a language
while flattening the bank, or silently skipped a dimension, would leave the
source model untouched and the generated bank wrong. `dimension_coverage`
therefore re-measures the bank's own text, not the model's, and does it with
`str.strip()` rather than a bare truthiness check — `Field(min_length=1)`
happily accepts `"   "`, and a question that is visually blank in one language
would otherwise count as covered while being useless to whoever has to read it
aloud in Catalan.

**What this module does not do.** It does not decide *when* a question is
asked, does not sequence an interview, and does not consult
`integral.decline.DeclineLedger` — there is no candidate, no session and
nothing to ask yet at this layer; the bank is a static, candidate-independent
artefact. Wiring "never ask a declined subject again" belongs to whichever
step actually puts questions in front of a candidate — T27, the onboarding
interview protocol, per `status/plan.md`'s T7 row (`T7, T8, T24` feed T27, not
the reverse). Reaching into `DeclineLedger` from here would mean inventing a
`step`/`at` context this module has no way to know, against an interview loop
that does not exist yet — exactly the half-wiring the payload asks not to do.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from integral.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    DEFAULT_METHODS_PATH,
    SCHEMA_LANGUAGES,
    Dimension,
    DimensionError,
    DimensionId,
    Elicitation,
    Extraction,
    LocalisedText,
    Question,
    load_dimensions,
    synthetic_levels,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T7.json"


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this module's schema.

    Matches `integral.dimensions.Strict`: a bank entry is as much a load-bearing
    contract for T27 as a dimension file is for the extractor, and an ignored
    key should not be able to look like a setting that took effect.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class BankEntry(Strict):
    """One elicitation question, addressable independently of its source file.

    `dimension_id` is what makes a question traceable back to the model —
    `test_every_generated_question_maps_to_a_dimension` holds every entry to
    resolving against a real, loaded dimension. `order` is the entry's position
    in the whole bank (`build_bank`'s deterministic walk), not merely within its
    own dimension, so a consumer can present or resume the bank without
    re-deriving an ordering of its own.
    """

    bank_id: str = Field(min_length=3)
    dimension_id: DimensionId
    question_id: DimensionId
    order: int = Field(ge=0)
    #: Carried through from `Question.form`, so a consumer walking the bank can
    #: see how an item is put without reloading the dimension model — and so
    #: `measure_monotone` can check the bank itself rather than only the files
    #: it was built from.
    form: Literal["narrative", "level_rating", "trade_off"] = "narrative"
    text: LocalisedText

    def resolves(self, dimension_ids: set[str]) -> bool:
        """Whether this entry's `dimension_id` names a dimension actually loaded."""
        return self.dimension_id in dimension_ids


class QuestionBank(Strict):
    """The whole generated bank, in the order an interview should walk it."""

    entries: tuple[BankEntry, ...]
    dimension_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _bank_ids_are_unique(self) -> QuestionBank:
        """Belt-and-braces: `build_bank`'s composition should already guarantee
        this, but a bank assembled some other way (a probe, a future caller)
        gets the same check `Elicitation` gives a single dimension's questions.
        """
        seen = [entry.bank_id for entry in self.entries]
        duplicates = sorted({bank_id for bank_id in seen if seen.count(bank_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate bank id(s): {', '.join(duplicates)}")
        return self

    def by_dimension(self, dimension_id: str) -> tuple[BankEntry, ...]:
        """Every entry for one dimension, in bank order."""
        return tuple(entry for entry in self.entries if entry.dimension_id == dimension_id)


def build_bank(dimensions: list[Dimension]) -> QuestionBank:
    """Project the dimension model's elicitation blocks into a flat, ordered bank.

    Order is deterministic and reproducible — the load-bearing property is not
    "some order" but "the same order every time the same model is walked",
    matching the determinism this repo already holds `profile_rebuild` to
    (T6): dimensions in the order `load_dimensions` already sorts them (by
    id), each dimension's own questions in the order they are written in its
    file. Nothing here reorders by language, length or any other property that
    could change between runs.
    """
    entries: list[BankEntry] = []
    order = 0
    for dimension in dimensions:
        for question in dimension.elicitation.questions:
            entries.append(
                BankEntry(
                    bank_id=f"{dimension.id}:{question.id}",
                    dimension_id=dimension.id,
                    question_id=question.id,
                    order=order,
                    form=question.form,
                    text=question.text,
                )
            )
            order += 1
    return QuestionBank(entries=tuple(entries), dimension_count=len(dimensions))


#: T96. Quantities where, everything else equal, more is never worse, and
#: which are **not** `dimensions/*.yaml` files. Pay is the case the candidate
#: reported — *"7 is weird. Given the same job, always better more money."* —
#: and it has no dimension file because it is not a soft dimension at all: it
#: is a currency amount, carried by `weights.Package.salary_per_month`.
#:
#: Without this register the rule would be true of nothing that was actually
#: asked. A dimension file joins the set by declaring `monotone: true`.
MONOTONE_ELICITABLES: frozenset[str] = frozenset({"salary"})

#: Where each of those is elicited instead. Not decoration: forbidding the
#: level rating without naming the replacement is how a dimension stops being
#: elicited at all, and `trade_off_route` is what a test can hold to it.
_TRADE_OFF_ROUTES: dict[str, str] = {
    "salary": (
        "integral.weights — forced pairwise choice between two whole packages, "
        "each priced, fitted to part-worths in salary-equivalent terms"
    ),
}


def trade_off_route(elicitable: str) -> str | None:
    """How this monotone quantity *is* asked, or `None` if nothing asks it."""
    return _TRADE_OFF_ROUTES.get(elicitable)


def monotone_ids(
    dimensions: list[Dimension], elicitables: frozenset[str] = MONOTONE_ELICITABLES
) -> frozenset[str]:
    """Everything monotone: the register, plus every dimension declaring it."""
    return elicitables | {d.id for d in dimensions if d.monotone}


class Answer(Strict):
    """One recorded response to a bank item."""

    bank_id: str = Field(min_length=3)
    value: float


def answers_for_the_fit(
    answers: Sequence[Answer],
    bank: QuestionBank,
    dimensions: list[Dimension] | None = None,
    elicitables: frozenset[str] = MONOTONE_ELICITABLES,
) -> tuple[Answer, ...]:
    """The answers a fit may read. Two kinds are dropped, for one reason.

    An answer to a `bank_id` the bank no longer carries is answering a retired
    item, and retirement is what happens to a malformed one — keeping it would
    let the question go on shaping weights after it was withdrawn. And an
    answer to a level rating on a monotone quantity is noise however recently
    it was given, because the question had no coherent answer at the moment it
    was asked.

    The second check is belt to the first's braces: `Dimension` already
    refuses to define such an item. This is what holds if one ever reaches a
    bank by another route, the same way `QuestionBank` re-checks duplicate ids
    that `build_bank` should already have prevented.

    **Both sources of "monotone" are consulted, via `monotone_ids`.** There are
    two — the `MONOTONE_ELICITABLES` register and a dimension file's own
    `monotone: true` — and a filter that reads only the constant is checking a
    hardcoded list against data that declares the same property for itself.
    Pass `dimensions` (the model the bank was built from) and a dimension
    declaring itself monotone is covered too; omit it and only the register is,
    which is the fail-open reading of a safety filter.
    """
    monotone = monotone_ids(dimensions or [], elicitables)
    live = {
        entry.bank_id: entry
        for entry in bank.entries
        if not (entry.form == "level_rating" and entry.dimension_id in monotone)
    }
    return tuple(answer for answer in answers if answer.bank_id in live)


def level_rating_items(
    bank: QuestionBank,
    dimensions: list[Dimension],
    elicitables: frozenset[str] = MONOTONE_ELICITABLES,
) -> list[str]:
    """Bank items asking a monotone quantity for a level rating."""
    monotone = monotone_ids(dimensions, elicitables)
    return [
        entry.bank_id
        for entry in bank.entries
        if entry.form == "level_rating" and entry.dimension_id in monotone
    ]


def measure_monotone(
    dimensions: list[Dimension],
    *,
    bank: QuestionBank | None = None,
    elicitables: frozenset[str] = MONOTONE_ELICITABLES,
) -> dict[str, Any]:
    """T96's gate: `monotone_dimensions_asked_as_level_ratings`.

    The denominator is every bank item put through the check plus every
    monotone quantity considered, because a rule true of nothing is true. A
    monotone quantity with no trade-off route counts as a violation too — the
    rule deletes a question, and deleting it without a replacement leaves the
    dimension unasked, which is a quieter version of the same fault.

    `probe_answer_filter` adds its own checks to both sides of that count. The
    committed model carries no malformed item — that is the point of it — so
    measuring only the model would leave `answers_for_the_fit` itself
    unmeasured, which is how it went a whole review round consulting one of
    the two sources of "monotone". The probe runs only when there was
    something else to measure, so an empty model still reports `unmeasured`
    rather than passing on its synthetic cases alone.
    """
    bank = build_bank(dimensions) if bank is None else bank
    offending = level_rating_items(bank, dimensions, elicitables)
    monotone = monotone_ids(dimensions, elicitables)
    unrouted = [
        elicitable
        for elicitable in sorted(elicitables)
        if trade_off_route(elicitable) is None
    ]
    considered = len(bank.entries) + len(monotone)
    probe: dict[str, Any] = (
        probe_answer_filter() if considered else {"checks_run": 0, "failures": []}
    )
    checked = considered + probe["checks_run"]
    return {
        "monotone_dimensions_asked_as_level_ratings": (
            len(offending) + len(unrouted) + len(probe["failures"])
        ),
        # Both names, as every gate in this increment carries.
        "monotone_dimensions_asked_as_level_ratings_evaluated": checked,
        "items_checked": checked,
        "monotone_elicitables_checked": len(monotone),
        "gate_status": "measured" if considered else "unmeasured",
        "monotone": sorted(monotone),
        "offending_items": offending,
        "elicitables_with_no_trade_off_route": unrouted,
        "answer_filter_checks_run": probe["checks_run"],
        "answer_filter_failures": probe["failures"],
    }


DEFAULT_MONOTONE_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T96.json"


def write_monotone_evidence(
    evidence: Path = DEFAULT_MONOTONE_EVIDENCE_PATH,
    dimensions: list[Dimension] | None = None,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T96.json`."""
    measured = measure_monotone(load_dimensions() if dimensions is None else dimensions)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def unresolved_dimension_ids(bank: QuestionBank, dimensions: list[Dimension]) -> list[str]:
    """Bank entries whose `dimension_id` names no dimension actually loaded.

    This is the exact property `test_every_generated_question_maps_to_a_dimension`
    holds the generator to. A question that cannot be traced back to a real
    dimension is not a usable question, whatever its text says — nothing
    downstream would know what it was measuring.
    """
    known = {dimension.id for dimension in dimensions}
    return sorted({entry.dimension_id for entry in bank.entries if not entry.resolves(known)})


def dimension_coverage(bank: QuestionBank, dimensions: list[Dimension]) -> tuple[float, list[str]]:
    """`question_dimension_coverage` — the T7 gate metric.

    The divisor is `len(dimensions)`, read from whatever model was actually
    loaded, never a stored constant — the lesson `extractor_coverage` (T3)
    already carries: a checker holding its own copy of "how many dimensions
    there are" is correct the day it is written and silently wrong on the next
    dimension added.

    A dimension counts as covered only when the bank holds at least one
    question for it whose text is non-empty, after stripping whitespace, in
    *every* corpus language (`SCHEMA_LANGUAGES`) — not "some question exists
    for it somewhere", and not "the field is technically non-empty". See the
    module docstring for why the stripped check matters even though
    `LocalisedText` already requires all three languages at the schema level.

    An empty `dimensions` list reports `(0.0, [])`: nothing to cover is not the
    same as full coverage, matching `integral.dimensions.extractor_coverage`'s
    same refusal.
    """
    if not dimensions:
        return 0.0, []
    by_dimension: dict[str, list[BankEntry]] = defaultdict(list)
    for entry in bank.entries:
        by_dimension[entry.dimension_id].append(entry)
    uncovered = [
        dimension.id
        for dimension in dimensions
        if not any(
            all(entry.text.get(language).strip() for language in SCHEMA_LANGUAGES)
            for entry in by_dimension.get(dimension.id, ())
        )
    ]
    covered = len(dimensions) - len(uncovered)
    return covered / len(dimensions), sorted(uncovered)


def _synthetic_dimension(
    dimension_id: str,
    question_id: str,
    *,
    es_text: str = "Cuéntame algo.",
    form: Literal["narrative", "level_rating", "trade_off"] = "narrative",
    monotone: bool = False,
) -> Dimension:
    """One minimal, valid `Dimension` built in memory — no YAML, no disk.

    Used only by `probe_bank_generation` to construct adversarial scenarios
    that the committed model does not (and should not) contain organically,
    such as a whitespace-only translation. `methods_ref` points at a heading
    that really exists in `docs/METHODS.md`, but nothing here resolves it
    against that file — these dimensions never go through `load_dimensions`.
    """
    return Dimension(
        id=dimension_id,
        kind="soft",
        polarity="bipolar",
        group="the_work",
        monotone=monotone,
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe the bank generator",
        levels=synthetic_levels(),
        elicitation=Elicitation(
            questions=[
                Question(
                    id=question_id,
                    form=form,
                    text=LocalisedText(en="Tell me about it.", es=es_text, ca="Explica'm-ho."),
                )
            ]
        ),
        extraction=Extraction(),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


def probe_answer_filter() -> dict[str, Any]:
    """Hold `answers_for_the_fit` to a bank the model validator never saw.

    The validator refuses a monotone dimension carrying a level rating, so no
    bank `build_bank` produces can exercise the filter at all — the only way to
    measure it is to forge the bank the filter exists for. Both directions are
    checked, because a filter is wrong in two ways and only one of them is
    loud:

    * **fail-open** — an answer to a level rating on a dimension that declares
      `monotone: true` reaches the fit. It is noise, and `weights.py` turns it
      into a part-worth. This is the one the filter existed to stop and did
      not, for anything outside `MONOTONE_ELICITABLES`;
    * **fail-closed** — an answer to an ordinary level rating is dropped. The
      question was fine and the candidate's answer is thrown away silently.
    """
    declared = _synthetic_dimension("dim_monotone", "q1", form="trade_off", monotone=True)
    ordinary = _synthetic_dimension("dim_rated", "q1", form="level_rating")
    text = LocalisedText(en="Rate it 1-7", es="Puntúa 1-7", ca="Puntua-ho de l'1 al 7")
    forged = QuestionBank(
        entries=(
            BankEntry(
                bank_id="dim_monotone:q1",
                dimension_id="dim_monotone",
                question_id="q1",
                order=0,
                form="level_rating",
                text=text,
            ),
            BankEntry(
                bank_id="dim_rated:q1",
                dimension_id="dim_rated",
                question_id="q1",
                order=1,
                form="level_rating",
                text=text,
            ),
        ),
        dimension_count=2,
    )
    answers = [
        Answer(bank_id="dim_monotone:q1", value=7.0),
        Answer(bank_id="dim_rated:q1", value=4.0),
    ]
    kept = {a.bank_id for a in answers_for_the_fit(answers, forged, [declared, ordinary])}

    failures: list[str] = []
    if "dim_monotone:q1" in kept:
        failures.append(
            "fail-open: an answer to a level rating on a dimension declaring "
            "monotone: true reached the fit — the declaration was not read"
        )
    if "dim_rated:q1" not in kept:
        failures.append(
            "fail-closed: an answer to an ordinary level rating was dropped — "
            "the filter is refusing questions that had a coherent answer"
        )
    return {"checks_run": 2, "failures": failures}


MINIMUM_PROBES = 4


def probe_bank_generation() -> dict[str, Any]:
    """Try to break the generator with edge cases the real model does not carry.

    Every scenario here is one the committed 22-dimension model happens not to
    exercise today, which is exactly why a probe over the real model would not
    catch a regression in any of them:

    1. two dimensions reusing the same raw question id (real today: `cs_q1`
       in both `company_stage.yaml` and `contract_stability.yaml`) must not
       collide in the bank;
    2. a whitespace-only translation must not count as coverage;
    3. a dimension the generator silently drops must be reported uncovered,
       not averaged away into a passing score;
    4. a bank entry naming a dimension outside the loaded model must be
       caught by `unresolved_dimension_ids`, not trusted.
    """
    failures: list[str] = []
    checks = 0

    # 1. Reused per-dimension question ids must not collide once composed.
    colliding = [_synthetic_dimension("dim_alpha", "q1"), _synthetic_dimension("dim_beta", "q1")]
    bank = build_bank(colliding)
    checks += 1
    if len({entry.bank_id for entry in bank.entries}) != 2:
        failures.append("reused per-dimension question ids collided into one bank id")
    checks += 1
    if unresolved_dimension_ids(bank, colliding):
        failures.append("questions built from a real dimension list were reported unresolved")

    # 2. A whitespace-only translation is not coverage.
    blank_es = [_synthetic_dimension("dim_gamma", "q1", es_text="   ")]
    bank_blank = build_bank(blank_es)
    coverage_blank, uncovered_blank = dimension_coverage(bank_blank, blank_es)
    checks += 1
    if coverage_blank != 0.0 or uncovered_blank != ["dim_gamma"]:
        failures.append("a whitespace-only Spanish question counted as full-language coverage")

    # 3. A dimension missing from the generated bank must show up as uncovered.
    present = _synthetic_dimension("dim_present", "q1")
    dropped = _synthetic_dimension("dim_dropped", "q1")
    bank_partial = build_bank([present])  # `dropped` never reaches the generator
    coverage_partial, uncovered_partial = dimension_coverage(bank_partial, [present, dropped])
    checks += 1
    if coverage_partial != 0.5 or uncovered_partial != ["dim_dropped"]:
        failures.append("a dimension absent from the bank was not reported uncovered")

    # 4. A question naming a dimension outside the model is flagged, not trusted.
    ghost_entry = BankEntry(
        bank_id="dim_present:ghost",
        dimension_id="dim_ghost",
        question_id="ghost",
        order=0,
        text=LocalisedText(en="x", es="x", ca="x"),
    )
    ghost_bank = QuestionBank(entries=(ghost_entry,), dimension_count=1)
    checks += 1
    if unresolved_dimension_ids(ghost_bank, [present]) != ["dim_ghost"]:
        failures.append("a question naming no real dimension was not flagged as unresolved")

    return {"checks_run": checks, "failures": failures}


def measure(
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> dict[str, Any]:
    """Build the bank from the committed model and report T7's gate plus detail.

    Raises `DimensionError` (propagated from `load_dimensions`) if the model
    itself does not load — coverage over a broken model is not a measurement
    of anything, the same stance `integral.dimensions.write_coverage_evidence`
    takes for T3.
    """
    dimensions = load_dimensions(directory, methods_path)
    bank = build_bank(dimensions)
    coverage, uncovered = dimension_coverage(bank, dimensions)
    unresolved = unresolved_dimension_ids(bank, dimensions)
    probe = probe_bank_generation()
    return {
        "question_dimension_coverage": round(coverage, 4),
        "dimension_count": len(dimensions),
        "question_count": len(bank.entries),
        "languages_required": list(SCHEMA_LANGUAGES),
        "dimensions_missing_full_language_coverage": uncovered,
        "questions_with_unresolved_dimension": unresolved,
        "adversarial_checks_run": probe["checks_run"],
        "adversarial_failures": probe["failures"],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    directory: Path = DEFAULT_DIMENSIONS_DIR,
    methods_path: Path = DEFAULT_METHODS_PATH,
) -> dict[str, Any]:
    """Measure T7's gate from the committed model and record it."""
    measured = measure(directory, methods_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.question_bank [--check] [--write-evidence [PATH]]` → T7's gate.

    `--check` measures and reports without writing a file — the read-only path
    a test or a reviewer runs. Without it (the default, matching every other
    gate module: `dimensions`, `step_skills`, ...), the evidence file is
    written; `--write-evidence [PATH]` makes the target explicit or overrides
    it, defaulting to `status/evidence/T7.json`.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T7.json)",
    )
    parser.add_argument(
        "--dimensions-dir",
        default=str(DEFAULT_DIMENSIONS_DIR),
        metavar="DIR",
        help="dimension model directory to measure (default: dimensions/)",
    )
    args = parser.parse_args(argv[1:])
    directory = Path(args.dimensions_dir)

    try:
        if args.check:
            measured = measure(directory)
        else:
            measured = write_evidence(Path(args.write_evidence), directory)
    except DimensionError as exc:
        print(f"cannot measure question bank coverage: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(measured, ensure_ascii=False))

    if measured["dimension_count"] == 0:
        print(f"no dimensions in {directory} — nothing measured", file=sys.stderr)
        return 3
    if measured["adversarial_checks_run"] < MINIMUM_PROBES:
        print(
            f"only {measured['adversarial_checks_run']} adversarial checks ran "
            f"(floor {MINIMUM_PROBES}) — a clean score without exercising the edge "
            "cases is not a measurement",
            file=sys.stderr,
        )
        return 3

    # T96's record, beside T7's — one walk of the model, two questions of it:
    # whether every dimension has a question, and whether any of those
    # questions has a coherent answer. Written wherever T7's was asked for, so
    # a caller redirecting one to a scratch directory is not asking to have
    # the other written into the repository.
    monotone = (
        measure_monotone(load_dimensions(directory))
        if args.check
        else write_monotone_evidence(
            Path(args.write_evidence).parent / "T96.json", load_dimensions(directory)
        )
    )

    violations: list[str] = []
    violations.extend(
        f"monotone and asked as a level rating: {bank_id} — one end of the scale is "
        "incoherent, so the answer is noise. Ask what it is worth in terms of "
        "something else"
        for bank_id in monotone["offending_items"]
    )
    violations.extend(
        f"{elicitable} is monotone and nothing elicits it as a trade-off — the level "
        "rating is refused and no replacement is declared"
        for elicitable in monotone["elicitables_with_no_trade_off_route"]
    )
    violations.extend(monotone["answer_filter_failures"])
    if measured["question_dimension_coverage"] != 1.0:
        violations.append(
            f"question_dimension_coverage = {measured['question_dimension_coverage']} (want 1.0)"
        )
    violations.extend(
        f"question maps to no loaded dimension: {dimension_id}"
        for dimension_id in measured["questions_with_unresolved_dimension"]
    )
    violations.extend(
        f"dimension missing full-language question coverage: {dimension_id}"
        for dimension_id in measured["dimensions_missing_full_language_coverage"]
    )
    violations.extend(measured["adversarial_failures"])

    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
