"""T340 — mark an offer applied, expired or rejected from the conversation.

`python -m integral.applications mark <offer_id> applied|expired|rejected --id <handle>`
does under ONE timestamp what a session did by hand: the §7.1 lifecycle
transition (`lifecycle.transition`, so `ALLOWED_TRANSITIONS` decides) and, for
`applied` and `rejected`, the §5.2 application status. `expired` has no
application status — an expired advert was never sent.

What is guaranteed: every refusal (a transition the table forbids, a bad `--at`,
a corrupt or candidate-confirmed application record) happens before the first
write. What is not: an I/O failure part-way through the writes can still split
the files. The application status is written first on purpose, so a retry of the
same command repairs that case; the reverse order would wedge it, because
`applied -> applied` is refused for good. A reason goes through the evidence log
(`capture_offer_decision_reason`, as `feedback.record_decision` does), so
`feedback.orphaned_reasons` stays empty.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import cast

from integral.identity import IdentityError, ProfileLeak, ProfileStore
from integral.lifecycle import (
    LifecycleError,
    _parse_at,
    load_lifecycle_offer,
    read_application_status,
    record_application_status,
    save_lifecycle_offer,
)
from integral.offers import OfferError, OfferStatus
from integral.profile import ProfileError
from integral.profile_capture import capture_offer_decision_reason
from integral.state_home import StateHomeRefused, ensure_outside_a_work_tree, profiles_root

# offer status -> application status written beside it (§5.2 has no "expired").
MARKS: dict[str, str | None] = {"applied": "applied", "expired": None, "rejected": "rejected"}


# Confirmed by the candidate (§5.2); a mark must not overwrite one unasked.
_CONFIRMED = ("hired", "offer_declined")


def _check_at(at: str, since: str) -> None:
    """`at` is ISO-8601 with a timezone and not before the last transition."""
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError(f"--at {at!r} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise LifecycleError(f"--at {at!r} has no timezone (e.g. 2026-10-16T09:30:00+00:00)")
    if parsed < _parse_at(since):
        raise LifecycleError(f"--at {at!r} is earlier than the last transition ({since})")


def mark(
    store: ProfileStore, offer_id: str, to_status: str, *, at: str, reason: str | None
) -> None:
    if to_status not in MARKS:
        raise LifecycleError(f"{to_status!r} is not one of {sorted(MARKS)}")
    offer, record = load_lifecycle_offer(store, offer_id)
    _check_at(at, record.status_changed_at)
    application = MARKS[to_status]
    if application is not None:
        current = read_application_status(store, offer_id)  # corrupt record refuses here
        if current in _CONFIRMED:
            raise LifecycleError(
                f"{offer_id}: the application is already {current!r}, which the candidate "
                "confirmed; it is not overwritten by a mark"
            )
    # The transition is computed first inside the helper, so a refusal writes no row.
    new_offer, new_record, _row = capture_offer_decision_reason(
        store, offer, record, cast(OfferStatus, to_status), at=at, reason=reason
    )
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
    cmd.add_argument("--at", default=None, help="ISO-8601 with timezone; default now (UTC)")
    cmd.add_argument("--reason", default=None)
    args = parser.parse_args(argv)
    at = args.at if args.at is not None else datetime.now(UTC).isoformat(timespec="seconds")
    try:
        root = (
            ensure_outside_a_work_tree(args.input_dir, source="--input-dir")
            if args.input_dir
            else profiles_root()
        )
        store = ProfileStore(root, args.handle)
        store.identity()
        mark(store, args.offer_id, args.status, at=at, reason=args.reason)
    except (
        LifecycleError,
        OfferError,
        StateHomeRefused,
        IdentityError,
        ProfileError,
        ProfileLeak,
    ) as exc:
        print(f"applications: {exc}", file=sys.stderr)
        return 2
    print(f"{args.offer_id}: {args.status} at {at}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli(sys.argv[1:]))
