"""T139 — what was shown, what was chosen, and why the rest were not.

A reason given while rejecting an offer is the cheapest evidence this tool
ever gets: unprompted, specific, and about a real advert the candidate has
just read. It is worth more than an answer to a question, because nobody
asked for it. The owner said *"Applied Research Scientist, eso no sería mi
perfil"* and it was used once, in one reply, and lost.

**The engine for keeping it already existed.** `feedback.record_decision`
moves the offer, writes the words into the offer's own history *and* into
`profile/evidence.jsonl`, and rebuilds the weights so the next ranking is
computed from what was just said — and T21's `orphaned_reasons` already
counts any reason that reached a lifecycle history without becoming a row.
Nothing here re-implements that. What did not exist is anything **calling**
it: 561 of 567 offers in the owner's own tree were still `new`.

**Choosing one of five does not reject the other four**, and this is the
design decision the module exists to hold. Marking them `screened_out` would
be tidy and wrong twice over:

* `screened_out` is in `lifecycle.PURGE_ELIGIBLE_STATUSES`, so at sixty days
  those four lose their text. A candidate who picked the second advert would
  be scheduling the deletion of the other four for not having been picked
  first, which is the opposite of keeping them to compare against later.
* Silence is not a verdict. They may have read the second and stopped.

So being shown and passed over is recorded **here**, as a fact about a
presentation, and the offer's status is left alone. That is real information
and it is not a rejection.

**Weak signal becomes strong by asking, not by inferring.** When the same
offer has been passed over repeatedly, `passed_over` names it, and the
session asks once — *"has pasado de cuatro de investigación, ¿te las quito?"*
What is then stored is something the candidate said, with their words as the
reason, not a category this module guessed.

**And nothing is dropped silently.** `partition` returns what is shown *and*
what is being withheld with the reason for each, because a filter nobody is
told about is indistinguishable from a thin market — the failure
`step-07-sourcing` already names for liveness, arriving by a different route.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.feedback import DecisionResult, record_decision
from integral.identity import ProfileStore
from integral.lifecycle import (
    LifecycleRecord,
    _ever_reached,
    advert_components,
    load_lifecycle_offer,
    read_application_status,
    save_lifecycle_offer,
    stored_identities,
    stored_posting_keys,
    track_new_offer,
)
from integral.offers import Offer, is_advert, names_an_employer, open_application
from integral.profile_standing import Standing
from integral.same_vacancy import employer_key, same_vacancy
from integral.sourcing_exclusions import (
    EMPLOYER_UNKNOWN,
    candidate_of,
    held_in_words,
    load_exclusions,
    pending_skill_checks,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T139.json"
DEFAULT_T255_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T255.json"

#: One row per batch shown to the candidate. Under `search/` beside the aim,
#: not under `offers/`: it is a fact about a conversation, not about an advert,
#: and the same advert appears in as many rows as it was shown in.
PRESENTATIONS = ("search", "presentations.jsonl")

#: How many times an offer must be shown and passed over before it is worth
#: interrupting the candidate about. One is noise — they may have taken the
#: first thing they liked and never reached it.
PASS_OVER_THRESHOLD = 2

#: Statuses that mean the candidate has ruled on this advert already, so it is
#: not "passed over" — it is settled, in one direction or the other.
_RULED = frozenset({"shortlisted", "applied", "screened_out", "rejected", "archived"})

#: The two statuses `partition` withholds. One definition, because T224 reads it
#: for the offer itself and for every other stored copy of the same advert.
_RULED_OUT = ("screened_out", "rejected")


#: T250. Why an offer is held back because the same vacancy (see
#: `same_vacancy`) is already on record. One constant per kind, so
#: `withheld_line` counts them per reason rather than in one lump.
REASON_APPLIED = "ya te presentaste a esta vacante"
REASON_SHORTLISTED = "ya la tenías en tu lista de interesantes"
REASON_SHOWN = "el mismo anuncio ya se te mostró"
#: T255. Not a vacancy: nothing to rank, so it is told about rather than listed.
REASON_OPEN_APPLICATION = "es una candidatura abierta, no una vacante"


class PresentationError(Exception):
    """A decision that would record something nobody said."""


@dataclass(frozen=True)
class Withheld:
    """One offer kept back, and the candidate's own words for why."""

    offer_id: str
    reason: str
    #: T225. The other stored copy of the same advert that caused the hold, when
    #: one did; `None` when the offer's own record or an exclusion did.
    sibling: str | None = None


