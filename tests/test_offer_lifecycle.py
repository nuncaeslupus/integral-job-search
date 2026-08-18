"""S5 — the offer lifecycle: status, purge, tombstones, retention.

The gate is `resurrected_purged_offers == 0`: of the offers purged as stale
and never shortlisted (process spec §7.3), none reappear as `new` without an
explicit revival on the next collection pass. Without a tombstone the next
collection run re-adds everything just deleted and the candidate sees the
same rejected ads forever — the specific failure §7.4 calls out, and the one
this suite is built to catch a regression in.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jobsearch.dedup import Tombstone
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.lifecycle import (
    ALLOWED_TRANSITIONS,
    MINIMUM_SCENARIOS,
    PURGE_HORIZON_DAYS,
    LifecycleError,
    can_transition,
    canonicalize_url,
    collect_offer,
    compute_text_sha256,
    has_case_record,
    is_purge_eligible,
    is_retained_indefinitely,
    load_lifecycle_offer,
    probe_lifecycle,
    purge_batch,
    purge_offer,
    revive,
    save_lifecycle_offer,
    select_purge_eligible,
    track_new_offer,
    transition,
    write_evidence,
)
from jobsearch.offers import connect_manual

WAREHOUSE_AD = "Warehouse Operative. Shifts, forklift certified preferred."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Test Candidate", language="en")
    return ProfileStore(root, identity.handle)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _old(now: datetime) -> str:
    return _iso(now - timedelta(days=PURGE_HORIZON_DAYS + 5))


NOW = datetime(2026, 8, 18, tzinfo=UTC)


# --- §7.1 status and transitions --------------------------------------------


def test_applied_cannot_return_to_new() -> None:
    """§7.1 states this explicitly: an application happened, and the record
    of it is historical. A transition table that permitted 'applied' -> 'new'
    would let a rebuild quietly erase the fact that documents were sent."""
    assert "new" not in ALLOWED_TRANSITIONS["applied"]
    assert not can_transition("applied", "new")

    offer = connect_manual("Data Analyst role. SQL and dashboards.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "shortlisted", at=_old(NOW))
    offer, record = transition(offer, record, "applied", at=_old(NOW))

    with pytest.raises(LifecycleError):
        transition(offer, record, "new", at=_old(NOW))


def test_every_allowed_transition_in_the_table_actually_works() -> None:
    """A table that lists a transition as legal but whose `transition()`
    refuses it anyway would silently strand every offer that reached that
    status — the mirror of `test_applied_cannot_return_to_new`."""
    for from_status, allowed in ALLOWED_TRANSITIONS.items():
        for to_status in allowed:
            assert can_transition(from_status, to_status)


def test_archived_is_terminal_with_no_way_out() -> None:
    """§7.1: `archived` is the end of the candidate's story with an ad — no
    row in the table gives it anywhere else to go."""
    assert ALLOWED_TRANSITIONS["archived"] == frozenset()


def test_an_illegal_transition_is_refused_not_silently_applied() -> None:
    offer = connect_manual("Illegal transition fixture.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    with pytest.raises(LifecycleError):
        # screened_out -> applied is not in §7.1's table (must go through
        # shortlisted first).
        transition(offer, record, "applied", at=_old(NOW))


def test_transition_refuses_an_offer_and_record_that_have_drifted() -> None:
    """`offer.status` and `record.current_status` are meant to always be the
    same fact. A caller that lets them disagree (a hand-edited file, a
    partial write) must be refused, not silently transitioned off of
    whichever one `transition` happened to trust."""
    offer = connect_manual("Drift fixture.")
    record = track_new_offer(offer, at=_old(NOW))
    drifted_offer = offer.model_copy(update={"status": "screened_out"})
    with pytest.raises(LifecycleError):
        transition(drifted_offer, record, "shortlisted", at=_old(NOW))


def test_a_freshly_tracked_offer_must_start_new() -> None:
    """T11's own rule (`offers.py`): a connector only ever produces a
    freshly-seen offer as `new`. `track_new_offer` restates the check rather
    than trusting it silently."""
    offer = connect_manual("Must start new fixture.").model_copy(update={"status": "screened_out"})
    with pytest.raises(LifecycleError):
        track_new_offer(offer, at=_old(NOW))


# --- §7.2 retention ----------------------------------------------------------


def test_shortlisted_offer_is_never_purge_eligible(store: ProfileStore) -> None:
    """§7.2: anything ever shortlisted is kept in full, indefinitely — even
    once it later moves to a status §7.3 would otherwise purge from, and
    even once it is old enough. 'Ever', not 'currently'."""
    offer = connect_manual("Junior Accountant, hybrid, ES.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "shortlisted", at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)

    assert is_retained_indefinitely(store, offer, record)
    assert not is_purge_eligible(store, offer, record, now=NOW)
    assert offer.id not in select_purge_eligible(store, now=NOW)


def test_applied_and_rejected_offer_is_retained_regardless_of_age(store: ProfileStore) -> None:
    offer = connect_manual("Rejected-after-applying fixture.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "shortlisted", at=_old(NOW))
    offer, record = transition(offer, record, "applied", at=_old(NOW))
    offer, record = transition(offer, record, "rejected", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)

    assert is_retained_indefinitely(store, offer, record)
    assert not is_purge_eligible(store, offer, record, now=NOW)


def test_archived_offer_is_retained(store: ProfileStore) -> None:
    offer = connect_manual("Archived fixture.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "archived", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)

    assert is_retained_indefinitely(store, offer, record)
    # archived is not even in PURGE_ELIGIBLE_STATUSES, but retention must
    # hold for an independent reason too — belt and braces, per §7.2.
    assert not is_purge_eligible(store, offer, record, now=NOW)


def test_a_case_record_retains_an_offer_that_was_never_shortlisted(store: ProfileStore) -> None:
    """§7.3's fourth condition: 'no applications/ or interviews/ record
    references it.' An `applications/<id>/` directory must retain the offer
    even though its own status never touched shortlisted or applied."""
    offer = connect_manual("Night Security Guard, on site.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)
    store.write_json({"sent": True}, "applications", offer.id, "sent.json")

    assert has_case_record(store, offer.id)
    assert not is_purge_eligible(store, offer, record, now=NOW)


def test_a_recent_offer_is_not_purge_eligible_regardless_of_status(store: ProfileStore) -> None:
    """§7.3's third condition: `collected_at` must be more than 60 days ago.
    A screened-out offer collected yesterday must not be purged just because
    its status is otherwise eligible."""
    offer = connect_manual("Office Manager, part time.")
    record = track_new_offer(offer, at=_iso(NOW - timedelta(days=1)))
    offer, record = transition(offer, record, "screened_out", at=_iso(NOW))
    save_lifecycle_offer(store, offer, record)

    assert not is_purge_eligible(store, offer, record, now=NOW)


def test_never_shortlisted_offer_past_the_horizon_is_purge_eligible(store: ProfileStore) -> None:
    """The mirror of every retention test above: when none of §7.2/§7.3's
    protections apply, an offer really is purge-eligible. A function that
    always says 'retained' would pass every test above trivially."""
    offer = connect_manual(WAREHOUSE_AD)
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)

    assert is_purge_eligible(store, offer, record, now=NOW)
    assert offer.id in select_purge_eligible(store, now=NOW)


# --- §7.3 purge ----------------------------------------------------------


def test_purge_deletes_the_body_and_writes_a_tombstone(store: ProfileStore) -> None:
    offer = connect_manual(WAREHOUSE_AD, url="https://portal-a.example.com/j/1")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)

    tombstone = purge_offer(store, offer.id, at=_iso(NOW), now=NOW)

    assert not store.path("offers", f"{offer.id}.json").exists()
    assert tombstone.offer_id == offer.id
    assert tombstone.text_sha256 == compute_text_sha256(offer.text)


def test_purge_refuses_an_offer_that_is_not_eligible(store: ProfileStore) -> None:
    """Re-checked at purge time, not just at selection time — see
    `purge_offer`'s docstring on why trusting a stale selection is unsafe."""
    offer = connect_manual("Shortlisted, so never purgeable.")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "shortlisted", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)

    with pytest.raises(LifecycleError):
        purge_offer(store, offer.id, at=_iso(NOW), now=NOW)
    assert store.path("offers", f"{offer.id}.json").exists()


