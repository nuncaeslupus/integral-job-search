"""T230 — a stored offer whose `salary.period` is a variant spelling loads, an
unmappable one is refused by name, and one bad record never aborts a loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest

from integral.identity import ProfileStore, create_profile
from integral.offers import (
    UNREADABLE_LOG,
    Offer,
    OfferError,
    Salary,
    SalaryPeriod,
    canonical_period,
    connect_manual,
    load_offer,
    load_offers,
    save_offer,
)
from integral.salary_period import _TABLE, normalize_period
from integral.salary_period_backfill import apply_repairs, scan_profile

MEMBERS: tuple[str, ...] = get_args(SalaryPeriod)


def _store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Fixture", handle="fixture", language="en", fiction=True)
    return ProfileStore(tmp_path, "fixture")


def _raw(text: str, period: Any) -> dict[str, Any]:
    raw = connect_manual(text).model_dump(mode="json")
    raw["salary"] = {"min": 1.0, "max": 2.0, "currency": "EUR", "period": period, "stated": True}
    return raw


def _put(store: ProfileStore, raw: dict[str, Any]) -> str:
    store.write_json(raw, "offers", f"{raw['id']}.json")
    return str(raw["id"])


def _variants(member: str) -> list[str]:
    # derived from the literal, never listed: the member in every case, padded
    return [member, member.upper(), member.title(), f"  {member.upper()} "]


@pytest.mark.parametrize("member", MEMBERS)
def test_every_variant_derived_from_the_literal_loads_as_its_member(
    tmp_path: Path, member: str
) -> None:
    store = _store(tmp_path)
    for i, spelling in enumerate(_variants(member)):
        oid = _put(store, _raw(f"ad {member} {i}", spelling))
        loaded = load_offer(store, oid)
        assert loaded.salary is not None and loaded.salary.period == member, spelling
        assert canonical_period(spelling) == member


def test_the_observed_spellings_load(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for spelling, member in (("YEAR", "year"), ("MONTH", "month"), ("hourly", "hour")):
        oid = _put(store, _raw(f"observed {spelling}", spelling))
        loaded = load_offer(store, oid)
        assert loaded.salary is not None and loaded.salary.period == member


@pytest.mark.parametrize(
    "bad", ["fortnightly", "one-time", "", "yearly-bonus", "per-year", "yea", 5, ["year"]]
)
def test_an_unmappable_period_is_refused_by_name_never_coerced(tmp_path: Path, bad: Any) -> None:
    store = _store(tmp_path)
    oid = _put(store, _raw("unmappable", bad))
    assert canonical_period(bad) is None
    with pytest.raises(OfferError, match=r"unmappable salary\.period"):
        load_offer(store, oid)


def test_a_null_period_still_loads(tmp_path: Path) -> None:
    store = _store(tmp_path)
    offer = connect_manual("plain", salary=Salary(min=1, max=2, period=None, stated=True))
    save_offer(store, offer)
    assert load_offer(store, offer.id).salary == offer.salary


def test_one_bad_record_does_not_abort_a_loop_and_is_recorded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    good = _put(store, _raw("good", "month"))
    variant = _put(store, _raw("variant", "YEAR"))
    bad = _put(store, _raw("bad", "fortnightly"))
    broken = "sha256:" + "0" * 64
    not_a_dict = "sha256:" + "1" * 64
    store.write_text("{not json", "offers", f"{broken}.json")
    store.write_text("[]", "offers", f"{not_a_dict}.json")

    scan = load_offers(store, record=True)

    assert sorted(o.id for o in scan.offers) == sorted([good, variant])
    skipped = {s.offer_id: s.reason for s in scan.skipped}
    assert set(skipped) == {bad, broken, not_a_dict}
    assert "fortnightly" in skipped[bad]
    logged = [json.loads(line) for line in store.read_text("offers", UNREADABLE_LOG).splitlines()]
    assert {row["offer_id"] for row in logged} == set(skipped)
    # the log is never read back as an offer
    assert load_offers(store).skipped == scan.skipped


def test_a_clean_rerun_removes_a_stale_unreadable_log(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bad = _put(store, _raw("bad", "fortnightly"))
    assert load_offers(store, record=True).skipped
    assert store.path("offers", UNREADABLE_LOG).exists()
    store.path("offers", f"{bad}.json").unlink()
    assert not load_offers(store, record=True).skipped
    assert not store.path("offers", UNREADABLE_LOG).exists()


def test_save_offer_refuses_a_variant_period_and_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    base = connect_manual("write guard")
    salary = Salary.model_construct(min=1.0, max=2.0, currency="EUR", period="YEAR", stated=True)
    forged = Offer.model_construct(**{**dict(base), "salary": salary})
    with pytest.raises(OfferError, match="refusing to store"):
        save_offer(store, forged)
    assert not store.path("offers", f"{base.id}.json").exists()


def test_the_read_path_and_t170_share_one_vocabulary() -> None:
    # every key of the T170 table, every member variant, and the near-misses:
    # the two functions may never disagree (F1). A wrong entry anywhere in
    # `_TABLE` (`"h": "month"`) still agrees with itself, which is why the
    # meaning is pinned separately by `test_t170_labels_load_as_their_period`.
    spellings = list(_TABLE) + [v for m in MEMBERS for v in [*_variants(m), m + "ly"]]
    spellings += ["yearly-bonus", "fortnightly", "one-time", "", "dayly"]
    for spelling in spellings:
        assert canonical_period(spelling) == normalize_period(spelling), spelling


@pytest.mark.parametrize(
    ("label", "member"),
    [
        ("h", "hour"),
        ("per-year-salary", "year"),
        ("per-month-salary", "month"),
        ("per-week-salary", "week"),
        ("per-day-wage", "day"),
        ("per-hour-wage", "hour"),
    ],
)
def test_t170_labels_load_as_their_period(tmp_path: Path, label: str, member: str) -> None:
    store = _store(tmp_path)
    oid = _put(store, _raw(f"label {label}", label))
    loaded = load_offer(store, oid)
    assert loaded.salary is not None and loaded.salary.period == member


def test_the_backfill_keeps_every_salary_the_read_path_recovers(tmp_path: Path) -> None:
    # F4, a measurement on a constructed store: stored_offers_that_do_not_load
    # and salaries lost by the migration, over spellings from both sources.
    store = _store(tmp_path)
    spellings = [v for m in MEMBERS for v in _variants(m)] + list(_TABLE) + ["hourly", "YEAR"]
    unmappable = _put(store, _raw("unmappable", "fortnightly"))
    ids = {_put(store, _raw(f"spelling {i} {sp}", sp)): sp for i, sp in enumerate(spellings)}
    readable_before = {o.id for o in load_offers(store).offers}
    apply_repairs(store, scan_profile(store))
    after = load_offers(store)
    assert {o.id for o in after.offers} >= set(ids)
    assert readable_before <= {o.id for o in after.offers}
    assert all(o.salary is not None for o in after.offers if o.id in ids)
    assert [s.offer_id for s in after.skipped] in ([], [unmappable])


def test_a_bad_file_of_any_kind_does_not_abort_the_loop(tmp_path: Path) -> None:
    store = _store(tmp_path)
    good = _put(store, _raw("good", "year"))
    offers = store.path("offers")
    (offers / f"sha256:{'2' * 64}.json").write_bytes(b"\xff\xfe{}")
    (offers / f"sha256:{'3' * 64}.json").mkdir()
    (offers / f"sha256:{'4' * 64}.json").write_text("[" * 100000, encoding="utf-8")
    scan = load_offers(store)
    assert [o.id for o in scan.offers] == [good]
    assert {s.offer_id[7] for s in scan.skipped} == {"2", "3", "4"}
    assert all(s.reason for s in scan.skipped)


def test_an_underscore_file_in_offers_is_not_an_offer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_json({"anything": 1}, "offers", "_index.json")
    scan = load_offers(store)
    assert scan.offers == () and scan.skipped == ()
