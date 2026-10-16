"""T340 — `integral.applications mark`: both files, one timestamp, or nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.applications import _cli
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    ALLOWED_TRANSITIONS,
    load_lifecycle_offer,
    read_application_status,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import Offer, compute_offer_id

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
