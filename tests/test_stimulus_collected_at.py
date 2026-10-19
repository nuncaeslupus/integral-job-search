"""T281: a live stimulus's provenance clock is the lifecycle `collected_at`.

Owner decision 2026-10-19 (option a): `Offer.fetched_at` is never stamped by a
connector (§5.2), so `check_stimulus` reads the lifecycle record instead. Pinned
both ways: a stored offer with a real collection is reactable, one without is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.lifecycle import LifecycleRecord, collect_offer, save_lifecycle_offer
from integral.offers import Offer, compute_offer_id, save_offer
from integral.reaction_elicit import (
    ElicitationError,
    check_stimulus,
    check_stored_stimulus,
)

_AT = "2026-10-01T09:00:00+00:00"
_TEXT = "Buscamos cocinero para restaurante en Girona. " * 12


def _offer(**over: object) -> Offer:
    fields: dict[str, object] = {
        "id": compute_offer_id(_TEXT),
        "source": "remotive",
        "url": "https://remotive.com/ad/1",
        "fetched_at": None,
        "text": _TEXT,
        "status": "new",
    }
    fields.update(over)
    return Offer(**fields)  # type: ignore[arg-type]


def _store(tmp_path: Path) -> ProfileStore:
    handle = create_profile(tmp_path, "Clock Fixture", handle="clock", fiction=True).handle
    return ProfileStore(tmp_path, handle)


def test_fetched_at_none_with_a_lifecycle_collected_at_is_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer = _offer()
    assert offer.fetched_at is None
    collect_offer(store, offer, at=_AT)
    assert check_stored_stimulus(store, offer.id).id == offer.id
    check_stimulus(offer, collected_at=_AT)


def test_no_lifecycle_record_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ElicitationError, match="no lifecycle record"):
        check_stored_stimulus(store, compute_offer_id(_TEXT))
    with pytest.raises(ElicitationError, match="collected_at"):
        check_stimulus(_offer())


def test_a_missing_collected_at_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer = _offer()
    collect_offer(store, offer, at=_AT)
    record = LifecycleRecord.model_validate(
        {**store.read_json("offers", "lifecycle", f"{offer.id}.json"), "collected_at": ""}
    )
    save_lifecycle_offer(store, offer, record)
    with pytest.raises(ElicitationError, match="collected_at"):
        check_stored_stimulus(store, offer.id)
    with pytest.raises(ElicitationError, match="collected_at"):
        check_stimulus(offer, collected_at="")


def test_fetched_at_without_a_lifecycle_record_is_refused(tmp_path: Path) -> None:
    """The old clock no longer counts."""
    store = _store(tmp_path)
    offer = _offer(fetched_at=_AT)
    with pytest.raises(ElicitationError, match="collected_at"):
        check_stimulus(offer)
    save_offer(store, offer)
    with pytest.raises(ElicitationError, match="no lifecycle record"):
        check_stored_stimulus(store, offer.id)
