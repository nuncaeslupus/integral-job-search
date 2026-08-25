"""T15 — staged extraction: rules first, the model last, evidence always.

Written against the committed dimension model and corpus rather than inline
look-alikes, for the reason the other suites here give: a hand-built fixture
drifts away from the real thing the first time somebody edits the real thing.
Where a test needs a cue set that does not exist, it builds one explicitly and
says so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.dimensions import Cue, Dimension, Extraction, Language, load_dimensions
from integral.extraction import (
    DECLARED_SUBSET,
    DimensionScore,
    EvidenceSpan,
    ExtractionError,
    ModelRequest,
    accept_model_scores,
    cue_findings,
    extract,
    measure,
    model_request,
    negation_recall,
    normalise,
    rules_stage,
    unsettled_dimensions,
    write_evidence,
)
from integral.harness import load_store
from integral.offers import Offer, compute_offer_id

_DIMENSIONS = load_dimensions()


def _offer(text: str, language: Language = "es") -> Offer:
    return Offer(id=compute_offer_id(text), source="test", text=text, language=language)


def _dimension(dimension_id: str) -> Dimension:
    return next(d for d in _DIMENSIONS if d.id == dimension_id)


def _with_cues(base: Dimension, cues: list[Cue], language: Language = "es") -> Dimension:
    """The real dimension with a cue set this test controls."""
    return base.model_copy(update={"extraction": Extraction(cues={language: cues})})


# ---------------------------------------------------------------------------
# the gate


def test_extraction_matches_corpus_labels() -> None:
    """The named gate test — and today it asserts a *refusal*, on purpose.

    `extraction_macro_f1 >= 0.75` is measured over evaluation-split labels a
    person placed. There are 14, no dimension above 1, and D-2 (`lo-77a6`)
    binds this task to refuse a number below the per-dimension floor rather
    than compute one over three rows.

    So the correct output is `null` plus `unmeasured` plus the dimensions
    named. When the corpus grows past the floor this test is what should start
    failing — that is the signal to implement scoring, and `measure` raises
    rather than silently reporting a number it never computed.
    """
    measured = measure()
    assert measured["extraction_status"] == "unmeasured"
    assert measured["extraction_macro_f1"] is None
    assert measured["scorable_dimensions"] == []
    assert measured["dimensions_below_floor"], "a refusal must say what it could not score"
    assert measured["evaluation_label_count"] < (
        measured["label_floor"] * len(measured["dimensions_below_floor"])
    )


def test_unmeasured_is_not_a_zero_score() -> None:
    """Null, not 0.0 — the distinction the whole of D-2 rests on.

    A 0.0 in this key is a *failing* extractor. An extractor nobody has been
    able to measure is not failing, and a reader who cannot tell those apart
    will either ship something broken or rewrite something that works.
    """
    measured = measure()
    # Present-and-null, which is a third thing from absent and from 0.0. An
    # absent key reads as "this run never happened"; 0.0 reads as "the
    # extractor scored nothing right".
    assert "extraction_macro_f1" in measured
    assert measured["extraction_macro_f1"] is None
    assert measured["extraction_macro_f1"] != 0.0


def test_the_evidence_file_records_what_it_measured(tmp_path: Path) -> None:
    evidence = tmp_path / "T15.json"
    write_evidence(evidence)
    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded["extraction_macro_f1"] is None
    assert recorded["prefilter_suppressed_positives"] == 0
    assert recorded["prefilter_positives_checked"] > 0, "a clean result over nothing is nothing"


# ---------------------------------------------------------------------------
# stage 1 — normalise


def test_decomposed_characters_are_composed_before_cues_run() -> None:
    """A Catalan advert saved decomposed would match no Catalan cue at all.

    The failure mode is silence: every dimension comes back unsettled and the
    run looks like an advert that says nothing, rather than like a bug.
    """
    composed = normalise(_offer("es valora l'autonomia", language="ca"))
    decomposed = normalise(_offer("es valora l'autonomià", language="ca"))
    assert "̀" not in decomposed.text
    assert composed.language == "ca"


def test_an_offer_without_a_language_falls_back_visibly() -> None:
    offer = Offer(id=compute_offer_id("hola"), source="test", text="hola")
    assert normalise(offer, default_language="ca").language == "ca"


# ---------------------------------------------------------------------------
# stage 2 — the rules stage


def test_a_unipolar_dimension_settles_on_one_match() -> None:
    """Presence is the signal on a scale that runs absent-to-present."""
    dimension = _with_cues(_dimension("travel_requirement"), [Cue(pattern=r"viajes", value=0.8)])
    found = cue_findings(normalise(_offer("Se requieren viajes frecuentes.")), dimension)
    assert found is not None and found.value > 0
    assert found.spans[0].quote == "viajes"


def test_a_bipolar_dimension_is_not_settled_by_one_keyword() -> None:
    """The team_autonomy case, which `prefilter_suppression` caught.

    "Ejecutar las tareas asignadas con autonomía" contains the word and means
    the opposite of what the word alone suggests; a person labelled it -0.6
    while a single +0.7 cue settled it +1. On a bipolar scale one keyword is
    evidence of the *topic*, not of a direction, so the dimension stays on the
    model's agenda instead.
    """
    dimension = _with_cues(
        _dimension("team_autonomy"), [Cue(pattern=r"autonom\w+", value=0.7, negatable=True)]
    )
    ad = normalise(_offer("-Ejecutar las tareas asignadas con autonomía garantizando la calidad."))
    assert cue_findings(ad, dimension) is None


def test_disagreeing_cues_on_a_bipolar_dimension_go_to_the_model() -> None:
    """Two cues pointing opposite ways is the clearest case for asking a model.

    Averaging them would produce a confident number out of a contradiction.
    """
    dimension = _with_cues(
        _dimension("team_autonomy"),
        [Cue(pattern=r"autonomía", value=0.7), Cue(pattern=r"microgestión", value=-0.8)],
    )
    ad = normalise(_offer("Tendrás autonomía. Hay microgestión constante."))
    assert cue_findings(ad, dimension) is None


def test_a_negatable_cue_inverts_rather_than_disappearing() -> None:
    """ "no on-call" is evidence *against*, not absence of evidence."""
    dimension = _with_cues(
        _dimension("on_call_load"), [Cue(pattern=r"guardias", value=0.8, negatable=True)]
    )
    plain = cue_findings(normalise(_offer("Incluye guardias rotativas.")), dimension)
    negated = cue_findings(normalise(_offer("El puesto es sin guardias.")), dimension)
    assert plain is not None and plain.value > 0 and not plain.negated
    assert negated is not None and negated.value < 0 and negated.negated


def test_no_cue_match_is_unsettled_and_never_absent() -> None:
    """The prefilter's whole recall obligation, in one assertion.

    "No regex matched" may narrow what the model is asked; it may never become
    "the advert says this dimension is absent", which is a claim no regex is
    entitled to make.
    """
    dimension = _with_cues(_dimension("travel_requirement"), [Cue(pattern=r"zzz", value=0.9)])
    assert cue_findings(normalise(_offer("Nada relevante aquí.")), dimension) is None
    assert "travel_requirement" in unsettled_dimensions([dimension], [])


# ---------------------------------------------------------------------------
# stage 3 — the model, and what it is not allowed to do


def test_model_is_not_called_for_a_dimension_rules_settled() -> None:
    """The named test: what stage 2 settled never reaches stage 3's agenda.

    This is the cost control the whole staging exists for — "the model is the
    last resort rather than the first" — and the request object is where it is
    observable.
    """
    dimension = _with_cues(_dimension("travel_requirement"), [Cue(pattern=r"viajes", value=0.8)])
    ad = normalise(_offer("Se requieren viajes frecuentes."))
    scores = rules_stage(ad, [dimension])
    assert [s.dimension for s in scores] == ["travel_requirement"]
    assert model_request(ad, unsettled_dimensions([dimension], scores)).dimensions == []


def test_the_model_request_has_nowhere_to_put_the_candidate() -> None:
    """Step 8's "never send the candidate's profile with the advert", structurally.

    A rule that lives only in prose is one a future caller breaks by accident;
    `extra="forbid"` makes the attempt a `ValidationError` at the boundary.
    """
    assert "profile" not in ModelRequest.model_fields
    with pytest.raises(ValueError, match=r"extra_forbidden|Extra inputs"):
        ModelRequest(offer_id="x", language="es", text="t", dimensions=[], profile={"pay": 1})  # type: ignore[call-arg]


def test_a_model_span_that_is_not_in_the_advert_is_refused() -> None:
    """An invented quote would put fabricated words in front of the candidate
    as the employer's own — the one thing evidence spans exist to prevent."""
    ad = normalise(_offer("Trabajo remoto disponible."))
    fabricated = DimensionScore(
        dimension="remote_arrangement",
        value=0.9,
        spans=[EvidenceSpan(start=0, end=7, quote="Salario")],
        provenance="model",
    )
    with pytest.raises(ExtractionError, match="not what the advert says"):
        accept_model_scores(ad, [fabricated], ["remote_arrangement"])