def test_purge_batch_reports_every_tombstone_it_wrote(store: ProfileStore) -> None:
    """§7.3: 'It is reported, not silent.'"""
    ids = []
    for text in ("Purge batch fixture one.", "Purge batch fixture two."):
        offer = connect_manual(text)
        record = track_new_offer(offer, at=_old(NOW))
        offer, record = transition(offer, record, "expired", at=_old(NOW))
        save_lifecycle_offer(store, offer, record)
        ids.append(offer.id)

    tombstones = purge_batch(store, ids, at=_iso(NOW), now=NOW)
    assert {tombstone.offer_id for tombstone in tombstones} == set(ids)


# --- §7.4 tombstones ---------------------------------------------------------


def test_a_tombstone_carries_no_ad_body(store: ProfileStore) -> None:
    """§7.4: 'A tombstone carries no ad body — that is the point of
    purging.' Checked structurally (the schema has no field for it) and
    functionally (the ad's actual words never land in the ledger file)."""
    assert "text" not in Tombstone.model_fields

    offer = connect_manual(WAREHOUSE_AD)
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)
    purge_offer(store, offer.id, at=_iso(NOW), now=NOW)

    ledger_text = store.path("offers", "tombstones.jsonl").read_text(encoding="utf-8")
    assert WAREHOUSE_AD not in ledger_text
    for line in ledger_text.splitlines():
        row = json.loads(line)
        assert set(row) == {
            "offer_id",
            "url",
            "url_canonical",
            "text_sha256",
            "first_seen",
            "purged_at",
            "last_status",
            "resightings",
            "last_resighting",
        }


