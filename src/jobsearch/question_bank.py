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
(`jobsearch.dimensions.load_dimensions`) and turns each dimension's
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
`jobsearch.decline.DeclineLedger` — there is no candidate, no session and
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
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jobsearch.dimensions import (
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
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T7.json"


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this module's schema.

    Matches `jobsearch.dimensions.Strict`: a bank entry is as much a load-bearing
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
                    text=question.text,
                )
            )
            order += 1
    return QuestionBank(entries=tuple(entries), dimension_count=len(dimensions))


def unresolved_dimension_ids(bank: QuestionBank, dimensions: list[Dimension]) -> list[str]:
    """Bank entries whose `dimension_id` names no dimension actually loaded.

    This is the exact property `test_every_generated_question_maps_to_a_dimension`
    holds the generator to. A question that cannot be traced back to a real
    dimension is not a usable question, whatever its text says — nothing
    downstream would know what it was measuring.
    """
    known = {dimension.id for dimension in dimensions}
    return sorted({entry.dimension_id for entry in bank.entries if not entry.resolves(known)})


def dimension_coverage(
    bank: QuestionBank, dimensions: list[Dimension]
) -> tuple[float, list[str]]:
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
    same as full coverage, matching `jobsearch.dimensions.extractor_coverage`'s
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
    dimension_id: str, question_id: str, *, es_text: str = "Cuéntame algo."
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
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe the bank generator",
        elicitation=Elicitation(
            questions=[
                Question(
                    id=question_id,
                    text=LocalisedText(en="Tell me about it.", es=es_text, ca="Explica'm-ho."),
                )
            ]
        ),
        extraction=Extraction(),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


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
    of anything, the same stance `jobsearch.dimensions.write_coverage_evidence`
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
    """`python -m jobsearch.question_bank [--check] [--write-evidence [PATH]]` → T7's gate.

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

    violations: list[str] = []
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