def test_a_dimension_the_model_was_not_asked_about_is_refused() -> None:
    ad = normalise(_offer("Trabajo remoto disponible."))
    score = DimensionScore(
        dimension="on_call_load",
        value=0.5,
        spans=[EvidenceSpan(start=0, end=7, quote="Trabajo")],
        provenance="model",
    )
    with pytest.raises(ExtractionError, match="not asked about"):
        accept_model_scores(ad, [score], ["remote_arrangement"])


def test_the_same_dimension_scored_twice_is_refused() -> None:
    ad = normalise(_offer("Trabajo remoto disponible."))
    score = DimensionScore(
        dimension="remote_arrangement",
        value=0.5,
        spans=[EvidenceSpan(start=0, end=7, quote="Trabajo")],
        provenance="model",
    )
    with pytest.raises(ExtractionError, match="twice"):
        accept_model_scores(ad, [score, score], ["remote_arrangement"])


def test_score_without_evidence_span_is_rejected() -> None:
    """The named test. Pinned on the schema, so no call site can produce one."""
    with pytest.raises(ValueError, match="at least 1 item"):
        DimensionScore(dimension="remote_arrangement", value=0.5, spans=[], provenance="model")


def test_a_span_whose_quote_does_not_match_its_own_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not match the length"):
        EvidenceSpan(start=0, end=3, quote="much longer than three")