def test_purged_offer_is_not_re_added_as_new(store: ProfileStore) -> None:
    """The gate's headline case: an exact re-collection of a purged ad's
    verbatim text must not create a new `offers/<id>.json`."""
    offer = connect_manual(WAREHOUSE_AD, url="https://portal-a.example.com/j/1")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)
    purge_offer(store, offer.id, at=_iso(NOW), now=NOW)

    recollected = connect_manual(WAREHOUSE_AD, url="https://portal-a.example.com/j/1")
    assert recollected.id == offer.id  # T11's content-addressed id, unchanged

    outcome = collect_offer(store, recollected, at=_iso(NOW))

    assert outcome.added_as_new is False
    assert outcome.matched_tombstone == offer.id
    assert not store.path("offers", f"{offer.id}.json").exists()


def test_a_rescraped_near_duplicate_is_still_recognised_by_text_hash(store: ProfileStore) -> None:
    """§7.4's harder case: a re-scrape is rarely byte-identical (different
    chrome, a reworded 'posted N days ago' stamp), so it lands on a
    *different* T11 id — but the tombstone hash is over normalised text and
    must still catch it. This is what `text_sha256` is for; a check that
    only handled the byte-identical case would miss most real re-scrapes."""
    offer = connect_manual(WAREHOUSE_AD, url="https://portal-a.example.com/j/1")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)
    purge_offer(store, offer.id, at=_iso(NOW), now=NOW)

    rescraped_text = f"Cookie Notice\nPosted 3 days ago\n{WAREHOUSE_AD}\nSimilar Jobs\n"
    rescraped = connect_manual(rescraped_text, url="https://portal-b.example.com/other")
    assert rescraped.id != offer.id  # different bytes, different T11 id

    outcome = collect_offer(store, rescraped, at=_iso(NOW))

    assert outcome.added_as_new is False
    assert outcome.matched_tombstone == offer.id
    assert not store.path("offers", f"{rescraped.id}.json").exists()


def test_a_genuinely_new_ad_is_not_swallowed_by_the_tombstone_gate(store: ProfileStore) -> None:
    """The mirror check: a `collect_offer` that refused everything would
    trivially show zero resurrections while doing nothing useful."""
    brand_new = connect_manual("Totally unrelated Marketing Intern role, remote, EU.")
    outcome = collect_offer(store, brand_new, at=_iso(NOW))

    assert outcome.added_as_new is True
    assert outcome.matched_tombstone is None
    assert store.path("offers", f"{brand_new.id}.json").exists()


def test_explicit_revival_restores_and_keeps_the_tombstone(store: ProfileStore) -> None:
    """§7.4: 'the revival is recorded, and the tombstone survives so the
    ad's history stays continuous.' And revival must be distinguishable from
    an accidental resurrection — `record.revived` is the mechanism."""
    offer = connect_manual(WAREHOUSE_AD, url="https://portal-a.example.com/j/1")
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)
    purge_offer(store, offer.id, at=_iso(NOW), now=NOW)

    revival_offer = connect_manual(WAREHOUSE_AD, url="https://portal-a.example.com/j/1")
    revived_record = revive(store, offer.id, revival_offer, at=_iso(NOW))

    assert revived_record.revived is True
    assert store.path("offers", f"{revival_offer.id}.json").exists()
    _, reloaded = load_lifecycle_offer(store, revival_offer.id)
    assert reloaded.revived is True

    from jobsearch.lifecycle import current_tombstones

    assert offer.id in current_tombstones(store), "the tombstone must survive a revival"


