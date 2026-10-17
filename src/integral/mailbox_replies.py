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
from integral.applications import mark
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
    TRANSITION_REFUSED = "the lifecycle table forbids the change this reply implies"
    PROPOSED = "a status change is proposed; it is applied only when the candidate confirms"


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


def assess(store: ProfileStore, reply: Reply, permissions: list[am.MailboxPermission]) -> Verdict:
    """Judge one reply. Reads the store, writes nothing."""
    if (why := am.refusal(reply.pointer, permissions)) is not None:
        return Verdict(Outcome.REFUSED, refusal=why)
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
    offer, _record = load_lifecycle_offer(store, offer_id)
    if not can_transition(offer.status, "rejected"):
        return Verdict(Outcome.TRANSITION_REFUSED, offer_id=offer_id, to_status="rejected")
    return Verdict(Outcome.PROPOSED, offer_id=offer_id, to_status="rejected")


def _rows(store: ProfileStore) -> list[dict[str, Any]]:
    if not store.exists(*LEDGER_PARTS):
        return []
    return [dict(row) for row in store.read_jsonl(*LEDGER_PARTS)]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def propose(
    store: ProfileStore, reply: Reply, *, now: str | None = None
) -> tuple[Verdict, str | None]:
    """`assess`, and for a proposal only, one ledger row. Never applies anything."""
    verdict = assess(store, reply, am.load(store))
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
            "at": now or _now(),
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


def confirm(
    store: ProfileStore, proposal_id: str, *, informative_reason: str | None = None
) -> None:
    """Apply a pending proposal, once, after the candidate said yes.

    The change goes through `applications.mark`, which refuses what the
    lifecycle table forbids before writing anything; the ledger row follows, so
    a refused change leaves the proposal pending."""
    row = _pending(store, proposal_id)
    mark(
        store,
        str(row["offer_id"]),
        str(row["to_status"]),
        at=str(row["received_at"]),
        reason=informative_reason,
    )
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
MINIMUM_CASES_MEASURED = 34

_T0 = "2026-10-05T09:00:00+00:00"  # every permission is granted here
_READ = "2026-10-05T09:30:00+00:00"  # the read, after the grant
_RECEIVED = "2026-10-05T08:00:00+00:00"  # the reply's own date, before the read
_SEEDED = "2026-10-01T00:00:00+00:00"  # every lifecycle event is here
_AFTER = "2026-10-06T09:00:00+00:00"  # later than every lifecycle event below


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
    }
    for key in ("acme", "beta", "delta1", "delta2", "epsilon"):
        record_application_status(store, ids[key], status="applied", at=_SEEDED)
    record_application_status(store, ids["gamma"], status="drafted", at=_SEEDED)
    # `zeta` has a lifecycle record but no application on record.
    return ids


def _permissions() -> list[am.MailboxPermission]:
    return [
        am.MailboxPermission("p1", "r1", "a@x.org", "s1", _T0),
        am.MailboxPermission("p2", "r2", "b@y.net", "s1", _T0),
    ]


def _reply(
    kind: ReplyKind = ReplyKind.REJECTION,
    title: str = "Backend Engineer",
    employer: str = "Acme",
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
        _RECEIVED,
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
            title=" backend  ENGINEER ",
            employer="acme",
            read_id="r2",
            mailbox=" B@Y.NET ",
            permission_id="p2",
        ),
        O.PROPOSED,
        None,
        "acme",
    ),
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


def _unpermitted_that_got_through(
    store: ProfileStore, fn: _Assess, permissions: list[am.MailboxPermission]
) -> int:
    """Replies with no valid yes for their read that were not refused outright."""
    return sum(
        fn(store, reply, permissions).outcome is not O.REFUSED
        for reply, outcome, _why, _offer in _CASES
        if outcome is O.REFUSED
    )


def _everything_proposable(
    store: ProfileStore, reply: Reply, permissions: list[am.MailboxPermission]
) -> Verdict:
    """A control that ignores permissions: the metric must read above zero on it."""
    pointer = am.AlertPointer(reply.title, reply.employer, "r1", "s1", "a@x.org", "p1", _READ)
    perfect = Reply(reply.kind, reply.title, reply.employer, reply.received_at, pointer)
    return assess(store, perfect, permissions)


def _evidence_rows(store: ProfileStore) -> int:
    return sum(1 for _ in store.read_jsonl(*EVIDENCE_PARTS)) if store.exists(*EVIDENCE_PARTS) else 0


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
        wrong_verdicts = 0
        unpermitted = 0
        permitted_refused = 0
        proposals: list[str] = []
        for reply, outcome, why, offer in _CASES:
            verdict, proposal_id = propose(store, reply)
            expected_id = ids[offer] if offer else None
            if (verdict.outcome, verdict.refusal, verdict.offer_id) != (outcome, why, expected_id):
                wrong_verdicts += 1
            if outcome is O.REFUSED and verdict.outcome is not O.REFUSED:
                unpermitted += 1
            if outcome is not O.REFUSED and verdict.outcome is O.REFUSED:
                permitted_refused += 1
            if proposal_id is not None:
                proposals.append(proposal_id)
        applied_by_proposing = int(_digest(store) != before)
        expected_proposals = sum(1 for _r, o, _w, _f in _CASES if o is O.PROPOSED)
        stray_rows = abs(len(_rows(store)) - expected_proposals)

        # Controls: the same counters must be able to read above zero.
        control_unpermitted = _unpermitted_that_got_through(
            store, _everything_proposable, permissions
        )
        mark(store, ids["beta"], "rejected", at=_AFTER, reason=None)
        control_digest_moves = int(_digest(store) != before)

        # 2. Follow-ups through the real commands, on the first proposal.
        first, second = proposals[0], proposals[1]
        rows_before = _evidence_rows(store)
        confirm(store, first, informative_reason="they wanted a manager's track record")
        offer_after, _rec = load_lifecycle_offer(store, ids["acme"])
        confirmed_applied = int(
            offer_after.status == "rejected"
            and read_application_status(store, ids["acme"]) == "rejected"
        )
        informative_recorded = _evidence_rows(store) - rows_before
        try:
            confirm(store, first)
            second_confirm_refused = 0
        except ProposalError:
            second_confirm_refused = 1
        digest_before_decline = _digest(store)
        decline(store, second)
        declined_changed = int(_digest(store) != digest_before_decline)
        try:
            confirm(store, second)
            confirm_after_decline_refused = 0
        except ProposalError:
            confirm_after_decline_refused = 1
        try:
            confirm(store, "reply-unknown")
            unknown_refused = 0
        except ProposalError:
            unknown_refused = 1
        # A reply for the offer just rejected no longer proposes anything.
        again = assess(store, _reply(), permissions)
        stale_proposal = int(again.outcome is O.PROPOSED)

    follow_ups = (
        confirmed_applied,
        int(informative_recorded == 1),
        second_confirm_refused,
        1 - declined_changed,
        confirm_after_decline_refused,
        unknown_refused,
        1 - stale_proposal,
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
        "control_unpermitted_reads_that_got_through": control_unpermitted,
        "control_digest_moves_when_a_change_is_applied": control_digest_moves,
        "cases_measured": cases,
        "cases_measured_at_least": MINIMUM_CASES_MEASURED,
        "refusing_cases": sum(1 for _r, o, _w, _f in _CASES if o is O.REFUSED),
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
        and measured["control_unpermitted_reads_that_got_through"] > 0
        and measured["control_digest_moves_when_a_change_is_applied"] > 0
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
