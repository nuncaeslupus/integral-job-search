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
session, and a pointer from another read that cites it is refused.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from integral.identity import ProfileStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T247.json"
LEDGER_PARTS = ("session", "mailbox_permissions.jsonl")

# A mailbox is named by its address, and the whole string must already be one:
# a display name, "me" or padding inside it is unresolvable and never repaired
# into an identity (the rule `review_reader.resolve_identity` learnt).
_ADDRESS = re.compile(r"[^\s@<>()]+@[^\s@<>()]+\.[^\s@<>()]+")


class MailboxPermissionError(ValueError):
    """A permission that cannot be recorded."""


def resolve_mailbox(shown: str) -> str | None:
    """The mailbox as a comparable identity, or `None` when it is not an address."""
    text = shown.strip()
    return text.casefold() if _ADDRESS.fullmatch(text) else None


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


def grant(
    *, permission_id: str, read_id: str, mailbox: str, session: str, granted_at: str
) -> MailboxPermission:
    """The record of one yes, or an error when it would not identify a read."""
    if resolve_mailbox(mailbox) is None:
        raise MailboxPermissionError(f"{mailbox!r} is not a mailbox address shown on screen")
    for name, value in (
        ("permission_id", permission_id),
        ("read_id", read_id),
        ("session", session),
    ):
        if not value.strip():
            raise MailboxPermissionError(f"a permission with no {name} licenses no read")
    try:
        datetime.fromisoformat(granted_at)
    except ValueError as exc:
        raise MailboxPermissionError(f"{granted_at!r} is not a timestamp") from exc
    return MailboxPermission(permission_id, read_id, mailbox.strip(), session, granted_at)


def record(store: ProfileStore, permission: MailboxPermission) -> None:
    store.append_jsonl(asdict(permission), *LEDGER_PARTS)


def load(store: ProfileStore) -> list[MailboxPermission]:
    if not store.exists(*LEDGER_PARTS):
        return []
    return [MailboxPermission(**row) for row in store.read_jsonl(*LEDGER_PARTS)]


def refusal(pointer: AlertPointer, permissions: list[MailboxPermission]) -> str | None:
    """Why `pointer` may not be used, or `None` when a permission for its read holds."""
    if pointer.permission_id is None:
        return "no permission is cited: the read was never asked about"
    held = next((p for p in permissions if p.permission_id == pointer.permission_id), None)
    if held is None:
        return f"permission {pointer.permission_id!r} is not on record"
    if held.read_id != pointer.read_id or held.session != pointer.session:
        return "the permission was recorded for a different read; permission is not standing"
    seen, asked = resolve_mailbox(pointer.mailbox), resolve_mailbox(held.mailbox)
    if seen is None or asked is None:
        return "the mailbox is not an address, so who was asked cannot be shown"
    if seen != asked:
        return "the permission names a different mailbox than the one read"
    return None


# --- T247's gate: a constructed population, refusing cases included ----------

#: Pointers the rule must let through. A zero over fewer is `unmeasured` (-1).
#: arsenal-floor-margin: MINIMUM_PERMITTED_CASES value=2
MINIMUM_PERMITTED_CASES = 2

#: Pointers the rule must stop: no record, an unknown record, another mailbox,
#: another read, another session, a blank and a non-address mailbox. Seven today.
#: arsenal-floor-margin: MINIMUM_REFUSING_CASES value=7
MINIMUM_REFUSING_CASES = 7


def _permissions() -> list[MailboxPermission]:
    return [
        grant(
            permission_id="p1",
            read_id="r1",
            mailbox="a@x.org",
            session="s1",
            granted_at="2026-10-05T09:00:00+00:00",
        ),
        grant(
            permission_id="p2",
            read_id="r2",
            mailbox="b@y.net",
            session="s1",
            granted_at="2026-10-05T10:00:00+00:00",
        ),
    ]


def _ptr(read: str, mailbox: str, cite: str | None, session: str = "s1") -> AlertPointer:
    return AlertPointer("Role", "Employer", read, session, mailbox, cite)


#: (pointer, may_be_used). The verdicts are written from the rule's own text:
#: asked for this read, in this session, naming the mailbox that was read.
_CASES: tuple[tuple[AlertPointer, bool], ...] = (
    (_ptr("r1", "a@x.org", "p1"), True),
    (_ptr("r2", " B@Y.NET ", "p2"), True),  # the same mailbox, spelled differently
    (_ptr("r1", "a@x.org", None), False),  # never asked
    (_ptr("r1", "a@x.org", "p9"), False),  # cites a record that does not exist
    (_ptr("r1", "other@x.org", "p1"), False),  # a different mailbox than the one asked
    (_ptr("r2", "b@y.net", "p1"), False),  # a record reused for another read
    (_ptr("r1", "a@x.org", "p1", session="s2"), False),  # a record from another session
    (_ptr("r1", "", "p1"), False),  # blank mailbox
    (_ptr("r1", "a person", "p1"), False),  # not an address
)


def measure() -> dict[str, Any]:
    """T247's gate: pointers a refusing case let through, and permitted ones refused."""
    permissions = _permissions()
    permitted = [p for p, ok in _CASES if ok]
    refusing = [p for p, ok in _CASES if not ok]
    enough = len(permitted) >= MINIMUM_PERMITTED_CASES and len(refusing) >= MINIMUM_REFUSING_CASES
    unlicensed = sum(refusal(p, permissions) is None for p in refusing)
    wrongly_refused = sum(refusal(p, permissions) is not None for p in permitted)
    return {
        "job_alert_emails_read_without_a_recorded_permission": unlicensed if enough else -1,
        "permitted_pointers_refused": wrongly_refused if enough else -1,
        "permitted_cases_at_least": MINIMUM_PERMITTED_CASES,
        "refusing_cases_at_least": MINIMUM_REFUSING_CASES,
        "gate_status": "measured" if enough else "unmeasured",
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    measured = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured))
    if measured["gate_status"] == "unmeasured":
        return 3
    return int(
        bool(measured["job_alert_emails_read_without_a_recorded_permission"])
        or bool(measured["permitted_pointers_refused"])
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
