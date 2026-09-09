"""The offer lifecycle: status, purge, tombstones, retention (S5).

Ads go stale, and a tool that accumulates them forever becomes unusable
(brief §2.4). Process specification §7 gives four things a shape, and this
module is that shape:

* **§7.1 Status** — seven statuses, one per offer, and the transitions
  between them held as **data** (`ALLOWED_TRANSITIONS`), not scattered `if`s
  spread across every place a status might change. `applied` cannot go back
  to `new`: an application happened, and the record of it is historical.
  `can_transition` and `transition` are the only way a status ever moves, so
  a caller cannot express an illegal move by accident the way it could with a
  bare attribute assignment.

* **§7.2 Retention** — anything ever `shortlisted`, `applied` or `rejected`,
  anything `archived`, and anything with an `applications/` or `interviews/`
  record, is kept in full, indefinitely, regardless of age. These are the ads
  that explain a candidate's own history; deleting them would make that
  history unreconstructable. `is_retained_indefinitely` is the one place this
  rule is evaluated, and `is_purge_eligible` below is built directly on top of
  it rather than re-deriving the same three conditions a second time.

* **§7.3 Purge** — an offer past `PURGE_HORIZON_DAYS` (60, per process spec
  §7.3 — a module constant, not a number spelled out again at each call site)
  that was never shortlisted or applied and carries no case record is
  purge-eligible. Purging deletes the offer body and keeps a tombstone. It is
  reported, not silent: `purge_batch` returns every tombstone it wrote so a
  caller can tell the candidate what was retired.

* **§7.4 Tombstones** — the gate. A purged offer's id, url, canonical url and
  `text_sha256` survive its body; the body does not. That is both the privacy
  property ("purging is a privacy improvement, not a bookkeeping trick") and
  the mechanism that makes re-collection detectable: `collect_offer` is the
  one gate any connector or re-collection pass must go through, and it
  refuses to re-add a tombstoned ad as `new` — matched by `offer_id` (T11's
  content-addressed id, so byte-identical re-collection always lands on the
  same id) or by `dedup.tombstone_match`'s `url_canonical`/`text_sha256`
  (a re-scrape that is not byte-identical but normalises to the same ad).
  `resurrected_purged_offers == 0` (S5's gate, §7.4) counts purged offers that
  reappear as `new` *without* an explicit revival — `revive` is the one path
  that is allowed to do that, and it is a separate, explicitly-named entry
  point (a candidate has to name the tombstone, the same "nothing without a
  name" shape `retraction.delete_profile` uses for its own irreversible
  action) that marks what it created `revived=True`, precisely so an
  accidental resurrection and a deliberate one are never the same fact.

**Ownership boundary, stated once.** T11 (`integral.offers`) owns the `Offer`
schema and `offers/<id>.json`'s file contract — `extra="forbid"`, so nothing
here adds a field to that file. T13 (`integral.dedup`) owns the `Tombstone`
schema and `tombstone_match`; this module is the "seam" T13's docstring
explicitly leaves for S5 — computing `url_canonical` and `text_sha256`,
writing the ledger, and deciding what happens on a match. Status-change
history (`status_changed_at`, an append-only `history` array — §7.1) is data
T11's `Offer` does not carry and this module cannot add to that file without
breaking `extra="forbid"`, so it lives in a companion file,
`offers/lifecycle/<id>.json`, next to T11's `offers/<id>.json`. Every mutating
function here keeps the two in sync (`save_lifecycle_offer`) and every reader
checks them for agreement (`load_lifecycle_offer` raises `LifecycleError` on
drift) rather than trusting one silently. This split — not one merged file —
is the decision the payload leaves open; see the S5 report for why.

**Tombstones are an append-only ledger, current state is folded.** Same rule
`profile.EvidenceLog` and `retraction`'s survivor scan already use for a
log that is never rewritten in place: `offers/tombstones.jsonl` only ever
grows (a purge appends one row, a resighting appends another with the counter
incremented), and `current_tombstones` folds it down to one row per offer id
by taking the latest. This is what lets `resightings` increase over time
without ever mutating a row that already exists on disk.

**T82 — the application status vocabulary (spec §5.2), a second and separate
vocabulary from §7.1's `OfferStatus` above.** `applications/{offer_id}/`
records what was sent and when (T46's `approval.record_sent`) but, until now,
had no vocabulary for what became of it. §5.2 fixes nine statuses, closed,
split Open (`drafted`, `applied`, `interview`, `offer`) and Final (`hired`,
`rejected`, `no_response`, `offer_declined`, `withdrawn`) — a vocabulary's
entire value is in being fixed, so `normalise_application_status` refuses
anything outside it rather than growing to fit a new case. Legacy
space-spellings (`no response`) are tolerated on *read* only: the migration
strategy is tolerance at the boundary, not a rewrite of stored records, so
`record_application_status` always canonicalises before it writes and
`read_application_status` never rewrites the file it just tolerated a legacy
spelling from. `hired` and `offer_declined` are never inferred — accepting or
declining is the candidate's decision, so `record_application_status` refuses
either without an explicit `candidate_confirmed=True`, the same "nothing
without a name" shape `revive` above uses for its own irreversible action.
Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen); T83
records the attribution, not this docstring.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, get_args
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from integral.dedup import Tombstone, load_tombstones, tombstone_match
from integral.identity import IdentityError, ProfileStore, create_profile
from integral.offers import Offer, OfferError, OfferStatus, Strict, connect_manual, load_offer
from integral.offers import save_offer as _save_offer_body

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S5.json"


class LifecycleError(Exception):
    """A transition, a purge, or a revival broke §7's rules."""


# ---------------------------------------------------------------------------
# §7.1 — status and transitions, as data


# Process spec §7.1's table, verbatim. A status absent as a key here has no
# legal way out (only `archived` is meant to be that — see the completeness
# check below, which fails at import time if a status is ever missing).
ALLOWED_TRANSITIONS: dict[OfferStatus, frozenset[OfferStatus]] = {
    "new": frozenset({"screened_out", "shortlisted", "expired", "archived"}),
    "screened_out": frozenset({"shortlisted", "expired", "archived"}),
    "shortlisted": frozenset({"applied", "screened_out", "expired", "archived"}),
    "applied": frozenset({"rejected", "archived"}),
    "rejected": frozenset({"archived"}),
    "expired": frozenset({"archived"}),
    "archived": frozenset(),
}