# ---------------------------------------------------------------------------
# the whole pipeline


def test_an_extraction_names_what_it_could_not_settle() -> None:
    """ "The advert does not say" is a finding a ranking is entitled to show.

    Omitting the key instead would be indistinguishable from a dimension
    nobody looked at.
    """
    dimension = _with_cues(_dimension("travel_requirement"), [Cue(pattern=r"zzz", value=0.9)])
    result = extract(_offer("Nada relevante."), [dimension])
    assert result.scores == []
    assert result.unsettled == ["travel_requirement"]


def test_a_model_score_lands_in_the_extraction_marked_as_the_models() -> None:
    dimension = _with_cues(_dimension("travel_requirement"), [Cue(pattern=r"zzz", value=0.9)])
    offer = _offer("Se viaja mucho.")
    ad = normalise(offer)
    proposed = [
        DimensionScore(
            dimension="travel_requirement",
            value=0.8,
            spans=[EvidenceSpan(start=3, end=8, quote=ad.slice(3, 8))],
            provenance="rules",
        )
    ]
    result = extract(offer, [dimension], model_scores=proposed)
    claimed = [s.provenance for s in result.scores]
    assert claimed == ["model"], "provenance is set here, not claimed by the model"
    assert result.unsettled == []


# --- D-19: a vocabulary that reached nothing is not understanding -----------


def test_an_extraction_that_settled_nothing_is_not_reported_as_read() -> None:
    """The failure D-19 was filed for: 0 of 25 settled, and step 8 said coverage met.

    The artefact is present — the step ran and wrote a file per offer — so
    coverage counts it. What must not follow is the step being read as having
    understood anything, and that refusal holds whether or not T56 has built the
    acceptance gate.
    """
    from integral.step_gates import VOCABULARY_SILENT, checkpoint_exit

    settled_nothing = {
        "runnable": True,
        "coverage_met": True,
        "certifiable": True,
        "vocabulary_settled": False,
    }

    assert checkpoint_exit(settled_nothing) == VOCABULARY_SILENT


def test_every_supported_market_has_applicable_dimensions() -> None:
    """Every `job_family` the corpus covers has at least one dimension that applies.

    The market, not the advert, is the unit: 33 of 208 individual ads settle
    nothing at the rules stage and that is ordinary — stage 3 asks a model for
    the rest. A whole *family* with no applicable dimension is the D-19 defect,
    and is what this refuses. `trades` is the family that case came from.
    """
    from integral.vocabulary_reach import market_reach

    reach = market_reach()

    assert reach, "the corpus reported no job families at all"
    unreached = {family: row for family, row in reach.items() if row["applicable_dimensions"] == 0}
    assert not unreached, f"markets with no applicable dimension: {unreached}"