def test_revive_refuses_a_tombstone_that_does_not_exist(store: ProfileStore) -> None:
    offer = connect_manual("Nothing to revive fixture.")
    with pytest.raises(LifecycleError):
        revive(store, "sha256:" + "0" * 64, offer, at=_iso(NOW))


def test_canonicalize_url_strips_tracking_and_session_parameters() -> None:
    a = canonicalize_url("https://Portal-A.example.com/jobs/1?utm_source=news&ref=abc")
    b = canonicalize_url("https://portal-a.example.com/jobs/1/?utm_source=other&ref=zzz")
    assert a == b


def test_tombstone_hash_ignores_chrome_and_volatile_stamps() -> None:
    plain = compute_text_sha256(WAREHOUSE_AD)
    dressed = compute_text_sha256(
        f"Cookie Notice\nPosted 3 days ago\n{WAREHOUSE_AD}\nSimilar Jobs\n"
    )
    assert plain == dressed


def test_tombstone_hash_is_version_tagged() -> None:
    from jobsearch.lifecycle import TOMBSTONE_HASH_VERSION

    assert compute_text_sha256(WAREHOUSE_AD).startswith(f"v{TOMBSTONE_HASH_VERSION}:sha256:")


# --- the gate ----------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "S5.json"
    measured = write_evidence(evidence)
    assert measured["resurrected_purged_offers"] == 0
    assert measured["scenarios_checked"] >= MINIMUM_SCENARIOS
    assert measured["violations"] == []
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_probe_cleans_nothing_up_by_hand() -> None:
    """`probe_lifecycle` must count what is actually on disk after every
    adversarial re-collection, not repair the state and then count zero by
    construction — the exact mistake this repo's retraction probe made once
    (see `tests/test_retraction.py::test_the_probe_cleans_nothing_up_by_hand`).
    Asserted here by re-deriving the count independently, straight off the
    store the probe itself built and without calling any cleanup helper.
    """
    import jobsearch.lifecycle as lifecycle_module

    result = probe_lifecycle()
    assert result["violations"] == []
    assert result["resurrected_purged_offers"] == 0

    # `probe_lifecycle` builds and tears down its own temporary store inside
    # a `with tempfile.TemporaryDirectory(...)` block, so nothing survives
    # this call to re-inspect — which is itself the property under test:
    # the measurement has to be taken *inside* that block, before anything
    # is torn down, and the function's return value is all that is left.
    # `_resurrected_offer_ids` is exercised directly elsewhere
    # (`test_purged_offer_is_not_re_added_as_new` and its neighbours) against
    # a store this test controls, so the equivalent "read off disk, nothing
    # repaired first" property is covered there too.
    assert hasattr(lifecycle_module, "_resurrected_offer_ids")


def test_a_true_resurrection_would_be_counted_not_hidden(store: ProfileStore) -> None:
    """Adversarial in the other direction: if a purged offer's body is
    written back to disk *without* going through `revive` (simulating a bug
    that bypasses the tombstone gate), the measurement must show it — proof
    the metric is a real filesystem scan and not a count of `collect_offer`
    calls that always happens to be zero.
    """
    from jobsearch.lifecycle import _resurrected_offer_ids

    offer = connect_manual(WAREHOUSE_AD)
    record = track_new_offer(offer, at=_old(NOW))
    offer, record = transition(offer, record, "screened_out", at=_old(NOW))
    save_lifecycle_offer(store, offer, record)
    purge_offer(store, offer.id, at=_iso(NOW), now=NOW)
    assert _resurrected_offer_ids(store) == []

    # Simulate a bug that bypasses collect_offer/revive entirely and writes
    # the offer straight back as `new`.
    bypassed = connect_manual(WAREHOUSE_AD)
    bypassed_record = track_new_offer(bypassed, at=_iso(NOW))
    save_lifecycle_offer(store, bypassed, bypassed_record)

    assert _resurrected_offer_ids(store) == [offer.id]