# §7.1's table names these three terminal. `archived` has no outgoing
# transitions either, but it earns that the same way the other two do — by
# being the end of the candidate's story with this ad, not by construction.
TERMINAL_STATUSES: frozenset[OfferStatus] = frozenset({"rejected", "expired", "archived"})

# A missing or extra status here is a schema defect, not a runtime condition —
# fail at import time, the same fail-fast shape `candidate.py` uses for its
# `_CHECKS`/`FIELD_MODELS` pair.
_ALL_STATUSES: frozenset[OfferStatus] = frozenset(get_args(OfferStatus))
if set(ALLOWED_TRANSITIONS) != _ALL_STATUSES:
    raise LifecycleError(
        "ALLOWED_TRANSITIONS disagrees with offers.OfferStatus on: "
        f"{sorted(_ALL_STATUSES ^ set(ALLOWED_TRANSITIONS))}"
    )


def can_transition(from_status: OfferStatus, to_status: OfferStatus) -> bool:
    """Whether §7.1 permits `from_status -> to_status`."""
    return to_status in ALLOWED_TRANSITIONS[from_status]


# ---------------------------------------------------------------------------
# the lifecycle record — a companion to T11's offers/<id>.json


class TransitionEvent(Strict):
    """One status change, or the initial `new` a fresh collection starts at.

    `from_status` is `None` only for that first event — every later one has a
    real predecessor, because the whole point of an append-only `history` is
    that it can be walked to answer "was this ever shortlisted", not just
    "what is it now".
    """

    from_status: OfferStatus | None
    to_status: OfferStatus
    at: str
    reason: str | None = None


class LifecycleRecord(Strict):
    """§7.1's `status_changed_at` and `history`, kept next to (not inside)
    T11's `Offer` — see the module docstring's ownership-boundary note.

    `collected_at` is stamped here, not read off `Offer.fetched_at`: T11's
    `connect_manual` leaves `fetched_at` `None` unless a caller supplies it
    (§5.2: "a connector may not invent fields"), but §7.3's 60-day purge
    clock needs a value that always exists the moment S5 starts tracking an
    offer. So this module keeps its own clock rather than depending on an
    optional field a connector is free to leave unset.
    """

    offer_id: str
    collected_at: str
    status_changed_at: str
    history: tuple[TransitionEvent, ...]
    # Set only by `revive`. This is the mechanical half of "explicit revival
    # is distinguishable from accidental resurrection" — the gate's probe
    # reads this field back off disk rather than trusting its own bookkeeping
    # of which path it called.
    revived: bool = False

    @property
    def current_status(self) -> OfferStatus:
        """Derived from the last event, never stored twice. A `history` with
        nothing in it cannot happen — every record starts with one event
        (`track_new_offer` / `revive`) — so this is total, not a fallback."""
        return self.history[-1].to_status


def track_new_offer(offer: Offer, *, at: str) -> LifecycleRecord:
    """The lifecycle record for a freshly collected offer.

    Requires `offer.status == "new"` — T11's own rule ("the only value this
    module ever assigns is 'new'", `offers.py`'s module docstring) restated
    as a check here rather than trusted silently, because a record built
    from an offer that starts anywhere else would have a `history` that lies
    about how it got there.
    """
    if offer.status != "new":
        raise LifecycleError(
            f"a freshly collected offer must start 'new' (T11 §5.2); got {offer.status!r}"
        )
    event = TransitionEvent(from_status=None, to_status="new", at=at, reason="collected")
    return LifecycleRecord(
        offer_id=offer.id, collected_at=at, status_changed_at=at, history=(event,)
    )


def transition(
    offer: Offer,
    record: LifecycleRecord,
    to_status: OfferStatus,
    *,
    at: str,
    reason: str | None = None,
) -> tuple[Offer, LifecycleRecord]:
    """Move `offer`/`record` to `to_status`, or refuse (§7.1).

    Both halves are checked for agreement first: `offer.status` and
    `record.current_status` are two numbers that must always be the same
    fact, and a caller that has let them drift (a partial write, a hand-edited
    file) gets a `LifecycleError` here rather than a transition computed off
    whichever one happened to be asked.
    """
    if offer.id != record.offer_id:
        raise LifecycleError(f"offer {offer.id!r} does not match record for {record.offer_id!r}")
    current = record.current_status
    if current != offer.status:
        raise LifecycleError(
            f"{offer.id}: offer.status {offer.status!r} disagrees with the lifecycle "
            f"record's {current!r} — refusing to transition off an inconsistent pair"
        )
    if not can_transition(current, to_status):
        raise LifecycleError(f"{current!r} -> {to_status!r} is not an allowed transition (§7.1)")
    new_offer = offer.model_copy(update={"status": to_status})
    event = TransitionEvent(from_status=current, to_status=to_status, at=at, reason=reason)
    new_record = record.model_copy(
        update={"status_changed_at": at, "history": (*record.history, event)}
    )
    return new_offer, new_record


# ---------------------------------------------------------------------------
# persistence — offers/<id>.json (T11's) + offers/lifecycle/<id>.json (S5's)


def _lifecycle_parts(offer_id: str) -> tuple[str, str, str]:
    return ("offers", "lifecycle", f"{offer_id}.json")


def save_lifecycle_offer(store: ProfileStore, offer: Offer, record: LifecycleRecord) -> None:
    """Write both halves of one offer's record. The only way either is
    written here — nothing in this module calls `offers.save_offer` or
    writes `offers/lifecycle/*.json` on its own."""
    if offer.id != record.offer_id:
        raise LifecycleError(f"offer {offer.id!r} does not match record for {record.offer_id!r}")
    _save_offer_body(store, offer)
    store.write_json(record.model_dump(mode="json"), *_lifecycle_parts(offer.id))


def load_lifecycle_offer(store: ProfileStore, offer_id: str) -> tuple[Offer, LifecycleRecord]:
    """Read both halves back, raising `LifecycleError` if either is missing
    or if they disagree about the current status."""
    offer = load_offer(store, offer_id)
    try:
        raw = store.read_json(*_lifecycle_parts(offer_id))
    except IdentityError as exc:
        raise LifecycleError(f"{offer_id} has no lifecycle record: {exc}") from exc
    try:
        record = LifecycleRecord.model_validate(raw)
    except Exception as exc:
        raise LifecycleError(f"{offer_id}'s lifecycle record is malformed: {exc}") from exc
    if record.current_status != offer.status:
        raise LifecycleError(
            f"{offer_id}: offer.status {offer.status!r} disagrees with the lifecycle "
            f"record's {record.current_status!r}"
        )
    return offer, record