def present(
    store: ProfileStore,
    offer_ids: list[str],
    *,
    at: str,
    phrase: str | None = None,
    standing: Standing | None = None,
) -> Path:
    """Record that these adverts were shown together.

    T209: `standing` is the strengths / widen-the-fit pair said with the batch;
    its presence in the row is what the step-9 checkpoint reads.
    """
    row: dict[str, Any] = {"at": at, "phrase": phrase, "offer_ids": list(offer_ids), "chosen": []}
    if standing is not None:
        row["standing"] = {
            "strengths": standing.strengths,
            "widen": standing.widen,
            "language": standing.language,
        }
    return store.append_jsonl(row, *PRESENTATIONS)


def choose(
    store: ProfileStore, offer_id: str, *, at: str, reason: str | None = None
) -> DecisionResult:
    """The candidate said this one interests them.

    Goes to `shortlisted`, which `lifecycle._RETAINED_IF_EVER_REACHED` keeps
    indefinitely — so the advert survives to be compared against later, which
    is the whole ask. The others in its batch are **not** touched.
    """
    _mark_chosen(store, offer_id)
    return record_decision(store, offer_id, "shortlisted", at=at, reason=reason)


def record_open_application(
    store: ProfileStore, company: str, url: str, form_questions: list[str], *, at: str
) -> Offer:
    """T255. Record a CV sent to `company` with no advert, ready for step 11.

    Stored and shortlisted (the candidate chose it by asking), so step 11 and the
    retention rule see it. It is not an advert: see `offers.is_advert`. Asking
    twice for the same employer and destination returns the stored record, unless it
    was ruled out: that is refused by name, since the record is not ready for step 11.
    A stored record that cannot be read is an error, never overwritten."""
    offer = open_application(company, url, form_questions, fetched_at=at)
    if not store.exists("offers", f"{offer.id}.json"):
        save_lifecycle_offer(store, offer, track_new_offer(offer, at=at))
        return choose(store, offer.id, at=at, reason=None).offer
    stored, lifecycle = load_lifecycle_offer(store, offer.id)
    if lifecycle.current_status == "screened_out":
        raise PresentationError(
            f"{offer.id}: this open application was ruled out; it is not ready for step 11"
        )
    return stored


def rule_out(store: ProfileStore, offer_id: str, reason: str, *, at: str) -> DecisionResult:
    """The candidate said why this one is wrong. That sentence is the point.

    A blank reason is refused rather than accepted quietly: a `screened_out`
    with nothing behind it is the record that teaches the next ranking
    nothing, and it is indistinguishable afterwards from a reason that was
    given and dropped.
    """
    if not reason.strip():
        raise PresentationError(
            f"{offer_id}: ruling an offer out needs the candidate's reason — "
            "a blank one records the verdict and loses the only part worth keeping"
        )
    return record_decision(store, offer_id, "screened_out", at=at, reason=reason)


def _mark_chosen(store: ProfileStore, offer_id: str) -> None:
    """Note the choice on the most recent batch that offered it."""
    rows = _rows(store)
    for row in reversed(rows):
        if offer_id in row.get("offer_ids", ()):
            row.setdefault("chosen", []).append(offer_id)
            store.write_text(
                "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                *PRESENTATIONS,
            )
            return


def _rows(store: ProfileStore) -> list[dict[str, Any]]:
    if not store.exists(*PRESENTATIONS):
        return []
    return [row for row in store.read_jsonl(*PRESENTATIONS) if isinstance(row, dict)]


def _loaded(store: ProfileStore, offer_id: str) -> tuple[Offer, LifecycleRecord] | None:
    try:
        return load_lifecycle_offer(store, offer_id)
    except Exception:
        return None


def times_shown(store: ProfileStore) -> Counter[str]:
    """How often each advert has been put in front of the candidate."""
    shown: Counter[str] = Counter()
    for row in _rows(store):
        for offer_id in row.get("offer_ids", ()):
            shown[str(offer_id)] += 1
    return shown


