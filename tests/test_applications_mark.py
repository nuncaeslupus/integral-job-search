"""T340 — `integral.applications mark`: both files, one timestamp, or nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.applications import _cli
from integral.feedback import orphaned_reasons
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    ALLOWED_TRANSITIONS,
    load_lifecycle_offer,
    read_application_status,
    record_application_status,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import Offer, compute_offer_id
from integral.profile import EvidenceLog

T0 = "2026-01-01T00:00:00+00:00"
AT = "2026-10-16T09:30:00+00:00"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "profiles"
    create_profile(r, "Fixture", handle="fixture", language="en", fiction=True)
    return r


def _offer(root: Path, status: str) -> str:
    store = ProfileStore(root, "fixture")
    text = "ad " + status
    offer = Offer(
        id=compute_offer_id(text),
        source="b",
        url="https://b.example/1",
        title="T",
        company="C",
        text=text,
    )
    record = track_new_offer(offer, at=T0)
    path = {"new": [], "shortlisted": ["shortlisted"], "applied": ["shortlisted", "applied"]}
    for step in path[status]:
        offer, record = transition(offer, record, step, at=T0)  # type: ignore[arg-type]
    save_lifecycle_offer(store, offer, record)
    return offer.id


def _run(root: Path, oid: str, status: str, *extra: str) -> int:
    return _cli(["mark", oid, status, "--id", "fixture", "--input-dir", str(root), *extra])


@pytest.mark.parametrize(
    ("start", "to", "application"),
    [
        ("shortlisted", "applied", "applied"),
        ("shortlisted", "expired", None),
        ("applied", "rejected", "rejected"),
    ],
)
def test_each_allowed_transition_writes_both_files_under_one_timestamp(
    root: Path, start: str, to: str, application: str | None
) -> None:
    oid = _offer(root, start)
    assert _run(root, oid, to, "--at", AT, "--reason", "because") == 0
    store = ProfileStore(root, "fixture")
    offer, record = load_lifecycle_offer(store, oid)
    assert offer.status == to
    assert record.status_changed_at == AT
    assert record.history[-1].at == AT
    assert record.history[-1].reason == "because"
    assert read_application_status(store, oid) == application
    if application:
        assert store.read_json("applications", oid, "status.json")["recorded_at"] == AT


def test_a_refused_transition_writes_nothing(root: Path) -> None:
    oid = _offer(root, "new")  # new -> applied is not in ALLOWED_TRANSITIONS
    assert "applied" not in ALLOWED_TRANSITIONS["new"]
    store = ProfileStore(root, "fixture")
    before = store.read_json("offers", "lifecycle", f"{oid}.json")
    assert _run(root, oid, "applied") != 0
    assert store.read_json("offers", "lifecycle", f"{oid}.json") == before
    assert load_lifecycle_offer(store, oid)[0].status == "new"
    assert read_application_status(store, oid) is None


def test_a_corrupt_application_record_refuses_before_any_write(root: Path) -> None:
    oid = _offer(root, "applied")
    store = ProfileStore(root, "fixture")
    store.write_json({"nonsense": 1}, "applications", oid, "status.json")
    assert _run(root, oid, "rejected") != 0
    assert load_lifecycle_offer(store, oid)[0].status == "applied"


def test_an_unknown_offer_exits_non_zero(root: Path) -> None:
    assert _run(root, "nope", "applied") != 0


def test_a_reason_reaches_the_evidence_log_so_nothing_is_orphaned(root: Path) -> None:
    oid = _offer(root, "applied")
    assert _run(root, oid, "rejected", "--at", AT, "--reason", "they wanted someone senior") == 0
    store = ProfileStore(root, "fixture")
    assert orphaned_reasons(store) == []
    rows = [r for r in EvidenceLog(store).effective_rows() if r.source == "offer_reaction"]
    assert [(r.about.id, r.text) for r in rows if r.about] == [(oid, "they wanted someone senior")]


def test_a_refused_transition_with_a_reason_writes_no_evidence_row(root: Path) -> None:
    oid = _offer(root, "new")
    assert _run(root, oid, "applied", "--reason", "sent it") != 0
    log = EvidenceLog(ProfileStore(root, "fixture"))
    assert [r for r in log.effective_rows() if r.source == "offer_reaction"] == []


@pytest.mark.parametrize(
    "at",
    ["yesterday", "", "2026-10-16", "2026-10-16T09:30:00", "2025-01-01T00:00:00+00:00"],
)
def test_a_bad_at_is_refused_and_writes_nothing(root: Path, at: str) -> None:
    oid = _offer(root, "shortlisted")  # last transition is T0 = 2026-01-01
    store = ProfileStore(root, "fixture")
    before = store.read_json("offers", "lifecycle", f"{oid}.json")
    assert _run(root, oid, "applied", "--at", at) != 0
    assert store.read_json("offers", "lifecycle", f"{oid}.json") == before
    assert read_application_status(store, oid) is None


@pytest.mark.parametrize("confirmed", ["hired", "offer_declined"])
def test_rejected_never_overwrites_a_confirmed_application_status(
    root: Path, confirmed: str
) -> None:
    oid = _offer(root, "applied")
    store = ProfileStore(root, "fixture")
    record_application_status(store, oid, status=confirmed, at=T0, candidate_confirmed=True)
    assert _run(root, oid, "rejected", "--reason", "x") != 0
    assert read_application_status(store, oid) == confirmed
    assert load_lifecycle_offer(store, oid)[0].status == "applied"
    assert orphaned_reasons(store) == []


def test_a_path_escaping_offer_id_exits_2_without_a_traceback(root: Path) -> None:
    assert _run(root, "../../other/x", "applied") == 2


def test_an_unknown_handle_exits_non_zero(root: Path) -> None:
    oid = _offer(root, "shortlisted")
    code = _cli(["mark", oid, "applied", "--id", "nobody", "--input-dir", str(root)])
    assert code != 0
    assert read_application_status(ProfileStore(root, "fixture"), oid) is None
