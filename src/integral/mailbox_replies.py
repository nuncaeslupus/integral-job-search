"""T341 — replies to sent applications, read from the mailbox, propose a status change.

The mailbox half of keeping the applications board true: an acknowledgement, a
rejection, an interview invitation, a portal message. Three rules, each pinned
by `measure()` against the property rather than a proxy for it:

1. **Reading needs a yes for that read.** A reply is judged with
   `alert_mailbox.refusal` (T247's ledger and rule, reused as is): the
   permission names one read, one session and the mailbox the screen showed,
   recorded at or before the read. A yes for read 1 never authorises read 2.
   A refused reply is not even matched against the applications on record.
2. **Nothing is applied by a proposal.** `propose` writes one row into
   `session/reply_proposals.jsonl` and touches no lifecycle or application
   file. Only `confirm <proposal_id>` applies it, once, through T340's
   `applications.mark` (so `ALLOWED_TRANSITIONS` still decides), after the
   candidate said yes. `decline` closes it unapplied.
3. **Only an application on record is matched**, by `lifecycle.posting_key`
   (employer and title, normalised), and only an unambiguous match proposes.
4. **A reply must be provably visible to the read it is credited to.** Its own
   date parses, is not after the read, and the read is not in the future (the
   clock is injected, never supplied by a caller); and a read id is bound to the
   first read time it was used with, so reusing a minted id for a later read is
   refused. Otherwise a second read would run on the first read's yes.
5. **A proposal is made only if confirming it could succeed.** The checks
   `applications.mark` makes (date, a status the candidate confirmed, the
   lifecycle table) are made at propose time, and a second pending proposal for
   one application is refused. `confirm` judges the stored permission again.

What the proposal can be: T340 marks `applied`, `expired` and `rejected`, so a
**rejection** is the one reply that proposes a change. An acknowledgement
changes nothing (the application is already `applied`); an interview
invitation has no mark to propose (step 12 records the interview); **offers or
new terms** in portal mail are routed to the T334 path and never touched here.
On confirming a rejection the candidate is asked whether its reason is
informative; only then is it passed on as `--informative-reason`, which
`mark` stores as a `statement` in the evidence log (a preference input).

Stored: ids, the offer id, the proposed status, the times. Never a subject,
body, sender or link.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from integral import alert_mailbox as am
from integral.applications import _CONFIRMED, _check_at, mark
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    LifecycleError,
    can_transition,
    load_lifecycle_offer,
    posting_key,
    read_application_status,
    record_application_status,
    save_lifecycle_offer,
    stored_posting_keys,
    track_new_offer,
    transition,
)
from integral.offers import Offer, OfferStatus, compute_offer_id
from integral.profile import EVIDENCE_PARTS

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T341.json"
LEDGER_PARTS = ("session", "reply_proposals.jsonl")
READS_PARTS = ("session", "mailbox_reads.jsonl")  # read id -> the first read time it was used with


class ReplyKind(StrEnum):
    ACKNOWLEDGEMENT = "acknowledgement"
    REJECTION = "rejection"
    INTERVIEW_INVITATION = "interview_invitation"
    OFFER_TERMS = "offer_terms"


class Outcome(StrEnum):
    REFUSED = "no yes on record for this read: nothing was matched"
    ROUTED_TO_T334 = "offer or new terms: routed to the T334 path, not handled here"
    UNMATCHED = "no application on record matches this reply"
    AMBIGUOUS = "more than one application on record matches: nothing is proposed"
    NO_CHANGE = "an acknowledgement: the application stays as recorded"
    NO_MARK = "an interview invitation: `applications mark` has no such status; step 12 records it"
    REPLY_DATE_BAD = "the reply's own date is not a timezone-aware timestamp"
    READ_IN_FUTURE = "the read time is later than now: a read that has not happened has no yes"
    REPLY_AFTER_READ = "the reply arrived after the read it cites, so that read cannot have seen it"
    READ_TIME_REBOUND = "this read id was already used for a different read time"
    TRANSITION_REFUSED = "the lifecycle table forbids the change this reply implies"
    BEFORE_LAST_TRANSITION = "the reply is dated before the application's last transition"
    CONFIRMED_BY_CANDIDATE = "the candidate already confirmed this application's status"
    ALREADY_PENDING = "a proposal for this application is already waiting for the candidate"
    PROPOSED = "a status change is proposed; it is applied only when the candidate confirms"


#: The outcomes that mean "this read had no standing for this reply".
REFUSALS = frozenset(
    {
        Outcome.REFUSED,
        Outcome.REPLY_DATE_BAD,
        Outcome.READ_IN_FUTURE,
        Outcome.REPLY_AFTER_READ,
        Outcome.READ_TIME_REBOUND,
    }
)


@dataclass(frozen=True)
class Reply:
    """What was read from one message: a kind and the posting it names, nothing else."""

    kind: ReplyKind
    title: str
    employer: str
    received_at: str
    pointer: am.AlertPointer  # the read it came from, citing its permission


@dataclass(frozen=True)
class Verdict:
    outcome: Outcome
    refusal: am.Reason | None = None
    offer_id: str | None = None
    to_status: str | None = None


def _matches(store: ProfileStore, reply: Reply) -> list[str]:
    key = posting_key(reply.title, reply.employer)
    if key is None:
        return []
    return sorted(
        offer_id
        for offer_id, stored in stored_posting_keys(store).items()
        if stored == key and read_application_status(store, offer_id) is not None
    )


def _bound_read_at(store: ProfileStore, read_id: str) -> str | None:
    if not store.exists(*READS_PARTS):
        return None
    for row in store.read_jsonl(*READS_PARTS):
        if row.get("read_id") == read_id:
            return str(row.get("read_at"))
    return None


def _bind_read(store: ProfileStore, pointer: am.AlertPointer, at: str) -> None:
    """The first use of a read id fixes its read time; later uses must agree."""
    if _bound_read_at(store, pointer.read_id) is None:
        store.append_jsonl(
            {"read_id": pointer.read_id, "read_at": pointer.read_at, "at": at}, *READS_PARTS
        )


def _visibility_refusal(store: ProfileStore, reply: Reply, now: datetime) -> Outcome | None:
    """Why this reply cannot have been seen by the read it cites, or `None`."""
    received = am._moment(reply.received_at)
    read_at = am._moment(reply.pointer.read_at)
    if received is None:
        return Outcome.REPLY_DATE_BAD
    if read_at is None:  # unreachable after `am.refusal`; refused rather than assumed
        return Outcome.REFUSED
    if read_at > now:
        return Outcome.READ_IN_FUTURE
    if received > read_at:
        return Outcome.REPLY_AFTER_READ
    bound = _bound_read_at(store, reply.pointer.read_id)
    if bound is not None and am._moment(bound) != read_at:
        return Outcome.READ_TIME_REBOUND
    return None


def _pending_offers(store: ProfileStore) -> set[str]:
    """Offers with a proposal that nobody has confirmed or declined."""
    states: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(store):
        states.setdefault(str(row.get("proposal_id")), []).append(row)
    return {
        str(rows[0]["offer_id"])
        for rows in states.values()
        if len(rows) == 1 and rows[0].get("state") == "proposed"
    }


def assess(
    store: ProfileStore,
    reply: Reply,
    permissions: list[am.MailboxPermission],
    *,
    now: datetime | None = None,
) -> Verdict:
    """Judge one reply. Reads the store, writes nothing."""
    if (why := am.refusal(reply.pointer, permissions)) is not None:
        return Verdict(Outcome.REFUSED, refusal=why)
    if (hidden := _visibility_refusal(store, reply, now or datetime.now(UTC))) is not None:
        return Verdict(hidden)
    if reply.kind is ReplyKind.OFFER_TERMS:
        return Verdict(Outcome.ROUTED_TO_T334)
    found = _matches(store, reply)
    if not found:
        return Verdict(Outcome.UNMATCHED)
    if len(found) > 1:
        return Verdict(Outcome.AMBIGUOUS)
    offer_id = found[0]
    if reply.kind is ReplyKind.ACKNOWLEDGEMENT:
        return Verdict(Outcome.NO_CHANGE, offer_id=offer_id)
    if reply.kind is ReplyKind.INTERVIEW_INVITATION:
        return Verdict(Outcome.NO_MARK, offer_id=offer_id)
    # Everything `confirm` -> `applications.mark` would refuse is refused here.
    offer, record = load_lifecycle_offer(store, offer_id)
    if not can_transition(offer.status, "rejected"):
        return Verdict(Outcome.TRANSITION_REFUSED, offer_id=offer_id, to_status="rejected")
    if read_application_status(store, offer_id) in _CONFIRMED:
        return Verdict(Outcome.CONFIRMED_BY_CANDIDATE, offer_id=offer_id, to_status="rejected")
    try:
        _check_at(reply.received_at, record.status_changed_at)
    except LifecycleError:
        return Verdict(Outcome.BEFORE_LAST_TRANSITION, offer_id=offer_id, to_status="rejected")
    if offer_id in _pending_offers(store):
        return Verdict(Outcome.ALREADY_PENDING, offer_id=offer_id, to_status="rejected")
    return Verdict(Outcome.PROPOSED, offer_id=offer_id, to_status="rejected")


def _rows(store: ProfileStore) -> list[dict[str, Any]]:
    if not store.exists(*LEDGER_PARTS):
        return []
    return [dict(row) for row in store.read_jsonl(*LEDGER_PARTS)]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def propose(
    store: ProfileStore, reply: Reply, *, now: datetime | None = None
) -> tuple[Verdict, str | None]:
    """`assess`, and for a proposal only, one ledger row. Never applies anything.

    A read that happened under a yes binds its read id to its read time, whether
    or not a proposal follows."""
    clock = now or datetime.now(UTC)
    verdict = assess(store, reply, am.load(store), now=clock)
    # Every read that really happened under a yes is recorded, whatever became of
    # its reply; a read that failed for want of a yes, or lies in the future, is not. Binding a
    # refused read would let a caller with no yes claim any read id first and make the real read
    # of that id READ_TIME_REBOUND; a refused read saw nothing, so it fixes no read time.
    read_at = am._moment(reply.pointer.read_at)
    if verdict.outcome is not Outcome.REFUSED and read_at is not None and read_at <= clock:
        _bind_read(store, reply.pointer, clock.isoformat(timespec="seconds"))
    if verdict.outcome in REFUSALS:
        return verdict, None
    stamp = clock.isoformat(timespec="seconds")
    if verdict.outcome is not Outcome.PROPOSED:
        return verdict, None
    proposal_id = f"reply-{uuid.uuid4().hex}"
    store.append_jsonl(
        {
            "proposal_id": proposal_id,
            "state": "proposed",
            "offer_id": verdict.offer_id,
            "to_status": verdict.to_status,
            "received_at": reply.received_at,
            "permission_id": reply.pointer.permission_id,
            "read_id": reply.pointer.read_id,
            "session": reply.pointer.session,
            "read_at": reply.pointer.read_at,
            "at": stamp,
        },
        *LEDGER_PARTS,
    )
    return verdict, proposal_id


class ProposalError(ValueError):
    """A proposal that cannot be confirmed or declined."""


def _pending(store: ProfileStore, proposal_id: str) -> dict[str, Any]:
    rows = [r for r in _rows(store) if r.get("proposal_id") == proposal_id]
    proposed = [r for r in rows if r.get("state") == "proposed"]
    if len(proposed) != 1:
        raise ProposalError(f"{proposal_id!r} is not a proposal on record")
    if len(rows) > 1:
        raise ProposalError(f"{proposal_id!r} was already decided: {rows[-1].get('state')}")
    return proposed[0]


def _recheck_permission(store: ProfileStore, row: dict[str, Any]) -> am.AlertPointer:
    """The ledger row is not trusted: the permission it cites must still hold for its read."""
    permissions = am.load(store)
    held = [p for p in permissions if p.permission_id == row.get("permission_id")]
    pointer = am.AlertPointer(
        "",
        "",
        str(row.get("read_id") or ""),
        str(row.get("session") or ""),
        held[0].mailbox if len(held) == 1 else "",
        row.get("permission_id"),
        str(row.get("read_at") or ""),
    )
    if (why := am.refusal(pointer, permissions)) is not None:
        raise ProposalError(f"{row.get('proposal_id')!r} no longer has a yes for its read: {why}")
    return pointer


def _recheck_visibility(
    store: ProfileStore, row: dict[str, Any], pointer: am.AlertPointer, now: datetime
) -> None:
    """The reply must still be provably visible to its read, and the read id still bound to it."""
    # `propose` binds the read id before it writes any proposal, so a proposal whose read id has
    # no binding lost it (the reads file was deleted or emptied) and is not trusted on its own row.
    if _bound_read_at(store, pointer.read_id) is None:
        raise ProposalError(
            f"{row.get('proposal_id')!r} is no longer visible to its read: "
            "the read id has no recorded read time"
        )
    stored = Reply(ReplyKind.REJECTION, "", "", str(row.get("received_at") or ""), pointer)
    if (hidden := _visibility_refusal(store, stored, now)) is not None:
        raise ProposalError(
            f"{row.get('proposal_id')!r} is no longer visible to its read: {hidden.value}"
        )


def confirm(
    store: ProfileStore,
    proposal_id: str,
    *,
    informative_reason: str | None = None,
    now: datetime | None = None,
) -> None:
    """Apply a pending proposal, once, after the candidate said yes.

    The change goes through `applications.mark`, which refuses what the
    lifecycle table forbids before writing anything. The stored row is not
    trusted: its permission, the reply's visibility to its read and the read-id
    binding are judged again. A refused confirm marks the proposal `refused`, so
    it no longer blocks later replies for the application."""
    row = _pending(store, proposal_id)
    try:
        pointer = _recheck_permission(store, row)
        _recheck_visibility(store, row, pointer, now or datetime.now(UTC))
        mark(
            store,
            str(row["offer_id"]),
            str(row["to_status"]),
            at=str(row["received_at"]),
            reason=informative_reason,
        )
    except (ValueError, LifecycleError):
        store.append_jsonl(
            {"proposal_id": proposal_id, "state": "refused", "at": _now()}, *LEDGER_PARTS
        )
        raise
    store.append_jsonl(
        {"proposal_id": proposal_id, "state": "confirmed", "at": _now()}, *LEDGER_PARTS
    )


def decline(store: ProfileStore, proposal_id: str) -> None:
    """Close a pending proposal without applying it."""
    _pending(store, proposal_id)
    store.append_jsonl(
        {"proposal_id": proposal_id, "state": "declined", "at": _now()}, *LEDGER_PARTS
    )


# --- T341's gate: a constructed population, refusing cases included -----------

#: Constructed replies and follow-ups the metrics are measured over. A floor:
#: deleting a case makes the gate fail, it cannot silently shrink the denominator.
MINIMUM_CASES_MEASURED = 47

_T0 = "2026-10-05T09:00:00+00:00"  # every permission is granted here
_READ = "2026-10-05T09:30:00+00:00"  # the read, after the grant
_RECEIVED = "2026-10-05T08:00:00+00:00"  # the reply's own date, before the read
_SEEDED = "2026-10-01T00:00:00+00:00"  # every lifecycle event is here
_AFTER = "2026-10-06T09:00:00+00:00"  # later than every lifecycle event below
_LATER_READ = "2026-10-05T10:00:00+00:00"  # a second read time for a read id first used at _READ
_NOW = datetime(2026, 10, 20, tzinfo=UTC)  # the injected clock every constructed case runs on


def _seed_offer(
    store: ProfileStore, title: str, company: str, path: list[OfferStatus], *, source: str = "b"
) -> str:
    text = f"ad {source} {company} {title}"
    offer = Offer(
        id=compute_offer_id(text),
        source=source,
        url=f"https://{source}.example/{company}/{title}".replace(" ", "-"),
        title=title,
        company=company,
        text=text,
    )
    record = track_new_offer(offer, at=_SEEDED)
    for step in path:
        offer, record = transition(offer, record, step, at=_SEEDED)
    save_lifecycle_offer(store, offer, record)
    return offer.id


def _seed(store: ProfileStore) -> dict[str, str]:
    sent: list[OfferStatus] = ["shortlisted", "applied"]
    ids = {
        "acme": _seed_offer(store, "Backend Engineer", "Acme", sent),
        "beta": _seed_offer(store, "Data Analyst", "Beta", sent),
        "gamma": _seed_offer(store, "Designer", "Gamma", ["shortlisted"]),
        "delta1": _seed_offer(store, "Ops Lead", "Delta", sent),
        "delta2": _seed_offer(store, "Ops Lead", "Delta", sent, source="c"),
        "epsilon": _seed_offer(store, "QA Lead", "Epsilon", [*sent, "rejected"]),
        "zeta": _seed_offer(store, "Never Applied", "Zeta", sent),
        "eta": _seed_offer(store, "Support Lead", "Eta", sent),
        "theta": _seed_offer(store, "Site Manager", "Theta", sent),
        "iota": _seed_offer(store, "Chief Analyst", "Iota", sent),
    }
    for key in ("acme", "beta", "delta1", "delta2", "epsilon", "eta", "theta"):
        record_application_status(store, ids[key], status="applied", at=_SEEDED)
    # the candidate confirmed this one is hired; the lifecycle still reads `applied`
    record_application_status(
        store, ids["iota"], status="hired", at=_SEEDED, candidate_confirmed=True
    )
    record_application_status(store, ids["gamma"], status="drafted", at=_SEEDED)
    # `zeta` has a lifecycle record but no application on record.
    return ids


def _permissions() -> list[am.MailboxPermission]:
    return [
        am.MailboxPermission("p1", "r1", "a@x.org", "s1", _T0),
        am.MailboxPermission("p2", "r2", "b@y.net", "s1", _T0),
        am.MailboxPermission("p3", "r3", "a@x.org", "s1", _T0),
    ]


def _reply(
    kind: ReplyKind = ReplyKind.REJECTION,
    title: str = "Backend Engineer",
    employer: str = "Acme",
    received_at: str = _RECEIVED,
    **pointer: str | None,
) -> Reply:
    base: dict[str, str | None] = {
        "read_id": "r1",
        "session": "s1",
        "mailbox": "a@x.org",
        "permission_id": "p1",
        "read_at": _READ,
    }
    merged = {**base, **pointer}
    return Reply(
        kind,
        title,
        employer,
        received_at,
        am.AlertPointer(title, employer, **merged),  # type: ignore[arg-type]
    )


R = ReplyKind
O = Outcome  # noqa: E741
X = am.Reason

#: (reply, expected outcome, expected refusal reason, expected offer key). Verdicts
#: come from the rule's text: asked for this read, in this session, naming the
#: mailbox that was read, before the read; then an application on record, one
#: match, a transition the table allows.
_CASES: tuple[tuple[Reply, Outcome, am.Reason | None, str | None], ...] = (
    # permitted: each its own verdict
    (_reply(), O.PROPOSED, None, "acme"),
    (
        _reply(
            title=" support  LEAD ",
            employer="eta",
            read_id="r2",
            mailbox=" B@Y.NET ",
            permission_id="p2",
        ),
        O.PROPOSED,
        None,
        "eta",
    ),
    (_reply(title="Site Manager", employer="Theta"), O.PROPOSED, None, "theta"),
    (_reply(R.ACKNOWLEDGEMENT, "Data Analyst", "Beta"), O.NO_CHANGE, None, "beta"),
    (_reply(R.INTERVIEW_INVITATION, "Data Analyst", "Beta"), O.NO_MARK, None, "beta"),
    (_reply(R.OFFER_TERMS, "Data Analyst", "Beta"), O.ROUTED_TO_T334, None, None),
    (_reply(R.OFFER_TERMS, "Something New", "Unknown Ltd"), O.ROUTED_TO_T334, None, None),
    (_reply(title="Backend Engineer", employer="Nobody Inc"), O.UNMATCHED, None, None),
    (_reply(title="Backend Engineer (senior)", employer="Acme"), O.UNMATCHED, None, None),
    (_reply(title="", employer="Acme"), O.UNMATCHED, None, None),
    (_reply(title="Never Applied", employer="Zeta"), O.UNMATCHED, None, None),
    (_reply(title="Ops Lead", employer="Delta"), O.AMBIGUOUS, None, None),
    (_reply(title="Designer", employer="Gamma"), O.TRANSITION_REFUSED, None, "gamma"),
    (_reply(title="QA Lead", employer="Epsilon"), O.TRANSITION_REFUSED, None, "epsilon"),
    # permitted and visible, but confirming could not succeed: refused up front
    (_reply(title="Chief Analyst", employer="Iota"), O.CONFIRMED_BY_CANDIDATE, None, "iota"),
    (_reply(received_at="2026-09-01T00:00:00+00:00"), O.BEFORE_LAST_TRANSITION, None, "acme"),
    (_reply(), O.ALREADY_PENDING, None, "acme"),  # the first case's proposal still waits
    # refused: the proposable twin, differing in exactly one permission dimension
    (_reply(permission_id=None), O.REFUSED, X.NO_CITE, None),
    (_reply(permission_id="p9"), O.REFUSED, X.UNKNOWN, None),
    (_reply(read_id="r2"), O.REFUSED, X.OTHER_READ, None),  # p1 was the yes for read 1 only
    (_reply(read_id="r3", permission_id="p2"), O.REFUSED, X.OTHER_READ, None),
    (_reply(read_id=""), O.REFUSED, X.BLANK_ID, None),
    (_reply(session="s2"), O.REFUSED, X.OTHER_SESSION, None),
    (_reply(mailbox="other@x.org"), O.REFUSED, X.OTHER_MAILBOX, None),
    (_reply(mailbox="a person"), O.REFUSED, X.MAILBOX_UNRESOLVABLE, None),
    (_reply(read_at="yesterday"), O.REFUSED, X.READ_TIME_BAD, None),
    (_reply(read_at="2026-10-05T08:30:00+00:00"), O.REFUSED, X.PERMISSION_AFTER_READ, None),
    # permitted for this read, but the reply cannot have been seen by it
    (_reply(received_at="2026-10-12T09:00:00+00:00"), O.REPLY_AFTER_READ, None, None),
    (_reply(received_at="2026-10-05T09:30:01+00:00"), O.REPLY_AFTER_READ, None, None),
    (_reply(received_at="yesterday"), O.REPLY_DATE_BAD, None, None),
    (_reply(received_at="2026-10-05T08:00:00"), O.REPLY_DATE_BAD, None, None),  # no zone
    (
        _reply(read_id="r3", permission_id="p3", read_at="2099-01-01T00:00:00+00:00"),
        O.READ_IN_FUTURE,
        None,
        None,
    ),
    (
        _reply(read_id="r3", permission_id="p3", read_at="2026-12-31T00:00:00+00:00"),
        O.READ_IN_FUTURE,
        None,
        None,
    ),
    (_reply(read_at=_LATER_READ), O.READ_TIME_REBOUND, None, None),  # r1 was first read at _READ
    (_reply(R.ACKNOWLEDGEMENT, read_at=_LATER_READ), O.READ_TIME_REBOUND, None, None),
    # refused whatever the kind: no yes, no routing, no matching
    (_reply(R.OFFER_TERMS, permission_id=None), O.REFUSED, X.NO_CITE, None),
    (_reply(R.ACKNOWLEDGEMENT, permission_id=None), O.REFUSED, X.NO_CITE, None),
    (_reply(R.INTERVIEW_INVITATION, read_id="r2"), O.REFUSED, X.OTHER_READ, None),
    (_reply(title="Nobody", employer="Nobody Inc", permission_id=None), O.REFUSED, X.NO_CITE, None),
)

_Assess = Callable[[ProfileStore, Reply, list[am.MailboxPermission]], Verdict]


def _digest(store: ProfileStore) -> str:
    """Every file of the profile except the session ledgers, as one hash."""
    root = store.path("offers").parent
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if rel.parts[0] == "session":
            continue
        h.update(str(rel).encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _unpermitted_that_got_through(verdicts: list[Verdict]) -> int:
    """Replies whose read had no standing that were not refused outright.

    The one counter: `measure` feeds it the real verdicts for the metric and the
    permission-blind control's verdicts for the control, so a counter that always
    reads zero makes the control read zero too."""
    return sum(
        verdict.outcome not in REFUSALS
        for (_reply_, outcome, _why, _offer), verdict in zip(_CASES, verdicts, strict=True)
        if outcome in REFUSALS
    )


def _everything_proposable(
    store: ProfileStore, reply: Reply, permissions: list[am.MailboxPermission]
) -> Verdict:
    """A control that ignores permissions and visibility: the metric must read above zero on it."""
    pointer = am.AlertPointer(reply.title, reply.employer, "r1", "s1", "a@x.org", "p1", _READ)
    perfect = Reply(reply.kind, reply.title, reply.employer, _RECEIVED, pointer)
    return assess(store, perfect, permissions, now=_NOW)


def _outcomes_without_a_case(cases: tuple[tuple[Reply, Outcome, Any, Any], ...]) -> int:
    """Outcomes no constructed case expects: a branch of `assess` nothing exercises."""
    return len(set(Outcome) - {outcome for _r, outcome, _w, _o in cases})


def _evidence_rows(store: ProfileStore) -> int:
    return sum(1 for _ in store.read_jsonl(*EVIDENCE_PARTS)) if store.exists(*EVIDENCE_PARTS) else 0


def _evidence_rows_added_by(store: ProfileStore, action: Callable[[], object]) -> int:
    """Rows `action` appended to the evidence log: the one counter for a recorded reason."""
    before = _evidence_rows(store)
    action()
    return _evidence_rows(store) - before


def measure() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch) / "profiles"
        create_profile(root, "Fixture", handle="fixture", language="en", fiction=True)
        store = ProfileStore(root, "fixture")
        ids = _seed(store)
        permissions = _permissions()
        for permission in permissions:
            am.record(store, permission)

        # 1. Verdicts, with a digest before and after to see that none applied anything.
        before = _digest(store)
        evidence_before = _evidence_rows(store)
        wrong_verdicts = 0
        permitted_refused = 0
        verdicts: list[Verdict] = []
        proposals: dict[str, str] = {}
        for reply, outcome, why, offer in _CASES:
            verdict, proposal_id = propose(store, reply, now=_NOW)
            verdicts.append(verdict)
            expected_id = ids[offer] if offer else None
            if (verdict.outcome, verdict.refusal, verdict.offer_id) != (outcome, why, expected_id):
                wrong_verdicts += 1
            if outcome not in REFUSALS and verdict.outcome in REFUSALS:
                permitted_refused += 1
            if proposal_id is not None and offer is not None:
                proposals[offer] = proposal_id
        unpermitted = _unpermitted_that_got_through(verdicts)
        applied_by_proposing = int(_digest(store) != before)
        expected_proposals = sum(1 for _r, o, _w, _f in _CASES if o is O.PROPOSED)
        stray_rows = abs(len(_rows(store)) - expected_proposals)
        reasons_by_proposing = _evidence_rows(store) - evidence_before

        # Controls: the same counters must be able to read above zero.
        control_unpermitted = _unpermitted_that_got_through(
            [_everything_proposable(store, reply, permissions) for reply, *_ in _CASES]
        )
        mark(store, ids["beta"], "rejected", at=_AFTER, reason=None)
        control_digest_moves = int(_digest(store) != before)

        # 2. Follow-ups through the real commands. A reason is stored only when the
        # candidate says the rejection's reason is informative, on confirming.
        acme, eta, theta = proposals["acme"], proposals["eta"], proposals["theta"]
        reasons_without_yes = reasons_by_proposing + _evidence_rows_added_by(
            store, lambda: confirm(store, theta)
        )
        informative_recorded = _evidence_rows_added_by(
            store,
            lambda: confirm(store, acme, informative_reason="they wanted a manager's track record"),
        )
        offer_after, _rec = load_lifecycle_offer(store, ids["acme"])
        confirmed_applied = int(
            offer_after.status == "rejected"
            and read_application_status(store, ids["acme"]) == "rejected"
        )
        try:
            confirm(store, acme)
            second_confirm_refused = 0
        except ProposalError:
            second_confirm_refused = 1
        digest_before_decline = _digest(store)
        reasons_without_yes += _evidence_rows_added_by(store, lambda: decline(store, eta))
        declined_changed = int(_digest(store) != digest_before_decline)
        try:
            confirm(store, eta)
            confirm_after_decline_refused = 0
        except ProposalError:
            confirm_after_decline_refused = 1
        try:
            confirm(store, "reply-unknown")
            unknown_refused = 0
        except ProposalError:
            unknown_refused = 1
        # A reply for the offer just rejected no longer proposes anything.
        again = assess(store, _reply(), permissions, now=_NOW)
        stale_proposal = int(again.outcome is O.PROPOSED)
        # A hand-written row that cites no permission is not confirmable.
        store.append_jsonl(
            {
                "proposal_id": "reply-handwritten",
                "state": "proposed",
                "offer_id": ids["zeta"],
                "to_status": "rejected",
                "received_at": _RECEIVED,
                "permission_id": None,
                "read_id": "r1",
            },
            *LEDGER_PARTS,
        )
        try:
            confirm(store, "reply-handwritten")
            handwritten_refused = 0
        except ProposalError:
            handwritten_refused = 1

    follow_ups = (
        confirmed_applied,
        int(informative_recorded == 1),
        second_confirm_refused,
        1 - declined_changed,
        confirm_after_decline_refused,
        unknown_refused,
        1 - stale_proposal,
        handwritten_refused,
    )
    cases = len(_CASES) + len(follow_ups)
    follow_up_failures = len(follow_ups) - sum(follow_ups)
    return {
        "mailbox_reads_without_a_per_read_permission": unpermitted,
        "permitted_replies_refused": permitted_refused,
        "replies_judged_wrongly": wrong_verdicts,
        "status_changes_applied_without_confirmation": applied_by_proposing,
        "proposals_on_record_beyond_the_proposable": stray_rows,
        "confirmation_follow_up_failures": follow_up_failures,
        "reasons_recorded_without_the_candidates_yes": reasons_without_yes,
        "outcomes_without_a_case": _outcomes_without_a_case(_CASES),
        "control_unpermitted_reads_that_got_through": control_unpermitted,
        "control_digest_moves_when_a_change_is_applied": control_digest_moves,
        "control_reason_rows_counted_when_the_candidate_says_yes": informative_recorded,
        "control_outcomes_without_a_case_when_proposals_are_dropped": _outcomes_without_a_case(
            tuple(c for c in _CASES if c[1] is not O.PROPOSED)
        ),
        "cases_measured": cases,
        "cases_measured_at_least": MINIMUM_CASES_MEASURED,
        "refusing_cases": sum(1 for _r, o, _w, _f in _CASES if o in REFUSALS),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def gate_passes(measured: dict[str, Any]) -> bool:
    return bool(
        measured["mailbox_reads_without_a_per_read_permission"] == 0
        and measured["permitted_replies_refused"] == 0
        and measured["replies_judged_wrongly"] == 0
        and measured["status_changes_applied_without_confirmation"] == 0
        and measured["proposals_on_record_beyond_the_proposable"] == 0
        and measured["confirmation_follow_up_failures"] == 0
        and measured["reasons_recorded_without_the_candidates_yes"] == 0
        and measured["outcomes_without_a_case"] == 0
        and measured["control_unpermitted_reads_that_got_through"] > 0
        and measured["control_digest_moves_when_a_change_is_applied"] > 0
        and measured["control_reason_rows_counted_when_the_candidate_says_yes"] > 0
        and measured["control_outcomes_without_a_case_when_proposals_are_dropped"] > 0
        and measured["cases_measured"] >= MINIMUM_CASES_MEASURED
        and measured["refusing_cases"] >= 1
    )


# --- command line --------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    session_default = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    parser = argparse.ArgumentParser(prog="python -m integral.mailbox_replies")
    parser.add_argument("--root", required=True)
    parser.add_argument("--handle", required=True)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose", help="judge one reply read from the mailbox; applies nothing")
    p.add_argument("--kind", required=True, choices=[k.value for k in ReplyKind])
    p.add_argument("--title", required=True)
    p.add_argument("--employer", required=True)
    p.add_argument("--received-at", required=True, help="the reply's date (ISO, zoned)")
    p.add_argument("--read-id", required=True)
    p.add_argument("--session", default=session_default)
    p.add_argument("--mailbox", required=True)
    p.add_argument("--permission-id", default=None)
    p.add_argument("--read-at", required=True)
    c = sub.add_parser("confirm", help="apply a proposal the candidate said yes to")
    c.add_argument("proposal_id")
    c.add_argument("--informative-reason", default=None, help="only if the candidate says it is")
    d = sub.add_parser("decline", help="close a proposal the candidate said no to")
    d.add_argument("proposal_id")
    args = parser.parse_args(argv)
    try:
        store = ProfileStore(Path(args.root), args.handle)
        store.identity()
    except Exception as exc:
        print(f"mailbox_replies: no such profile {args.handle!r}: {exc}", file=sys.stderr)
        return 2
    try:
        if args.cmd == "propose":
            pointer = am.AlertPointer(
                args.title,
                args.employer,
                args.read_id,
                args.session,
                args.mailbox,
                args.permission_id,
                args.read_at,
            )
            reply = Reply(
                ReplyKind(args.kind), args.title, args.employer, args.received_at, pointer
            )
            verdict, proposal_id = propose(store, reply)
            print(
                json.dumps(
                    {
                        **{k: v for k, v in asdict(verdict).items() if v is not None},
                        "outcome": verdict.outcome.name,
                        "meaning": verdict.outcome.value,
                        "refusal": verdict.refusal.value if verdict.refusal else None,
                        "proposal_id": proposal_id,
                        "ask_whether_the_reason_is_informative": proposal_id is not None,
                    }
                )
            )
            return 0 if proposal_id is not None else 1
        if args.cmd == "confirm":
            confirm(store, args.proposal_id, informative_reason=args.informative_reason)
        else:
            decline(store, args.proposal_id)
    except (ProposalError, LifecycleError, am.MailboxPermissionError) as exc:
        print(f"mailbox_replies: {exc}", file=sys.stderr)
        return 2
    print(f"{args.proposal_id}: {'confirmed' if args.cmd == 'confirm' else 'declined'}")
    return 0


def _main(argv: list[str]) -> int:
    if len(argv) > 2 or (len(argv) == 2 and argv[1].startswith("-")):
        return _cli(argv[1:])
    measured = write_evidence(Path(argv[1]) if len(argv) > 1 else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    return 0 if gate_passes(measured) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv))