# ---------------------------------------------------------------------------
# §7.2 — retention


def _ever_reached(record: LifecycleRecord, statuses: frozenset[OfferStatus]) -> bool:
    return any(event.to_status in statuses for event in record.history)


# §7.2's three named statuses that retain on their own, regardless of what
# the offer's status is now — "ever", not "currently".
_RETAINED_IF_EVER_REACHED: frozenset[OfferStatus] = frozenset(
    {"shortlisted", "applied", "rejected"}
)


def has_case_record(store: ProfileStore, offer_id: str) -> bool:
    """Whether `applications/<offer_id>/` or `interviews/<offer_id>/` exists.

    That directory-per-offer-id layout is not this module's invention:
    `revision.py`'s `_CLASSES` table already keys `interviews/*/preparation`
    the same way, and `test_retraction.py` writes application evidence at
    `applications/offer-1/sent.json` — this reads the same shape rather than
    introducing a second one.
    """
    return (
        store.path("applications", offer_id).is_dir() or store.path("interviews", offer_id).is_dir()
    )


def is_retained_indefinitely(store: ProfileStore, offer: Offer, record: LifecycleRecord) -> bool:
    """§7.2, all three routes in one place.

    `is_purge_eligible` is built directly on top of this rather than
    re-deriving the same three conditions with the opposite polarity — one
    definition of "kept forever", used both to explain retention and to gate
    purge.
    """
    if offer.status == "archived":
        return True
    if _ever_reached(record, _RETAINED_IF_EVER_REACHED):
        return True
    return has_case_record(store, offer.id)


# ---------------------------------------------------------------------------
# §7.3 — purge


PURGE_HORIZON_DAYS = 60
# process spec §7.3: "`collected_at` is more than 60 days ago". One constant,
# not a number spelled out again at every call site that needs it.

# The three statuses §7.3 allows a purge from. Not `_ALL_STATUSES` minus the
# retained ones — spelled out explicitly so a new status added to §7.1 in the
# future does not silently become purge-eligible by omission.
PURGE_ELIGIBLE_STATUSES: frozenset[OfferStatus] = frozenset({"new", "screened_out", "expired"})


def _parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def is_purge_eligible(
    store: ProfileStore, offer: Offer, record: LifecycleRecord, *, now: datetime
) -> bool:
    """§7.3's four conditions, ANDed. All four must hold, and the retention
    check (three of the four, restated as "not kept forever") is the same
    function `is_retained_indefinitely` uses to explain retention — a single
    source of truth for what "mattered" means, checked from both directions.
    """
    if offer.status not in PURGE_ELIGIBLE_STATUSES:
        return False
    if is_retained_indefinitely(store, offer, record):
        return False
    age = now - _parse_at(record.collected_at)
    return age >= timedelta(days=PURGE_HORIZON_DAYS)


def select_purge_eligible(store: ProfileStore, *, now: datetime) -> list[str]:
    """Every offer id currently eligible for §7.3 purge, in id order.

    A record this module cannot load (a broken pair, a missing companion) is
    skipped rather than raised through: deciding what is wrong with a broken
    record is a different job (`queue_doctor`-style auditing) from selecting
    what is safe to purge, and treating "unreadable" as "eligible" would be
    the more dangerous of the two wrong answers.
    """
    offers_dir = store.path("offers")
    if not offers_dir.is_dir():
        return []
    eligible: list[str] = []
    for path in sorted(offers_dir.glob("*.json")):
        offer_id = path.stem
        try:
            offer, record = load_lifecycle_offer(store, offer_id)
        except (OfferError, LifecycleError):
            continue
        if is_purge_eligible(store, offer, record, now=now):
            eligible.append(offer_id)
    return eligible


# ---------------------------------------------------------------------------
# §7.4 — tombstone-hash normalisation (comparison-only, never touches
# Offer.text — same rule dedup.normalise_for_comparison states for itself)


TOMBSTONE_HASH_VERSION = 1
# process spec §7.4: "It is declared once and versioned — changing it
# invalidates every existing tombstone, so the version travels with the
# hash." The version prefixes every hash this module ever produces
# (`compute_text_sha256`), so a tombstone written under a later rule can
# never accidentally compare equal to one written under this one.

_CHROME_LINE = re.compile(
    r"^\s*("
    r"cookie[s]?\s*(notice|policy|banner)"
    r"|similar jobs|related jobs|you may also like"
    r"|apply now|share this job|back to search results"
    r")\s*$",
    re.IGNORECASE,
)
# §7.4: "strip the source's chrome (navigation, cookie banners, 'similar
# jobs', the application form)". A whole-line match, not a substring one — a
# job ad that happens to *mention* "apply now" mid-sentence is content, not
# chrome; a portal's own boilerplate renders it as its own line.

_VOLATILE_STAMP_PATTERNS = (
    re.compile(
        r"\bposted\s+\d+\s+(day|days|hour|hours|week|weeks|month|months)\s+ago\b", re.IGNORECASE
    ),
    re.compile(r"\bjust\s+posted\b", re.IGNORECASE),
    re.compile(r"\bexpir(?:es|ing)?\s+(?:in\s+)?\d+\s+(day|days|hour|hours)\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+(day|days)\s+left\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+(view|views|applicant|applicants|click|clicks)\b", re.IGNORECASE),
)
# §7.4: "strip volatile stamps ('posted 3 days ago', view counts, expiry
# countdowns)". Each pattern replaces with a single space, not the empty
# string, so two stamps that were the only thing separating two words do not
# fuse them into one token the whitespace-collapse step cannot undo.

_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
        "referer",
        "session_id",
        "sid",
    }
)

_EMBEDDED_URL = re.compile(r"https?://\S+")


def canonicalize_url(url: str) -> str:
    """§7.4: 'sources are normalised — tracking parameters and session ids
    removed'. Lowercases scheme and host, drops a trailing slash, sorts and
    filters the query string, and drops any fragment (job-board session state
    routinely lives there too). Applied identically whether `url` is an
    offer's own `url` field or one found embedded in the ad text.
    """
    parsed = urlsplit(url.strip())
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), ""))


def _strip_chrome(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _CHROME_LINE.match(line.strip()))


def _strip_volatile_stamps(text: str) -> str:
    for pattern in _VOLATILE_STAMP_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def _strip_embedded_url_tracking(text: str) -> str:
    return _EMBEDDED_URL.sub(lambda match: canonicalize_url(match.group(0)), text)


