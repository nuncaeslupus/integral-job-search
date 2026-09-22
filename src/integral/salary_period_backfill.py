"""Backfill offers persisted before T170 with an un-normalized `salary.period`.

Before T170, `Salary.period` accepted any string, so a connector's raw board
vocabulary (`"annual"`, `"MONTH"`, `"hourly"`, ...) could reach disk unchanged.
T170 closed `period` to `SalaryPeriod` and made every current construction
site route through `salary_period.normalize_period` — but a record written
before that landed keeps its old, now-invalid value forever: `Offer.model_validate`
raises on it every time the record is read, not just once at write time.

This repairs those records in place: for each offer that fails validation
*only* because of `salary.period`, apply `normalize_period` to the stored raw
value. When it maps cleanly, the period is corrected. When it does not (an
unrecognized label), the whole `salary` object is dropped — mirroring
`connectors.build_offer`'s own rule that a stated-but-unrepresentable period
means no salary at all, rather than a guessed one.

Defaults to a dry run. `--apply` writes, after copying the affected profile's
`offers/` directory to a timestamped sibling backup — this data lives under
`$INTEGRAL_HOME`, outside git, so that copy is the only undo.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from integral.identity import ProfileStore, default_profiles_root, list_identities
from integral.offers import Offer, save_offer
from integral.salary_period import normalize_period


def repair_raw_offer(raw: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """Repair `raw` if it fails validation only on `salary.period`.

    Returns `(patched, description)`, or `None` when there is nothing this
    function should touch — already valid, or invalid for some other reason.
    Callers must leave those files untouched.
    """
    try:
        Offer.model_validate(raw)
        return None
    except ValidationError as exc:
        errors = exc.errors()
    if not errors or any(error["loc"] != ("salary", "period") for error in errors):
        return None
    salary = raw.get("salary")
    if not isinstance(salary, dict):
        return None
    raw_period = salary.get("period")
    normalized = normalize_period(raw_period if isinstance(raw_period, str) else None)
    if normalized is None:
        patched = {**raw, "salary": None}
        description = f"dropped salary (unrepresentable period {raw_period!r})"
    else:
        patched = {**raw, "salary": {**salary, "period": normalized}}
        description = f"normalized period {raw_period!r} -> {normalized!r}"
    try:
        Offer.model_validate(patched)
    except ValidationError:
        return None
    return patched, description


def scan_profile(store: ProfileStore) -> list[tuple[dict[str, Any], str]]:
    """Every repairable offer in `store`, read-only."""
    offers_dir = store.path("offers")
    if not offers_dir.is_dir():
        return []
    repairs = []
    for path in sorted(offers_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = repair_raw_offer(raw)
        if result is not None:
            repairs.append(result)
    return repairs


def backup_offers_dir(store: ProfileStore) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = store.path(f"offers.pre-t170-backfill.{stamp}")
    shutil.copytree(store.path("offers"), backup)
    return backup


def apply_repairs(store: ProfileStore, repairs: list[tuple[dict[str, Any], str]]) -> None:
    for patched, _description in repairs:
        save_offer(store, Offer.model_validate(patched))


def _main(argv: list[str]) -> int:
    """`python -m integral.salary_period_backfill [--apply]`."""
    apply = "--apply" in argv
    root = default_profiles_root()
    total_repairs = 0
    for identity in list_identities(root):
        store = ProfileStore(root, identity.handle)
        repairs = scan_profile(store)
        if not repairs:
            print(f"{identity.handle}: nothing to repair")
            continue
        total_repairs += len(repairs)
        print(f"{identity.handle}: {len(repairs)} offer(s) to repair")
        for patched, description in repairs:
            print(f"  {patched['id']}: {description}")
        if apply:
            backup = backup_offers_dir(store)
            apply_repairs(store, repairs)
            print(f"  backed up offers/ to {backup.name}, wrote {len(repairs)} file(s)")
    if not apply and total_repairs:
        print(f"\n{total_repairs} offer(s) would be repaired — re-run with --apply to write them")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
