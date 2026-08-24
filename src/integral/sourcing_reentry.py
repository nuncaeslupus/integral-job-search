"""T63 — the measurement behind exhaustion re-opening step 7.

The trigger itself is one kind added to `integral.freshness` (§5.3), because
that module already re-opens a finished step and already requires a reason.
This module is only the gate: `stuck_cycles_without_a_proposal`, which asks of
every cycle judged exhausted whether the re-entry it produced carried a
proposal to change the search.

It lives beside `freshness` rather than inside it for one mechanical reason:
`make evidence` runs one `_main` per module and each writes one evidence file,
and `freshness._main` already owns T36's.

**The count is only worth reading because the probe tries to break it.** A
negative control constructs the re-entry the rule forbids — exhausted, no
proposal — and counts it as a stuck cycle if it is *accepted*; and a floor on
`reentry_offers` fails a run that fired nothing, since a trigger that never
fires reports zero proposalless re-entries by never having re-entered.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from integral.freshness import FreshnessError, Offer, exhaustion_offers
from integral.sourcing_strategy import judge_cycle

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T63.json"

#: Two cycles must actually re-enter, or the count above is zero by the trigger
#: never having fired — a pass over an empty probe rather than over a rule.
MINIMUM_TRIGGERS = 2

#: What a re-entry proposes, in the candidate's terms. A string here on purpose:
#: T64 owns `ScopeProposal` and its symmetry rule, and this gate is about
#: whether *a* proposal accompanies the trigger, not about its shape.
_PROPOSAL = "widen: drop the country filter, or narrow to the two employers you read"


def probe_reentry() -> dict[str, Any]:
    """Judge a spread of cycles and count every re-entry that carries no proposal."""
    judged = [
        judge_cycle(cycle=1, offers_returned=10, offers_already_seen=1),  # healthy
        judge_cycle(cycle=2, offers_returned=10, offers_already_seen=9),  # repeating
        judge_cycle(cycle=3, offers_returned=0, offers_already_seen=0),  # returned nothing
    ]
    stuck: list[str] = []
    other: list[str] = []
    raised: list[Offer] = []

    for cycle in judged:
        made = exhaustion_offers(cycle, proposal=_PROPOSAL)
        raised.extend(made)
        if not cycle.exhausted:
            if made:
                other.append(f"cycle {cycle.cycle} was not exhausted but re-entered anyway")
            continue
        if not made:
            stuck.append(f"cycle {cycle.cycle} was exhausted and offered no re-entry at all")
        for offer in made:
            if not (offer.proposal or "").strip():
                stuck.append(f"cycle {cycle.cycle} re-entered with no proposal")
            if offer.step != "sourcing":
                other.append(f"cycle {cycle.cycle} re-entered {offer.step} rather than sourcing")
            if offer.reason.strip() != cycle.reason.strip():
                other.append(f"cycle {cycle.cycle} re-entered without T62's reason for it")

    # Negative control: the rule has to bite, or the count is zero by nothing
    # ever having tried it.
    try:
        Offer(
            kind="exhausted",
            step="sourcing",
            subject="exhausted_sourcing",
            says="We keep finding the same jobs.",
            reason=judged[1].reason,
            proposal=None,
        )
    except FreshnessError:
        rejected = True
    else:
        rejected = False
        stuck.append("a re-entry with no proposal was accepted")

    return {
        "stuck_cycles_without_a_proposal": len(stuck),
        "cycles_judged": len(judged),
        "reentry_offers": len(raised),
        "trigger_kinds": sorted({offer.kind for offer in raised}),
        "proposalless_reentry_rejected": rejected,
        "failures": stuck + other,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T63's measurement to `evidence`, and return it."""
    measured = probe_reentry()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_reentry [path]` → T63's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["reentry_offers"] < MINIMUM_TRIGGERS:
        print(
            f"only {measured['reentry_offers']} cycles re-entered "
            f"(floor {MINIMUM_TRIGGERS}) — a trigger that never fires cannot be "
            "shown to carry a proposal when it does",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
