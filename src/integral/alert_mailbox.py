"""T247 — a job-alert email is read only with a permission recorded for that read.

A board's emailed recommendations are a second search engine run for this
candidate, and reading them means looking inside a mailbox. The candidate's
browser may be signed in to somebody else's mailbox or to another provider, so
**every read asks, naming the mailbox the screen shows**, and the answer is
recorded. A pointer harvested from an alert (`AlertPointer`) must cite that
record; `refusal` says why one does not hold.

What is stored, per candidate, in `session/mailbox_permissions.jsonl`: the
mailbox address as the screen showed it, the read's id, the session and the
time. No subject line, body, link, sender or address book — a pointer carries a
title and an employer to verify at source, and nothing else from the email.

Permission is per read, never standing: a record names one `read_id` and one
session, and a pointer from another read that cites it is refused. The ids and
the time are minted by the recorder (`python -m integral.alert_mailbox --root R
--handle H grant --mailbox <address>`), not typed by the session. A permission
must be recorded at or before the read.

Out of scope: nothing in the offer path calls `refusal` yet; enforcement rests
on step 7's rule until a task wires it in.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from integral.identity import ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T247.json"
LEDGER_PARTS = ("session", "mailbox_permissions.jsonl")

# A mailbox is named by its address, and the whole string must already be one:
# a display name, "me" or padding inside it is unresolvable and never repaired
# into an identity (the rule `review_reader.resolve_identity` learnt). Pure
# ASCII only: casefolding rewrites some other characters into different ones
# (Kelvin sign, sharp s), which would merge two distinct strings.
_ADDRESS = re.compile(r"[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]+")


class MailboxPermissionError(ValueError):
    """A permission that cannot be recorded."""


class Reason(StrEnum):
    """Why a pointer is refused. Every branch of `refusal` returns one of these."""

    NO_CITE = "no permission is cited: the read was never asked about"
    UNKNOWN = "the cited permission is not on record"
    INVALID_RECORD = "the cited record is not a permission: it identifies no read"
    DUPLICATE = "the permission id is on record twice, so it licenses nothing"
    BLANK_ID = "the pointer names no read or no session"
    OTHER_READ = "the permission was recorded for a different read; it is not standing"
    OTHER_SESSION = "the permission was recorded in a different session"
    MAILBOX_UNRESOLVABLE = "the mailbox is not an ASCII address, so who was asked is unknown"
    OTHER_MAILBOX = "the permission names a different mailbox than the one read"
    READ_TIME_BAD = "the read time is not a timezone-aware timestamp"
    PERMISSION_AFTER_READ = "the permission was recorded after the read"


def resolve_mailbox(shown: str) -> str | None:
    """The mailbox as a comparable identity, or `None` when it is not an ASCII address."""
    text = shown.strip()
    return text.lower() if text.isascii() and _ADDRESS.fullmatch(text) else None


def _moment(text: str) -> datetime | None:
    """A timezone-aware ISO timestamp, or `None`: a naive or unparsable one orders nothing."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


@dataclass(frozen=True)
class MailboxPermission:
    permission_id: str
    read_id: str
    mailbox: str  # as the screen showed it
    session: str
    granted_at: str


@dataclass(frozen=True)
class AlertPointer:
    """One recommendation read from an alert: where to look, never an advert."""

    title: str
    employer: str
    read_id: str
    session: str
    mailbox: str  # the mailbox this read was in, as shown
    permission_id: str | None  # the record the read cites
    read_at: str  # when the read happened


def invalid(permission: MailboxPermission) -> str | None:
    """The one validator: why `permission` identifies no read, or `None`."""
    if resolve_mailbox(permission.mailbox) is None:
        return f"{permission.mailbox!r} is not an ASCII mailbox address shown on screen"
    for name in ("permission_id", "read_id", "session"):
        if not getattr(permission, name).strip():
            return f"a permission with no {name} licenses no read"
    if _moment(permission.granted_at) is None:
        return f"{permission.granted_at!r} is not a timezone-aware timestamp"
    return None


def grant(
    *, permission_id: str, read_id: str, mailbox: str, session: str, granted_at: str
) -> MailboxPermission:
    """The record of one yes, or an error when it would not identify a read."""
    permission = MailboxPermission(permission_id, read_id, mailbox.strip(), session, granted_at)
    if (why := invalid(permission)) is not None:
        raise MailboxPermissionError(why)
    return permission


def load(store: ProfileStore) -> list[MailboxPermission]:
    """The ledger as stored. `refusal` is the one place a row is judged."""
    if not store.exists(*LEDGER_PARTS):
        return []
    return [MailboxPermission(**row) for row in store.read_jsonl(*LEDGER_PARTS)]


