"""T344 — `offers_presented_for_decision_without_an_employer_brief`, on constructed profiles."""

from __future__ import annotations

from pathlib import Path

from integral.employer_brief import _main, load_brief, presented_without_brief, record_brief
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    load_lifecycle_offer,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import connect_manual
from integral.presentation_log import present
from integral.sourcing_exclusions import Exclusion, record_exclusion

_AT = "2026-10-16T09:00:00Z"


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    return ProfileStore(tmp_path, identity.handle)


def _shown_offer(store: ProfileStore) -> str:
    offer = connect_manual(
        "Backend en Barcelona.", title="Backend", company="Aggregator", language="es"
    )
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    present(store, [offer.id], at=_AT)
    return offer.id


def _brief(store: ProfileStore, offer_id: str, **over: str) -> None:
    fields: dict[str, str] = {
        "real_employer": "Real SL",
        "resolved_via": "apply_link",
        "live_at_source": "true",
        "checked_at": _AT,
        "what_they_do": "logistics software",
        "sector": "logistics",
        "pay": "not published",
        "hires_in_candidate_country": "true",
    }
    fields.update(over)
    record_brief(store, offer_id, **fields)  # type: ignore[arg-type]


def test_a_presented_offer_with_no_brief_is_counted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    assert presented_without_brief(store) == [offer_id]
    _brief(store, offer_id)
    assert presented_without_brief(store) == []


def test_an_offer_never_presented_owes_no_brief(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer = connect_manual("x y z", title="T", company="C", language="es")
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    assert presented_without_brief(store) == []


def test_closed_at_source_is_not_briefed_unless_also_expired(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, live_at_source="false")
    assert presented_without_brief(store) == [offer_id]
    offer, record = load_lifecycle_offer(store, offer_id)
    offer, record = transition(offer, record, "expired", at=_AT, reason="closed at source")
    save_lifecycle_offer(store, offer, record)
    assert presented_without_brief(store) == []


def test_unknown_liveness_still_counts_as_briefed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, live_at_source="unknown")
    assert presented_without_brief(store) == []


def test_an_exclusion_stated_after_the_brief_makes_it_stale(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id)
    record_exclusion(
        store, Exclusion(about="sector:gambling", stated_at_cycle=1, words="no betting")
    )
    assert presented_without_brief(store) == [offer_id]
    _brief(store, offer_id)
    assert presented_without_brief(store) == []
    assert load_brief(store, offer_id).exclusions_compared == ("sector:gambling",)  # type: ignore[union-attr]


def test_the_real_employer_is_compared_not_the_aggregator(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    record_exclusion(store, Exclusion(about="employer:Real", stated_at_cycle=1, words="not them"))
    _brief(store, offer_id)
    brief = load_brief(store, offer_id)
    assert brief is not None and brief.exclusions_tripped == ("employer:Real",)


def test_a_blank_or_corrupt_brief_is_no_brief(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    store.write_json(
        {"offer_id": offer_id, "real_employer": " "}, "offers", "briefs", f"{offer_id}.json"
    )
    assert presented_without_brief(store) == [offer_id]


def test_cli_record_show_missing(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    base = ["--id", "candidate", "--root", str(tmp_path)]
    assert _main(["missing", *base]) == 1
    args = ["record", *base, "--offer", offer_id, "--employer", "Real SL"]
    args += ["--resolved-via", "advert_wording", "--live", "true", "--checked-at", _AT]
    args += ["--what", "x", "--sector", "y", "--pay", "n/a", "--hires", "unknown"]
    assert _main(args) == 0
    assert _main(["show", *base, "--offer", offer_id]) == 0
    assert _main(["missing", *base]) == 0
    assert "Real SL" in capsys.readouterr().out