def passed_over(store: ProfileStore, *, at_least: int = PASS_OVER_THRESHOLD) -> list[str]:
    """Adverts shown repeatedly, never chosen, and never ruled on.

    The list to ask one question about — not a list to act on. Nothing here
    changes a status; a status changes when the candidate says something.
    """
    chosen = {str(i) for row in _rows(store) for i in row.get("chosen", ())}
    out = []
    for offer_id, count in times_shown(store).items():
        if count < at_least or offer_id in chosen:
            continue
        loaded = _loaded(store, offer_id)
        if loaded is None or loaded[0].status in _RULED:
            continue
        out.append(offer_id)
    return sorted(out)


def reason_for(store: ProfileStore, offer_id: str) -> str | None:
    """The last thing the candidate said about this advert, if anything."""
    loaded = _loaded(store, offer_id)
    if loaded is None:
        return None
    for event in reversed(loaded[1].history):
        if event.from_status is not None and (event.reason or "").strip():
            return event.reason
    return None


def _presented_ids(store: ProfileStore) -> set[str]:
    return {str(i) for row in _rows(store) for i in row.get("offer_ids", ())}


def _ever(store: ProfileStore, offer_id: str, statuses: frozenset[str]) -> bool:
    """T250. Whether the stored offer is, or ever was, in one of `statuses`.

    Lifecycle §7.2's "ever, not currently" (`lifecycle._ever_reached`): an advert
    applied to and then archived, or shortlisted and then expired, is still one
    the candidate acted on, and reading only the current status re-presents it."""
    loaded = _loaded(store, offer_id)
    if loaded is None:
        return False
    offer, record = loaded
    return offer.status in statuses or _ever_reached(record, statuses)  # type: ignore[arg-type]


def _has_applied(store: ProfileStore, offer_id: str) -> bool:
    """T250. Ever applied, or an `applications/<id>/status.json` record past
    `drafted` (a draft is not an application) which can exist while the offer
    still reads `new`. A record that cannot be read is not evidence of an
    application: the offer is shown. Only siblings are asked: an offer's own
    application record is left to the ranking (T242 ranks applied offers on
    purpose)."""
    if _ever(store, offer_id, frozenset({"applied"})):
        return True
    try:
        recorded = read_application_status(store, offer_id)
        return recorded is not None and recorded != "drafted"
    except Exception:
        return False


def _keys_by_employer(
    keys: dict[str, str | None],
) -> dict[tuple[str, ...], list[tuple[str, str]]]:
    """Stored posting keys indexed by comparable employer: employer -> [(id, title)]."""
    index: dict[tuple[str, ...], list[tuple[str, str]]] = {}
    for stored_id, key in keys.items():
        if key is None:
            continue
        employer, title = json.loads(key)
        comparable = employer_key(employer)
        if comparable is not None:
            index.setdefault(comparable, []).append((stored_id, title))
    return index


def _similar_stored(
    offer: Offer, offer_id: str, by_employer: dict[tuple[str, ...], list[tuple[str, str]]]
) -> set[str]:
    """Stored ids, other than `offer_id`, that are the same vacancy by
    employer and title. A blank employer finds nothing (`names_an_employer`)."""
    if not names_an_employer(offer.company):
        return set()
    comparable = employer_key(offer.company)
    if comparable is None:
        return set()
    return {
        stored_id
        for stored_id, title in by_employer.get(comparable, ())
        if stored_id != offer_id and same_vacancy(offer.company, offer.title, offer.company, title)
    }


def unchecked_line(store: ProfileStore, offer_ids: list[str]) -> str:
    """T250. Offers shown without being compared, because no employer is named.

    `partition` cannot tell a blank-employer offer from one already seen, so it
    shows it; the candidate is told, since for these the check did not run.
    """
    blank = [
        i
        for i in offer_ids
        if (loaded := _loaded(store, i)) and not names_an_employer(loaded[0].company)
    ]
    if not blank:
        return ""
    return f"{len(blank)} sin empresa indicada: no se pudo comprobar si ya las habías visto"


def pending_skill_counts(store: ProfileStore, offer_ids: list[str]) -> dict[str, int]:
    """T229. For each `skill:` exclusion, how many of these adverts it could not be checked on.

    A `skill:<tech>` exclusion holds an advert only on its step-8 extraction
    listing the skill as required; an advert not read yet is shown, so it is
    counted here rather than passing for a cleared one.
    """
    exclusions = load_exclusions(store)
    pending: dict[str, int] = {}
    for offer_id in offer_ids:
        loaded = _loaded(store, offer_id)
        if loaded is None:
            continue
        for about in pending_skill_checks(candidate_of(loaded[0], store), exclusions):
            pending[about] = pending.get(about, 0) + 1
    return pending