def normalise_ad_text_for_tombstone(text: str) -> str:
    """§7.4's tombstone-hash normalisation, in the order the process spec
    states it: chrome, then volatile stamps, then embedded-URL tracking
    params, then whitespace, then case. Comparison-only — like
    `dedup.normalise_for_comparison`, this never touches a stored
    `Offer.text` (offers.py's module docstring: verbatim, byte-for-byte).
    Deliberately a *different*, more thorough rule than dedup's: that one
    only needs two ads to compare as similar; this one needs the same ad to
    hash identically every time it is seen, which is a stricter promise.
    """
    stripped = _strip_chrome(text)
    stripped = _strip_volatile_stamps(stripped)
    stripped = _strip_embedded_url_tracking(stripped)
    return " ".join(stripped.split()).lower()


def compute_text_sha256(text: str) -> str:
    """§7.4's `text_sha256`, over normalised text and tagged with the rule
    version that produced it (see `TOMBSTONE_HASH_VERSION`)."""
    digest = hashlib.sha256(normalise_ad_text_for_tombstone(text).encode("utf-8")).hexdigest()
    return f"v{TOMBSTONE_HASH_VERSION}:sha256:{digest}"


# ---------------------------------------------------------------------------
# the tombstone ledger


_TOMBSTONES_PARTS = ("offers", "tombstones.jsonl")


def read_tombstone_ledger(store: ProfileStore) -> list[Tombstone]:
    """Every row ever appended, in append order. Uses T13's own loader
    (`dedup.load_tombstones`) rather than re-parsing the file, so a malformed
    row is refused the same way whichever module reads it."""
    path = store.path(*_TOMBSTONES_PARTS)
    if not path.exists():
        return []
    return load_tombstones(path)


def current_tombstones(store: ProfileStore) -> dict[str, Tombstone]:
    """The ledger folded to one row per offer id — the latest write wins.

    Same "derive current state from an append-only log" rule
    `profile.EvidenceLog`'s readers already use; nothing in `tombstones.jsonl`
    is ever rewritten in place, so this fold is how a resighting's
    incremented counter becomes "the" tombstone for that id without the
    earlier row disappearing from the file.
    """
    latest: dict[str, Tombstone] = {}
    for row in read_tombstone_ledger(store):
        latest[row.offer_id] = row
    return latest


def _append_tombstone(store: ProfileStore, tombstone: Tombstone) -> Path:
    return store.append_jsonl(tombstone.model_dump(mode="json"), *_TOMBSTONES_PARTS)


def build_tombstone(offer: Offer, record: LifecycleRecord, *, purged_at: str) -> Tombstone:
    """§7.4's shape, populated from the offer being purged. No field here
    can carry the ad body — `Tombstone` (T13's schema) has no such field to
    begin with, so this function could not smuggle one in even by accident.
    """
    return Tombstone(
        offer_id=offer.id,
        url=offer.url,
        url_canonical=canonicalize_url(offer.url) if offer.url else None,
        text_sha256=compute_text_sha256(offer.text),
        first_seen=record.collected_at,
        purged_at=purged_at,
        last_status=offer.status,
        resightings=0,
        last_resighting=None,
    )


def purge_offer(store: ProfileStore, offer_id: str, *, at: str, now: datetime) -> Tombstone:
    """§7.3: delete the offer body, keep a tombstone.

    Re-checks eligibility itself rather than trusting the caller's earlier
    `select_purge_eligible` snapshot: a candidate could have shortlisted the
    offer in the moment between selection and this call, and a purge that
    trusted a stale list would delete something that just started to matter.
    """
    offer, record = load_lifecycle_offer(store, offer_id)
    if not is_purge_eligible(store, offer, record, now=now):
        raise LifecycleError(f"{offer_id} is not purge-eligible (§7.3) — refusing to purge")
    tombstone = build_tombstone(offer, record, purged_at=at)
    _append_tombstone(store, tombstone)
    store.path("offers", f"{offer_id}.json").unlink(missing_ok=True)
    store.path(*_lifecycle_parts(offer_id)).unlink(missing_ok=True)
    return tombstone


def purge_batch(
    store: ProfileStore, offer_ids: Sequence[str], *, at: str, now: datetime
) -> list[Tombstone]:
    """§7.3: 'It is reported, not silent.' Returns every tombstone written,
    so a caller has what it needs to tell the candidate what was retired
    before running this, or what just was after."""
    return [purge_offer(store, offer_id, at=at, now=now) for offer_id in offer_ids]


# ---------------------------------------------------------------------------
# §7.4 — collection through the tombstone gate, and explicit revival


@dataclass(frozen=True)
class CollectionOutcome:
    """What happened when one incoming `Offer` was run through the
    tombstone check — the fact `resurrected_purged_offers` is ultimately
    counted from."""

    offer_id: str
    added_as_new: bool
    matched_tombstone: str | None


def collect_offer(store: ProfileStore, offer: Offer, *, at: str) -> CollectionOutcome:
    """The one gate a connector, or a re-collection pass, must go through
    (§7.4). Never called `save_offer`/`save_lifecycle_offer` directly for a
    freshly-seen ad without checking this first.

    Matched two ways: by `offer.id` (T11's id is content-addressed off the
    verbatim text, so a byte-identical re-collection of a tombstoned ad
    always lands on the same id — the cheap, exact case) or by
    `dedup.tombstone_match` over `url_canonical`/`text_sha256` (a re-scrape
    that is not byte-identical — different chrome, a reworded stamp — but
    normalises to the same ad). Either match drops the offer and records a
    resighting instead of adding it; neither ever creates
    `offers/<id>.json` for a tombstoned ad.
    """
    tombstones = current_tombstones(store)
    matched = tombstones.get(offer.id)
    if matched is None:
        text_sha256 = compute_text_sha256(offer.text)
        url_canonical = canonicalize_url(offer.url) if offer.url else None
        matched = tombstone_match(
            list(tombstones.values()), url_canonical=url_canonical, text_sha256=text_sha256
        )
    if matched is not None:
        _record_resighting(store, matched, at=at)
        return CollectionOutcome(offer.id, added_as_new=False, matched_tombstone=matched.offer_id)
    record = track_new_offer(offer, at=at)
    save_lifecycle_offer(store, offer, record)
    return CollectionOutcome(offer.id, added_as_new=True, matched_tombstone=None)


