"""T340 — mark an offer applied, expired or rejected from the conversation.

`python -m integral.applications mark <offer_id> applied|expired|rejected --id <handle>`
does under ONE timestamp what a session did by hand: the §7.1 lifecycle
transition (`lifecycle.transition`, so `ALLOWED_TRANSITIONS` decides) and, for
`applied` and `rejected`, the §5.2 application status. `expired` has no
application status — an expired advert was never sent. Every check that can
refuse runs before the first write, so the two files never disagree.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import cast

from integral.identity import IdentityError, ProfileStore
from integral.lifecycle import (
    LifecycleError,
    load_lifecycle_offer,
    record_application_status,
    save_lifecycle_offer,
    transition,
)
from integral.offers import OfferError, OfferStatus
from integral.profile import ProfileError
from integral.state_home import StateHomeRefused, ensure_outside_a_work_tree, profiles_root

# offer status -> application status written beside it (§5.2 has no "expired").
MARKS: dict[str, str | None] = {"applied": "applied", "expired": None, "rejected": "rejected"}


def mark(
    store: ProfileStore, offer_id: str, to_status: str, *, at: str, reason: str | None
) -> None:
    if to_status not in MARKS:
        raise LifecycleError(f"{to_status!r} is not one of {sorted(MARKS)}")
    offer, record = load_lifecycle_offer(store, offer_id)
    new_offer, new_record = transition(
        offer,
        record,
        cast(OfferStatus, to_status),
        at=at,
        reason=reason,
    )
    # record_application_status refuses (corrupt record) before save_lifecycle_offer writes
    application = MARKS[to_status]
    if application is not None:
        record_application_status(store, offer_id, status=application, at=at)
    save_lifecycle_offer(store, new_offer, new_record)


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integral.applications")
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("mark")
    cmd.add_argument("offer_id")
    cmd.add_argument("status", choices=sorted(MARKS))
    cmd.add_argument("--id", required=True, dest="handle")
    cmd.add_argument("--input-dir", default=None)
    cmd.add_argument("--at", default=None, help="ISO date; default now (UTC)")
    cmd.add_argument("--reason", default=None)
    args = parser.parse_args(argv)
    at = args.at or datetime.now(UTC).isoformat(timespec="seconds")
    try:
        root = (
            ensure_outside_a_work_tree(args.input_dir, source="--input-dir")
            if args.input_dir
            else profiles_root()
        )
        store = ProfileStore(root, args.handle)
        store.identity()
        mark(store, args.offer_id, args.status, at=at, reason=args.reason)
    except (LifecycleError, OfferError, StateHomeRefused, IdentityError, ProfileError) as exc:
        print(f"applications: {exc}", file=sys.stderr)
        return 2
    print(f"{args.offer_id}: {args.status} at {at}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli(sys.argv[1:]))