def pending_skill_line(store: ProfileStore, offer_ids: list[str]) -> str:
    """T229. The note for adverts shown while a `skill:` exclusion could not be checked.

    Empty when nothing is pending. Spanish, like the other lines the candidate reads.
    """
    pending = pending_skill_counts(store, offer_ids)
    if not pending:
        return ""
    parts = ", ".join(f"{about} en {count}" for about, count in sorted(pending.items()))
    return f"sin leer todavía para saber si lo exigen: {parts}"


def shown_notes(store: ProfileStore, show: list[str]) -> list[str]:
    """Every note that must accompany a shown list: unchecked employers, unread skills.

    The one call step 9 makes after `partition`, so a note added here reaches the
    candidate without the SKILL having to name it.
    """
    return [line for line in (unchecked_line(store, show), pending_skill_line(store, show)) if line]


def presented_pending_skill_counts(store: ProfileStore) -> dict[str, int]:
    """`pending_skill_counts` over every advert ever shown (step 9's checkpoint)."""
    return pending_skill_counts(store, sorted(_presented_ids(store)))


def partition(store: ProfileStore, offer_ids: list[str]) -> tuple[list[str], list[Withheld]]:
    """Split a batch into what to show and what is being held back, with why.

    Both halves are returned because returning only the first is the silent
    filter this module exists to prevent: four of nine withheld looks exactly
    like five having been found.

    **What counts as the same advert (T224, T225).** A *sibling* is another
    stored offer in the same connected component (`lifecycle.advert_components`):
    linked by the same `advert_identity` (same URL) or the same `posting_key`
    (same employer and title; see `lifecycle.posting_key`), directly or through
    a chain of such links, **or** (T250) the same vacancy by `same_vacancy`:
    one employer and a similar title, which joins another board's wording. A
    sibling holds an offer back when it was applied to (by status or by an
    application record past `drafted`), shortlisted, ruled out
    (`screened_out`/`rejected`), or already shown through `present()` while this
    offer was not; in that order. Each kind has its own reason, so
    `withheld_line` counts them separately. Withheld rows from a sibling carry
    its id in `Withheld.sibling`. Nothing is deleted: a withheld offer stays
    stored. An offer with no employer is compared with nothing and is shown;
    `unchecked_line` says so.
    """
    show: list[str] = []
    held: list[Withheld] = []
    # T203. Read here, at the one place every list the candidate reads passes
    # through: an offer stored *before* they ruled its topic out is not touched
    # by `source()`, and would otherwise be shown with the exclusion on file.
    exclusions = load_exclusions(store)
    identities = stored_identities(store)
    keys = stored_posting_keys(store)
    presented = _presented_ids(store)
    components = advert_components(identities, keys)
    by_employer = _keys_by_employer(keys)
    shown_by_component: dict[tuple[str, ...], str] = {}
    shown_in_batch: list[tuple[str, str | None, str | None]] = []
    for offer_id in offer_ids:
        loaded = _loaded(store, offer_id)
        component = components.get(offer_id, ())
        # T250. The same vacancy under another board's wording is not in the
        # component (no shared URL, no equal key): add it by employer and title.
        siblings = sorted(
            {i for i in component if i != offer_id}
            | (_similar_stored(loaded[0], offer_id, by_employer) if loaded else set())
        )
        # T224. A rule-out recorded against one stored copy of an advert covers
        # every other copy: the offer id hashes text, which a list row changes on
        # every search, so the same advert was stored under several ids and only
        # one of them carried the verdict. Read-time, not a migration: the copies
        # stay as the board served them and the verdict follows the advert.
        applied_copy = next((c for c in siblings if _has_applied(store, c)), None)
        shortlisted_copy = next(
            (c for c in siblings if _ever(store, c, frozenset({"shortlisted"}))), None
        )
        ruled_copy = next((c for c in siblings if _ever(store, c, frozenset(_RULED_OUT))), None)
        # T225. Likewise a copy the candidate was already shown holds back the
        # others, unless this one was shown itself: repeating an offer is what
        # `passed_over` counts and is not this rule's business.
        shown_copy = (
            None
            if offer_id in presented
            else next((copy for copy in siblings if copy in presented), None)
        )
        in_batch = shown_by_component.get(component) if component else None
        if in_batch is None and loaded is not None:
            in_batch = next(
                (
                    other
                    for other, company, title in shown_in_batch
                    if same_vacancy(loaded[0].company, loaded[0].title, company, title)
                ),
                None,
            )
        if loaded is not None and not is_advert(loaded[0]):
            held.append(Withheld(offer_id, REASON_OPEN_APPLICATION))
        elif loaded is not None and loaded[0].status in _RULED_OUT:
            held.append(Withheld(offer_id, reason_for(store, offer_id) or "ruled out earlier"))
        elif applied_copy is not None:
            held.append(Withheld(offer_id, REASON_APPLIED, applied_copy))
        elif shortlisted_copy is not None:
            held.append(Withheld(offer_id, REASON_SHORTLISTED, shortlisted_copy))
        elif ruled_copy is not None:
            held.append(
                Withheld(offer_id, reason_for(store, ruled_copy) or "ruled out earlier", ruled_copy)
            )
        elif shown_copy is not None:
            held.append(Withheld(offer_id, REASON_SHOWN, shown_copy))
        elif in_batch is not None:
            # The same advert twice in one batch is one advert shown once.
            held.append(Withheld(offer_id, "el mismo anuncio ya está en esta lista", in_batch))
        elif loaded is not None and (
            topics := held_in_words(candidate_of(loaded[0], store), exclusions)
        ):
            shown_as = ", ".join(topics)
            if all(t.endswith(f"({EMPLOYER_UNKNOWN})") for t in topics):
                # F6: held because nothing says who published it, not for a topic.
                reason = f"no dice quién lo publica y descartaste un empleador ({shown_as})"
            else:
                reason = f"es de un tema que descartaste ({shown_as})"
            held.append(Withheld(offer_id, reason))
        else:
            show.append(offer_id)
            if component:
                shown_by_component[component] = offer_id
            if loaded is not None:
                shown_in_batch.append((offer_id, loaded[0].company, loaded[0].title))
    return show, held


