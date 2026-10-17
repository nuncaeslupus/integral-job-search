"""T345 - an offer already applied to, rejected or expired is not shown again.

`offers_presented_again_after_applied_or_rejected` counts the offers whose own
record says the candidate applied (by status, by history, or by an application
record past `drafted`), was rejected, or the vacancy expired, and that
`presentation_log.partition` still puts in the list to show. Each case is built
in a throwaway profile and run; none reads source text. Controls (a new offer,
a shortlisted one, a screened-out one revived) must stay shown, because hiding
an offer the candidate never ruled on costs as much as repeating one they did,
and a run that withholds everything would otherwise score a clean zero.

An offer shown before is not withheld (`passed_over` counts repeats); it is
named by `presentation_log.shown_notes` (the call step 9 makes), and
`offers_seen_not_marked` counts the repeats that line fails to name.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    record_application_status,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import Offer, OfferStatus, compute_offer_id
from integral.presentation_log import partition, present, shown_notes

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T345.json"
_AT = "2026-01-01T00:00:00+00:00"
#: Floors, literals on purpose: deleting a case breaches them (population: 9 ruled, 3 controls).
#: arsenal-floor-margin: MINIMUM_RULED_OFFERS_CHECKED value=9
MINIMUM_RULED_OFFERS_CHECKED = 9
MINIMUM_CONTROLS = 3

#: Each case: a name and the statuses walked from `new` (all legal, section 7.1).
RULED_CASES: tuple[tuple[str, tuple[OfferStatus, ...]], ...] = (
    ("applied", ("shortlisted", "applied")),
    ("applied then archived", ("shortlisted", "applied", "archived")),
    ("rejected", ("shortlisted", "applied", "rejected")),
    ("rejected then archived", ("shortlisted", "applied", "rejected", "archived")),
    ("expired", ("expired",)),
    ("expired then archived", ("expired", "archived")),
    ("shortlisted then expired", ("shortlisted", "expired")),
)
#: Reads `new` but has an application record past `drafted`.
RECORD_ONLY_CASES: tuple[str, ...] = ("applied", "rejected")
CONTROLS: tuple[tuple[str, tuple[OfferStatus, ...]], ...] = (
    ("new", ()),
    ("shortlisted", ("shortlisted",)),
    ("screened out and taken back", ("screened_out", "shortlisted")),
)


def _store(root: Path) -> ProfileStore:
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    return ProfileStore(root, "fixture")


def _save(store: ProfileStore, label: str, path: tuple[OfferStatus, ...]) -> str:
    text = f"advert {label}"
    key = compute_offer_id(label)
    offer = Offer(
        id=compute_offer_id(text),
        source="fixture",
        url=f"https://fixture.example/{key}",
        title=f"Role {label}",
        company=f"Employer {key[:8]}",
        text=text,
    )
    record = track_new_offer(offer, at=_AT)
    for step in path:
        offer, record = transition(offer, record, step, at=_AT)
    save_lifecycle_offer(store, offer, record)
    return offer.id


def _shown(build: Callable[[ProfileStore], str]) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        store = _store(Path(tmp))
        offer_id = build(store)
        show, _ = partition(store, [offer_id])
        return offer_id in show


def _built(label: str, path: tuple[OfferStatus, ...]) -> Callable[[ProfileStore], str]:
    return lambda store: _save(store, label, path)


def _record_only(status: str) -> Callable[[ProfileStore], str]:
    def build(store: ProfileStore) -> str:
        offer_id = _save(store, f"record {status}", ())
        record_application_status(store, offer_id, status=status, at=_AT)
        return offer_id

    return build


def _repeat_unmarked() -> int:
    """Repeats `shown_notes` fails to name plus new offers it wrongly names, over the
    order step 9's SKILL documents (partition, present, then shown_notes) and the
    reverse (shown_notes before present)."""
    wrong = 0
    for notes_after_present in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(Path(tmp))
            seen = _save(store, "seen", ())
            fresh = _save(store, "fresh", ())
            present(store, [seen], at=_AT)
            show, _ = partition(store, [seen, fresh])
            before = shown_notes(store, show)
            present(store, show, at=_AT)
            line = "\n".join(shown_notes(store, show) if notes_after_present else before)
            wrong += int("Role seen" not in line) + int("Role fresh" in line)
    return wrong


def measure() -> dict[str, Any]:
    again: list[str] = []
    for name, path in RULED_CASES:
        if _shown(_built(name, path)):
            again.append(name)
    for status in RECORD_ONLY_CASES:
        if _shown(_record_only(status)):
            again.append(f"record only: {status}")
    withheld_controls = [name for name, path in CONTROLS if not _shown(_built(name, path))]
    checked = len(RULED_CASES) + len(RECORD_ONLY_CASES)
    ok = (
        checked >= MINIMUM_RULED_OFFERS_CHECKED
        and len(CONTROLS) >= MINIMUM_CONTROLS
        and not withheld_controls
    )
    return {
        "offers_presented_again_after_applied_or_rejected": len(again) if ok else -1,
        "ruled_offers_checked_at_least": MINIMUM_RULED_OFFERS_CHECKED,
        "controls_withheld": len(withheld_controls),
        "offers_seen_not_marked": _repeat_unmarked(),
        "gate_status": "measured" if ok else "unmeasured",
        "presented_again": again,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main() -> int:
    measured = write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] != "measured":
        return 3
    bad = measured["offers_presented_again_after_applied_or_rejected"]
    return int(bool(bad or measured["controls_withheld"] or measured["offers_seen_not_marked"]))


if __name__ == "__main__":
    raise SystemExit(_main())
