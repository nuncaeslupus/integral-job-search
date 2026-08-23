"""T21 — the feedback loop: a rejection reason reaches the weights, or is counted.

Step 10's gate: *"`feedback_traceability == 1.0` — every derived value names the
evidence rows that produced it, so 'the ranking changed because you said X' is
checkable rather than a story."* That sentence can be false in two ways, and a
metric that saw only one of them would certify the other.

**A derived value with no provenance.** A stated constraint, a trait, a
part-worth that names no row is a number nothing can attribute. Naming a row
that is not in the effective log is the same failure wearing a citation.

**A reason that never became a row.** `lifecycle.transition` takes a `reason`,
writes it into the offer's own history, and writes nothing to `evidence.jsonl` —
by design, because coupling the lifecycle to the profile store crosses the
ownership line S5 drew and `profile_capture.capture_offer_decision_reason`
exists to compose the two from outside. So a decision made through `transition`
directly moves the offer and leaves the weights untouched, and the candidate is
told their words changed the list when they did not.

**The decision this task owed (T28's review, PR #27).** The brief offered three
resolutions for that bypass: make the wrapper the only way to pass a reason,
have `transition` refuse one, or accept it and say why. This takes the third,
with a condition: *accepted, and counted.*

* Refusing a `reason` in `transition` would be wrong on its own terms. The
  reason is not going nowhere — `TransitionEvent.reason` is where "why did this
  offer move" lives, and §7.1's history is supposed to answer that. Removing it
  would delete a real record to prevent a different one from being missed.
* Making the wrapper the only route means importing the profile store into
  `lifecycle`, which is the coupling S5 drew the line to prevent.

So `transition` is untouched and `orphaned_reasons` names every reason sitting
in a lifecycle history with no evidence row about that offer carrying it. A
bypass is then a number in this gate rather than a silence, which is the only
form of "accept it" that does not decay into "nobody noticed".

`record_decision` is the production flow the brief says is missing: it is the
one route a reason-bearing decision takes, it goes through the wrapper, and it
rebuilds the profile afterwards so the ranking the candidate is shown next is
computed from what they just said.

**Stated ceiling — a part-worth is traced to the choice set, not to one choice.**
`weights.json` names every reaction row that entered the fit and does not
attribute each coefficient separately. That is not laziness: T10 fits a joint
logit, where every choice contributes to every coefficient, so a per-coefficient
row list would be a fabricated attribution. The claim "these rows produced these
weights" is exactly the true one.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.decline import DeclineLedger
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    LifecycleRecord,
    load_lifecycle_offer,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import Offer, OfferStatus, connect_manual
from integral.profile import DERIVED_DIR, EvidenceLog, EvidenceRow, rebuild
from integral.profile_capture import capture, capture_offer_decision_reason

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T21.json"


class FeedbackError(Exception):
    """A decision cannot be recorded against the profile as asked."""


@dataclass(frozen=True)
class DecisionResult:
    """What one recorded decision did: the offer, its record, its row."""

    offer: Offer
    record: LifecycleRecord
    row: EvidenceRow | None
    derived: dict[str, str]


def record_decision(
    store: ProfileStore,
    offer_id: str,
    to_status: OfferStatus,
    *,
    at: str,
    reason: str | None,
) -> DecisionResult:
    """Step 10's decision: move the offer, keep the words, rebuild what they move.

    The order matters and is the order `capture_offer_decision_reason` already
    imposes: the transition is computed first, so a move §7.1 refuses raises
    before any row is written. A reason recorded against a decision the offer
    never made would be worse than a lost one — it is evidence for something
    that did not happen.
    """
    try:
        offer, record = load_lifecycle_offer(store, offer_id)
    except Exception as exc:
        raise FeedbackError(f"{offer_id}: no offer to decide about — {exc}") from exc

    new_offer, new_record, row = capture_offer_decision_reason(
        store, offer, record, to_status, at=at, reason=reason
    )
    save_lifecycle_offer(store, new_offer, new_record)
    # The rebuild is the loop. Without it the reason is in the log and the
    # weights the next ranking reads are the ones from before it was said,
    # which is the "show the consequence immediately" of step 10 not happening.
    return DecisionResult(new_offer, new_record, row, rebuild(store))


def _lifecycle_records(store: ProfileStore) -> Iterator[LifecycleRecord]:
    directory = store.path("offers", "lifecycle")
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.json")):
        yield LifecycleRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def orphaned_reasons(store: ProfileStore) -> list[dict[str, str]]:
    """Reasons recorded against an offer that never reached `evidence.jsonl`.

    Matched on `(offer, text)` rather than on a row id, because `transition`
    holds no row id to write down — which is the whole shape of the bypass.
    """
    rows = list(EvidenceLog(store).effective_rows())
    said = {
        (row.about.id, row.text)
        for row in rows
        if row.about is not None and row.about.kind == "offer"
    }
    return [
        {"offer": record.offer_id, "reason": event.reason, "at": event.at}
        for record in _lifecycle_records(store)
        for event in record.history
        # `from_status is None` is the initial `collected` event, which
        # `track_new_offer` writes itself. Its "reason" is the system saying how
        # the offer got here, not the candidate saying anything — counting it
        # would make every profile untraceable for a sentence nobody uttered.
        if event.from_status is not None
        and event.reason
        and (record.offer_id, event.reason) not in said
    ]


def _claims(store: ProfileStore) -> list[tuple[str, Sequence[str]]]:
    """Every derived value, as `(name, the row ids it names)`.

    A value whose provenance is genuinely not a row is not here — an `unknown`
    or `declined` constraint field was not derived from anything, and asking it
    for a citation would measure a fact about the schema instead of about the
    log.
    """
    found: list[tuple[str, Sequence[str]]] = []

    constraints = _read_json(store, "constraints.json") or {}
    for name, field in sorted((constraints.get("fields") or {}).items()):
        if isinstance(field, dict) and field.get("state") == "stated":
            found.append((f"constraints.{name}", field.get("evidence") or ()))

    traits = _read_json(store, "traits.json") or {}
    for name, entry in sorted((traits.get("dimensions") or {}).items()):
        found.append((f"traits.{name}", (entry or {}).get("evidence") or ()))

    weights = _read_json(store, "weights.json") or {}
    if weights.get("part_worths"):
        found.append(("weights.part_worths", weights.get("reaction_evidence") or ()))

    for line in _read_jsonl(store, "stories.jsonl"):
        story_id = line.get("id")
        # An episode is its own provenance: the derived row *is* the log row,
        # carried forward. It still goes through the same check, because the id
        # it carries has to be one the effective log still has — a retracted
        # episode that stayed in `stories.jsonl` is exactly that failure.
        found.append((f"stories.{story_id}", (str(story_id),) if story_id else ()))

    return found


def _read_json(store: ProfileStore, filename: str) -> dict[str, Any] | None:
    path = store.path(DERIVED_DIR, filename)
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _read_jsonl(store: ProfileStore, filename: str) -> list[dict[str, Any]]:
    path = store.path(DERIVED_DIR, filename)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def traceability(store: ProfileStore) -> dict[str, Any]:
    """T21's gate: the fraction of claims that name a row really in the log."""
    known = {row.id for row in EvidenceLog(store).effective_rows()}
    claims = _claims(store)
    orphans = orphaned_reasons(store)

    untraced: list[str] = []
    for name, ids in claims:
        if not ids:
            untraced.append(f"{name}: names no evidence row")
            continue
        missing = sorted(set(ids) - known)
        if missing:
            untraced.append(f"{name}: cites {', '.join(missing)}, which the log does not have")
    untraced += [
        f"lifecycle.{orphan['offer']}: the reason {orphan['reason']!r} never reached the log"
        for orphan in orphans
    ]

    total = len(claims) + len(orphans)
    return {
        "feedback_traceability": 1.0 if not total else (total - len(untraced)) / total,
        "values": len(claims),
        "orphaned_reasons": len(orphans),
        "untraced": untraced,
    }


