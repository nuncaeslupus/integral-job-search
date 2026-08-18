"""T7 — the question bank, generated from the dimension model.

`status/plan.md`'s T7 row names one test: every generated question maps to a
dimension. That is the RED test below. The rest hold the two properties the
payload calls out as the ones worth getting wrong: coverage measured *per
language*, not merely "some question exists somewhere" (a whitespace-only
translation must not pass), and a divisor read from the loaded model, never a
number this file writes down and lets go stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from jobsearch.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    SCHEMA_LANGUAGES,
    Dimension,
    load_dimensions,
)
from jobsearch.question_bank import (
    MINIMUM_PROBES,
    BankEntry,
    QuestionBank,
    _synthetic_dimension,
    build_bank,
    dimension_coverage,
    measure,
    probe_bank_generation,
    unresolved_dimension_ids,
    write_evidence,
)


@pytest.fixture(scope="module")
def dimensions() -> list[Dimension]:
    return load_dimensions(DEFAULT_DIMENSIONS_DIR)


@pytest.fixture(scope="module")
def bank(dimensions: list[Dimension]) -> QuestionBank:
    return build_bank(dimensions)


# --- the RED test named in the payload -------------------------------------


def test_every_generated_question_maps_to_a_dimension(
    bank: QuestionBank, dimensions: list[Dimension]
) -> None:
    """Each generated question carries >=1 resolvable dimension ID.

    A question a downstream consumer cannot trace back to a real dimension is
    not askable in any meaningful sense — nothing tells the interview what it
    is measuring, or where to file the answer. Guards `build_bank` composing a
    `dimension_id` that does not survive as a key into the model it came from.
    """
    known_ids = {dimension.id for dimension in dimensions}
    assert bank.entries, "the bank generated no questions at all"
    for entry in bank.entries:
        assert entry.resolves(known_ids), f"{entry.bank_id} names no loaded dimension"
    assert unresolved_dimension_ids(bank, dimensions) == []


# --- coverage is per-language, not "a question exists somewhere" -----------


def test_full_coverage_over_the_committed_model(
    bank: QuestionBank, dimensions: list[Dimension]
) -> None:
    """The real, committed model reaches `question_dimension_coverage == 1.0`.

    This is T7's actual gate, exercised directly rather than only through the
    evidence file — a green gate file that this assertion disagrees with would
    mean the two have drifted apart.
    """
    coverage, uncovered = dimension_coverage(bank, dimensions)
    assert uncovered == []
    assert coverage == 1.0


def test_divisor_is_the_loaded_dimension_count_not_a_constant(
    bank: QuestionBank, dimensions: list[Dimension]
) -> None:
    """A checker with its own copy of "how many dimensions" silently rots.

    Removing one dimension from the list handed to `dimension_coverage` must
    change the divisor it computes against — proving there is no hardcoded
    count standing in for `len(dimensions)`.
    """
    coverage_full, _ = dimension_coverage(bank, dimensions)
    coverage_fewer, _ = dimension_coverage(bank, dimensions[:-1])
    assert coverage_full == 1.0
    assert coverage_fewer == 1.0  # still full coverage, but the divisor moved
    assert dimension_coverage(bank, [])[0] == 0.0  # nothing to cover != covered


def test_whitespace_only_translation_does_not_count_as_coverage() -> None:
    """A field that is technically non-empty can still be visually blank.

    `LocalisedText` only enforces `min_length=1`, which a single space
    satisfies. A candidate reading that question in Spanish would see nothing
    to answer — the coverage metric has to catch this itself rather than
    trust the schema to have already ruled it out.
    """
    blank = _synthetic_dimension("dim_blank", "q1", es_text="   ")
    coverage, uncovered = dimension_coverage(build_bank([blank]), [blank])
    assert coverage == 0.0
    assert uncovered == ["dim_blank"]


def test_coverage_checks_every_corpus_language_not_just_english() -> None:
    """Coverage over one language while silent on the rest is not coverage.

    The corpus is 60% Spanish and 15% Catalan (`test_dimension_content.py`);
    a bank that only reached English would be unusable for most candidates.
    This asserts the coverage check actually walks `SCHEMA_LANGUAGES`, not a
    single hardcoded language.
    """
    assert set(SCHEMA_LANGUAGES) == {"en", "es", "ca"}
    ok = _synthetic_dimension("dim_ok", "q1", es_text="Cuéntame algo.")
    blank = _synthetic_dimension("dim_blank", "q1", es_text=" ")
    coverage, uncovered = dimension_coverage(build_bank([ok, blank]), [ok, blank])
    assert coverage == 0.5
    assert uncovered == ["dim_blank"]


def test_dimension_missing_from_the_bank_is_reported_not_averaged_away() -> None:
    """A dimension the generator silently drops must show up by name.

    A bare fraction (`0.5`) tells nobody *which* dimension is missing a
    question; `dimension_coverage` also returns the uncovered ids so a gate
    failure is actionable rather than a number to stare at.
    """
    present = _synthetic_dimension("dim_present", "q1")
    dropped = _synthetic_dimension("dim_dropped", "q1")
    coverage, uncovered = dimension_coverage(build_bank([present]), [present, dropped])
    assert coverage == 0.5
    assert uncovered == ["dim_dropped"]


# --- bank ids stay unique even when raw per-dimension ids collide ----------


def test_reused_per_dimension_question_ids_do_not_collide_in_the_bank() -> None:
    """Two dimensions may reuse the same short question id.

    `Elicitation` only enforces id uniqueness *within* one dimension — and the
    committed model already has a collision across files (`cs_q1` in both
    `company_stage.yaml` and `contract_stability.yaml`). `bank_id` composes the
    dimension id in, so the two never merge into one entry.
    """
    alpha = _synthetic_dimension("dim_alpha", "q1")
    beta = _synthetic_dimension("dim_beta", "q1")
    bank = build_bank([alpha, beta])
    assert len(bank.entries) == 2
    assert len({entry.bank_id for entry in bank.entries}) == 2


def test_committed_model_has_a_real_id_collision_the_bank_must_survive(
    dimensions: list[Dimension],
) -> None:
    """Not hypothetical: `company_stage` and `contract_stability` both use `cs_q1`.

    If this collision is ever fixed by renaming one side, this test simply
    stops finding it — it does not need to keep passing on old wording, only
    to prove the bank survives the real, current shape of the model.
    """
    ids_by_dimension = {
        dimension.id: [question.id for question in dimension.elicitation.questions]
        for dimension in dimensions
    }
    all_question_ids = [qid for ids in ids_by_dimension.values() for qid in ids]
    assert len(all_question_ids) != len(set(all_question_ids)), (
        "expected the model to still carry a cross-dimension question id "
        "collision — if it no longer does, this assertion (not the bank) is stale"
    )


def test_bank_rejects_a_hand_assembled_duplicate_bank_id() -> None:
    """`QuestionBank` re-checks bank-id uniqueness rather than trusting composition."""
    text = _synthetic_dimension("dim_x", "q1").elicitation.questions[0].text
    duplicate = BankEntry(
        bank_id="dim_x:q1", dimension_id="dim_x", question_id="q1", order=0, text=text
    )
    with pytest.raises(ValidationError):
        QuestionBank(entries=(duplicate, duplicate), dimension_count=1)


# --- a question naming no real dimension is caught, not trusted ------------


def test_unresolved_dimension_id_is_flagged() -> None:
    ghost = BankEntry(
        bank_id="dim_present:ghost",
        dimension_id="dim_ghost",
        question_id="ghost",
        order=0,
        text=_synthetic_dimension("dim_present", "q1").elicitation.questions[0].text,
    )
    present = _synthetic_dimension("dim_present", "q1")
    ghost_bank = QuestionBank(entries=(ghost,), dimension_count=1)
    assert unresolved_dimension_ids(ghost_bank, [present]) == ["dim_ghost"]


# --- determinism: the bank is a pure, reproducible projection --------------


def test_build_bank_is_deterministic(dimensions: list[Dimension]) -> None:
    """Rebuilding from the same model twice must produce byte-identical output.

    Matches the determinism this repo already holds `profile_rebuild` to
    (T6): a bank a consumer cannot reproduce is a bank nobody can resume
    against or diff.
    """
    first = build_bank(dimensions)
    second = build_bank(dimensions)
    assert first.model_dump_json() == second.model_dump_json()


def test_bank_order_is_stable_and_dimension_grouped(bank: QuestionBank) -> None:
    """Entries appear in ascending `order`, and each dimension's own questions
    stay contiguous — the ordering guarantee a resuming interview relies on.
    """
    orders = [entry.order for entry in bank.entries]
    assert orders == sorted(orders)
    assert orders == list(range(len(orders)))
    seen: set[str] = set()
    previous_dimension: str | None = None
    for entry in bank.entries:
        if entry.dimension_id != previous_dimension:
            assert entry.dimension_id not in seen, (
                f"{entry.dimension_id}'s questions are not contiguous in the bank"
            )
            seen.add(entry.dimension_id)
            previous_dimension = entry.dimension_id


def test_by_dimension_returns_only_that_dimensions_questions(bank: QuestionBank) -> None:
    entries = bank.by_dimension("remote_arrangement")
    assert entries
    assert all(entry.dimension_id == "remote_arrangement" for entry in entries)


# --- the adversarial probe and the evidence writer --------------------------


def test_probe_bank_generation_runs_at_least_the_declared_floor() -> None:
    """The probe must actually exercise >=MINIMUM_PROBES adversarial scenarios.

    A probe that quietly stopped running its checks would still report zero
    failures — this pins the floor so "nothing failed" cannot mean "nothing
    ran".
    """
    probed = probe_bank_generation()
    assert probed["checks_run"] >= MINIMUM_PROBES
    assert probed["failures"] == []


def test_write_evidence_reports_full_coverage(tmp_path: Path) -> None:
    evidence_path = tmp_path / "T7.json"
    measured = write_evidence(evidence_path)
    assert evidence_path.exists()
    assert measured["question_dimension_coverage"] == 1.0
    assert measured["dimensions_missing_full_language_coverage"] == []
    assert measured["questions_with_unresolved_dimension"] == []
    assert measured["adversarial_failures"] == []
    assert measured["adversarial_checks_run"] >= MINIMUM_PROBES


def test_measure_raises_on_a_missing_dimensions_directory(tmp_path: Path) -> None:
    """Coverage over a model that could not load is not a measurement.

    Matches `jobsearch.dimensions.write_coverage_evidence`'s stance for T3: a
    broken or missing model is reported as a load failure, not silently scored.
    """
    from jobsearch.dimensions import DimensionError

    missing = tmp_path / "no-such-dimensions-dir"
    with pytest.raises(DimensionError):
        measure(missing)


def test_measure_reports_zero_dimensions_for_an_empty_directory(tmp_path: Path) -> None:
    """An *existing but empty* directory is not an error — it is zero coverage.

    `load_dimensions` treats "no files here" differently from "this path does
    not exist"; `_main`'s `dimension_count == 0` floor is what catches this
    case and refuses to call it a passing measurement.
    """
    empty = tmp_path / "empty-dimensions"
    empty.mkdir()
    measured = measure(empty)
    assert measured["dimension_count"] == 0
    assert measured["question_dimension_coverage"] == 0.0
