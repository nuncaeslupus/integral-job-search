"""T41 — the constraints step engine.

§2.1: Constraints "opens by showing what Intake already established and asks
the candidate to correct it rather than restate it" when a CV exists, and asks
from scratch when it does not. Both openings must resolve every one of T24's
ten pinned fields to exactly one of `stated`, `declined`, `unknown` — the
trichotomy §3.1 names and `step_runtime._constraints_resolved` reads back.

The rule every test here is really checking: a claim is not a fact, and
`declined` is not `unknown` wearing a different label.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.candidate import CONSTRAINT_FIELD_NAMES, load_constraints
from jobsearch.constraints_step import (
    CONSTRAINTS_PARTS,
    CandidateTurn,
    ConstraintsStepError,
    open_fields,
    probe_resolution,
    read_claims,
    resolve,
    write_evidence,
)
from jobsearch.decline import DeclineLedger
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.profile import EvidenceLog
from jobsearch.step_runtime import ProfileView, sufficiency


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def _written_fields(store: ProfileStore) -> dict[str, dict[str, object]]:
    payload = json.loads(store.path(*CONSTRAINTS_PARTS).read_text(encoding="utf-8"))
    fields: dict[str, dict[str, object]] = payload["fields"]
    return fields


# --- the trichotomy ----------------------------------------------------------


def test_every_constraint_field_resolves_to_one_of_three_states(store: ProfileStore) -> None:
    """A write that only records the fields it touched hides the ones it
    forgot — all ten pinned fields must land, every single call."""
    resolve(
        store,
        [
            CandidateTurn(
                field="location", action="state",
                value={"country": "ES", "accepts_onsite_in_country": True},
            ),
            CandidateTurn(field="salary", action="decline"),
        ],
        now="2026-08-18T09:00:00Z",
    )
    fields = _written_fields(store)
    assert set(fields) == set(CONSTRAINT_FIELD_NAMES)
    for name in CONSTRAINT_FIELD_NAMES:
        assert fields[name]["state"] in {"stated", "declined", "unknown"}

    # And T24's own loader — the ranking filter's contract — accepts the shape.
    loaded = load_constraints({"fields": fields})
    assert loaded.location.state == "stated"
    assert loaded.salary.state == "declined"
    assert loaded.reach.state == "unknown"


def test_unconfirmed_claim_stays_unknown(store: ProfileStore) -> None:
    """"Barcelona" on a CV header is the document's claim, not the candidate's
    confirmed fact (§2.1) — only an actual turn promotes it."""
    log = EvidenceLog(store)
    log.append(
        recorded_at="2026-08-18T08:00:00Z", step="intake", kind="statement",
        dimensions=["location"], text="Barcelona (CV header)", source="cv_document",
    )
    claims = read_claims(log)
    assert claims["location"].text == "Barcelona (CV header)"

    # The step runs and shows the claim, but the candidate never addresses it.
    resolve(store, [], now="2026-08-18T09:00:00Z")
    fields = _written_fields(store)
    assert fields["location"]["state"] == "unknown"


def test_declined_is_distinct_from_unknown(store: ProfileStore) -> None:
    resolve(store, [CandidateTurn(field="reach", action="decline")], now="2026-08-18T09:00:00Z")
    fields = _written_fields(store)
    assert fields["reach"]["state"] == "declined"
    assert fields["languages"]["state"] == "unknown"

    # And the distinction keeps mattering downstream: declined is a resolved
    # non-answer and is not still owed; unknown is.
    loaded = load_constraints({"fields": fields})
    assert "reach" not in loaded.outstanding()
    assert "languages" in loaded.outstanding()


def test_step_runs_with_no_claims_present(tmp_path: Path) -> None:
    """The required-only path — a candidate with no CV, Intake declined — must
    still reach a fully resolved constraint set. This is what broke in PR #16."""
    root = tmp_path / "profiles"
    identity = create_profile(root, "Grace Hopper", handle="grace", language="en")
    no_cv_store = ProfileStore(root, identity.handle)
    log = EvidenceLog(no_cv_store)
    assert log.effective_rows() == []  # nothing from Intake at all
    assert read_claims(log) == {}

    resolve(
        no_cv_store,
        [
            CandidateTurn(
                field="location", action="state",
                value={"country": "PT", "accepts_onsite_in_country": True},
            ),
            CandidateTurn(field="salary", action="decline"),
        ],
        now="2026-08-18T09:00:00Z",
    )
    fields = _written_fields(no_cv_store)
    assert set(fields) == set(CONSTRAINT_FIELD_NAMES)
    assert all(fields[name]["state"] in {"stated", "declined", "unknown"} for name in fields)
    assert sufficiency(ProfileView(no_cv_store)) == "L1"


# --- confirm vs. state --------------------------------------------------------


def test_confirming_a_claim_requires_the_claim_to_exist(store: ProfileStore) -> None:
    """`confirm` means correcting something Intake said; with nothing to
    correct, the caller wanted `state` and the engine says so."""
    with pytest.raises(ConstraintsStepError):
        resolve(
            store,
            [
                CandidateTurn(
                    field="salary", action="confirm", value={"floor": 1, "currency": "EUR"}
                )
            ],
            now="2026-08-18T09:00:00Z",
        )