# ---------------------------------------------------------------------------
# T56 — macro-F1, on a corpus that clears the floor


def _store(
    tmp_path: Path,
    rows: list[tuple[str, str, float]],
    dimension: str = "remote_arrangement",
) -> Path:
    """A store of evaluation-split ads, one label each on `dimension`."""
    path = tmp_path / "ads.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": ad_id,
                    "language": "es",
                    "text": text,
                    "source_url": "https://example.test/ad",
                    "split": "evaluation",
                    "labels": [
                        {
                            "dimension": dimension,
                            "value": value,
                            "spans": [{"start": 0, "end": len(text)}],
                            "labeller": "test",
                        }
                    ],
                }
            )
            for ad_id, text, value in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_macro_f1_is_measured_once_a_dimension_clears_the_floor(tmp_path: Path) -> None:
    """Six cue hits, two misses, two true negatives — F1 = 2·6/(2·6+0+2) = 0.8571."""
    rows = (
        [(f"hit{i}", "Puesto 100% remoto en Madrid.", 1.0) for i in range(6)]
        + [(f"off{i}", "Puesto presencial en Madrid.", 0.0) for i in range(2)]
        + [(f"miss{i}", "Puedes trabajar desde casa siempre.", 1.0) for i in range(2)]
    )
    measured = measure(_store(tmp_path, rows))

    assert measured["extraction_status"] == "measured"
    assert measured["scorable_dimensions"] == ["remote_arrangement"]
    per = measured["extraction_f1_by_dimension"]["remote_arrangement"]
    assert (per["true_positives"], per["false_positives"], per["false_negatives"]) == (6, 0, 2)
    assert per["n"] == 10, "D-2 requires n beside every per-dimension score"
    assert per["f1"] == 0.8571
    assert measured["extraction_macro_f1"] == 0.8571
    assert measured["extraction_scored_n"] == 10, "and n beside the aggregate too"


def test_a_dimension_nobody_asserted_is_not_a_free_1_point_0(tmp_path: Path) -> None:
    """Ten labels, none of them positive, no cue firing: there is no ratio.

    Scoring that as 1.0 would let a dimension the extractor was never asked to
    find anything in carry the macro mean upwards — the same "a number appeared
    so it must be true" failure D-2 exists to stop, one level down.
    """
    measured = measure(_store(tmp_path, [(f"n{i}", "Puesto presencial.", 0.0) for i in range(10)]))

    assert measured["extraction_f1_by_dimension"]["remote_arrangement"]["f1"] is None
    assert measured["dimensions_without_positives"] == ["remote_arrangement"]
    assert measured["extraction_macro_f1"] is None
    assert measured["extraction_status"] == "unmeasured"


def test_a_false_positive_cannot_manufacture_a_score_for_an_unasserted_dimension(
    tmp_path: Path,
) -> None:
    """Ten class-0 labels and ten cue hits: `f1: null`, and the ten stay visible.

    F1 on an empty positive class is undefined. Keying the refusal on the F1
    denominator instead of on the labels let a single false positive make the
    denominator non-zero, yield the conventional `0.0`, and drag a dimension
    into the macro that the macro cannot say anything about — averaging a
    convention and calling the result a measurement.

    Dropping it must not hide the false positives, and this asserts that too:
    they are what `false_positives_outside_the_macro` is for.
    """
    rows = [(f"fp{i}", "Puesto 100% remoto en Madrid.", 0.0) for i in range(10)]
    measured = measure(_store(tmp_path, rows))

    per = measured["extraction_f1_by_dimension"]["remote_arrangement"]
    assert (per["true_positives"], per["false_positives"], per["false_negatives"]) == (0, 10, 0)
    assert per["f1"] is None, "no positive class, so no F1 — not a zero"
    assert measured["extraction_macro_f1"] is None
    assert measured["extraction_status"] == "unmeasured"
    assert measured["false_positives_outside_the_macro"] == 10


def test_an_unmeasured_result_has_the_same_shape_as_a_measured_one(tmp_path: Path) -> None:
    """Aggregate keys are emitted on every run, not only on the runs that score.

    A key that appears only on success makes the two outcomes different shapes,
    and a reader who has to branch on which keys exist cannot tell an unmeasured
    run from a run that never happened — the distinction the whole file rests on.
    """
    rows = [(f"n{i}", "Puesto presencial.", 0.0) for i in range(10)]
    unmeasured = measure(_store(tmp_path, rows))

    assert unmeasured["extraction_scored_n"] == 0
    assert unmeasured["extraction_scored_dimensions"] == []
    assert unmeasured["extraction_macro_f1"] is None


