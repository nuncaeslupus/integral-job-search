"""T186: a retraction chain resolves to a current value, at any depth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from integral import generate as generate_module
from integral.approval import ApprovalError, PersonalDetails, payload_digest, prepare, record_sent
from integral.cv_store import (
    SCALAR_FIELDS,
    SECTION_MODELS,
    ConversationTurn,
    CVMaster,
    Education,
    Experience,
    measure_provenance,
    write_master,
)
from integral.feedback import traceability as fb_traceability
from integral.generate import generate, render_entry, retracted_claims_still_traced, traceability
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, EvidenceRow, rebuild

_AT = "2026-08-24T09:00:00Z"


def _log(tmp_path: Path) -> tuple[ProfileStore, EvidenceLog]:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    store = ProfileStore(tmp_path, identity.handle)
    return store, EvidenceLog(store)


def _add(
    log: EvidenceLog, text: str, *, retracts: str | None = None, kind: str | None = None
) -> EvidenceRow:
    return log.append(
        recorded_at=_AT,
        step="history",
        kind="retraction" if retracts else (kind or "statement"),  # type: ignore[arg-type]
        text=text,
        source="conversation",
        retracts=retracts,
        dimensions=() if retracts else ("learning_support",),
    )


def _chain(log: EvidenceLog, depth: int) -> list[str]:
    """A row followed by `depth` retractions, each retracting the previous one."""
    ids = [_add(log, "Dietètica").id]
    for _ in range(depth):
        ids.append(_add(log, "retracts the previous", retracts=ids[-1]).id)
    return ids


def test_a_retracted_row_is_not_effective(tmp_path: Path) -> None:
    _, log = _log(tmp_path)
    wrong = _add(log, "Nutrició")
    right = _add(log, "Dietètica")
    retraction = _add(log, "no", retracts=wrong.id)

    live = {row.id for row in log.effective()}
    assert wrong.id not in live
    assert retraction.id not in live
    assert live == {right.id}
    assert len(log.rows()) == 3  # still append-only


def test_retracting_a_retraction_restores_the_original_row(tmp_path: Path) -> None:
    """ev-48 -> ev-60 retracts it -> ev-66 retracts ev-60: ev-48 is live again."""
    _, log = _log(tmp_path)
    original = _add(log, "Dietètica")
    wrong = _add(log, "Nutrició", retracts=original.id, kind="statement")
    assert wrong.kind == "retraction"  # a retraction row carries the wrong value
    undo = _add(log, "no", retracts=wrong.id)

    live = [row.id for row in log.effective()]
    assert live == [original.id]
    assert undo.id not in live


@pytest.mark.parametrize("depth", range(0, 14))
def test_a_chain_of_any_depth_resolves_by_parity(tmp_path: Path, depth: int) -> None:
    """The rule, not the enumeration: the row is live iff an even number of
    retractions stack on it. Both parities, every depth, must agree."""
    _, log = _log(tmp_path)
    ids = _chain(log, depth)
    live = {row.id for row in log.effective()}
    assert (ids[0] in live) is (depth % 2 == 0)
    assert not set(ids[1:]) & live  # retraction rows are never evidence


def test_a_withdrawn_value_never_reads_as_current_beside_a_restored_one(tmp_path: Path) -> None:
    _, log = _log(tmp_path)
    kept = _chain(log, 2)[0]  # restored
    gone = _chain(log, 3)[0]  # withdrawn
    live = {row.id for row in log.effective()}
    assert kept in live
    assert gone not in live


def _education_master(store: ProfileStore, turn_id: str) -> CVMaster:
    master = CVMaster(
        education=(
            Education(
                qualification="Diploma en Nutrició",
                institution="Uni",
                provenance=(ConversationTurn(evidence_id=turn_id),),
            ),
        )
    )
    write_master(store, master)
    return master


def _step11(
    store: ProfileStore, master: CVMaster, offer: str = "o-1"
) -> tuple[str, dict[str, Any]]:
    manifest = generate(store, master, offer_id=offer, advert="x", asks=())
    line = render_entry("education", master.education[0])
    return line, traceability(store, master, offer, manifest.version)


def test_a_claim_tracing_to_a_retracted_row_is_refused(tmp_path: Path) -> None:
    """Step 11 (T45), in a section that is not `episodes`."""
    store, log = _log(tmp_path)
    _add(log, "Diploma en Dietètica")
    wrong = _add(log, "Diploma en Nutrició")
    master = _education_master(store, wrong.id)

    line, live = _step11(store, master)
    assert live["claims_untraced"] == []  # control: backed while live

    _add(log, "no", retracts=wrong.id)
    line, measured = _step11(store, master)
    assert any(line in untraced for untraced in measured["claims_untraced"])
    assert measured["cv_generation_traceability"] < 1.0


def test_a_claim_whose_retraction_was_retracted_traces_again(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    row = _add(log, "Diploma en Nutrició")
    master = _education_master(store, row.id)
    for depth in range(1, 6):
        _add(log, "flip", retracts=_chain_tip(log, row.id))
        _, measured = _step11(store, master, f"o-{depth}")
        assert (measured["claims_untraced"] == []) is (depth % 2 == 0), depth


def _chain_tip(log: EvidenceLog, row_id: str) -> str:
    """The newest retraction stacked on `row_id` (or the row itself)."""
    tip = row_id
    for row in log.rows():
        if row.retracts == tip:
            tip = row.id
    return tip


def test_provenance_coverage_drops_for_a_retracted_turn(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    row = _add(log, "Diploma en Nutrició")
    master = _education_master(store, row.id)
    assert measure_provenance(store, master).coverage == 1.0
    _add(log, "no", retracts=row.id)
    assert measure_provenance(store, master).coverage < 1.0


def test_the_step_10_check_refuses_a_retracted_citation_too(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    row = _add(log, "Aprendí Rust por mi cuenta.", kind="episode")
    rebuild(store)
    assert fb_traceability(store)["untraced"] == []
    _add(log, "no", retracts=row.id)
    assert any(row.id in p for p in fb_traceability(store)["untraced"])


# --- the send path (approval.measure_prepared) shares the one backing rule ---

_DETAILS = PersonalDetails(
    full_name="Ada Lovelace",
    email="ada@example.invalid",
    phone="+34 600 111 222",
    postal_address="3 Carrer Nou, 17001 Girona",
)


def _experience_master(store: ProfileStore, turns: tuple[str, ...]) -> CVMaster:
    master = CVMaster(
        experience=(
            Experience(
                title="Dietista",
                organisation="Clinic",
                provenance=tuple(ConversationTurn(evidence_id=t) for t in turns),
            ),
        )
    )
    write_master(store, master)
    return master


def _prepare(store: ProfileStore, master: CVMaster, offer: str = "offer-1"):  # type: ignore[no-untyped-def]
    return prepare(
        store,
        master,
        offer_id=offer,
        advert="x",
        recipient="hr@example.invalid",
        details=_DETAILS,
    )


def test_prepare_refuses_an_experience_claim_on_a_retracted_turn(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    live = _add(log, "Dietista at Clinic")
    wrong = _add(log, "Dietista at Other")
    _add(log, "no", retracts=wrong.id)
    # the withdrawn turn is the SECOND provenance item: a first-item-only guard is blind to it
    master = _experience_master(store, (live.id, wrong.id))
    with pytest.raises(ApprovalError, match="no payload was written"):
        _prepare(store, master)
    assert not store.path("applications", "offer-1", "v1", "payload.json").exists()


def test_a_restored_twin_is_prepared_and_sent(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    row = _add(log, "Dietista at Clinic")
    _add(log, "oops", retracts=_add(log, "no", retracts=row.id).id)
    master = _experience_master(store, (row.id,))
    payload = _prepare(store, master)
    record_sent(store, master, "offer-1", 1, confirms=payload_digest(payload))
    assert store.path("applications", "offer-1", "v1.json").exists()


def test_record_sent_refuses_when_the_turn_is_retracted_after_drafting(tmp_path: Path) -> None:
    store, log = _log(tmp_path)
    live = _add(log, "Dietista at Clinic")
    wrong = _add(log, "Dietista at Other")
    master = _experience_master(store, (live.id, wrong.id))
    payload = _prepare(store, master)
    _add(log, "no", retracts=wrong.id)
    with pytest.raises(ApprovalError):
        record_sent(store, master, "offer-1", 1, confirms=payload_digest(payload))
    assert not store.path("applications", "offer-1", "v1.json").exists()


def test_every_claimable_section_is_probed_and_the_metric_is_per_section() -> None:
    measured = retracted_claims_still_traced()
    sections = set(generate_module._CLAIMABLE)
    assert measured["retraction_probe_sections"] == len(sections)
    assert sections <= {*SECTION_MODELS, *SCALAR_FIELDS}
    assert measured["claims_tracing_to_a_retracted_row"] == 0
    assert measured["retraction_probe_live_claims_traced"] == len(sections)


@pytest.mark.parametrize("section", sorted(generate_module._CLAIMABLE))
def test_a_guard_limited_to_one_section_moves_the_metric(
    section: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = generate_module.claim_is_backed

    def only_here(master: CVMaster, claim: Any, withdrawn: frozenset[str]) -> bool:
        return real(master, claim, withdrawn if claim.section == section else frozenset())

    monkeypatch.setattr(generate_module, "claim_is_backed", only_here)
    measured = retracted_claims_still_traced()
    assert measured["claims_tracing_to_a_retracted_row"] == len(generate_module._CLAIMABLE) - 1


def test_a_guard_reading_only_the_first_provenance_item_moves_the_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = generate_module.claim_is_backed

    def first_only(master: CVMaster, claim: Any, withdrawn: frozenset[str]) -> bool:
        entry = generate_module._entries(master, claim.section)[claim.entry_index]
        if not entry.provenance or not isinstance(entry.provenance[0], ConversationTurn):
            return real(master, claim, withdrawn)
        head = entry.provenance[0].evidence_id
        return real(master, claim, withdrawn & {head})

    monkeypatch.setattr(generate_module, "claim_is_backed", first_only)
    assert retracted_claims_still_traced()["claims_tracing_to_a_retracted_row"] > 0


def _fake_measure(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "cv_generation_traceability": 1.0,
        "claims_total": 1,
        "claims_untraced": [],
        "claims_unused": [],
        "claims_tracing_to_a_retracted_row": 0,
        "retraction_probe_sections": 6,
        "retraction_probe_live_claims_traced": 6,
    }
    return {**base, **over}


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({}, 0),
        ({"claims_tracing_to_a_retracted_row": 1}, 1),
        ({"retraction_probe_live_claims_traced": 5}, 1),
    ],
)
def test_main_exits_one_on_the_retraction_metric(
    over: dict[str, Any], code: int, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(generate_module, "measure", lambda *_a, **_k: _fake_measure(**over))
    assert generate_module._main(["generate", str(tmp_path / "T45.json")]) == code
