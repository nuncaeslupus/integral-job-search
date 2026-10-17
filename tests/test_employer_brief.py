"""T344 — `offers_presented_for_decision_without_an_employer_brief`, on constructed profiles."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

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
_EARLIER = "2026-10-16T08:00:00Z"


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    return ProfileStore(tmp_path, identity.handle)


def _shown_offer(store: ProfileStore, text: str = "Backend en Barcelona.") -> str:
    offer = connect_manual(text, title="Backend", company="Aggregator", language="es")
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    present(store, [offer.id], at=_AT)
    return offer.id


def _brief(store: ProfileStore, offer_id: str, **over: str) -> None:
    fields: dict[str, str] = {
        "real_employer": "Real SL",
        "resolved_via": "apply_link",
        "live_at_source": "true",
        "checked_at": _EARLIER,
        "source_posting_url": "https://real.example/job",
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
    args += ["--resolved-via", "advert_wording", "--live", "true", "--checked-at", _EARLIER]
    args += [
        "--source-url",
        "https://real.example/job",
        "--what",
        "x",
        "--sector",
        "y",
        "--pay",
        "n/a",
        "--hires",
        "unknown",
    ]
    assert _main(args) == 0
    assert _main(["show", *base, "--offer", offer_id]) == 0
    assert _main(["missing", *base]) == 0
    assert "Real SL" in capsys.readouterr().out


def _ban(store: ProfileStore) -> None:
    record_exclusion(
        store,
        Exclusion(about="sector:banca", stated_at_cycle=1, words="no banca", terms=("banking",)),
    )


def test_a_brief_whose_sector_trips_an_exclusion_is_not_briefed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ban(store)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, sector="banking", what_they_do="retail banking")
    assert presented_without_brief(store) == [offer_id]


def test_the_sector_is_compared_when_the_advert_ends_in_a_section(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ban(store)
    offer_id = _shown_offer(store, "Backend en Barcelona.\nRequisitos:\n- Python")
    _brief(store, offer_id, sector="banking", what_they_do="retail banking")
    brief = load_brief(store, offer_id)
    assert brief is not None and brief.exclusions_tripped == ("sector:banca",)


def test_a_brief_for_an_employer_that_does_not_hire_here_is_not_briefed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, hires_in_candidate_country="false")
    assert presented_without_brief(store) == [offer_id]


def test_liveness_with_no_source_posting_is_not_checked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    for live in ("true", "unknown"):
        _brief(store, offer_id, live_at_source=live, source_posting_url="")
        assert presented_without_brief(store) == [offer_id]


def test_a_truthful_brief_written_after_the_offer_was_shown_clears_it(tmp_path: Path) -> None:
    # F10: a backlog brief, and the re-check of a stale one, are written after the showing.
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, checked_at="2026-10-16T10:00:00Z")
    assert presented_without_brief(store) == []


def test_a_stale_brief_is_cleared_by_a_truthful_recheck(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id)
    record_exclusion(store, Exclusion(about="sector:gambling", stated_at_cycle=1, words="no"))
    assert presented_without_brief(store) == [offer_id]
    _brief(store, offer_id, checked_at="2026-10-16T11:00:00Z")
    assert presented_without_brief(store) == []


def test_a_brief_dated_after_it_was_written_does_not_clear(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, checked_at="2999-01-01T00:00:00Z")
    assert presented_without_brief(store) == [offer_id]


def test_a_brief_with_no_recorded_at_does_not_clear(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id)
    path = ("offers", "briefs", f"{offer_id}.json")
    data = store.read_json(*path)
    del data["recorded_at"]
    store.write_json(data, *path)
    assert presented_without_brief(store) == [offer_id]


def test_a_recorded_at_in_the_future_does_not_clear(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, checked_at="2999-01-01T00:00:00Z")
    path = ("offers", "briefs", f"{offer_id}.json")
    data = store.read_json(*path)
    data["recorded_at"] = "2999-01-02T00:00:00Z"
    store.write_json(data, *path)
    assert presented_without_brief(store) == [offer_id]


def test_restating_an_exclusion_with_broader_terms_makes_the_brief_stale(tmp_path: Path) -> None:
    # F6: same `about`, so `exclusions_compared` cannot see it; the words are re-compared.
    store = _store(tmp_path)
    record_exclusion(store, Exclusion(about="sector:finance", stated_at_cycle=1, words="no"))
    offer_id = _shown_offer(store)
    _brief(store, offer_id, sector="banca", what_they_do="una caja")
    assert presented_without_brief(store) == []
    record_exclusion(
        store,
        Exclusion(about="sector:finance", stated_at_cycle=2, words="no", terms=("banca",)),
    )
    assert presented_without_brief(store) == [offer_id]


def test_a_hand_edited_empty_verdict_does_not_clear_a_tripped_offer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _ban(store)
    offer_id = _shown_offer(store)
    _brief(store, offer_id, sector="banking", what_they_do="retail banking")
    path = ("offers", "briefs", f"{offer_id}.json")
    data = store.read_json(*path)
    assert data["exclusions_tripped"] == ["sector:banca"]
    data["exclusions_tripped"] = []
    store.write_json(data, *path)
    assert presented_without_brief(store) == [offer_id]


def test_checked_at_must_be_a_timestamp(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    with pytest.raises(ValidationError):
        _brief(store, offer_id, checked_at="yesterday")


def test_malformed_presentation_rows_are_named_not_crashed_on(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer_id = _shown_offer(store)
    _brief(store, offer_id)
    path = store.path("search", "presentations.jsonl")
    with path.open("a", encoding="utf-8") as f:
        f.write(f'{{"at": "{_AT}", "offer_ids": "abc"}}\n{{"offer_ids": null}}\nnot json\n')
    assert presented_without_brief(store) == [
        "presentations.jsonl line 2: unreadable row",
        "presentations.jsonl line 3: unreadable row",
        "presentations.jsonl line 4: unreadable row",
    ]