def withheld_line(held: list[Withheld]) -> str:
    """What the candidate is told, in the shape the owner asked for."""
    if not held:
        return ""
    by_reason: Counter[str] = Counter(item.reason for item in held)
    parts = [f"{count} porque «{reason}»" for reason, count in by_reason.most_common()]
    return f"{len(held)} descartada(s): " + "; ".join(parts)


# ---------------------------------------------------------------------------
# The gate — every contract built and run, none of them read
#
# Two numbers, and the second keeps the first honest. `discard_reasons_not_
# stored` counts a rejection whose words never became an evidence row, which
# is T21's `orphaned_reasons` asked about this flow rather than about the
# tree as a whole. `silently_dropped_offers` counts an advert withheld
# without the candidate being told the count and the reason — a filter nobody
# is told about is indistinguishable from a thin market.
#
# Both fail open by construction, which is why they are the pair: a reason
# not stored is asked for again next session, and a silent filter is a
# candidate wondering why so little came back.


_AT = "2026-01-01T00:00:00+00:00"


def _fixture(root: Path) -> tuple[ProfileStore, list[str]]:
    from integral.identity import create_profile
    from integral.lifecycle import save_lifecycle_offer, track_new_offer
    from integral.offers import compute_offer_id

    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    store = ProfileStore(root, "fixture")
    ids = []
    for n in range(5):
        text = f"advert number {n}"
        offer = Offer(id=compute_offer_id(text), source="fixture", text=text)
        save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
        ids.append(offer.id)
    return store, ids


def _c_choosing_one_does_not_reject_the_rest(root: Path) -> str | None:
    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    choose(store, ids[1], at=_AT, reason="me interesa")
    moved = [i for i in ids[2:] if (loaded := _loaded(store, i)) and loaded[0].status != "new"]
    if moved:
        return f"{len(moved)} advert(s) left `new` because one was chosen: {moved[0]}"
    return None


def _c_a_chosen_advert_is_kept_forever(root: Path) -> str | None:
    from integral.lifecycle import is_retained_indefinitely

    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    choose(store, ids[1], at=_AT, reason="me interesa")
    offer, record = load_lifecycle_offer(store, ids[1])
    if not is_retained_indefinitely(store, offer, record):
        return "a chosen advert is still purge-eligible, so it cannot be compared against later"
    return None