def test_confirming_a_claim_writes_the_corrected_value(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    log.append(
        recorded_at="2026-08-18T08:00:00Z", step="intake", kind="statement",
        dimensions=["salary"], text="somewhere around 35k, per a listed range",
        source="cv_document",
    )
    resolve(
        store,
        [
            CandidateTurn(
                field="salary", action="confirm",
                value={"floor": 40000, "currency": "EUR"},
                text="actually 40k, not what the CV implied",
            )
        ],
        now="2026-08-18T09:00:00Z",
    )
    fields = _written_fields(store)
    assert fields["salary"]["state"] == "stated"
    assert fields["salary"]["floor"] == 40000


# --- resolution survives a re-entry -------------------------------------------


def test_a_stated_field_survives_a_later_call_with_no_turn_for_it(store: ProfileStore) -> None:
    """A step run again later (§3.5) must not forget what an earlier run
    settled — the file is rebuilt in full every call, from the log."""
    resolve(
        store,
        [CandidateTurn(field="salary", action="state", value={"floor": 40000, "currency": "EUR"})],
        now="2026-08-18T09:00:00Z",
    )
    resolve(store, [CandidateTurn(field="reach", action="decline")], now="2026-08-18T09:05:00Z")
    fields = _written_fields(store)
    assert fields["salary"]["state"] == "stated"
    assert fields["salary"]["floor"] == 40000
    assert fields["reach"]["state"] == "declined"


# --- non-insistence, exercised through this module ----------------------------


def test_a_twice_declined_field_is_not_asked_again(store: ProfileStore) -> None:
    resolve(
        store, [CandidateTurn(field="employment_mode", action="decline")],
        now="2026-08-18T09:00:00Z",
    )
    # One decline is about this step (§5.4) — still open for a different one.
    assert "employment_mode" not in open_fields(store, step="constraints")
    assert "employment_mode" in open_fields(store, step="ranking")

    resolve(
        store, [CandidateTurn(field="employment_mode", action="decline")],
        now="2026-08-18T09:05:00Z", step="ranking",
    )
    # Two declines are about the subject — closed everywhere now.
    assert "employment_mode" not in open_fields(store, step="constraints")
    assert "employment_mode" not in open_fields(store, step="ranking")

    ledger = DeclineLedger(store)
    assert len(ledger.declines("employment_mode")) == 2

    # A third attempt to ask must not pile a spurious third decline on.
    resolve(
        store, [CandidateTurn(field="employment_mode", action="decline")],
        now="2026-08-18T09:10:00Z",
    )
    assert len(ledger.declines("employment_mode")) == 2
    fields = _written_fields(store)
    assert fields["employment_mode"]["state"] == "declined"


def test_the_candidate_reopening_a_declined_field_lets_it_be_stated(store: ProfileStore) -> None:
    resolve(store, [CandidateTurn(field="reach", action="decline")], now="2026-08-18T09:00:00Z")
    resolve(store, [CandidateTurn(field="reach", action="decline")], now="2026-08-18T09:01:00Z")
    assert "reach" not in open_fields(store, step="constraints")

    resolve(
        store, [CandidateTurn(field="reach", action="state", value={"modes": ["remote"]})],
        now="2026-08-18T10:00:00Z",
    )
    fields = _written_fields(store)
    assert fields["reach"]["state"] == "stated"
    assert "reach" in open_fields(store, step="constraints")


# --- shape ---------------------------------------------------------------------


def test_resolving_an_unpinned_field_is_refused(store: ProfileStore) -> None:
    with pytest.raises(ConstraintsStepError):
        resolve(
            store, [CandidateTurn(field="favourite_colour", action="decline")],
            now="2026-08-18T09:00:00Z",
        )


def test_two_turns_for_one_field_in_one_call_is_refused(store: ProfileStore) -> None:
    with pytest.raises(ConstraintsStepError):
        resolve(
            store,
            [
                CandidateTurn(field="salary", action="decline"),
                CandidateTurn(field="salary", action="decline"),
            ],
            now="2026-08-18T09:00:00Z",
        )


def test_a_malformed_stated_value_is_refused_not_written(store: ProfileStore) -> None:
    """`salary` requires `floor` and `currency` when stated (T24) — a turn
    missing them must fail loudly rather than write a field with a hidden gap."""
    with pytest.raises(ConstraintsStepError):
        resolve(
            store, [CandidateTurn(field="salary", action="state", value={"target": 50000})],
            now="2026-08-18T09:00:00Z",
        )


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T41.json"
    measured = write_evidence(evidence)
    assert measured["constraint_field_resolution"] == 1.0
    assert measured["fields_pinned"] == len(CONSTRAINT_FIELD_NAMES)
    assert measured["failures"] == []
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_probe_resolution_exercises_both_openings(tmp_path: Path) -> None:
    result = probe_resolution(tmp_path / "profiles")
    assert result["failures"] == []
    assert result["checks_run"] >= 10