_AT = "2026-08-24T09:00:00Z"


def _fixture_store(root: Path) -> ProfileStore:
    """One profile with something of every derived kind in it.

    A measurement over an empty profile is a 1.0 with nothing behind it, so the
    fixture states a constraint, tells an episode, and decides about an offer —
    the three shapes `_claims` walks, plus the loop this task builds.
    """
    identity = create_profile(root, "Fixture", handle="fixture")
    store = ProfileStore(root, identity.handle)
    log, ledger = EvidenceLog(store), DeclineLedger(store)
    capture(
        log,
        ledger,
        step="constraints",
        kind="constraint",
        text="No quiero desplazarme más de 30 minutos.",
        source="conversation",
        dimensions=("commute",),
        recorded_at=_AT,
    )
    capture(
        log,
        ledger,
        step="history",
        kind="episode",
        text="Monté el pipeline de despliegue del equipo en dos semanas.",
        source="conversation",
        dimensions=("team_autonomy",),
        recorded_at=_AT,
    )
    offer = connect_manual(
        "Backend en Barcelona, oficina cada día.", title="Backend", company="ACME", language="es"
    )
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
    record_decision(store, offer.id, "screened_out", at=_AT, reason="Otra agencia, no.")
    return store


def measure() -> dict[str, Any]:
    """The gate's number, and proof it can fall."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _fixture_store(Path(tmp))
        measured = traceability(store)

        # Route a second decision around the wrapper — `transition` and a save,
        # exactly the bypass. If the fraction does not move, the gate is not
        # looking at the lifecycle at all and a 1.0 says nothing about it.
        offer = connect_manual("Otra oferta, presencial.", title="Ops", language="es")
        save_lifecycle_offer(store, offer, track_new_offer(offer, at=_AT))
        loaded, record = load_lifecycle_offer(store, offer.id)
        save_lifecycle_offer(
            store, *transition(loaded, record, "screened_out", at=_AT, reason="Sin remoto.")
        )
        planted = traceability(store)

    return {
        **measured,
        "fraction_falls_when_a_reason_bypasses_the_log": int(
            planted["feedback_traceability"] < 1.0
        ),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T21's feedback traceability.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)

    print(f"feedback_traceability: {measured['feedback_traceability']} (== 1.0)")
    if measured["feedback_traceability"] != 1.0:
        for problem in measured["untraced"]:
            print(problem, file=sys.stderr)
        return 1
    if not measured["fraction_falls_when_a_reason_bypasses_the_log"]:
        print("the fraction did not fall when a reason bypassed the log", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