def _c_a_blank_reason_is_refused(root: Path) -> str | None:
    store, ids = _fixture(root)
    try:
        rule_out(store, ids[0], "   ", at=_AT)
    except PresentationError:
        return None
    return "an offer was ruled out with no reason, which records the verdict and loses the point"


def _c_a_reason_becomes_an_evidence_row(root: Path) -> str | None:
    from integral.feedback import orphaned_reasons

    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    rule_out(store, ids[0], "yo no soy applied researcher", at=_AT)
    orphans = orphaned_reasons(store)
    if orphans:
        return f"the reason never became an evidence row: {orphans[0]}"
    if reason_for(store, ids[0]) != "yo no soy applied researcher":
        return "the reason is not readable back off the advert's own history"
    return None


def _c_nothing_is_withheld_silently(root: Path) -> str | None:
    store, ids = _fixture(root)
    rule_out(store, ids[0], "es de investigación", at=_AT)
    rule_out(store, ids[1], "es de investigación", at=_AT)
    show, held = partition(store, ids)
    if len(show) != 3 or len(held) != 2:
        return f"partition split {len(ids)} into {len(show)} shown and {len(held)} held"
    line = withheld_line(held)
    if "2" not in line or "investigación" not in line:
        return f"the withheld line does not say how many or why: {line!r}"
    return None


def _c_an_unruled_advert_is_still_shown(root: Path) -> str | None:
    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    show, held = partition(store, ids)
    if held:
        return f"{len(held)} advert(s) withheld though the candidate has said nothing about them"
    if len(show) != len(ids):
        return "an advert nobody has ruled on was not shown"
    return None


def _c_passed_over_needs_repetition(root: Path) -> str | None:
    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    if passed_over(store):
        return "an advert shown once was already treated as passed over"
    present(store, ids, at=_AT)
    named = passed_over(store)
    if set(named) != set(ids):
        return f"after two showings, passed_over named {len(named)} of {len(ids)}"
    return None


def _c_a_chosen_advert_is_not_passed_over(root: Path) -> str | None:
    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    present(store, ids, at=_AT)
    choose(store, ids[1], at=_AT, reason="esta sí")
    if ids[1] in passed_over(store):
        return "the advert the candidate chose is being reported as passed over"
    return None


def _c_a_ruled_advert_is_not_passed_over(root: Path) -> str | None:
    store, ids = _fixture(root)
    present(store, ids, at=_AT)
    present(store, ids, at=_AT)
    rule_out(store, ids[0], "es de investigación", at=_AT)
    if ids[0] in passed_over(store):
        return "an advert already ruled on is being queued for a question about it"
    return None


def _c_a_rejection_can_be_undone(root: Path) -> str | None:
    """`screened_out -> shortlisted` is a legal transition, and it must stay
    reachable: being passed over is not meant to be permanent."""
    store, ids = _fixture(root)
    rule_out(store, ids[0], "creí que era de investigación", at=_AT)
    try:
        choose(store, ids[0], at=_AT, reason="me equivoqué, sí me interesa")
    except Exception as exc:
        return f"a rejection could not be undone: {exc}"
    offer, _ = load_lifecycle_offer(store, ids[0])
    if offer.status != "shortlisted":
        return f"after being taken back it reads {offer.status}"
    return None


CONTRACTS = (
    ("choosing one does not reject the rest", _c_choosing_one_does_not_reject_the_rest),
    ("a chosen advert is kept forever", _c_a_chosen_advert_is_kept_forever),
    ("a blank reason is refused", _c_a_blank_reason_is_refused),
    ("a reason becomes an evidence row", _c_a_reason_becomes_an_evidence_row),
    ("nothing is withheld silently", _c_nothing_is_withheld_silently),
    ("an unruled advert is still shown", _c_an_unruled_advert_is_still_shown),
    ("passed over needs repetition", _c_passed_over_needs_repetition),
    ("a chosen advert is not passed over", _c_a_chosen_advert_is_not_passed_over),
    ("a ruled advert is not passed over", _c_a_ruled_advert_is_not_passed_over),
    ("a rejection can be undone", _c_a_rejection_can_be_undone),
)

#: Which contracts are about the reason surviving, and which about the filter
#: being visible. Split so the two committed numbers mean what they are named,
#: rather than one total wearing two labels.
_REASON_CONTRACTS = frozenset({"a blank reason is refused", "a reason becomes an evidence row"})
_FILTER_CONTRACTS = frozenset({"nothing is withheld silently", "an unruled advert is still shown"})

