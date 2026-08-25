"""T67 — the standing scope, re-surfaced when the candidate comes back (§5.7).

Step 0 already opens on **position**: `session.Resumption` carries the step, the
rule that chose it and the sentence that says so, and §5.3 forbids resuming
silently. §5.7 extends that opening to **substance** — the scope decisions the
system is still acting on — for a reason that is not courtesy:

> Consent nobody can review is not consent.

§5.5's gate counts narrowings without a recorded decision. A decision recorded
in cycle 3 and never shown again licenses a search a month later that nobody
remembers agreeing to, so the re-surfacing is what makes that gate mean anything
after the session it was recorded in.

**Both stances re-surface.** A refusal is evidence and is not permanent (§5.5),
so an opening that showed only what the candidate agreed to would hide exactly
the decisions they might want to revisit.

Its own module rather than more of `sourcing_strategy`: `make evidence` runs one
`_main` per module and each writes one evidence file, and that module's `_main`
already owns T62's, T64's and T65's.

**The count is only worth reading because the probe tries to break it.** Two
negative controls construct the opening the rule forbids — one omitting a
standing decision, one listing them with no invitation to change any — and count
them if they are *accepted*; a third hands the reader a log out of recorded
order. A floor on the standing decisions fails a run with nothing to re-surface,
since an opening covering no decisions covers all of them.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError, model_validator

from integral.session import Resumption
from integral.sourcing_strategy import EvidenceRow, ScopeDecision, Strict

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T67.json"

#: The probe has to *re-surface* something, not merely fail to hide a thing — an
#: opening with no standing decisions covers every one of them by there being
#: none. Two, so an acceptance and a refusal are both shown.
MINIMUM_STANDING = 2

#: What the correction is prompted by. A `trigger` is required of every §5.5 row
#: and is half of the re-ask rule, so a decision changed on review carries the
#: review as its trigger rather than borrowing the exhaustion that first asked.
REVIEW_TRIGGER = "reviewed on return"

#: The sentence that turns a list into a review. Without it the opening reports
#: decisions the candidate cannot act on, which is the thing §5.7 denies is
#: consent.
CORRECTION_INVITATION = "Any of that can change — say so and I'll record it."


def _stance(decision: ScopeDecision) -> str:
    return "accepted" if decision.accepted else "refused"


def standing_decisions(log: Sequence[EvidenceRow]) -> tuple[ScopeDecision, ...]:
    """The candidate's latest word on each facet and direction, in log order.

    Same rule `sourcing_strategy.apply_scope_change` applies when it licenses a
    change — one reading of "standing", so what re-surfaces is what acts.

    The order of `log` is a claim, not a convention: "latest wins" is read off
    it. So it is checked rather than documented, and a log whose scope decisions
    run backwards is refused instead of silently answered wrongly.
    """
    rows = list(log)
    seen_cycle = 0
    latest: dict[tuple[str, str], ScopeDecision] = {}
    for row in rows:
        if not isinstance(row, ScopeDecision):
            continue
        if row.cycle < seen_cycle:
            raise ValueError(
                f"cycle {row.cycle} follows cycle {seen_cycle}: the log is not in recorded "
                "order, and the latest word cannot be read off an order that is not one"
            )
        seen_cycle = row.cycle
        latest[(row.facet, row.decision)] = row
    return tuple(latest.values())


class Opening(Strict):
    """What step 0 says on a return: where we stopped, and what still stands."""

    position: str  # `Resumption.announcement()` — §5.3's half, unchanged
    standing: tuple[ScopeDecision, ...]
    lines: tuple[str, ...]  # the substance half, one line per standing decision

    def say(self) -> str:
        return "\n".join((self.position, *self.lines))

    @model_validator(mode="after")
    def _every_standing_decision_is_reviewable(self) -> Opening:
        if not self.position.strip():
            raise ValueError("§5.7 extends the opening; an opening with no position is not one")
        for decision in self.standing:
            if not any(
                decision.about in line and decision.decision in line and _stance(decision) in line
                for line in self.lines
            ):
                raise ValueError(
                    f"{decision.about} was {_stance(decision)} and does not appear in the "
                    "opening — a scope decision nobody is shown cannot be corrected"
                )
        if not any(CORRECTION_INVITATION in line for line in self.lines):
            raise ValueError(
                "the opening never invites a correction: consent nobody can review is not consent"
            )
        return self


def resurface(resumption: Resumption, log: Sequence[EvidenceRow]) -> Opening:
    """Step 0's opening, extended from position to substance."""
    standing = standing_decisions(log)
    return Opening(
        position=resumption.announcement(),
        standing=standing,
        lines=(
            *(
                f"{d.about} — {d.decision} ({_stance(d)} in cycle {d.cycle}: {d.reason})"
                for d in standing
            ),
            CORRECTION_INVITATION,
        ),
    )