def _record_resighting(store: ProfileStore, tombstone: Tombstone, *, at: str) -> Tombstone:
    """§7.4: 'its `resightings` counter increments and it is dropped.'
    Appended as a new ledger row, not a rewrite — see `current_tombstones`."""
    updated = tombstone.model_copy(
        update={"resightings": tombstone.resightings + 1, "last_resighting": at}
    )
    _append_tombstone(store, updated)
    return updated


def revive(store: ProfileStore, tombstone_id: str, offer: Offer, *, at: str) -> LifecycleRecord:
    """§7.4: 'If the candidate pastes or asks for a tombstoned ad, it is
    restored as `new`, the revival is recorded, and the tombstone survives.'

    `tombstone_id` names which tombstone this is a revival *of* — nothing
    here infers that from `offer` alone, the same "nothing without a name"
    shape `retraction.delete_profile` uses for its own action that cannot be
    undone by accident (§4.3). The tombstone is never deleted or rewritten by
    this function: reviving an ad restores it, it does not erase that the ad
    was ever purged, so the next purge of the same listing still has a
    `first_seen` to report.
    """
    tombstones = current_tombstones(store)
    if tombstone_id not in tombstones:
        raise LifecycleError(f"{tombstone_id!r} is not a tombstoned offer — nothing to revive")
    if offer.status != "new":
        raise LifecycleError("a revived offer must start 'new', same as any freshly collected one")
    event = TransitionEvent(
        from_status=None, to_status="new", at=at, reason=f"explicit revival of {tombstone_id}"
    )
    record = LifecycleRecord(
        offer_id=offer.id, collected_at=at, status_changed_at=at, history=(event,), revived=True
    )
    save_lifecycle_offer(store, offer, record)
    return record


# ---------------------------------------------------------------------------
# the gate