MINIMUM_CONTRACTS = 10


def measure() -> dict[str, Any]:
    import tempfile

    failures: list[str] = []
    failed_names: set[str] = set()
    for name, contract in CONTRACTS:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                complaint = contract(Path(tmp))
            except Exception as exc:
                complaint = f"raised {type(exc).__name__}: {exc}"
        if complaint:
            failures.append(f"{name}: {complaint}")
            failed_names.add(name)
    measured: dict[str, Any] = {
        "discard_reasons_not_stored": len(failed_names & _REASON_CONTRACTS),
        "silently_dropped_offers": len(failed_names & _FILTER_CONTRACTS),
        "presentation_defects": len(failures),
        "contracts_run": len(CONTRACTS),
        "failed_contracts": failures,
        "gate_status": "measured",
    }
    if len(CONTRACTS) < MINIMUM_CONTRACTS:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [f"only {len(CONTRACTS)} contract(s), floor {MINIMUM_CONTRACTS}"]
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# T255 — an open application is not stored as an advert
#
# `open_applications_stored_as_adverts` counts the open applications that the four
# consumers of an advert (liveness, deduplication, ranking, the ruled-out-before
# check) still treat as a vacancy. The counter is also run over the hand-written
# shape the first two sessions used (`source: manual`, an invented title, the form
# as the advert text), and over a real advert: a counter that cannot flag the first
# or that flags everything counts nothing.

#: (employer, where it is sent, the form's questions): recorded the supported way.
OPEN_APPLICATIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Acme Robotics",
        "https://acme.example/careers/open-application",
        ("Why us?", "Salary expectation"),
    ),
    ("Forja Ejemplo", "https://forja.example/trabaja-con-nosotros", ()),
    ("  ACME   robotics ", "https://acme.example/careers/open-application?ref=a", ("Why us?",)),
    ("Fiction Labs", "https://community.example/profile/fiction-labs/apply", ("Tell us more",)),
)

#: The same shape hand-written as an `Offer`: the defect the task was filed for.
SYNTHETIC_OPEN_APPLICATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "Acme Robotics",
        "https://acme.example/careers/open-application",
        "Open application",
        "Name\nWhy us?",
    ),
    (
        "Fiction Labs",
        "https://community.example/profile/fiction-labs/apply",
        "Candidatura",
        "Cover note",
    ),
    ("Forja Ejemplo", "https://forja.example/trabaja-con-nosotros", "Candidatura abierta", "CV"),
)

#: Floor on the recorded open applications checked: emptying the population must make the
#: gate `unmeasured`, since with none of it the counter has counted nothing.
MINIMUM_OPEN_APPLICATION_CASES = 4

#: Floor on the hand-written shapes: with none, nothing shows the counter can count one.
MINIMUM_SYNTHETIC_SHAPES = 3

#: Floor on the plain-advert controls: with none, nothing shows it does not flag everything.
MINIMUM_ADVERT_CONTROLS = 1

#: A plain advert, kept shortlisted like the others: every consumer must claim it.
ADVERT_CONTROLS: tuple[tuple[str, str, str, str], ...] = (
    ("Acme Robotics", "https://acme.example/jobs/1", "Backend", "Backend, remote"),
)

_CONSUMERS = ("liveness", "deduplication", "ranking", "ruled-out-before")


def _ranked(offer: Offer) -> bool:
    """Whether the real ranking door (`pay_normalise.candidate_for`, then `rank.rank`
    and the page `presentation.page_ids` shows) takes `offer` in. Not `partition`, which
    is the presentation hold and a different function."""
    from integral.extraction import OfferExtraction
    from integral.pay_normalise import PayNormaliseError, RateTable, candidate_for
    from integral.presentation import page_ids
    from integral.profile import ProfileRevision
    from integral.rank import rank

    try:
        candidate, _ = candidate_for(
            offer,
            OfferExtraction(offer_id=offer.id, language="es", unsettled=["remote"]),
            dimensions=("remote",),
            table=RateTable("EUR"),
        )
    except PayNormaliseError:
        return False
    ranking = rank(
        [candidate],
        dimensions=("remote",),
        revision=ProfileRevision(rows=1, sha256="0" * 64),
        weights=None,
        at=_AT,
    )
    return offer.id in page_ids(ranking)


