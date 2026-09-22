"""Backfill for offers persisted before T170 with a raw `salary.period`.

`Salary.period` is a closed `Literal` (T170) and every current construction
site normalizes before it gets there — see `test_salary_period.py` and
`connectors.build_offer`. What this covers is the record that predates that:
a raw board label already on disk, which fails `Offer.model_validate` on
every read until repaired.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, connect_manual, load_offer, save_offer
from integral.revision import REVISIONED, classify
from integral.salary_period_backfill import (
    _main,
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
    raw = _raw_offer_with_period("fortnightly")  # unrepresentable: would drop salary
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
    assert [patched["id"] for _, patched, _ in repairs] == [broken.id]

    backup = backup_offers_dir(store)
    assert (backup / f"{broken.id}.json").is_file()
    assert json.loads((backup / f"{broken.id}.json").read_text())["salary"]["period"] == "hourly"

    apply_repairs(store, repairs)

    repaired = load_offer(store, broken.id)
    assert repaired.salary is not None
    assert repaired.salary.period == "hour"
    load_offer(store, fine.id)  # the untouched offer still loads


def test_a_repair_goes_back_to_the_file_it_came_from(tmp_path: Path) -> None:
    """Not to `offers/<id>.json`, which is a different file for a legacy name.

    Writing by id assumes every pre-T170 filename already equals its content
    id. When it does not, the failure is silent and permanent: the repaired
    copy lands beside the broken one, `load_offer` finds the good one, and the
    scan keeps reporting the same offer as needing repair on every future run.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)

    broken = connect_manual("Senior Widget Engineer, remote")
    raw = broken.model_dump(mode="json")
    raw["salary"] = {"min": None, "max": 2500.0, "currency": "EUR", "period": "annual"}
    raw["salary"]["stated"] = True
    store.write_json(raw, "offers", "legacy-name.json")

    apply_repairs(store, scan_profile(store))

    offers = sorted(p.name for p in store.path("offers").glob("*.json"))
    assert offers == ["legacy-name.json"], offers
    assert (
        json.loads((store.path("offers") / "legacy-name.json").read_text())["salary"]["period"]
        == "year"
    )
    assert scan_profile(store) == []  # and the migration is actually done


def test_one_unreadable_file_does_not_abort_the_run(tmp_path: Path) -> None:
    """A half-written record is what a migration over old data is likely to
    meet. Letting the decoder exception escape would leave the run half
    applied, with no summary saying which profiles were never reached."""
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)

    raw = _raw_offer_with_period("MONTH")
    store.write_json(raw, "offers", f"{raw['id']}.json")
    store.write_text('{"id": "truncated"', "offers", "half-written.json")

    repairs = scan_profile(store)
    assert [patched["id"] for _, patched, _ in repairs] == [raw["id"]]


def test_a_dry_run_reports_pending_work_in_its_exit_code(tmp_path: Path, monkeypatch: Any) -> None:
    """So `python -m integral.salary_period_backfill` is usable as a check.

    This also pins the ordering `--apply` depends on: the backup exists before
    any offer is rewritten. Asserting that by reading `_main` pins nothing.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    raw = _raw_offer_with_period("MONTH")
    store.write_json(raw, "offers", f"{raw['id']}.json")
    monkeypatch.setattr("integral.salary_period_backfill.default_profiles_root", lambda: root)

    assert _main([]) == 1  # pending work, nothing written
    assert json.loads(store.read_text("offers", f"{raw['id']}.json"))["salary"]["period"] == "MONTH"

    assert _main(["--apply"]) == 0
    repaired = load_offer(store, raw["id"]).salary
    assert repaired is not None and repaired.period == "month"

    backups = sorted(p.name for p in store.path("backups").glob("offers.pre-t170.*"))
    assert len(backups) == 1, backups
    backup = store.path("backups", backups[0])
    assert json.loads((backup / f"{raw['id']}.json").read_text())["salary"]["period"] == "MONTH"

    assert _main([]) == 0  # and now it is migrated


def test_the_backup_is_not_mistaken_for_an_artefact_to_regenerate() -> None:
    """A backup is frozen bytes, so `revision` must place it as historical.

    Sited anywhere else in the tree it falls through to `authored`, and
    `revision.refresh` then writes a `.stale.json` sidecar *inside* the backup
    and reports every backed-up offer as one to regenerate — a permanent entry
    per offer in the candidate's staleness report, added by every `--apply`.
    The backed-up bytes survive either way, so nothing here fails loudly; this
    is the test that makes the placement visible.
    """
    assert classify(Path("backups") / "offers.pre-t170.20260922T000000Z" / "x.json") == "historical"
    assert "historical" not in REVISIONED


def test_a_second_backup_in_the_same_second_does_not_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp has one-second resolution and `copytree` refuses an existing path.

    Retrying after a partial failure is exactly when two runs land in the same
    second, and exactly when the backup matters most. Without the suffix loop
    the second call raises `FileExistsError` and the retry cannot start.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    store.write_json(_raw_offer_with_period("MONTH"), "offers", "legacy-name.json")

    monkeypatch.setattr(
        "integral.salary_period_backfill.datetime",
        type("_Frozen", (), {"now": staticmethod(lambda _tz: datetime(2026, 9, 22, tzinfo=UTC))}),
    )
    first = backup_offers_dir(store)
    second = backup_offers_dir(store)
    assert first != second
    assert first.is_dir() and second.is_dir()