def _resurrected_offer_ids(store: ProfileStore) -> list[str]:
    """Every tombstoned offer id that currently exists on disk as a live
    offer *without* having gone through `revive`. This is a filesystem scan
    of whatever state the store is actually in when called — it does not
    consult what `collect_offer`/`revive` claimed to have done, so a probe
    that called the right functions but left a bug behind still shows up
    here.
    """
    resurrected: list[str] = []
    for offer_id in current_tombstones(store):
        if not store.path("offers", f"{offer_id}.json").exists():
            continue
        try:
            _, record = load_lifecycle_offer(store, offer_id)
        except (OfferError, LifecycleError):
            # Present but unreadable is still a tombstoned id with a live
            # file next to it — exactly as suspicious as a clean resurrection,
            # so it counts rather than being swallowed as "not measurable".
            resurrected.append(offer_id)
            continue
        if not record.revived:
            resurrected.append(offer_id)
    return sorted(resurrected)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def probe_lifecycle() -> dict[str, Any]:
    """§7's full loop, run for real, against a throwaway profile tree.

    Builds several offers by actually driving them through `track_new_offer`
    and `transition` (never by hand-assigning `.status`), purges the ones
    that should be eligible, retains the ones that should not be, then runs
    two more collection passes over the exact source text of a purged ad —
    one byte-identical, one a differently-formatted re-scrape of the same
    listing — plus one genuinely new ad, plus one explicit revival, and
    *only then* scans the tree for what survived. `resurrected_purged_offers`
    is read off that scan (`_resurrected_offer_ids`), never asserted or
    computed from what the calls above claimed to do: this function does not
    clean up, delete, or repair anything before that count — see
    `tests/test_offer_lifecycle.py::test_the_probe_cleans_nothing_up_by_hand`
    for the failure mode ("makes zero true by construction") this guards.
    """
    violations: list[str] = []
    scenarios = 0

    def check(condition: bool, message: str) -> None:
        nonlocal scenarios
        scenarios += 1
        if not condition:
            violations.append(message)

    with tempfile.TemporaryDirectory(prefix="integral-s5-") as tmp:
        root = Path(tmp) / "profiles"
        identity = create_profile(root, "Probe Candidate", language="en")
        store = ProfileStore(root, identity.handle)

        now = datetime(2026, 8, 18, tzinfo=UTC)
        old = _iso(now - timedelta(days=PURGE_HORIZON_DAYS + 5))
        borderline_recent = _iso(now - timedelta(days=PURGE_HORIZON_DAYS - 5))

        # --- §7.1: transitions are data, checked both ways ------------------
        for from_status, allowed in ALLOWED_TRANSITIONS.items():
            for to_status in allowed:
                check(
                    can_transition(from_status, to_status),
                    f"{from_status!r} -> {to_status!r} is in ALLOWED_TRANSITIONS but "
                    "can_transition refused it",
                )
            for to_status in _ALL_STATUSES - allowed - {from_status}:
                check(
                    not can_transition(from_status, to_status),
                    f"{from_status!r} -> {to_status!r} is not in §7.1's table but "
                    "can_transition allowed it",
                )
        check(
            "new" not in ALLOWED_TRANSITIONS["applied"],
            "'applied' can transition back to 'new' — §7.1 forbids this explicitly",
        )
        applied_offer = connect_manual("Data Analyst role. SQL and dashboards.")
        applied_record = track_new_offer(applied_offer, at=old)
        applied_offer, applied_record = transition(
            applied_offer, applied_record, "shortlisted", at=old
        )
        applied_offer, applied_record = transition(applied_offer, applied_record, "applied", at=old)
        try:
            transition(applied_offer, applied_record, "new", at=old)
        except LifecycleError:
            pass
        else:
            violations.append("transition() allowed 'applied' -> 'new'")
        scenarios += 1

        # --- build the retention/purge scenarios -----------------------------

        never_shortlisted_text = "Warehouse Operative. Shifts, forklift certified preferred."
        never_shortlisted = connect_manual(
            never_shortlisted_text, url="https://portal-a.example.com/j/1?utm_source=news&ref=abc"
        )
        ns_record = track_new_offer(never_shortlisted, at=old)
        never_shortlisted, ns_record = transition(
            never_shortlisted, ns_record, "screened_out", at=old
        )
        save_lifecycle_offer(store, never_shortlisted, ns_record)

        shortlisted_then_screened_out = connect_manual("Junior Accountant, hybrid, ES.")
        sl_record = track_new_offer(shortlisted_then_screened_out, at=old)
        shortlisted_then_screened_out, sl_record = transition(
            shortlisted_then_screened_out, sl_record, "shortlisted", at=old
        )
        shortlisted_then_screened_out, sl_record = transition(
            shortlisted_then_screened_out, sl_record, "screened_out", at=old
        )
        save_lifecycle_offer(store, shortlisted_then_screened_out, sl_record)

        save_lifecycle_offer(
            store, applied_offer, applied_record
        )  # applied -> ... old, kept forever

        recent = connect_manual("Office Manager, part time.")
        recent_record = track_new_offer(recent, at=borderline_recent)
        save_lifecycle_offer(store, recent, recent_record)

        cased = connect_manual("Night Security Guard, on site.")
        cased_record = track_new_offer(cased, at=old)
        cased, cased_record = transition(cased, cased_record, "screened_out", at=old)
        save_lifecycle_offer(store, cased, cased_record)
        store.write_json({"sent": True}, "applications", cased.id, "sent.json")

        # --- §7.2 retention: exactly the right set is excluded ---------------
        retained_ids = {shortlisted_then_screened_out.id, applied_offer.id, recent.id, cased.id}
        for offer_id in retained_ids:
            offer, record = load_lifecycle_offer(store, offer_id)
            check(
                not is_purge_eligible(store, offer, record, now=now),
                f"{offer_id} was purge-eligible but should be retained (§7.2)",
            )
        check(
            is_purge_eligible(store, never_shortlisted, ns_record, now=now),
            "a never-shortlisted, screened-out offer past the purge horizon was not eligible",
        )

        selected = set(select_purge_eligible(store, now=now))
        check(
            selected == {never_shortlisted.id},
            f"select_purge_eligible returned {sorted(selected)}, expected only "
            f"[{never_shortlisted.id!r}]",
        )

        # --- §7.3/§7.4: an actual purge -----------------------------
        tombstones = purge_batch(store, sorted(selected), at=old, now=now)
        check(len(tombstones) == 1, "purge_batch did not report the offer it purged")
        purged_id = never_shortlisted.id

        check(
            not store.path("offers", f"{purged_id}.json").exists(),
            "purge left the offer body behind",
        )
        check(
            not store.path(*_lifecycle_parts(purged_id)).exists(),
            "purge left the lifecycle companion behind",
        )
        for offer_id in retained_ids:
            check(
                store.path("offers", f"{offer_id}.json").exists(),
                f"purge deleted a retained offer, {offer_id}",
            )

        # --- §7.4: a tombstone carries no ad body ---------------------------
        tombstone_line = store.path(*_TOMBSTONES_PARTS).read_text(encoding="utf-8")
        check(
            never_shortlisted_text not in tombstone_line,
            "the ad's text survived into the tombstone ledger",
        )
        check(
            "text" not in Tombstone.model_fields,
            "Tombstone gained a field that could carry an ad body",
        )

        # --- the adversarial re-collections ----------------------------------

        # 1) byte-identical re-collection of the purged ad.
        recollected_exact = connect_manual(never_shortlisted_text, url=never_shortlisted.url)
        check(
            recollected_exact.id == purged_id, "test setup: verbatim text did not reproduce the id"
        )
        outcome_exact = collect_offer(store, recollected_exact, at=_iso(now))
        check(
            outcome_exact.added_as_new is False and outcome_exact.matched_tombstone == purged_id,
            "an exact re-collection of a purged ad was not recognised as tombstoned",
        )

        # 2) a differently-formatted re-scrape of the same listing: different
        #    chrome and a volatile stamp wrapped around identical content, so
        #    the id differs but the §7.4 normalised hash does not.
        rescraped_text = (
            "Cookie Notice\nPosted 3 days ago\n" + never_shortlisted_text + "\nSimilar Jobs\n"
        )
        check(
            compute_text_sha256(rescraped_text) == compute_text_sha256(never_shortlisted_text),
            "test setup: the re-scrape fixture does not normalise to the same hash",
        )
        rescraped = connect_manual(rescraped_text, url="https://portal-b.example.com/other-path")
        check(rescraped.id != purged_id, "test setup: the re-scrape fixture collided on id anyway")
        outcome_rescraped = collect_offer(store, rescraped, at=_iso(now))
        check(
            outcome_rescraped.added_as_new is False
            and outcome_rescraped.matched_tombstone == purged_id,
            "a re-scraped near-duplicate of a purged ad (same text_sha256) was added as new",
        )

        # 3) same underlying URL, entirely different wording, only the
        #    canonical URL ties it back — isolates the url_canonical route.
        url_variant_text = "A completely different description of the same warehouse role."
        check(
            compute_text_sha256(url_variant_text) != compute_text_sha256(never_shortlisted_text),
            "test setup: the URL-variant fixture accidentally shares a text hash",
        )
        url_variant = connect_manual(
            url_variant_text, url="https://portal-a.example.com/j/1?utm_source=other&ref=zzz"
        )
        check(
            canonicalize_url(url_variant.url or "")
            == canonicalize_url(never_shortlisted.url or ""),
            "test setup: the URL-variant fixture does not canonicalise to the same URL",
        )
        outcome_url_variant = collect_offer(store, url_variant, at=_iso(now))
        check(
            outcome_url_variant.added_as_new is False
            and outcome_url_variant.matched_tombstone == purged_id,
            "a differently-worded ad at the purged ad's canonical URL was added as new",
        )

        # 4) mirror check: a genuinely new ad is not swallowed by the gate.
        brand_new = connect_manual("Totally unrelated Marketing Intern role, remote, EU.")
        outcome_new = collect_offer(store, brand_new, at=_iso(now))
        check(
            outcome_new.added_as_new is True and outcome_new.matched_tombstone is None,
            "collect_offer refused a genuinely new ad that matches no tombstone",
        )
        check(
            store.path("offers", f"{brand_new.id}.json").exists(),
            "a genuinely new ad that collect_offer accepted was never written",
        )

        # 5) explicit revival: distinguishable, and the tombstone survives.
        revival_offer = connect_manual(never_shortlisted_text, url=never_shortlisted.url)
        revival_record = revive(store, purged_id, revival_offer, at=_iso(now))
        check(revival_record.revived is True, "revive() did not mark its own record revived")
        check(
            store.path("offers", f"{revival_offer.id}.json").exists(),
            "an explicit revival did not restore the offer",
        )
        check(
            purged_id in current_tombstones(store),
            "an explicit revival deleted the tombstone it revived — §7.4 requires it to survive",
        )

        # --- the measurement itself: read off disk, nothing repaired first ---
        resurrected_ids = _resurrected_offer_ids(store)

    return {
        "resurrected_purged_offers": len(resurrected_ids),
        "resurrected_offer_ids": resurrected_ids,
        "scenarios_checked": scenarios,
        "violations": violations,
    }


