"""Trait evidence sufficiency — the step 4 gate `trait_evidence_sufficiency` (T49, D-4).

`status/plan.md`'s "Step gate ownership" table records how this task came to
exist: `gate.task` is not an attribution, it is a lookup key —
`step_gates.evidence_path` turns it into the evidence file the register reads
for a step. Every other document assigned the Traits step to T28, but T28's own
`status/plan.md` gate is `profile_capture_coverage`, and T27's is
`interview_profile_coverage` — **neither is `trait_evidence_sufficiency`**, so
no amount of reassigning the step between them could ever make
`step_gates.register()` read the step truthfully: `evidence_path` would still
be pointed at a file that never carries the number. That was D-4, and it is
resolved by this module: the task whose own `status/plan.md` gate row **is**
`trait_evidence_sufficiency`, so `gate.task`, the plan row and the evidence file
finally name one thing.

**What this module does not do.** It does not count episodes, does not decide
what "two occasions" means, and does not run the interview. `jobsearch.interview`
(T27) already owns exactly that — `trait_floor_state` is where the
two-episode/two-occasion floor lives, read from the evidence log and the decline
ledger, and `TraitFloorState` already resolves every trait to exactly one of
`"sufficient"`/`"insufficient"`. Reimplementing that counting here would be a
second copy of the floor, which is the drift `jobsearch.profile`'s own module
docstring warns against for derived files ("recomputed... and never edited in
place") applied to logic instead of data: two floors is how the two disagree.
What T27's own module docstring reserves for this module, in so many words, is
narrower: *"`trait_evidence_sufficiency` belongs to T49... the step 4 metric
that scores a trait against it"* — turning `TraitFloorState.status` into the
scored-or-insufficient contract the step 4 gate promises, and measuring that
contract *over every trait dimension in the model*, not over one trait at a
time. `TraitFloorState` answers "where does one trait stand"; this module
answers "did every trait land somewhere, honestly" — the difference between a
per-item predicate and the completeness property built on top of it.

**A denial counts toward the floor exactly like an affirmation — and, as things
stand, could not do otherwise.** `elicit_extract.ExtractionResult.denied` exists
so a scorer "can tell an affirmation from its opposite" (its own docstring), but
that sign is never persisted: `EvidenceRow` carries only `dimensions`, no
polarity, so by the time a row reaches `EvidenceLog.effective_rows()` the
information `denied` once carried is already gone — `store_answer` writes
`result.dimensions`, never `result.denied`. And structurally, a `candidate_trait`
dimension can *only* ever be the primary of the question that elicited it: T2's
schema forbids a trait from carrying cues at all
(`Dimension._a_trait_cannot_be_read_from_an_ad`), `_matched_cue_hits` only
scans `side == "matched"` dimensions for a secondary hit, and
`candidate_dimensions`'s own docstring is explicit that "the primary is never
[in `denied`]" — so no trait id has ever reached `denied` under this model, and
none can until some future task both persists the sign on the row and lets a
trait carry cues. Given that, the only decision available today is the one made
here on purpose rather than by omission: an episode counts toward a trait's
floor because the candidate's answer was evidence *about* that trait, not
because of which way it pointed. The floor protects evidentiary density —
"is there enough here to score with confidence" — and a denial ("I have never
really pushed to reopen a decision once it was made") answers that question as
completely as an affirmation does; only the eventual numeric score, which this
module does not compute, would need to read the sign. `_a_denial_counts_like_an_affirmation`
in the probe below demonstrates it directly, on wording chosen to read as a
denial to a person, over the same `trait_floor_state` this module calls.

**Recent and relevant experience is weighted by scoring, not by sufficiency.**
`spec-v2-steps.md` step 4's protocol: "evidence from long ago, or from a field
the candidate has left behind, counts for less and is never the sole support for
a score." That sentence is about what a *score* should weigh once one is
computed — and nothing in this codebase computes a trait's numeric score yet
(`profile._build_traits` "scores nothing, deliberately"; T27 and T28 both stop
at the floor and the capture, respectively). Sufficiency is a coarser, binary
question that comes *before* any score exists: is there enough material to
score at all. An episode from a job the candidate left five years ago is a real
occasion of evidence for whether scoring is possible, even though the score a
future scorer computes from it should count for less than a recent one — so
recency belongs to that scorer's weighting function, not to this module's floor
check, and `trait_sufficiency_reading` does not read `occurred_at` at all.

**A trait's `reason` is never candidate-facing, for the same cause T27 names for
its own.** `TraitFloorState.reason` is, by its own docstring, "never the text
of a question put to the candidate", and `trait_sufficiency_reading` carries it
through unchanged rather than rewording it — a rewrite would be a second place
the floor could leak, this time unchecked by `leaks_quota_language` because
nothing here calls it on a fresh string. `test_the_floor_is_never_in_candidate_facing_text`
proves the leak detector still fires if `reason` were ever shown raw, which is
exactly why it must not be: `TraitSufficiencyReading` has no field named `text`
or `question`, on purpose, so nothing about its shape invites a caller to
display it.

**The metric must not pass over nothing.** `trait_evidence_sufficiency` is a
fraction over trait dimensions in the model; `MINIMUM_TRAITS` refuses to call
one trait, or none, a measurement — "1.0 over one trait is not a measurement"
(the payload's own words) — the same posture `elicit_extract.story_dimension_linkage`
and `interview.profile_coverage`'s sparse-transcript check already take, applied
here to the denominator itself rather than to what fills it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jobsearch.decline import DeclineLedger
from jobsearch.dimensions import (
    Dimension,
    Elicitation,
    Extraction,
    LocalisedText,
    Question,
    synthetic_levels,
)
from jobsearch.interview import (
    MINIMUM_TRAIT_EPISODES,
    MINIMUM_TRAIT_OCCASIONS,
    leaks_quota_language,
    trait_floor_state,
)
from jobsearch.profile import EvidenceLog

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T49.json"

# "1.0 over one trait is not a measurement" — the payload's own floor. Below
# this many trait dimensions in the model, `trait_evidence_sufficiency` reports
# 0.0 rather than a vacuous full mark over too small a denominator to mean
# anything, mirroring `interview.MINIMUM_CHECKS`'s "a clean score without
# exercising the scenarios is not a measurement" for the runtime metric itself
# rather than only for the probe's exit code.
MINIMUM_TRAITS = 2

Status = Literal["sufficient", "insufficient"]


class TraitSufficiencyError(Exception):
    """A caller asked this module to measure something it cannot make sense of."""


@dataclass(frozen=True)
class TraitSufficiencyReading:
    """One trait dimension's scored-or-insufficient verdict — the step 4 contract.

    `status` is never a third value: `trait_sufficiency_reading` derives it
    from `TraitFloorState.status` (`"sufficient"` -> `"sufficient"`,
    `"insufficient"` -> `"insufficient"`), the same completeness
    `TraitFloorState.status` itself is held to. `evidence` is the row ids a
    `"sufficient"` reading is backed by — always non-empty for a scored trait,
    always empty for an insufficient one — so a caller (or `traits.json`, once
    something builds it) can trace the verdict back to what was said, the same
    discipline `EvidenceRow`'s own ids exist for. `reason` is carried through
    from `TraitFloorState.reason` unchanged — see the module docstring for why
    it is never candidate-facing.
    """

    dimension_id: str
    status: Status
    episodes: int
    occasions: int
    declined: bool
    reason: str
    evidence: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# reading one trait, and every trait


def trait_dimension_ids(dimensions: Sequence[Dimension]) -> tuple[str, ...]:
    """Every `candidate_trait` dimension in the model, sorted for a stable order."""
    return tuple(sorted(d.id for d in dimensions if d.side == "candidate_trait"))


def trait_sufficiency_reading(
    log: EvidenceLog, ledger: DeclineLedger, dimension_id: str
) -> TraitSufficiencyReading:
    """One trait's verdict, read from T27's own floor state — never recomputed.

    **The state is `"sufficient"`, not `"scored"`, and the difference is not
    cosmetic.** Nothing in this repository computes a trait *value*:
    `profile._build_traits` collects evidence references and says outright that
    it scores nothing. Naming this state `"scored"` — as it was first written —
    claimed an artefact that does not exist, and would have let a reader take
    `trait_evidence_sufficiency == 1.0` as "every trait has a score" when what
    it means is "every trait has enough evidence to *be* scored, or says what is
    missing".

    That is the honest reading of the gate, and it is what the step's own
    machine-readable metric asks for. Step 4's prose still says "a score backed
    by >= 2 episodes"; delivering the score itself is future work, and the day a
    scorer exists this state is what tells it which traits it may run on.

    `state.status == "sufficient"` is the only thing that can make this
    `"sufficient"`; everything else, declined included, is `"insufficient"` — the
    non-insistence mapping item 4 of the payload asks for (`TraitFloorState.declined`
    is what already keeps `profile_coverage` from counting a declined trait as
    *owed*, and this reuses the same signal rather than re-deriving it).
    """
    state = trait_floor_state(log, ledger, dimension_id)
    if state.status == "sufficient":
        evidence = tuple(
            row.id
            for row in log.effective_rows()
            if row.kind == "episode" and dimension_id in row.dimensions
        )
        return TraitSufficiencyReading(
            dimension_id=dimension_id,
            status="sufficient",
            episodes=state.episodes,
            occasions=state.occasions,
            declined=False,
            reason=state.reason,
            evidence=evidence,
        )
    return TraitSufficiencyReading(
        dimension_id=dimension_id,
        status="insufficient",
        episodes=state.episodes,
        occasions=state.occasions,
        declined=state.declined,
        reason=state.reason,
        evidence=(),
    )


def trait_sufficiency_readings(
    log: EvidenceLog, ledger: DeclineLedger, dimensions: Sequence[Dimension]
) -> tuple[TraitSufficiencyReading, ...]:
    """Every trait dimension's reading, in the model's own trait order."""
    return tuple(
        trait_sufficiency_reading(log, ledger, dimension_id)
        for dimension_id in trait_dimension_ids(dimensions)
    )


# ---------------------------------------------------------------------------
# the gate metric


def trait_evidence_sufficiency(
    dimension_ids: Sequence[str], readings: Sequence[TraitSufficiencyReading]
) -> tuple[float, list[str]]:
    """`trait_evidence_sufficiency` — fraction of `dimension_ids` genuinely resolved.

    Takes `readings` as data rather than recomputing them from a log, the same
    posture `interview.negative_episode_followup_rate` takes toward a
    transcript: a violation produced by hand — a reading built straight from
    `TraitSufficiencyReading`, bypassing `trait_sufficiency_reading` entirely —
    must be caught exactly as if the real pipeline had produced it. That is what
    makes the "required verification" deliberate breaks meaningful rather than
    only a test of this module's own writer.

    A dimension id with no matching reading at all is a violation (item 5: a
    trait must never be left neither scored nor marked insufficient). A
    `"sufficient"` reading below `MINIMUM_TRAIT_EPISODES`/`MINIMUM_TRAIT_OCCASIONS`,
    or carrying no evidence row ids, is a violation (a scored trait below the
    floor is "a stereotype presented as a finding" — the module docstring's own
    words, and the harm the gate exists for). An `"insufficient"` reading with an
    empty `reason` is a violation — `insufficient` is a reading, not a shrug.
    """
    if len(dimension_ids) < MINIMUM_TRAITS:
        return 0.0, [
            f"only {len(dimension_ids)} trait dimension(s) supplied — "
            f"below MINIMUM_TRAITS ({MINIMUM_TRAITS}); a fraction over this few "
            "is not a measurement"
        ]
    by_id = {reading.dimension_id: reading for reading in readings}
    violations: list[str] = []
    valid = 0
    for dimension_id in dimension_ids:
        reading = by_id.get(dimension_id)
        if reading is None:
            violations.append(
                f"{dimension_id}: no reading at all — neither scored nor marked insufficient"
            )
            continue
        if reading.status == "sufficient":
            below_episodes = reading.episodes < MINIMUM_TRAIT_EPISODES
            below_occasions = reading.occasions < MINIMUM_TRAIT_OCCASIONS
            if below_episodes or below_occasions:
                violations.append(
                    f"{dimension_id}: scored with {reading.episodes} episode(s) on "
                    f"{reading.occasions} occasion(s) — below the floor "
                    f"({MINIMUM_TRAIT_EPISODES} episodes / {MINIMUM_TRAIT_OCCASIONS} occasions)"
                )
                continue
            backing = len(set(reading.evidence))
            if backing < reading.episodes:
                # Non-empty was the whole check, so a reading claiming two
                # episodes while naming one row satisfied it. That matters
                # because `measure` takes readings as *data* on purpose — so a
                # hand-built violation is caught exactly as if the pipeline had
                # produced it — and a count nothing has to substantiate is the
                # easiest kind to overstate. The legitimate builder collects one
                # row id per qualifying episode, so anything fewer is either a
                # fabricated reading or a real bug in the builder; both deserve
                # to fail here rather than pass at 1.0.
                violations.append(
                    f"{dimension_id}: claims {reading.episodes} episode(s) but names "
                    f"{backing} distinct evidence row id(s) — a count nothing backs"
                )
                continue
        elif reading.status == "insufficient":
            if not reading.reason.strip():
                violations.append(f"{dimension_id}: insufficient with no reason given")
                continue
        else:  # pragma: no cover - Status is a two-value Literal; belt-and-braces
            violations.append(f"{dimension_id}: unrecognised status {reading.status!r}")
            continue
        valid += 1
    return valid / len(dimension_ids), violations


# ---------------------------------------------------------------------------
# fixtures for the adversarial probe — no committed `candidate_trait` dimension
# exists yet (T26 is unbuilt, same as `interview.py`'s own probe notes), so the
# measurement *is* a scripted scenario run over an in-memory model.


def _fixture_dimension(dimension_id: str) -> Dimension:
    """One minimal, valid `candidate_trait` `Dimension` — no cues, no gold, since
    T2's schema forbids a trait from carrying either (`_a_trait_cannot_be_read_from_an_ad`)."""
    return Dimension(
        id=dimension_id,
        kind="soft",
        polarity="bipolar",
        group="the_work",
        side="candidate_trait",
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic trait dimension used only to probe trait sufficiency",
        levels=synthetic_levels(),
        elicitation=Elicitation(
            questions=[
                Question(
                    id="q1",
                    text=LocalisedText(en="Tell me about it.", es="Cuéntame.", ca="Explica'm-ho."),
                )
            ]
        ),
        extraction=Extraction(cues={}),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


def _localised(text: str) -> LocalisedText:
    """One string in all three corpus languages — `leaks_quota_language` needs
    a `LocalisedText`, and the wording under test here is the same in each."""
    return LocalisedText(en=text, es=text, ca=text)


def probe_trait_sufficiency(root: Path) -> dict[str, Any]:
    """Run every scenario the module docstring and the payload name, and check them."""
    from jobsearch.identity import ProfileStore as _ProfileStore
    from jobsearch.identity import create_profile

    failures: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    scored_id = "trait_creativity"
    single_episode_id = "trait_ambition"
    same_day_id = "trait_curiosity"
    declined_id = "trait_resilience"
    trait_ids = (scored_id, single_episode_id, same_day_id, declined_id)
    dims = [_fixture_dimension(trait_id) for trait_id in trait_ids]

    identity = create_profile(root, "Probe Sufficiency", handle="probe-sufficiency")
    store = _ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    ledger = DeclineLedger(store)

    # `scored_id`: two episodes on two occasions, from two different surfaces
    # (history, then feedback) — item 4's "evidence from any surface counts",
    # continuous capture (T28) feeding the same floor an onboarding sitting would.
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text="Redesigned the onboarding flow from scratch — nobody asked me to.",
        source="conversation",
        dimensions=(scored_id,),
    )
    log.append(
        recorded_at="2026-08-14T09:00:00Z",
        step="feedback",
        kind="episode",
        text="Built a working prototype over a weekend just to see if an idea held up.",
        source="conversation",
        dimensions=(scored_id,),
    )

    # `single_episode_id`: exactly one episode, one occasion — below the floor.
    log.append(
        recorded_at="2026-08-10T09:00:00Z",
        step="history",
        kind="episode",
        text="Asked for a stretch project well outside my usual scope.",
        source="conversation",
        dimensions=(single_episode_id,),
    )

    # `same_day_id`: two episodes, same calendar day — one occasion, not two —
    # item 3's "the floor counts occasions, not repetitions".
    log.append(
        recorded_at="2026-08-12T09:00:00Z",
        step="history",
        kind="episode",
        text="Read the whole changelog before I ever touched the library.",
        source="conversation",
        dimensions=(same_day_id,),
    )
    log.append(
        recorded_at="2026-08-12T15:00:00Z",
        step="history",
        kind="episode",
        text="Spent the evening reading up on something I did not strictly need.",
        source="conversation",
        dimensions=(same_day_id,),
    )

    # `declined_id`: T40 non-insistence — declined, never chased for episodes.
    ledger.decline(declined_id, step="history", at="2026-08-10T09:00:00Z")

    readings = trait_sufficiency_readings(log, ledger, dims)
    ids = trait_dimension_ids(dims)
    fraction, violations = trait_evidence_sufficiency(ids, readings)
    check(
        fraction == 1.0,
        "a profile of legitimately mixed scored/insufficient traits did not read "
        f"1.0: {violations}",
    )
    check(
        violations == [],
        f"a legitimate profile reported violations against its own honest readings: {violations}",
    )

    by_id = {reading.dimension_id: reading for reading in readings}

    check(
        by_id[scored_id].status == "sufficient"
        and by_id[scored_id].episodes >= MINIMUM_TRAIT_EPISODES
        and by_id[scored_id].occasions >= MINIMUM_TRAIT_OCCASIONS,
        f"a trait that cleared the floor was not reported scored: {by_id[scored_id]}",
    )
    check(
        bool(by_id[scored_id].evidence),
        "a scored trait carried no evidence row ids to trace it back to what was said",
    )
    check(
        by_id[single_episode_id].status == "insufficient",
        f"a single-episode trait was reported scored: {by_id[single_episode_id]}",
    )
    check(
        by_id[same_day_id].status == "insufficient" and by_id[same_day_id].occasions == 1,
        f"two same-day episodes were counted as two occasions: {by_id[same_day_id]}",
    )
    check(
        by_id[declined_id].status == "insufficient" and by_id[declined_id].declined,
        f"a declined trait was not reported declined/insufficient: {by_id[declined_id]}",
    )
    # Non-insistence holds at the reading layer too: `insufficient` is the step
    # completing over a declined trait, not stalling on it — item 2's "insufficient
    # is a reading, not a failure" is what this asserts, over the actual verdict
    # rather than over prose describing it.
    check(
        by_id[declined_id].reason.strip() != "",
        "a declined trait's insufficient reading carried no reason",
    )

    # Any surface: the second `scored_id` episode was recorded at the `feedback`
    # step, not `history`, and still counted toward the floor.
    check(
        any(row.step == "feedback" for row in log.effective_rows() if scored_id in row.dimensions),
        "an episode recorded outside the History step was not visible to the floor",
    )

    # A denial counts toward the floor exactly like an affirmation (module
    # docstring) — proven on wording that reads as a denial to a person, over
    # the same evidence log and the same `trait_floor_state` this module calls,
    # since `EvidenceRow` carries no sign for `trait_sufficiency_reading` to
    # act on differently even if it wanted to.
    denial_id = "trait_deference"
    log.append(
        recorded_at="2026-08-15T09:00:00Z",
        step="history",
        kind="episode",
        text="I have never really pushed to reopen a decision once it was made.",
        source="conversation",
        dimensions=(denial_id,),
    )
    log.append(
        recorded_at="2026-08-16T09:00:00Z",
        step="history",
        kind="episode",
        text="Even when I disagreed strongly, I let the original call stand.",
        source="conversation",
        dimensions=(denial_id,),
    )
    denial_reading = trait_sufficiency_reading(log, ledger, denial_id)
    check(
        denial_reading.status == "sufficient",
        f"two occasions of evidence denying a trait did not clear the floor: {denial_reading}",
    )

    # Item 5, half (a): a trait "sufficient" from a single episode must be rejected
    # — the required-verification break, over a reading built by hand rather
    # than through `trait_sufficiency_reading`, so the check is of the metric
    # and not of this module's own writer.
    single_scored = TraitSufficiencyReading(
        dimension_id=scored_id,
        status="sufficient",
        episodes=1,
        occasions=1,
        declined=False,
        reason="hand-built violation",
        evidence=("ev-000099",),
    )
    broken_fraction, broken_violations = trait_evidence_sufficiency((scored_id,), (single_scored,))
    check(
        broken_fraction < 1.0 and bool(broken_violations),
        "a trait scored from a single episode on a single occasion was not rejected",
    )

    # Item 5, half (b): a trait dimension with no reading at all — neither
    # scored nor insufficient — must be rejected.
    missing_fraction, missing_violations = trait_evidence_sufficiency(
        (scored_id, single_episode_id), (by_id[scored_id],)
    )
    check(
        missing_fraction < 1.0 and bool(missing_violations),
        "a trait left with no reading at all was not rejected",
    )

    # The anti-vacuous floor: zero trait dimensions, and one, must not read 1.0.
    zero_fraction, zero_violations = trait_evidence_sufficiency((), ())
    check(zero_fraction != 1.0, "zero trait dimensions reported full sufficiency")
    check(
        bool(zero_violations),
        "zero trait dimensions reported no explanation for the non-measurement",
    )
    one_fraction, _ = trait_evidence_sufficiency((scored_id,), (by_id[scored_id],))
    check(
        one_fraction != 1.0,
        "a single trait dimension, even a genuinely well-scored one, reported a full measurement",
    )

    # The floor is never candidate-facing: `leaks_quota_language` (T27) still
    # fires on an insufficient reading's `reason` if it were ever shown raw —
    # which is exactly why `TraitSufficiencyReading` carries no field meant for
    # display, and why nothing in this module forwards `reason` to a candidate.
    leak_hits = leaks_quota_language(_localised(by_id[single_episode_id].reason))
    check(
        bool(leak_hits),
        "the quota-language tripwire did not fire on an insufficient reading's raw reason — "
        "it must, or a future caller could show that reason to a candidate unchecked",
    )
    check(
        not hasattr(TraitSufficiencyReading, "text")
        and not hasattr(TraitSufficiencyReading, "question"),
        "TraitSufficiencyReading grew a field shaped for display",
    )

    return {
        "trait_evidence_sufficiency": round(fraction, 4),
        "traits_checked": len(ids),
        "readings": [
            {
                "dimension_id": r.dimension_id,
                "status": r.status,
                "episodes": r.episodes,
                "occasions": r.occasions,
                "declined": r.declined,
                "evidence_count": len(r.evidence),
            }
            for r in readings
        ],
        "checks_run": checks,
        "failures": failures,
    }


MINIMUM_CHECKS = 15


def measure() -> dict[str, Any]:
    """Run the adversarial scenario probe in a throwaway tree and report T49's gate."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="jobsearch-t49-") as tmp:
        return probe_trait_sufficiency(Path(tmp) / "profiles")


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure T49's gate and record it."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.trait_sufficiency [--check] [--write-evidence [PATH]]` -> T49's gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T49.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))

    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} checks ran (floor {MINIMUM_CHECKS}) — a clean "
            "score without exercising the scenarios is not a measurement",
            file=sys.stderr,
        )
        return 3

    violations = list(measured["failures"])
    if measured["trait_evidence_sufficiency"] != 1.0:
        violations.append(
            f"trait_evidence_sufficiency = {measured['trait_evidence_sufficiency']} (want 1.0)"
        )
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