def test_the_declared_subset_is_recorded_beside_what_was_actually_scored(
    tmp_path: Path,
) -> None:
    """A widening must be visible, which is the enforceable half of "closed".

    `measure` scores every dimension that reaches the floor, deliberately — the
    macro should widen as the corpus grows. What must not happen is a sixth
    dimension entering the mean without anyone able to see that it did. So the
    declaration is recorded beside the outcome, and the difference is named.
    """
    rows = [(f"a{i}", "Incluye guardias semanales.", 0.8) for i in range(10)]
    measured = measure(_store(tmp_path, rows, dimension="on_call_load"))

    assert measured["declared_subset"] == sorted(DECLARED_SUBSET)
    assert "on_call_load" not in DECLARED_SUBSET
    assert measured["extraction_scored_dimensions"] == ["on_call_load"]
    assert measured["scored_beyond_the_declared_subset"] == ["on_call_load"]
    assert measured["extraction_macro_f1"] is not None, "it still counts — it is just named"
# T59 — a denial is not an absence


def test_a_denial_cue_records_a_denial_not_an_absence() -> None:
    """`Cue.denies` is how a cue whose pattern *contains* its own negator says so.

    `sin\\s+viajes` cannot be read by `_is_negated`, which looks backwards from
    the match for a negator: here the negator is inside the match. Before
    `denies` such a cue could only report `value=0.0, negated=False` — the
    encoding that means "the advert states the lowest rung", which is what
    `presencial` means and emphatically not what `sin viajes` means.
    """
    base = _dimension("travel_requirement")
    dimension = _with_cues(base, [Cue(pattern=r"sin\s+viajes", value=0.0, denies=True)])
    found = cue_findings(normalise(_offer("Sin viajes ni guardias.")), dimension)

    assert found is not None
    assert found.negated is True, "the advert denies travel; it does not omit it"


def test_a_zero_rung_cue_is_not_a_denial() -> None:
    """`presencial` states rung 0 affirmatively — that is a value, not a negation.

    The distinction this pair of tests draws is the whole of the change: of the
    sixteen zero-valued cues in the model, ten are denials and six are adverts
    naming their lowest rung outright. Marking the second kind `denies` would
    make "this job is on-site" read as "this job denies being on-site".
    """
    base = _dimension("remote_arrangement")
    dimension = _with_cues(base, [Cue(pattern="presencial", value=0.0)])
    found = cue_findings(normalise(_offer("Puesto presencial en Madrid.")), dimension)

    assert found is not None
    assert found.negated is False


def test_a_denial_cue_that_also_claims_to_be_negatable_is_refused() -> None:
    """Both at once is not wrong, it is unreadable — `negatable` would do nothing."""
    with pytest.raises(ValidationError):
        Cue(pattern=r"sin\s+viajes", value=0.0, denies=True, negatable=True)


def test_every_denial_in_the_model_reaches_the_store_as_a_denial() -> None:
    """The gate's own corpus: every negated evaluation label a cue settles is settled as negated.

    This is `negation_recall`'s "settled, but not as negated" bucket, asserted
    to be empty. It is the half of T59 the dimension model owns — the other
    half is denials no cue reaches at all, which is a coverage question and
    stays visible in `negation_recall_misses`.
    """
    _, misses = negation_recall(load_store(), load_dimensions())
    mis_encoded = [m for m in misses if "settled, but not as negated" in m]
    assert mis_encoded == []


def test_a_negated_single_match_settles_a_bipolar_dimension() -> None:
    """The asymmetry: corroboration is asked of positives, not of denials.

    `test_a_bipolar_dimension_is_not_settled_by_one_keyword` is still true and
    still the rule — one `sprint` in a tool list establishes nothing. A denial
    is the other case: the advert went out of its way to say it, and asking for
    a second one sends an unambiguous statement to the model as "unsettled".
    """
    base = _dimension("process_formality")
    dimension = _with_cues(base, [Cue(pattern="sprint", value=0.5, negatable=True)])
    found = cue_findings(normalise(_offer("Trabajamos sin sprints tradicionales.")), dimension)

    assert found is not None, "one denial is enough; one keyword is not"
    assert found.negated is True
    assert found.value == -0.5