# Comfortably below what the fixture above actually runs (every §7.1 table
# cell checked both ways, plus the retention/purge/tombstone/collection/
# revival scenarios) and comfortably above what any trivial fixture could
# produce — "zero over nothing is not a measurement" (payload, and every
# other T*/S* gate module's floor). Moved above the assignment it explains
# (T159): a comment placed below is invisible to a sweep reading "the comment
# above a declaration", and this floor was exactly that until round 2's
# parameter-via-callers tracing made it visible for the first time.
MINIMUM_SCENARIOS = 20


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `resurrected_purged_offers` and record it."""
    measured = probe_lifecycle()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _s5_report(measured: dict[str, Any]) -> int:
    """Print S5's measurement and say whether it fails that gate."""
    print(json.dumps(measured, ensure_ascii=False))
    if measured["scenarios_checked"] < MINIMUM_SCENARIOS:
        print(
            f"only {measured['scenarios_checked']} scenario(s) were checked "
            f"(floor {MINIMUM_SCENARIOS}) — zero resurrections over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    if measured["resurrected_purged_offers"]:
        print(
            f"{measured['resurrected_purged_offers']} purged offer(s) resurrected without an "
            f"explicit revival: {measured['resurrected_offer_ids']}",
            file=sys.stderr,
        )
    return 1 if (measured["violations"] or measured["resurrected_purged_offers"]) else 0


# ---------------------------------------------------------------------------
# T82 — the application status vocabulary (spec §5.2)

DEFAULT_APPLICATION_STATUS_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T82.json"

ApplicationStatus = Literal[
    "drafted",
    "applied",
    "interview",
    "offer",
    "hired",
    "rejected",
    "no_response",
    "offer_declined",
    "withdrawn",
]

# §5.2's table, split in two. A status absent from both sets is a schema
# defect, caught at import time below — the same fail-fast shape §7.1's
# `ALLOWED_TRANSITIONS` completeness check uses for `OfferStatus`.
OPEN_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"drafted", "applied", "interview", "offer"}
)
FINAL_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"hired", "rejected", "no_response", "offer_declined", "withdrawn"}
)

_ALL_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(get_args(ApplicationStatus))
if OPEN_APPLICATION_STATUSES & FINAL_APPLICATION_STATUSES:
    raise LifecycleError("a status cannot be both Open and Final (§5.2)")
_APPLICATION_STATUS_SPLIT = OPEN_APPLICATION_STATUSES | FINAL_APPLICATION_STATUSES
if _APPLICATION_STATUS_SPLIT != _ALL_APPLICATION_STATUSES:
    raise LifecycleError(
        "OPEN_APPLICATION_STATUSES/FINAL_APPLICATION_STATUSES disagree with ApplicationStatus "
        f"on: {sorted(_ALL_APPLICATION_STATUSES ^ _APPLICATION_STATUS_SPLIT)}"
    )

# §5.2: "Legacy space-spellings ... accepted on read, never written." Closed
# on purpose — only the spellings the spec names verbatim, not a general
# space-to-underscore rule, so a genuinely unrecognised string still refuses
# rather than being silently coerced into whatever it looks closest to.
_LEGACY_APPLICATION_STATUS_SPELLINGS: dict[str, ApplicationStatus] = {
    "no response": "no_response",
    "offer declined": "offer_declined",
}

# "Never infer hired or offer_declined. Accepting or declining is the
# candidate's decision and is recorded only when they say so." Made
# mechanical here rather than trusted to every future caller's memory — the
# same "nothing without a name" shape `revive` uses above for its own
# action that cannot happen by accident.
_CONFIRMATION_REQUIRED_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {"hired", "offer_declined"}
)


class ApplicationStatusError(LifecycleError):
    """A status is outside the closed nine-value vocabulary (§5.2), or
    `hired`/`offer_declined` was recorded without an explicit confirmation."""


def normalise_application_status(raw: str) -> ApplicationStatus:
    """Canonicalise `raw`, tolerating the legacy space-spellings §5.2 accepts
    **on read** — never called to normalise a value this module is about to
    write without first passing back through the canonical form, since
    `record_application_status` stores whatever this function returns, never
    the spelling it was given.
    """
    if raw in _ALL_APPLICATION_STATUSES:
        return raw
    canonical = _LEGACY_APPLICATION_STATUS_SPELLINGS.get(raw)
    if canonical is not None:
        return canonical
    raise ApplicationStatusError(
        f"{raw!r} is not one of the nine canonical application statuses (§5.2) — the "
        "vocabulary is closed; a case that seems unhandled is raised, never added"
    )


def application_status_class(status: ApplicationStatus) -> Literal["open", "final"]:
    """§5.2's two-way split. Every one of the nine statuses lands in exactly
    one class — enforced at import time by the completeness check above, so
    this is total rather than a fallback."""
    return "open" if status in OPEN_APPLICATION_STATUSES else "final"


class ApplicationStatusRecord(Strict):
    """`applications/{offer_id}/status.json` — spec §5.2's shape, verbatim.

    `status` is typed `str`, not `ApplicationStatus`: a legacy space-spelling
    already on disk (or in a file this module did not write) still has to
    parse so it can be tolerated on read, and a `Literal` field would refuse
    it before `normalise_application_status` ever got a chance to.
    """

    status: str
    recorded_at: str


def _application_status_parts(offer_id: str) -> tuple[str, str, str]:
    return ("applications", offer_id, "status.json")


def record_application_status(
    store: ProfileStore,
    offer_id: str,
    *,
    status: str,
    at: str,
    candidate_confirmed: bool = False,
) -> ApplicationStatusRecord:
    """Write `applications/{offer_id}/status.json` (§5.2).

    `status` is normalised before it is written, so even a caller that
    passes a legacy space-spelling lands a canonical, underscored value on
    disk — "accepted on read, never written" applies to every write this
    module performs, not only ones a candidate already typed correctly.
    `hired`/`offer_declined` are refused unless `candidate_confirmed=True` —
    see the module docstring's T82 paragraph.
    """
    canonical = normalise_application_status(status)
    if canonical in _CONFIRMATION_REQUIRED_APPLICATION_STATUSES and not candidate_confirmed:
        raise ApplicationStatusError(
            f"{canonical!r} is only recorded when the candidate says so — pass "
            "candidate_confirmed=True for an explicit confirmation; it is never inferred"
        )
    # Refusing to READ a corrupt record protects nothing on its own: the very
    # next write replaced it, which is the data loss the read guard was added
    # for. So the write refuses too, and the corrupt file survives to be looked
    # at by a person. `read_application_status` raises for exactly the cases
    # that must not be overwritten and returns None when there is no record, so
    # calling it here is the whole check.
    read_application_status(store, offer_id)

    record = ApplicationStatusRecord(status=canonical, recorded_at=at)
    store.write_json(record.model_dump(mode="json"), *_application_status_parts(offer_id))
    return record


