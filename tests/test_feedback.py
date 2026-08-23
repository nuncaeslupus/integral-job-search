"""T21 — the feedback loop: a rejection reason reaches the weights, or is counted.

Step 10's gate: *"`feedback_traceability == 1.0` — every derived value names the
evidence rows that produced it, so 'the ranking changed because you said X' is
checkable rather than a story."*

Two ways that sentence can be false, and the metric has to see both:

* **A derived value with no provenance.** A stated constraint, a trait, a
  part-worth that names no row is a number the tool cannot attribute. Naming a
  row that is not in the effective log is the same failure with a citation on it.
* **A reason that never became a row.** `lifecycle.transition` records a
  `reason` in the offer's own history and writes nothing to `evidence.jsonl` —
  by design, since coupling the lifecycle to the profile store crosses the
  ownership line S5 drew. So a decision made through `transition` directly moves
  the offer and leaves the weights untouched, and the candidate is told their
  words changed the list when they did not. That is the seam this task exists to
  close, and it is closed by counting it rather than by forbidding it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.decline import DeclineLedger
from integral.feedback import (
    FeedbackError,
    measure,
    orphaned_reasons,
    record_decision,
    traceability,
    write_evidence,
)
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    LifecycleError,
    load_lifecycle_offer,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import connect_manual
from integral.profile import EvidenceLog, EvidenceSubject, rebuild
from integral.profile_capture import capture

_AT = "2026-08-24T10:00:00Z"


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    return ProfileStore(tmp_path, identity.handle)


def _offer(store: ProfileStore, text: str = "Backend en Barcelona, oficina cada dia.") -> str:
    offer = connect_manual(text, title="Backend", company="ACME", language="es")
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    return offer.id


def _say(
    store: ProfileStore, text: str, *, kind: str = "constraint", dims: tuple[str, ...] = ()
) -> None:
    capture(
        EvidenceLog(store),
        DeclineLedger(store),
        step="constraints",
        kind=kind,  # type: ignore[arg-type]
        text=text,
        source="conversation",
        dimensions=dims,
        recorded_at=_AT,
    )


def test_every_profile_value_traces_to_evidence_rows(tmp_path: Path) -> None:
    """The named gate test."""
    store = _store(tmp_path)
    _say(store, "No quiero desplazarme más de 30 minutos.", dims=("commute",))
    _say(
        store,
        "Aprendí Rust por mi cuenta el año pasado.",
        kind="episode",
        dims=("learning_support",),
    )
    rebuild(store)

    measured = traceability(store)
    assert measured["untraced"] == []
    assert measured["feedback_traceability"] == 1.0
    assert measured["values"] > 0


def test_a_derived_value_naming_no_row_is_untraced(tmp_path: Path) -> None:
    """The measurement has to be able to fall, or it certifies nothing."""
    store = _store(tmp_path)
    _say(store, "No quiero desplazarme más de 30 minutos.", dims=("commute",))
    rebuild(store)

    traits = store.read_json("profile", "traits.json")
    traits["dimensions"]["commute"]["evidence"] = []
    store.write_json(traits, "profile", "traits.json")

    measured = traceability(store)
    assert measured["feedback_traceability"] < 1.0
    assert any("commute" in problem for problem in measured["untraced"])


def test_a_value_citing_a_row_that_is_not_in_the_log_is_untraced(tmp_path: Path) -> None:
    """A citation to nothing is worse than no citation: it looks checked."""
    store = _store(tmp_path)
    _say(store, "No quiero desplazarme más de 30 minutos.", dims=("commute",))
    rebuild(store)

    traits = store.read_json("profile", "traits.json")
    traits["dimensions"]["commute"]["evidence"] = ["ev-0000000000000000"]
    store.write_json(traits, "profile", "traits.json")

    assert traceability(store)["feedback_traceability"] < 1.0


def test_a_stated_pinned_constraint_names_the_row_that_stated_it(tmp_path: Path) -> None:
    """T24's ten fields carried a `state` and no provenance — a stated value
    nobody could trace. `unknown` and `declined` are not derived from a row and
    are not asked for one."""
    store = _store(tmp_path)
    _say(
        store,
        json.dumps(
            {
                "quote": "Vivo en Barcelona.",
                "value": {"country": "ES", "accepts_onsite_in_country": True},
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        dims=("location",),
    )
    rebuild(store)

    fields = store.read_json("profile", "constraints.json")["fields"]
    stated = {name: field for name, field in fields.items() if field.get("state") == "stated"}
    assert stated
    for name, field in stated.items():
        assert field.get("evidence"), name


def test_rejection_moves_offer_status_and_marks_weights_stale(tmp_path: Path) -> None:
    """The whole loop in one call: status moves, the reason lands, weights rebuild."""
    store = _store(tmp_path)
    offer_id = _offer(store)
    rebuild(store)
    before = store.read_json("profile", "weights.json")["profile_revision"]["rows"]

    result = record_decision(store, offer_id, "screened_out", at=_AT, reason="Otra agencia, no.")

    offer, record = load_lifecycle_offer(store, offer_id)
    assert offer.status == "screened_out"
    assert record.history[-1].reason == "Otra agencia, no."
    assert result.row is not None
    assert result.row.about is not None and result.row.about.id == offer_id
    assert store.read_json("profile", "weights.json")["profile_revision"]["rows"] > before


def test_the_reason_reaches_the_log_and_names_its_offer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _offer(store)
    record_decision(store, offer_id, "screened_out", at=_AT, reason="Otra agencia, no.")

    rows = list(EvidenceLog(store).effective_rows())
    reason_rows = [row for row in rows if row.about is not None and row.about.id == offer_id]
    assert [row.text for row in reason_rows] == ["Otra agencia, no."]
    assert orphaned_reasons(store) == []


def test_a_decision_with_no_reason_writes_no_row(tmp_path: Path) -> None:
    """Nothing was said, so there is nothing to have dropped."""
    store = _store(tmp_path)
    offer_id = _offer(store)
    result = record_decision(store, offer_id, "screened_out", at=_AT, reason=None)

    assert result.row is None
    assert orphaned_reasons(store) == []


def test_a_reason_routed_around_the_wrapper_is_counted_not_forbidden(tmp_path: Path) -> None:
    """`transition` still takes a `reason` and still writes only to the offer's
    own history — S5's ownership line. What changes is that the reason cannot
    stay invisible: it is a decision the candidate made whose words never
    reached the weights, and it is named."""
    store = _store(tmp_path)
    offer_id = _offer(store)
    offer, record = load_lifecycle_offer(store, offer_id)
    save_lifecycle_offer(
        store, *transition(offer, record, "screened_out", at=_AT, reason="Sin remoto.")
    )

    orphans = orphaned_reasons(store)
    assert [orphan["reason"] for orphan in orphans] == ["Sin remoto."]
    assert traceability(store)["feedback_traceability"] < 1.0


def test_an_unknown_offer_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(FeedbackError):
        record_decision(store, "sha256:" + "0" * 64, "screened_out", at=_AT, reason="x")


def test_an_illegal_transition_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    """A refused move must not leave the reason in the log claiming a decision
    the offer never made."""
    store = _store(tmp_path)
    offer_id = _offer(store)
    record_decision(store, offer_id, "screened_out", at=_AT, reason="Otra agencia, no.")
    rows_before = len(list(EvidenceLog(store).effective_rows()))

    with pytest.raises(LifecycleError):
        record_decision(store, offer_id, "new", at=_AT, reason="Vuelve atrás.")

    assert len(list(EvidenceLog(store).effective_rows())) == rows_before


def test_measure_proves_the_fraction_can_fall() -> None:
    measured = measure()
    assert measured["feedback_traceability"] == 1.0
    assert measured["fraction_falls_when_a_reason_bypasses_the_log"] == 1


def test_write_evidence_records_the_gate_key(tmp_path: Path) -> None:
    evidence = tmp_path / "T21.json"
    write_evidence(evidence)
    assert json.loads(evidence.read_text(encoding="utf-8"))["feedback_traceability"] == 1.0


# ---------------------------------------------------------------------------
# Matching a reason to a row is a count, not a membership test.


def test_the_same_reason_said_twice_needs_two_rows(tmp_path: Path) -> None:
    """One row cannot discharge two decisions. Set membership let a bypass hide
    behind an earlier, properly recorded decision that used the same words."""
    store = _store(tmp_path)
    first = _offer(store, "Primera oferta, oficina.")
    second = _offer(store, "Segunda oferta, oficina.")
    record_decision(store, first, "screened_out", at=_AT, reason="Otra agencia, no.")

    offer, record = load_lifecycle_offer(store, second)
    save_lifecycle_offer(
        store, *transition(offer, record, "screened_out", at=_AT, reason="Otra agencia, no.")
    )

    assert [orphan["offer"] for orphan in orphaned_reasons(store)] == [second]


def test_two_decisions_on_one_offer_with_the_same_words_need_two_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _offer(store)
    record_decision(store, offer_id, "screened_out", at=_AT, reason="No.")

    offer, record = load_lifecycle_offer(store, offer_id)
    save_lifecycle_offer(store, *transition(offer, record, "expired", at=_AT, reason="No."))

    assert len(orphaned_reasons(store)) == 1


def test_a_whitespace_only_reason_is_not_an_orphan(tmp_path: Path) -> None:
    """The wrapper writes no row for one, because nothing was said."""
    store = _store(tmp_path)
    offer_id = _offer(store)
    offer, record = load_lifecycle_offer(store, offer_id)
    save_lifecycle_offer(store, *transition(offer, record, "screened_out", at=_AT, reason="   "))

    assert orphaned_reasons(store) == []


def test_an_unrelated_row_about_the_offer_does_not_discharge_a_reason(tmp_path: Path) -> None:
    """Only the wrapper's own `offer_reaction` rows are eligible."""
    store = _store(tmp_path)
    offer_id = _offer(store)
    capture(
        EvidenceLog(store),
        DeclineLedger(store),
        step="feedback",
        kind="statement",
        text="Sin remoto.",
        source="conversation",
        recorded_at=_AT,
        about=EvidenceSubject(kind="offer", id=offer_id),
    )
    offer, record = load_lifecycle_offer(store, offer_id)
    save_lifecycle_offer(
        store, *transition(offer, record, "screened_out", at=_AT, reason="Sin remoto.")
    )

    assert len(orphaned_reasons(store)) == 1


def test_a_non_stated_constraint_field_may_not_name_evidence() -> None:
    """`unknown` and `declined` were not derived from a row, so naming one
    asserts a provenance for an answer that does not exist."""
    from integral.candidate import FIELD_MODELS

    model = FIELD_MODELS["location"]
    with pytest.raises(ValidationError):
        model(state="declined", evidence=("ev-0000000000000001",))
    with pytest.raises(ValidationError):
        model(state="unknown", evidence=("ev-0000000000000001",))