def record(store: ProfileStore, permission: MailboxPermission) -> None:
    if (why := invalid(permission)) is not None:
        raise MailboxPermissionError(why)
    if any(p.permission_id == permission.permission_id for p in load(store)):
        raise MailboxPermissionError(f"permission id {permission.permission_id!r} is taken")
    store.append_jsonl(asdict(permission), *LEDGER_PARTS)


def refusal(pointer: AlertPointer, permissions: list[MailboxPermission]) -> Reason | None:
    """Why `pointer` may not be used, or `None` when a permission for its read holds."""
    if not pointer.read_id.strip() or not pointer.session.strip():
        return Reason.BLANK_ID
    if pointer.permission_id is None or not pointer.permission_id.strip():
        return Reason.NO_CITE
    named = [p for p in permissions if p.permission_id == pointer.permission_id]
    if not named:
        return Reason.UNKNOWN
    if len(named) > 1:
        return Reason.DUPLICATE
    held = named[0]
    if invalid(held) is not None:
        return Reason.INVALID_RECORD
    if held.read_id != pointer.read_id:
        return Reason.OTHER_READ
    if held.session != pointer.session:
        return Reason.OTHER_SESSION
    seen = resolve_mailbox(pointer.mailbox)
    if seen is None:
        return Reason.MAILBOX_UNRESOLVABLE
    if seen != resolve_mailbox(held.mailbox):
        return Reason.OTHER_MAILBOX
    read_at = _moment(pointer.read_at)
    if read_at is None:
        return Reason.READ_TIME_BAD
    granted = _moment(held.granted_at)
    if granted is None or granted > read_at:
        return Reason.PERMISSION_AFTER_READ
    return None


# --- T247's gate: a constructed population, refusing cases included ----------

#: Pointers the rule must let through. A zero over fewer is `unmeasured` (-1).
#: arsenal-floor-margin: MINIMUM_PERMITTED_CASES value=2
MINIMUM_PERMITTED_CASES = 2

#: Pointers the rule must stop, each differing from a permitted twin in exactly
#: one dimension and each expected to be refused *for its own reason*: no cite,
#: unknown record, three kinds of invalid record (bad time, no address, naive
#: time), duplicated id, blank id, other read, other session, other mailbox,
#: four unresolvable mailboxes, two bad read times and a permission recorded
#: after the read. Seventeen today.
#: arsenal-floor-margin: MINIMUM_REFUSING_CASES value=17
MINIMUM_REFUSING_CASES = 17

KELVIN = chr(0x212A)  # Kelvin sign: casefolds to ASCII k
_T0 = "2026-10-05T09:00:00+00:00"  # every permission is granted here
_READ = "2026-10-05T09:30:00+00:00"  # the twin's read, after the grant


def _permissions() -> list[MailboxPermission]:
    def mk(pid: str, read: str, box: str, at: str = _T0) -> MailboxPermission:
        return MailboxPermission(pid, read, box, "s1", at)

    return [
        mk("p1", "r1", "a@x.org"),
        mk("p2", "r2", "b@y.net"),
        mk("p3", "r1", "a@x.org", at="never"),  # a row `grant` would refuse
        mk("p5", "r1", "a@x.org"),
        mk("p5", "r1", "a@x.org"),  # the same id on record twice
        mk("p6", "r1", "a person"),  # a mailbox that is no address
        mk("p7", "r1", "a@x.org", at="2026-10-05T09:00:00"),  # a naive grant time
    ]


def _ptr(**kw: str | None) -> AlertPointer:
    base: dict[str, str | None] = {
        "read_id": "r1",
        "mailbox": "a@x.org",
        "permission_id": "p1",
        "session": "s1",
        "read_at": _READ,
    }
    return AlertPointer("Role", "Employer", **{**base, **kw})  # type: ignore[arg-type]