def read_application_status(store: ProfileStore, offer_id: str) -> ApplicationStatus | None:
    """The current status for `offer_id`, or `None` if none was ever
    recorded. Tolerates a legacy space-spelling found on disk (§5.2)
    in-memory only — reading is never a migration, so the file itself is
    left exactly as it was found.
    """
    # `read_json` raises IdentityError for BOTH a missing file and malformed
    # JSON, so catching it wholesale reported a corrupt record as "never
    # recorded" — and the next `record_application_status` then overwrote the
    # corruption rather than refusing. Note the contradiction it created: a
    # record that parses as JSON but fails the schema below is already an
    # ApplicationStatusError, so the same damage was an error or a silent
    # overwrite depending only on *how* broken the file was.
    # ONE read, not exists() then read. Two operations left a window in which
    # the file could vanish between them — reporting a record that was merely
    # deleted as unreadable — and, worse, said nothing about failures that are
    # neither: `read_text` catches only FileNotFoundError, so a `status.json`
    # that is a directory raised IsADirectoryError straight through this
    # function. Measured: `ESCAPES as IsADirectoryError`.
    #
    # `__cause__` is what separates the two, because `read_text` re-raises the
    # FileNotFoundError as IdentityError `from` it. That couples this to
    # identity.py's internals, and an explicit ProfileStore API for "missing
    # versus unreadable" would be better — worth doing when something else
    # needs the same distinction.
    parts = _application_status_parts(offer_id)
    try:
        raw = store.read_json(*parts)
    except IdentityError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise ApplicationStatusError(
            f"{offer_id}'s application status record could not be read: {exc}"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise ApplicationStatusError(
            f"{offer_id}'s application status record could not be read: {exc}"
        ) from exc
    try:
        record = ApplicationStatusRecord.model_validate(raw)
    except Exception as exc:
        raise ApplicationStatusError(
            f"{offer_id}'s application status record is malformed: {exc}"
        ) from exc
    return normalise_application_status(record.status)


def audit_application_statuses(rows: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """The gate: every `(offer_id, raw_status)` pair checked against §5.2's
    closed vocabulary (legacy spellings tolerated, same as a real read).

    Takes `rows` rather than discovering them, so a test's handful of
    fixture rows and the real measurement below share one function — the
    same split `audit_documents`/T80 and `keyword_coverage`/T81 use in
    `ats.py`.
    """
    violations: list[str] = []
    for offer_id, raw in rows:
        try:
            normalise_application_status(raw)
        except ApplicationStatusError:
            violations.append(f"{offer_id}: {raw!r} is not a canonical application status")
    evaluated = len(rows)
    return {
        "applications_with_a_noncanonical_status": len(violations),
        "applications_with_a_noncanonical_status_evaluated": evaluated,
        # The dated addendum's own name for the same denominator — the
        # prose and the addendum name it differently, so both are written
        # with the same value rather than picking one and breaking the other.
        "application_records_checked": evaluated,
        "gate_status": "unmeasured" if evaluated == 0 else "measured",
        "violations": violations,
    }


def probe_application_statuses() -> dict[str, Any]:
    """§5.2's gate, measured for real against a throwaway profile.

    Drives every one of the nine canonical statuses through the real
    `record_application_status`, plus one legacy space-spelled record
    written directly to disk (never through this module's own write path —
    it is what a pre-existing or externally authored file looks like), then
    re-reads every `applications/*/status.json` from disk and audits it —
    the same "measure off disk, not off what the calls above claimed to do"
    discipline `probe_lifecycle` uses for S5. There is no candidate in this
    repository and there must not be one (see `ats.py`'s module docstring),
    so this fixture is a throwaway profile, not real data.
    """
    with tempfile.TemporaryDirectory(prefix="integral-t82-") as tmp:
        root = Path(tmp) / "profiles"
        identity = create_profile(root, "Probe Candidate", language="en")
        store = ProfileStore(root, identity.handle)

        at = _iso(datetime(2026, 8, 26, tzinfo=UTC))
        for index, status in enumerate(sorted(_ALL_APPLICATION_STATUSES)):
            record_application_status(
                store,
                f"offer-{index}",
                status=status,
                at=at,
                candidate_confirmed=status in _CONFIRMATION_REQUIRED_APPLICATION_STATUSES,
            )
        store.write_json(
            {"status": "no response", "recorded_at": at},
            *_application_status_parts("offer-legacy"),
        )

        rows: list[tuple[str, str]] = []
        for status_path in sorted(store.path("applications").glob("*/status.json")):
            offer_id = status_path.parent.name
            raw = json.loads(status_path.read_text(encoding="utf-8"))
            rows.append((offer_id, raw["status"]))

        return audit_application_statuses(rows)


def write_application_status_evidence(
    evidence: Path = DEFAULT_APPLICATION_STATUS_EVIDENCE_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T82.json`."""
    measured = probe_application_statuses()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _t82_report(measured: dict[str, Any]) -> int:
    """Print T82's measurement and say whether it fails that gate."""
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(
            "applications_with_a_noncanonical_status: UNMEASURED — "
            f"{measured['applications_with_a_noncanonical_status_evaluated']} application "
            "record(s) evaluated. Not a pass and not a fail (D-2).",
            file=sys.stderr,
        )
        return 0
    if measured["applications_with_a_noncanonical_status"]:
        print(
            "applications_with_a_noncanonical_status: " + "; ".join(measured["violations"]),
            file=sys.stderr,
        )
    return 1 if measured["applications_with_a_noncanonical_status"] else 0


def _main(argv: list[str]) -> int:
    """Write S5's and T82's gate evidence — one module, two gates. `make
    evidence` discovers this module once and runs `python -m
    integral.lifecycle` once, so both gates are written from the same entry
    point (the same shape `ats.py`'s `_main` uses for T80/T81).
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    s5_measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    s5_exit = _s5_report(s5_measured)

    t82_measured = write_application_status_evidence()
    t82_exit = _t82_report(t82_measured)

    return s5_exit if s5_exit else t82_exit


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
