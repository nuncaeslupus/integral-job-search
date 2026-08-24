"""T62 — exhaustion: judging that a sourcing cycle has stopped finding anything new.

`status/specs/iterative-sourcing.md` §5.2 settles the form as **dedup**, not
preference: *"we are finding the same jobs again."* No fitted weights, no
rejection history, nothing the candidate has to have done first — which is why
it works on cycle two, when nothing has been learned yet.

Two decisions carry the whole of the gate, `exhaustion_triggers_without_a_reason`.

**A reason is part of the trigger, not commentary on it.** `Exhaustion` refuses
to be constructed with `exhausted` set and an empty `reason`, so a reasonless
trigger is a `ValidationError` rather than a row somebody later has to explain
to a candidate. The measurement's negative control constructs exactly that and
records that it was rejected; without it the count would be zero because nothing
ever tried, which is a pass over an empty probe rather than over a working rule.

**A cycle that returned nothing is exhausted for a different reason.** Its
`repeat_share` is `0.0` — there is nothing to divide — and 0.0 is also what a
perfectly healthy cycle of all-new offers reads. The two are told apart by
`reason`, never by the share, so the reason for an empty return names the empty
return and does not mention repetition.

`§5.3`'s trigger kind — `exhausted` beside `stale` in `integral.freshness` — is
T63's, not this module's. This measures; nothing here re-opens a step.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T62.json"

#: A cycle is exhausted when this share of what it returned was already seen. Chosen by
#: common sense and not by evidence: there is no cycle to tune against yet, and a tuned
#: number pretending to be evidence is worse than an honest guess that says so. Revisit
#: once a real candidate has run four or more cycles.
EXHAUSTION_REPEAT_SHARE = 0.8

#: The probe has to fire the rule, not merely fail to break it — a run that
#: triggered nothing would report zero reasonless triggers by never having one.
MINIMUM_TRIGGERS = 2


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Exhaustion(Strict):
    """Why a sourcing cycle is judged to have stopped finding anything new."""

    cycle: int = Field(ge=1)  # 1-based, within this candidate
    offers_returned: int = Field(ge=0)
    offers_already_seen: int = Field(ge=0)  # deduped against the candidate's whole
    # tree, purged tombstones included — an ad the search keeps re-finding after
    # it was purged is the definition of stuck.
    repeat_share: float = Field(ge=0.0, le=1.0)
    exhausted: bool
    reason: str

    @model_validator(mode="after")
    def _the_measurement_holds_together(self) -> Exhaustion:
        if self.offers_already_seen > self.offers_returned:
            raise ValueError("more offers were already seen than the cycle returned")
        expected = self.offers_already_seen / self.offers_returned if self.offers_returned else 0.0
        if not math.isclose(self.repeat_share, expected, abs_tol=1e-9):
            raise ValueError(f"repeat_share {self.repeat_share} is not {expected} for these counts")
        if self.exhausted and not self.reason.strip():
            raise ValueError("an exhaustion with no reason is a violation, not a trigger")
        return self


def judge_cycle(*, cycle: int, offers_returned: int, offers_already_seen: int) -> Exhaustion:
    """Judge one cycle's return against `EXHAUSTION_REPEAT_SHARE`."""
    share = offers_already_seen / offers_returned if offers_returned else 0.0
    if offers_returned == 0:
        reason = f"cycle {cycle} returned no offers at all — the search found nothing to dedupe"
    elif share >= EXHAUSTION_REPEAT_SHARE:
        reason = (
            f"cycle {cycle} returned {offers_returned} offers and "
            f"{offers_already_seen} were already seen — a repeat share of "
            f"{share:.0%}, at or above the {EXHAUSTION_REPEAT_SHARE:.0%} threshold"
        )
    else:
        reason = ""
    return Exhaustion(
        cycle=cycle,
        offers_returned=offers_returned,
        offers_already_seen=offers_already_seen,
        repeat_share=share,
        exhausted=bool(reason),
        reason=reason,
    )


def probe_exhaustion() -> dict[str, Any]:
    """Judge a spread of cycles and count every trigger that carries no reason."""
    judged = [
        judge_cycle(cycle=1, offers_returned=10, offers_already_seen=1),  # healthy
        judge_cycle(cycle=2, offers_returned=10, offers_already_seen=9),  # repeating
        judge_cycle(cycle=3, offers_returned=10, offers_already_seen=8),  # on the threshold
        judge_cycle(cycle=4, offers_returned=0, offers_already_seen=0),  # returned nothing
    ]
    failures = [
        f"cycle {e.cycle} was judged exhausted with no reason"
        for e in judged
        if e.exhausted and not e.reason.strip()
    ]

    empty = judged[-1]
    if "repeat" in empty.reason.lower():
        failures.append("the empty cycle's reason spoke of repetition rather than the empty return")

    # Negative control: the rule has to bite, or the count above is zero by
    # nothing ever having tried it.
    try:
        Exhaustion(
            cycle=1,
            offers_returned=10,
            offers_already_seen=10,
            repeat_share=1.0,
            exhausted=True,
            reason="",
        )
    except ValidationError:
        rejected = True
    else:
        rejected = False
        failures.append("an exhaustion with an empty reason was accepted")

    return {
        "exhaustion_triggers_without_a_reason": len(failures),
        "cycles_judged": len(judged),
        "exhaustion_triggers": sum(1 for e in judged if e.exhausted),
        "reasonless_construction_rejected": rejected,
        "repeat_share_threshold": EXHAUSTION_REPEAT_SHARE,
        "failures": failures,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T62's measurement to `evidence`, and return it."""
    measured = probe_exhaustion()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_strategy [path]` → T62's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["exhaustion_triggers"] < MINIMUM_TRIGGERS:
        print(
            f"only {measured['exhaustion_triggers']} cycles triggered "
            f"(floor {MINIMUM_TRIGGERS}) — a rule that never fires cannot be shown "
            "to carry a reason when it does",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