#: (pointer, the reason it must be refused for, or None when it may be used).
#: Verdicts come from the rule's own text: asked for this read, in this session,
#: naming the mailbox that was read, before the read.
_CASES: tuple[tuple[AlertPointer, Reason | None], ...] = (
    (_ptr(), None),
    (_ptr(read_id="r2", mailbox=" B@Y.NET ", permission_id="p2"), None),  # spelled differently
    (_ptr(permission_id=None), Reason.NO_CITE),
    (_ptr(permission_id="p9"), Reason.UNKNOWN),
    (_ptr(permission_id="p3"), Reason.INVALID_RECORD),
    (_ptr(permission_id="p5"), Reason.DUPLICATE),
    (_ptr(permission_id="p6"), Reason.INVALID_RECORD),
    (_ptr(permission_id="p7"), Reason.INVALID_RECORD),
    (_ptr(read_id=""), Reason.BLANK_ID),
    (_ptr(read_id="r2"), Reason.OTHER_READ),  # same mailbox, other read
    (_ptr(session="s2"), Reason.OTHER_SESSION),
    (_ptr(mailbox="other@x.org"), Reason.OTHER_MAILBOX),
    (_ptr(mailbox=""), Reason.MAILBOX_UNRESOLVABLE),
    (_ptr(mailbox="a person"), Reason.MAILBOX_UNRESOLVABLE),
    (_ptr(mailbox=KELVIN + "@x.org"), Reason.MAILBOX_UNRESOLVABLE),  # Kelvin sign, not ASCII K
    (_ptr(mailbox="a@x.org junk"), Reason.MAILBOX_UNRESOLVABLE),  # fullmatch, not a prefix
    (_ptr(read_at="yesterday"), Reason.READ_TIME_BAD),
    (_ptr(read_at="2026-10-05T09:30:00"), Reason.READ_TIME_BAD),  # naive
    (_ptr(read_at="2026-10-05T08:00:00+00:00"), Reason.PERMISSION_AFTER_READ),
)


def measure() -> dict[str, Any]:
    """T247's gate: refusing cases not refused for their own reason, permitted ones refused."""
    permissions = _permissions()
    permitted = [p for p, why in _CASES if why is None]
    refusing = [(p, why) for p, why in _CASES if why is not None]
    enough = len(permitted) >= MINIMUM_PERMITTED_CASES and len(refusing) >= MINIMUM_REFUSING_CASES
    misrefused = sum(refusal(p, permissions) is not why for p, why in refusing)
    wrongly_refused = sum(refusal(p, permissions) is not None for p in permitted)
    # A reason no case expects is a branch the population never reaches.
    unreached = len(set(Reason) - {why for _, why in refusing})
    return {
        "job_alert_emails_read_without_a_recorded_permission": misrefused if enough else -1,
        "permitted_pointers_refused": wrongly_refused if enough else -1,
        "refusal_reasons_without_a_case": unreached if enough else -1,
        "permitted_cases_at_least": MINIMUM_PERMITTED_CASES,
        "refusing_cases_at_least": MINIMUM_REFUSING_CASES,
        "gate_status": "measured" if enough else "unmeasured",
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    return measured


_SUBCOMMANDS = ("grant", "check")


def _cli(argv: list[str]) -> int:
    """`grant` mints the ids and the time and records one yes; `check` judges one pointer."""
    session_default = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    parser = argparse.ArgumentParser(prog="python -m integral.alert_mailbox")
    parser.add_argument("--root", required=True)
    parser.add_argument("--handle", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)
    grant_p = sub.add_parser("grant")
    grant_p.add_argument("--mailbox", required=True, help="the address the screen shows")
    grant_p.add_argument("--session", default=session_default)
    check_p = sub.add_parser("check")
    check_p.add_argument("--read-id", required=True)
    check_p.add_argument("--session", default=session_default)
    check_p.add_argument("--mailbox", required=True)
    check_p.add_argument("--permission-id", default=None)
    check_p.add_argument("--read-at", required=True, help="when the read happened (ISO, zoned)")
    check_p.add_argument("--title", default="")
    check_p.add_argument("--employer", default="")
    args = parser.parse_args(argv)
    try:
        store = ProfileStore(Path(args.root), args.handle)
        store.identity()
    except Exception as exc:  # no such profile: nothing licensed, never "nothing to check"
        print(f"alert_mailbox: no such profile {args.handle!r}: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "grant":
        permission = MailboxPermission(
            f"perm-{uuid.uuid4().hex}",
            f"read-{uuid.uuid4().hex}",
            args.mailbox.strip(),
            args.session,
            datetime.now(UTC).isoformat(),
        )
        try:
            record(store, permission)
        except MailboxPermissionError as exc:
            print(f"alert_mailbox: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(permission)))
        return 0
    pointer = AlertPointer(
        args.title,
        args.employer,
        args.read_id,
        args.session,
        args.mailbox,
        args.permission_id,
        args.read_at,
    )
    why = refusal(pointer, load(store))
    print("ok" if why is None else why.value)
    return 0 if why is None else 1


def _main(argv: list[str]) -> int:
    # evidence mode is only "no argument, or one path"; anything else is argparse's to refuse
    if len(argv) > 2 or (len(argv) == 2 and (argv[1].startswith("-") or argv[1] in _SUBCOMMANDS)):
        return _cli(argv[1:])
    measured = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured))
    if measured["gate_status"] == "unmeasured":
        return 3
    return int(
        bool(measured["job_alert_emails_read_without_a_recorded_permission"])
        or bool(measured["permitted_pointers_refused"])
        or bool(measured["refusal_reasons_without_a_case"])
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
