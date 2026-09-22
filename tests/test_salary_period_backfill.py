"""Backfill for offers persisted before T170 with a raw `salary.period`.

`Salary.period` is a closed `Literal` (T170) and every current construction
site normalizes before it gets there — see `test_salary_period.py` and
`connectors.build_offer`. What this covers is the record that predates that:
a raw board label already on disk, which fails `Offer.model_validate` on
every read until repaired.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, connect_manual, load_offer, save_offer
from integral.salary_period_backfill import (
    apply_repairs,
    backup_offers_dir,
    repair_raw_offer,
    scan_profile,
)


def _raw_offer_with_period(period: str) -> dict[str, Any]:
    """A valid offer, dumped, with `salary.period` hand-set to a pre-T170
    raw value — `Salary`'s own `Literal` makes constructing it directly
    impossible, which is exactly why the legacy records need this repair."""
    offer = connect_manual("Senior Widget Engineer, remote, EUR 60000-80000/year")
    raw = offer.model_dump(mode="json")
    raw["salary"] = {
        "min": 60000.0,
        "max": 80000.0,
        "currency": "EUR",
        "period": "year",
        "stated": True,
    }
    raw["salary"]["period"] = period
    return raw


def test_a_recognized_raw_period_is_normalized_in_place() -> None:
    raw = _raw_offer_with_period("MONTH")
    result = repair_raw_offer(raw)
    assert result is not None
    patched, description = result
    assert patched["salary"]["period"] == "month"
    assert "MONTH" in description and "month" in description
    Offer.model_validate(patched)  # must not raise


def test_an_unrepresentable_raw_period_drops_the_whole_salary() -> None:
    raw = _raw_offer_with_period("fortnightly")
    result = repair_raw_offer(raw)
    assert result is not None
    patched, description = result
    assert patched["salary"] is None
    assert "dropped" in description
    Offer.model_validate(patched)  # must not raise


def test_an_already_valid_offer_is_left_alone() -> None:
    raw = _raw_offer_with_period("year")
    assert repair_raw_offer(raw) is None


def test_an_unrelated_validation_failure_is_left_alone() -> None:
    raw = _raw_offer_with_period("MONTH")
    raw["text"] = "   "  # a different, unrelated invalidity
    assert repair_raw_offer(raw) is None


def test_a_second_fault_inside_salary_is_left_alone() -> None:
    """The `any(...)` guard is what protects this record, not the re-validation.

    The test above passes with that guard deleted: its second fault is outside
    `salary`, so the patched record still fails `Offer.model_validate` and the
    function returns `None` for the wrong reason — the guard is never the thing
    under test. This is the case that separates them. Both faults are *inside*
    `salary`, and an unrepresentable period drops the whole object, which
    "repairs" the bad `min` as a side effect: the record validates, and a
    stated pay range is silently deleted from a record this module promised to
    leave alone. Only the guard refuses it.
    """
    raw = _raw_offer_with_period("hourly")  # unrepresentable: would drop salary
    raw["salary"]["min"] = "sixty thousand"  # a second fault, inside salary
    assert repair_raw_offer(raw) is None


def test_scan_and_apply_round_trip_through_load_offer(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)

    broken = connect_manual("Senior Widget Engineer, remote")
    raw = broken.model_dump(mode="json")
    raw["salary"] = {
        "min": None,
        "max": 2500.0,
        "currency": "EUR",
        "period": "hourly",
        "stated": True,
    }
    store.write_json(raw, "offers", f"{broken.id}.json")

    fine = connect_manual("Junior Widget Tester, on-site")
    save_offer(store, fine)

    repairs = scan_profile(store)
    assert [patched["id"] for patched, _ in repairs] == [broken.id]

    backup = backup_offers_dir(store)
    assert (backup / f"{broken.id}.json").is_file()
    assert json.loads((backup / f"{broken.id}.json").read_text())["salary"]["period"] == "hourly"

    apply_repairs(store, repairs)

    repaired = load_offer(store, broken.id)
    assert repaired.salary is not None
    assert repaired.salary.period == "hour"
    load_offer(store, fine.id)  # the untouched offer still loads