def treated_as_advert(store: ProfileStore, offer_id: str, twin_id: str) -> list[str]:
    """Which consumers treat `offer_id` as a vacancy. `twin_id` is a stored advert of the
    same employer at the same address: the neighbour a vacancy would be joined to, and
    the one a stored open application must not hold back."""
    from integral.liveness import needs_source_check

    loaded = _loaded(store, offer_id)
    if loaded is None:
        return list(_CONSUMERS)
    found = []
    if needs_source_check(loaded[0]):
        found.append("liveness")
    components = advert_components(stored_identities(store), stored_posting_keys(store))
    if twin_id in components.get(offer_id, ()):
        found.append("deduplication")
    if _ranked(loaded[0]):
        found.append("ranking")
    if twin_id not in partition(store, [twin_id])[0]:
        found.append("ruled-out-before")
    return found


def _advert(company: str, url: str, title: str, text: str) -> Offer:
    from integral.offers import compute_offer_id

    return Offer(
        id=compute_offer_id(text), source="manual", url=url, company=company, title=title, text=text
    )


def _store_with_twin(root: Path, company: str, url: str) -> tuple[ProfileStore, str]:
    from integral.identity import create_profile

    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    store = ProfileStore(root, "fixture")
    twin = _advert(company, url, "Backend", f"Backend engineer at {company}")
    save_lifecycle_offer(store, twin, track_new_offer(twin, at=_AT))
    return store, twin.id


def measure_open_applications() -> dict[str, Any]:
    """T255's gate: `open_applications_stored_as_adverts`."""
    import tempfile

    stored: list[str] = []
    for company, url, questions in OPEN_APPLICATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            store, twin = _store_with_twin(Path(tmp), company, url)
            made = record_open_application(store, company, url, list(questions), at=_AT)
            if found := treated_as_advert(store, made.id, twin):
                stored.append(f"{company}: {', '.join(found)}")
    not_counted = []
    for company, url, title, text in SYNTHETIC_OPEN_APPLICATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            store, twin = _store_with_twin(Path(tmp), company, url)
            offer = _advert(company, url, title, text)
            save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
            choose(store, offer.id, at=_AT)
            if len(treated_as_advert(store, offer.id, twin)) < len(_CONSUMERS):
                not_counted.append(company)
    missed: list[str] = []
    for company, url, title, text in ADVERT_CONTROLS:
        with tempfile.TemporaryDirectory() as tmp:
            store, twin = _store_with_twin(Path(tmp), company, url)
            advert = _advert(company, url, title, text)
            save_lifecycle_offer(store, advert, track_new_offer(advert, at=_AT))
            choose(store, advert.id, at=_AT)
            found = treated_as_advert(store, advert.id, twin)
            missed.extend(n for n in _CONSUMERS if n not in found)
    checked = len(OPEN_APPLICATIONS)
    measured = (
        checked >= MINIMUM_OPEN_APPLICATION_CASES
        and len(SYNTHETIC_OPEN_APPLICATIONS) >= MINIMUM_SYNTHETIC_SHAPES
        and len(ADVERT_CONTROLS) >= MINIMUM_ADVERT_CONTROLS
        and not not_counted
        and not missed
    )
    return {
        "open_applications_stored_as_adverts": len(stored) if measured else -1,
        # A floor, never the count of the day (T100, T150).
        "open_applications_checked_at_least": MINIMUM_OPEN_APPLICATION_CASES,
        "synthetic_shapes_not_counted": len(not_counted),
        "adverts_not_treated_as_adverts": len(missed),
        "gate_status": "measured" if measured else "unmeasured",
        "stored_as_adverts": stored,
    }


def write_open_applications_evidence(
    evidence: Path = DEFAULT_T255_EVIDENCE_PATH,
) -> dict[str, Any]:
    measured = measure_open_applications()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main() -> int:
    measured = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failed_contracts"]:
        print(f"  FAILED {failure}", file=sys.stderr)
    status = (
        3
        if measured["gate_status"] == "unmeasured"
        else int(bool(measured["presentation_defects"]))
    )
    opened = write_open_applications_evidence()
    if opened["gate_status"] != "measured":
        return 3
    return 1 if status == 1 or opened["open_applications_stored_as_adverts"] else status


if __name__ == "__main__":
    raise SystemExit(_main())
