"""T340 — mark an offer applied, expired or rejected from the conversation.

`python -m integral.applications mark <offer_id> applied|expired|rejected --id <handle>`
does under ONE timestamp what a session did by hand: the §7.1 lifecycle
transition (`lifecycle.transition`, so `ALLOWED_TRANSITIONS` decides) and, for
`applied` and `rejected`, the §5.2 application status. `expired` has no
application status — an expired advert was never sent.

`python -m integral.applications known --id <handle> <url>...` answers, for an
advert found outside `source()` (a careers-page scan, an aggregator, a link the
candidate pastes), whether it is already in the store and how far it got. A scan
diffed against the previous scan says what is new on the page, not what is new
to the candidate; this says the second.

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
    advert_identity,
    load_lifecycle_offer,
    read_application_status,
    record_application_status,
    save_lifecycle_offer,
)
from integral.offers import Offer, OfferError, OfferStatus, load_offers
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


def known(store: ProfileStore, urls: list[str]) -> tuple[list[str], list[str]]:
    """Lines for stdout and stderr. Per url: `NEW <url>`, or one line per stored
    copy of that advert (status, application status or `-`, title, company,
    url), matched on `advert_identity`. Every offer file that could not be read
    is named on stderr: an unread file may be the copy that was applied to."""
    scan = load_offers(store)
    by_identity: dict[str, list[Offer]] = {}
    for o in scan.offers:
        key = advert_identity(o.url, o.source)
        if key:
            by_identity.setdefault(key, []).append(o)
    # The found url has no source; its identity is resolved by host, and by
    # each stored source as a fallback, so no source's rule is missed.
    sources = {o.source for o in scan.offers}
    out = []
    for url in urls:
        keys = sorted({k for s in sources if (k := advert_identity(url, s))})
        copies = [o for k in keys for o in by_identity.get(k, [])]
        if not copies:
            out.append(f"NEW {url}")
        for o in copies:
            application = read_application_status(store, o.id) or "-"
            out.append(f"{o.status} {application} | {o.title} | {o.company} | {url}")
    err = [f"UNREADABLE {s.offer_id}: {s.reason}" for s in scan.skipped]
    return out, err


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
    seen = sub.add_parser("known")
    seen.add_argument("urls", nargs="+")
    seen.add_argument("--id", required=True, dest="handle")
    seen.add_argument("--input-dir", default=None)
    args = parser.parse_args(argv)
    at = getattr(args, "at", None)
    if at is None:
        at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        root = (
            ensure_outside_a_work_tree(args.input_dir, source="--input-dir")
            if args.input_dir
            else profiles_root()
        )
        store = ProfileStore(root, args.handle)
        store.identity()
        if args.command == "known":
            out, err = known(store, args.urls)
            print("\n".join(out))
            if err:
                print("\n".join(err), file=sys.stderr)
            return 1 if err else 0
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