def correct(
    standing: ScopeDecision,
    *,
    accepted: bool,
    reason: str,
    session: str,
    cycle: int,
) -> ScopeDecision:
    """The candidate's new word on a re-surfaced decision, as a row that stands.

    Corrected *in place* means it displaces the old decision from what stands,
    never that the old row is edited: `evidence.jsonl` is append-only, and a
    consent record that can be rewritten is not one anybody can review.
    """
    if cycle < standing.cycle:
        raise ValueError(
            f"a correction in cycle {cycle} cannot follow a decision from cycle {standing.cycle}"
        )
    return ScopeDecision(
        about=standing.about,
        decision=standing.decision,
        accepted=accepted,
        cycle=cycle,
        reason=reason,
        session=session,
        proposed_alternatives=standing.proposed_alternatives,
        trigger=REVIEW_TRIGGER,
    )


def probe_resurfacing() -> dict[str, Any]:
    """Open on a return and count every standing decision the opening left out."""
    accepted = ScopeDecision(
        about="employer:acme",
        decision="narrow",
        accepted=True,
        cycle=3,
        reason="you read both of Acme's adverts end to end and skipped the other six",
        session="s1",
        proposed_alternatives=("widen:country", "widen:seniority"),
        trigger="the same eight adverts keep coming back",
    )
    refused = ScopeDecision(
        about="country:spain",
        decision="widen",
        accepted=False,
        cycle=4,
        reason="you did not want to look outside Spain while the move is unsettled",
        session="s1",
        proposed_alternatives=("narrow:employer",),
        trigger="the same eight adverts keep coming back",
    )
    # A refusal that still stands, so the opening has to carry both stances: one
    # corrected below, one not. A review that only ever showed what the candidate
    # agreed to would hide exactly the decisions they might want to revisit.
    standing_refusal = ScopeDecision(
        about="stack:rust",
        decision="narrow",
        accepted=False,
        cycle=4,
        reason="you did not want the search limited to one language",
        session="s1",
        proposed_alternatives=("widen:seniority",),
        trigger="the same eight adverts keep coming back",
    )
    # A month later, in a new session: the first refusal is shown again and changed.
    corrected = correct(
        refused,
        accepted=True,
        reason="the move is settled, so Portugal is worth a look now",
        session="s2",
        cycle=5,
    )
    log: list[EvidenceRow] = [
        accepted,
        EvidenceRow(kind="episode", step="history", session="s1"),
        refused,
        standing_refusal,
        corrected,
    ]
    superseded = refused

    resumption = Resumption(
        step="history",
        rule="position",
        reason="last time we were partway through your work history",
    )
    opening = resurface(resumption, log)
    said = opening.say()

    standing = standing_decisions(log)
    missing = [d.about for d in standing if d.about not in said or _stance(d) not in said]
    failures = [f"{about} stands and was not re-surfaced" for about in missing]

    other: list[str] = []
    if resumption.reason not in said:
        other.append("the opening dropped the position it used to carry")
    if superseded in standing:
        other.append("a corrected decision is still standing")
    if corrected not in standing:
        other.append("the correction did not become what stands")

    # Negative controls: each rule has to bite, or the count above is zero by
    # nothing ever having tried the thing it forbids.
    try:
        Opening(position=opening.position, standing=standing, lines=(CORRECTION_INVITATION,))
    except ValidationError:
        omission_rejected = True
    else:
        omission_rejected = False
        failures.append("an opening that showed none of the standing decisions was accepted")

    try:
        Opening(position=opening.position, standing=(), lines=("you are back.",))
    except ValidationError:
        silent_review_rejected = True
    else:
        silent_review_rejected = False
        failures.append("an opening that invited no correction was accepted")

    try:
        standing_decisions([corrected, accepted])
    except ValueError:
        unordered_log_rejected = True
    else:
        unordered_log_rejected = False
        other.append("a log out of recorded order was read as if it were in one")

    return {
        "standing_scope_decisions_not_resurfaced": len(failures),
        "standing_decisions": len(standing),
        "acceptances_resurfaced": sum(1 for d in standing if d.accepted),
        "refusals_resurfaced": sum(1 for d in standing if not d.accepted),
        "corrections_applied": 1,
        "omission_rejected": omission_rejected,
        "silent_review_rejected": silent_review_rejected,
        "unordered_log_rejected": unordered_log_rejected,
        "failures": failures + other,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Write T67's measurement to `evidence`, and return it."""
    measured = probe_resurfacing()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.sourcing_scope_review [path]` → T67's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["standing_decisions"] < MINIMUM_STANDING:
        print(
            f"only {measured['standing_decisions']} decisions stood (floor "
            f"{MINIMUM_STANDING}) — an opening with nothing to re-surface has "
            "re-surfaced everything",
            file=sys.stderr,
        )
        return 3
    if not (measured["acceptances_resurfaced"] and measured["refusals_resurfaced"]):
        print(
            "the probe stood only one stance — a refusal is evidence too (§5.5), and a "
            "run that never held one cannot show refusals come back",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
