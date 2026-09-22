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
from integral.offers import Offer
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
    return patched, description


def scan_profile(store: ProfileStore) -> list[tuple[str, dict[str, Any], str]]:
    """Every repairable offer in `store`, read-only, as `(filename, patched, why)`.

    The filename travels with the repair because it is where the repair must
    go back. Writing by `offer.id` instead assumes every legacy filename
    already equals its content id — an assumption about pre-T170 data that the
    rest of this module refuses to make, and one that fails by *duplicating*
    the record: the fixed copy lands at `<id>.json`, the broken original stays
    where it was, and the next run reports the same repair forever.
    """
    offers_dir = store.path("offers")
    if not offers_dir.is_dir():
        return []
    repairs = []
    for path in sorted(offers_dir.glob("*.json")):
        # A half-written record is exactly what a migration over old data is
        # likely to meet, and a decoder exception escaping here would abort
        # the run mid-write — profiles already processed written, profiles
        # after this one silently left broken. `ProfileStore.read_json` has
        # the same rule for the same reason.
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"  skipped unreadable {path.name}: {exc}", file=sys.stderr)
            continue
        result = repair_raw_offer(raw)
        if result is not None:
            patched, description = result
            repairs.append((path.name, patched, description))
    return repairs


def backup_offers_dir(store: ProfileStore) -> Path:
    """Copy `offers/` aside before anything writes to it, and return the copy.

    Nothing prunes these. They sit inside the profile and accumulate one per
    `--apply` run, which is deliberate for a one-shot migration over data with
    no other copy, but it is not self-limiting: a caller that runs this on a
    schedule grows the profile without bound. They are not a retention leak —
    `retraction.plan_deletion` walks the profile directory, so a retracted
    profile takes its backups with it — but nobody deletes them otherwise.
    """
    # The stamp has one-second resolution, and `copytree` refuses an existing
    # destination. A second run inside the same second is not hypothetical:
    # it is what retrying after a partial failure looks like, which is the one
    # moment the backup matters most.
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = store.path(f"offers.pre-t170-backfill.{stamp}")
    suffix = 1
    while backup.exists():
        backup = store.path(f"offers.pre-t170-backfill.{stamp}.{suffix}")
        suffix += 1
    shutil.copytree(store.path("offers"), backup)
    return backup


def apply_repairs(store: ProfileStore, repairs: list[tuple[str, dict[str, Any], str]]) -> None:
    """Write each repair back to the file it came from.

    Through `store.write_json`, not `path.write_text`: the filename came from
    a glob under this store, but routing the write through the store keeps the
    leak guard on the path that actually touches disk.
    """
    for filename, patched, _description in repairs:
        # An assertion at the write boundary, not a filter: the guard in
        # `repair_raw_offer` establishes that `salary.period` was the only
        # error, so a patch that still fails here means `Offer` grew a rule
        # that guard no longer covers. Raising is the right answer then —
        # skipping would write nothing and report success. An earlier draft
        # also re-validated inside `repair_raw_offer`; that copy could not
        # fire (deleting it left every test green) and read as a second
        # protection the suite did not have.
        Offer.model_validate(patched)
        store.write_json(patched, "offers", filename)


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
        for filename, patched, description in repairs:
            print(f"  {filename} ({patched['id']}): {description}")
        if apply:
            backup = backup_offers_dir(store)
            apply_repairs(store, repairs)
            print(f"  backed up offers/ to {backup.name}, wrote {len(repairs)} file(s)")
    if not apply and total_repairs:
        print(f"\n{total_repairs} offer(s) would be repaired — re-run with --apply to write them")
        # Non-zero so a dry run is usable as a check: "is this store migrated?"
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
