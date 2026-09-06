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
from integral.lifecycle import LifecycleRecord, load_lifecycle_offer
from integral.offers import Offer

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T139.json"

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


class PresentationError(Exception):
    """A decision that would record something nobody said."""


@dataclass(frozen=True)
class Withheld:
    """One offer kept back, and the candidate's own words for why."""

    offer_id: str
    reason: str


def present(
    store: ProfileStore, offer_ids: list[str], *, at: str, phrase: str | None = None
) -> Path:
    """Record that these adverts were shown together."""
    return store.append_jsonl(
        {"at": at, "phrase": phrase, "offer_ids": list(offer_ids), "chosen": []},
        *PRESENTATIONS,
    )


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


def partition(store: ProfileStore, offer_ids: list[str]) -> tuple[list[str], list[Withheld]]:
    """Split a batch into what to show and what is being held back, with why.

    Both halves are returned because returning only the first is the silent
    filter this module exists to prevent: four of nine withheld looks exactly
    like five having been found.
    """
    show: list[str] = []
    held: list[Withheld] = []
    for offer_id in offer_ids:
        loaded = _loaded(store, offer_id)
        if loaded is not None and loaded[0].status in ("screened_out", "rejected"):
            held.append(Withheld(offer_id, reason_for(store, offer_id) or "ruled out earlier"))
        else:
            show.append(offer_id)
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


def _main() -> int:
    measured = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    for failure in measured["failed_contracts"]:
        print(f"  FAILED {failure}", file=sys.stderr)
    if measured["gate_status"] == "unmeasured":
        return 3
    return 1 if measured["presentation_defects"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
